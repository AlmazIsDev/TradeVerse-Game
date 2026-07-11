"""Активы: рынок недвижимости, бизнесов и автомобилей.

Игрок покупает активы с рынка (каталог), владеет ими, улучшает, собирает
пассивный доход (бизнесы/аренда) и продаёт обратно. Все денежные движения
проходят через единый реестр (ledger). Стоимость активов учитывается в
чистом капитале игрока (лидерборд).
"""
from __future__ import annotations

from typing import Optional

import random
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator

from auth import get_current_user
from database import get_db
from ledger import (
    INCOME, EXPENSE, CAT_REALESTATE, CAT_BUSINESS,
    adjust_balance, record_transaction,
)
from notifications import push_notification
from econ import get_econ

router = APIRouter(prefix="/api/assets", tags=["assets"])

TYPE_REALESTATE = "realestate"
TYPE_BUSINESS = "business"
TYPE_CAR = "car"
ASSET_TYPES = {TYPE_REALESTATE, TYPE_BUSINESS, TYPE_CAR}

SELL_RATE = 0.7          # возврат при продаже — 70% текущей стоимости
MAX_ACCRUAL_HOURS = 24   # максимум накопленного дохода за один сбор

# ── Тюнинг автомобилей ────────────────────────────────────────────────────────
# Каждая деталь повышает престиж авто; стоимость улучшения зависит от цены авто
# и текущего уровня детали. Вложения в тюнинг увеличивают стоимость авто (капитал).
TUNE_PARTS = {
    "engine": 18, "turbo": 22, "gearbox": 15, "suspension": 12,
    "brakes": 10, "tires": 9, "exhaust": 8,
}
TUNE_MAX_LEVEL = 5
TUNE_COST_FACTOR = 0.05      # доля от цены авто за уровень
TUNE_VALUE_RETAIN = 0.7      # какая часть вложений в тюнинг идёт в стоимость авто


def _tune_cost(asset: dict, level: int) -> float:
    """Стоимость следующего уровня детали (растёт с ценой авто и уровнем)."""
    return round(asset.get("price", 0) * TUNE_COST_FACTOR * (level + 1), 2)

RENT_MIN_WAIT_H = 1      # минимум ожидания арендатора
RENT_MAX_WAIT_H = 48     # максимум ожидания арендатора (2 суток)
RENTABLE_TYPES = {"realestate", "car"}

# ── Аренда: срок фиксированными пресетами, цена считается от стоимости актива ──
# Формула откалибрована так, чтобы самый дешёвый объект рынка (studio, ~5000$)
# сдавался за минимальный срок (1 день) примерно за 1500–2000$: 5000 × 0.052 ×
# 24^0.6 ≈ 1750$. Показатель степени < 1 даёт убывающую отдачу за час при
# длинных сроках (аренда на месяц дешевле в пересчёте на день, чем на сутки).
RENT_DURATIONS_H = [24, 48, 72, 144, 288, 336, 384, 720]   # 1,2,3,6,12,14,16 дней, 1 месяц
RENT_MAX_HOURS = 720
RENT_RATE = 0.052
RENT_DIMINISH = 0.6

# ── Материалы для бизнеса ────────────────────────────────────────────────────
# Цена за единицу = базовая × economy_mult × множитель текущего мирового
# события (см. market_events.EVENT_TYPES["materials"], настраивается через
# админ-панель — событие меняется, цена пересчитывается автоматически, без
# правки кода). Закупка временно поднимает доход бизнеса.
MATERIALS_BASE_COST = 45.0
MATERIALS_BOOST_PER_UNIT = 0.01     # +1% к доходу за единицу
MATERIALS_BOOST_CAP = 0.30          # максимум +30%
MATERIALS_DURATION_H = 6            # действует 6 часов с момента закупки

# ── Каталог рынка (сид) ──────────────────────────────────────────────────────
# income_per_hour — пассивный доход; upkeep_per_hour — расход (для бизнесов).

CATALOG = [
    # Недвижимость: аренда как доход, налог как расход
    {"slug": "studio", "type": TYPE_REALESTATE, "name": "Студия", "rarity": "common",
     "price": 5000, "income_per_hour": 12, "upkeep_per_hour": 3, "rooms": 1, "meta": {"tax": 3}},
    {"slug": "flat2", "type": TYPE_REALESTATE, "name": "Двухкомнатная квартира", "rarity": "common",
     "price": 14000, "income_per_hour": 32, "upkeep_per_hour": 7, "rooms": 2, "meta": {"tax": 7}},
    {"slug": "townhouse", "type": TYPE_REALESTATE, "name": "Таунхаус", "rarity": "uncommon",
     "price": 45000, "income_per_hour": 95, "upkeep_per_hour": 18, "rooms": 4, "meta": {"tax": 18}},
    {"slug": "villa", "type": TYPE_REALESTATE, "name": "Вилла у моря", "rarity": "rare",
     "price": 160000, "income_per_hour": 320, "upkeep_per_hour": 55, "rooms": 6, "meta": {"tax": 55}},
    {"slug": "penthouse", "type": TYPE_REALESTATE, "name": "Пентхаус", "rarity": "epic",
     "price": 480000, "income_per_hour": 950, "upkeep_per_hour": 140, "rooms": 8, "meta": {"tax": 140}},
    {"slug": "castle", "type": TYPE_REALESTATE, "name": "Замок", "rarity": "legendary",
     "price": 1500000, "income_per_hour": 3000, "upkeep_per_hour": 400, "rooms": 20, "meta": {"tax": 400}},
    # Бизнесы: доход и расходы, есть сотрудники
    {"slug": "shawarma", "type": TYPE_BUSINESS, "name": "Шаурмечная", "category": "retail",
     "price": 8000, "income_per_hour": 60, "upkeep_per_hour": 20, "employees": 2},
    {"slug": "coffee", "type": TYPE_BUSINESS, "name": "Кофейня", "category": "retail",
     "price": 25000, "income_per_hour": 170, "upkeep_per_hour": 55, "employees": 4},
    {"slug": "carwash", "type": TYPE_BUSINESS, "name": "Автомойка", "category": "service",
     "price": 60000, "income_per_hour": 380, "upkeep_per_hour": 110, "employees": 6},
    {"slug": "itstudio", "type": TYPE_BUSINESS, "name": "IT-студия", "category": "tech",
     "price": 200000, "income_per_hour": 1300, "upkeep_per_hour": 420, "employees": 12},
    {"slug": "factory", "type": TYPE_BUSINESS, "name": "Завод", "category": "office",
     "price": 750000, "income_per_hour": 4600, "upkeep_per_hour": 1500, "employees": 40},
    # Автомобили: престиж (без дохода), учитываются в капитале
    {"slug": "citycar", "type": TYPE_CAR, "name": "Городской хэтчбек", "rarity": "common",
     "price": 12000, "income_per_hour": 0, "upkeep_per_hour": 0, "meta": {"prestige": 5}},
    {"slug": "sedan", "type": TYPE_CAR, "name": "Бизнес-седан", "rarity": "uncommon",
     "price": 40000, "income_per_hour": 0, "upkeep_per_hour": 0, "meta": {"prestige": 20}},
    {"slug": "sport", "type": TYPE_CAR, "name": "Спорткар", "rarity": "rare",
     "price": 150000, "income_per_hour": 0, "upkeep_per_hour": 0, "meta": {"prestige": 60}},
    {"slug": "super", "type": TYPE_CAR, "name": "Суперкар", "rarity": "epic",
     "price": 600000, "income_per_hour": 0, "upkeep_per_hour": 0, "meta": {"prestige": 200}},
]

CATALOG_BY_SLUG = {c["slug"]: c for c in CATALOG}

# ── Динамическая экономика рынка ─────────────────────────────────────────────
# Цена каждого товара = базовая × множитель. Множитель двигается от спроса
# (покупки поднимают, продажи опускают), дрейфа и случайных событий.
ASSET_MARKET_TICK_S = 60
ASSET_MULT_MIN = 0.5
ASSET_MULT_MAX = 2.5
DEMAND_BUY = 0.015      # покупка поднимает множитель
DEMAND_SELL = 0.01      # продажа опускает множитель
RARITY_FLOOR = {"common": 0.0, "uncommon": 0.03, "rare": 0.07, "epic": 0.12, "legendary": 0.20}


async def _ensure_asset_market(db: AsyncIOMotorDatabase):
    for c in CATALOG:
        await db.asset_market.update_one(
            {"slug": c["slug"]},
            {"$setOnInsert": {"slug": c["slug"], "mult": 1.0, "updated_at": _now()}},
            upsert=True,
        )


async def _drift_asset_market(db: AsyncIOMotorDatabase):
    """Естественный дрейф цен к целевому уровню, определяемому реальными факторами:
    спрос (владельцы), предложение (объявления аренды), редкость, денежная масса,
    инфляция, активность игроков и мировые экономические события. Плавно, без скачков.
    """
    meta = await db.asset_market_meta.find_one({"key": "tick"})
    last = meta.get("updated_at") if meta else None
    if isinstance(last, datetime):
        la = last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last
        if (_now() - la).total_seconds() < ASSET_MARKET_TICK_S:
            return

    # Мировые события (могут стартовать/завершаться).
    try:
        from market_events import maybe_autostart, event_shifts, slug_event_shift
        await maybe_autostart(db)
        ev = await event_shifts(db)
    except Exception:
        ev = {"shifts": {}}

    econ = await get_econ(db)
    inflation = float(econ.get("inflation", 0.0))

    # Спрос — число владельцев по slug.
    owners: dict = {}
    async for a in db.user_assets.find({}, {"slug": 1}):
        owners[a.get("slug")] = owners.get(a.get("slug"), 0) + 1
    # Предложение — активные объявления аренды по slug.
    listings: dict = {}
    async for a in db.user_assets.find({"rental": {"$ne": None}}, {"slug": 1}):
        listings[a.get("slug")] = listings.get(a.get("slug"), 0) + 1
    # Активность игроков за последний час.
    since = _now() - timedelta(hours=1)
    activity = await db.transactions.count_documents({"timestamp": {"$gte": since}})
    activity_factor = min(0.10, activity * 0.002)
    # Денежная масса — средние деньги игроков слегка поднимают уровень цен.
    total_cash, users = 0.0, 0
    async for u in db.users.find({}, {"balance": 1}):
        users += 1
        total_cash += float(u.get("balance", 0) or 0)
    supply_factor = max(-0.10, min(0.20, (total_cash / users / 50000.0) * 0.10)) if users else 0.0

    for m in [x async for x in db.asset_market.find({})]:
        slug = m.get("slug")
        catalog = CATALOG_BY_SLUG.get(slug, {})
        atype = catalog.get("type", "realestate")
        rarity = catalog.get("rarity", "common")

        target = 1.0
        target += RARITY_FLOOR.get(rarity, 0.0)
        target += min(0.40, owners.get(slug, 0) * 0.02)      # спрос
        target -= min(0.30, listings.get(slug, 0) * 0.03)    # переизбыток предложения
        target += inflation + supply_factor + activity_factor
        target += slug_event_shift(ev.get("shifts", {}), slug, atype)  # событие

        cur = m.get("mult", 1.0)
        # Плавный дрейф к цели (8%) + маленький шум → без резких скачков.
        new = cur + (target - cur) * 0.08 + random.gauss(0, 0.01)
        new = max(ASSET_MULT_MIN, min(ASSET_MULT_MAX, new))
        await db.asset_market.update_one({"_id": m["_id"]}, {"$set": {"mult": round(new, 4), "updated_at": _now()}})

    await db.asset_market_meta.update_one({"key": "tick"}, {"$set": {"updated_at": _now()}}, upsert=True)


async def _mult_map(db: AsyncIOMotorDatabase) -> dict:
    return {m["slug"]: float(m.get("mult", 1.0)) async for m in db.asset_market.find({})}


async def _asset_mult(db: AsyncIOMotorDatabase, slug: str) -> float:
    m = await db.asset_market.find_one({"slug": slug})
    return float(m.get("mult", 1.0)) if m else 1.0


async def _bump_demand(db: AsyncIOMotorDatabase, slug: str, delta: float):
    m = await db.asset_market.find_one({"slug": slug})
    cur = m.get("mult", 1.0) if m else 1.0
    new = max(ASSET_MULT_MIN, min(ASSET_MULT_MAX, cur + delta))
    await db.asset_market.update_one(
        {"slug": slug},
        {"$set": {"mult": round(new, 4), "updated_at": _now()}, "$setOnInsert": {"slug": slug}},
        upsert=True,
    )


# ── Schemas ──────────────────────────────────────────────────────────────────


class BuyRequest(BaseModel):
    slug: str


class TuneBody(BaseModel):
    part: str

    @field_validator("part")
    @classmethod
    def part_ok(cls, v):
        if v not in TUNE_PARTS:
            raise ValueError("Неизвестная деталь тюнинга")
        return v


class RentListing(BaseModel):
    hours: int

    @field_validator("hours")
    @classmethod
    def hours_ok(cls, v):
        # Только фиксированные пресеты (см. RENT_DURATIONS_H) — никакого
        # произвольного ввода, максимум enforced и здесь, и в самом наборе.
        if v not in RENT_DURATIONS_H or v > RENT_MAX_HOURS:
            raise ValueError(f"Срок аренды должен быть одним из: {RENT_DURATIONS_H}")
        return int(v)


class MaterialsBuy(BaseModel):
    qty: int

    @field_validator("qty")
    @classmethod
    def qty_ok(cls, v):
        if v is None or v < 1:
            raise ValueError("Количество должно быть не меньше 1")
        if v > 500:
            raise ValueError("Слишком большое количество")
        return int(v)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _current_value(asset: dict) -> float:
    """Текущая рыночная стоимость экземпляра с учётом уровня улучшений и тюнинга."""
    base = asset.get("price", 0)
    level = asset.get("level", 1)
    return round(base * (1 + 0.35 * (level - 1)) + asset.get("tuning_value", 0.0), 2)


def _materials_boost(asset: dict) -> float:
    """Активный бонус к доходу бизнеса от закупленных материалов (0, если срок истёк)."""
    m = asset.get("materials")
    if not m:
        return 0.0
    expires = m.get("expires_at")
    if not isinstance(expires, datetime):
        return 0.0
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if _now() >= expires:
        return 0.0
    return float(m.get("boostPct", 0.0))


def _income_per_hour(asset: dict) -> float:
    base = asset.get("income_per_hour", 0)
    level = asset.get("level", 1)
    value = base * (1 + 0.25 * (level - 1))
    if asset.get("type") == TYPE_BUSINESS:
        value *= (1 + _materials_boost(asset))
    return round(value, 2)


def _rent_price(asset: dict, hours: int) -> float:
    """Стоимость аренды за срок — масштабируется от стоимости актива и срока
    (убывающая отдача за час: длинные сроки дешевле в пересчёте на день)."""
    return round(_current_value(asset) * RENT_RATE * (hours ** RENT_DIMINISH), 2)


def _rent_quotes(asset: dict) -> list[dict]:
    """Цена аренды на каждый из фиксированных сроков — для выбора на клиенте."""
    if asset.get("type") not in RENTABLE_TYPES:
        return []
    return [{"hours": h, "price": _rent_price(asset, h)} for h in RENT_DURATIONS_H]


def _upkeep_per_hour(asset: dict) -> float:
    return round(asset.get("upkeep_per_hour", 0), 2)


def _upgrade_cost(asset: dict) -> float:
    base = asset.get("price", 0)
    level = asset.get("level", 1)
    return round(base * 0.4 * level, 2)


def _accrued(asset: dict) -> float:
    """Чистый накопленный доход (доход − расход) с последнего сбора, cap 24ч."""
    last = asset.get("last_collected")
    if not isinstance(last, datetime):
        return 0.0
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    hours = min((_now() - last).total_seconds() / 3600.0, MAX_ACCRUAL_HOURS)
    if hours <= 0:
        return 0.0
    net = (_income_per_hour(asset) - _upkeep_per_hour(asset)) * hours
    return round(max(0.0, net), 2)


# ── Аренда ───────────────────────────────────────────────────────────────────


def _rental_view(asset: dict) -> Optional[dict]:
    r = asset.get("rental")
    if not r:
        return None
    return {
        "status": r.get("status"),
        "price": r.get("price"),
        "minHours": r.get("minHours"),
        "tenantAt": r["tenant_at"].isoformat() if isinstance(r.get("tenant_at"), datetime) else None,
        "endsAt": r["ends_at"].isoformat() if isinstance(r.get("ends_at"), datetime) else None,
    }


async def _process_rental(db: AsyncIOMotorDatabase, asset: dict) -> dict:
    """Ленивая обработка аренды: заселение арендатора и выплата по окончании.

    listed → (наступило tenant_at) → rented → (наступило ends_at) → выплата владельцу.
    """
    r = asset.get("rental")
    if not r:
        return asset
    now = _now()

    def _aware(dt):
        return dt.replace(tzinfo=timezone.utc) if isinstance(dt, datetime) and dt.tzinfo is None else dt

    # Заселение арендатора
    if r.get("status") == "listed":
        tenant_at = _aware(r.get("tenant_at"))
        if tenant_at and now >= tenant_at:
            ends_at = tenant_at + timedelta(hours=r.get("minHours", 1))
            r["status"] = "rented"
            r["ends_at"] = ends_at
            await db.user_assets.update_one({"_id": asset["_id"]}, {"$set": {"rental": r}})
            asset["rental"] = r
            await push_notification(
                db, asset["userId"], "rental",
                "Появился арендатор", f"«{asset.get('name')}» сдан в аренду.",
                data={"assetId": str(asset["_id"])},
            )
            try:
                from ws import push_to_user
                await push_to_user(asset["userId"], {"type": "asset_update", "assetId": str(asset["_id"])})
            except Exception:
                pass

    # Завершение аренды и выплата
    if r.get("status") == "rented":
        ends_at = _aware(r.get("ends_at"))
        if ends_at and now >= ends_at:
            payout = round(float(r.get("price", 0)), 2)
            # Админ-коэффициент аренды + влияние мировых событий (напр. туристический сезон).
            try:
                econ = await get_econ(db)
                payout = round(payout * econ.get("rent_mult", 1.0) * econ.get("economy_mult", 1.0), 2)
                from market_events import event_shifts
                payout = round(payout * (await event_shifts(db)).get("rental", 1.0), 2)
            except Exception:
                pass
            # Бонус «Гранд-отеля» (Крыша города) — +% к доходу от аренды.
            try:
                from cityroof import player_city_effect
                bonus = await player_city_effect(db, asset["userId"], "rental_income")
                if bonus:
                    payout = round(payout * (1 + bonus), 2)
            except Exception:
                pass
            await db.user_assets.update_one({"_id": asset["_id"]}, {"$set": {"rental": None}})
            asset["rental"] = None
            try:
                from ws import push_to_user
                await push_to_user(asset["userId"], {"type": "asset_update", "assetId": str(asset["_id"])})
            except Exception:
                pass
            if payout > 0:
                company_id = asset.get("companyId")
                if company_id and ObjectId.is_valid(company_id):
                    # Актив компании — доход поступает в бюджет компании.
                    await db.companies.update_one({"_id": ObjectId(company_id)}, {"$inc": {"budget": payout}})
                    company = await db.companies.find_one({"_id": ObjectId(company_id)})
                    from ledger import CAT_COMPANY
                    await record_transaction(
                        db, asset["userId"], INCOME, payout, CAT_COMPANY,
                        f"Аренда (компания): {asset.get('name')}",
                        meta={"assetId": str(asset["_id"]), "companyId": company_id, "toBudget": True},
                    )
                    if company:
                        await push_notification(
                            db, company.get("ownerId", asset["userId"]), "rental",
                            "Аренда компании завершена",
                            f"В бюджет «{company.get('name')}» начислено ${payout:.2f} за «{asset.get('name')}».",
                            data={"assetId": str(asset["_id"]), "payout": payout, "companyId": company_id},
                        )
                else:
                    new_balance = await adjust_balance(db, asset["userId"], payout)
                    await record_transaction(
                        db, asset["userId"], INCOME, payout, CAT_REALESTATE,
                        f"Аренда: {asset.get('name')}", balance_after=new_balance,
                        meta={"assetId": str(asset["_id"])},
                    )
                    await push_notification(
                        db, asset["userId"], "rental",
                        "Аренда завершена", f"Начислено ${payout:.2f} за «{asset.get('name')}».",
                        data={"assetId": str(asset["_id"]), "payout": payout},
                    )
    return asset


# ── Активы компании (реальный источник дохода) ───────────────────────────────


async def company_income_per_hour(db: AsyncIOMotorDatabase, company_id: str) -> float:
    """Чистый доход компании в час от принадлежащих ей активов."""
    total = 0.0
    async for a in db.user_assets.find({"companyId": company_id}):
        total += (_income_per_hour(a) - _upkeep_per_hour(a))
    return round(total, 2)


async def list_company_assets(db: AsyncIOMotorDatabase, company_id: str) -> list[dict]:
    return [_serialize(a) async for a in db.user_assets.find({"companyId": company_id})]


async def sweep_rentals(db: AsyncIOMotorDatabase):
    """Глобальная обработка аренды (заселение/выплаты) — вызывается Scheduler'ом."""
    async for a in db.user_assets.find({"rental": {"$ne": None}}):
        try:
            await _process_rental(db, a)
        except Exception:
            pass


async def tick_market(db: AsyncIOMotorDatabase):
    """Публичная точка для Scheduler: дрейф динамического рынка активов."""
    await _ensure_asset_market(db)
    await _drift_asset_market(db)
    try:
        from ws import broadcast
        await broadcast({"type": "market_update"})
    except Exception:
        pass


def _serialize(asset: dict) -> dict:
    return {
        "id": str(asset["_id"]),
        "slug": asset.get("slug"),
        "type": asset.get("type"),
        "name": asset.get("name"),
        "category": asset.get("category"),
        "rarity": asset.get("rarity"),
        "rooms": asset.get("rooms"),
        "employees": asset.get("employees", 0),
        "level": asset.get("level", 1),
        "price": asset.get("price", 0),
        "value": _current_value(asset),
        "incomePerHour": _income_per_hour(asset),
        "upkeepPerHour": _upkeep_per_hour(asset),
        "profitPerHour": round(_income_per_hour(asset) - _upkeep_per_hour(asset), 2),
        "upgradeCost": _upgrade_cost(asset),
        "accrued": _accrued(asset),
        "meta": asset.get("meta", {}),
        "companyId": asset.get("companyId"),
        "rental": _rental_view(asset),
        "rentQuotes": _rent_quotes(asset),
        "tuning": asset.get("tuning", {}),
        "tuneMaxLevel": TUNE_MAX_LEVEL,
        "materialsBoostPct": _materials_boost(asset),
        "purchasedAt": asset.get("purchased_at").isoformat() if isinstance(asset.get("purchased_at"), datetime) else None,
    }


# ── Market ───────────────────────────────────────────────────────────────────


@router.get("/market")
async def get_market(
    type: str = Query(None),
    search: str = Query(None),
    min_price: float = Query(None),
    max_price: float = Query(None),
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Каталог рынка с ДИНАМИЧЕСКИМИ ценами (спрос/предложение/дрейф/события)."""
    await _ensure_asset_market(db)
    await _drift_asset_market(db)
    mults = await _mult_map(db)

    items = CATALOG
    if type in ASSET_TYPES:
        items = [c for c in items if c["type"] == type]
    if search:
        s = search.lower()
        items = [c for c in items if s in c["name"].lower()]

    out = []
    for c in items:
        mult = mults.get(c["slug"], 1.0)
        price = round(c["price"] * mult, 2)
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue
        out.append({
            "slug": c["slug"], "type": c["type"], "name": c["name"],
            "category": c.get("category"), "rarity": c.get("rarity"),
            "rooms": c.get("rooms"), "employees": c.get("employees", 0),
            "price": price,
            "basePrice": c["price"],
            "trend": round((mult - 1) * 100, 1),   # % отклонения цены от базовой
            "incomePerHour": c.get("income_per_hour", 0),
            "upkeepPerHour": c.get("upkeep_per_hour", 0),
            "profitPerHour": round(c.get("income_per_hour", 0) - c.get("upkeep_per_hour", 0), 2),
            "meta": c.get("meta", {}),
        })
    out.sort(key=lambda x: x["price"])
    return out


@router.post("/buy", status_code=status.HTTP_201_CREATED)
async def buy_asset(
    payload: BuyRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Покупка актива с рынка: списывает баланс, создаёт экземпляр во владении."""
    catalog = CATALOG_BY_SLUG.get(payload.slug)
    if not catalog:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Актив не найден")

    user_id = str(current_user["_id"])
    # Динамическая цена покупки (базовая × текущий рыночный множитель).
    await _ensure_asset_market(db)
    mult = await _asset_mult(db, catalog["slug"])
    pay_price = round(float(catalog["price"]) * mult, 2)

    new_balance = await adjust_balance(db, user_id, -pay_price)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

    doc = {
        "userId": user_id,
        "slug": catalog["slug"],
        "type": catalog["type"],
        "name": catalog["name"],
        "category": catalog.get("category"),
        "rarity": catalog.get("rarity"),
        "rooms": catalog.get("rooms"),
        "employees": catalog.get("employees", 0),
        "price": float(catalog["price"]),   # базовая цена — для расчёта стоимости/улучшений
        "income_per_hour": catalog.get("income_per_hour", 0),
        "upkeep_per_hour": catalog.get("upkeep_per_hour", 0),
        "level": 1,
        "meta": catalog.get("meta", {}),
        "companyId": None,      # None = личный актив; иначе принадлежит компании
        "rental": None,         # активное объявление/аренда (см. rental)
        "purchased_at": _now(),
        "last_collected": _now(),
    }
    result = await db.user_assets.insert_one(doc)
    doc["_id"] = result.inserted_id

    cat = CAT_BUSINESS if catalog["type"] == TYPE_BUSINESS else CAT_REALESTATE
    await record_transaction(
        db, user_id, EXPENSE, pay_price, cat,
        f"Покупка: {catalog['name']}", balance_after=new_balance,
        meta={"slug": catalog["slug"], "type": catalog["type"]},
    )
    # Спрос поднимает рыночную цену этого товара.
    await _bump_demand(db, catalog["slug"], DEMAND_BUY)
    return {"asset": _serialize(doc), "balance": new_balance, "paid": pay_price}


# ── Ownership ────────────────────────────────────────────────────────────────


@router.get("/mine")
async def get_my_assets(
    type: str = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Личные активы игрока (без переданных компании) + агрегаты."""
    user_id = str(current_user["_id"])
    query = {"userId": user_id, "companyId": None}
    if type in ASSET_TYPES:
        query["type"] = type
    docs = [a async for a in db.user_assets.find(query)]
    assets = []
    for a in docs:
        a = await _process_rental(db, a)   # ленивое заселение/выплата аренды
        assets.append(_serialize(a))
    assets.sort(key=lambda a: a["value"], reverse=True)
    total_value = round(sum(a["value"] for a in assets), 2)
    total_profit = round(sum(a["profitPerHour"] for a in assets), 2)
    total_accrued = round(sum(a["accrued"] for a in assets), 2)
    return {
        "assets": assets,
        "totalValue": total_value,
        "profitPerHour": total_profit,
        "accrued": total_accrued,
        "count": len(assets),
    }


async def _load_owned(db, user_id, asset_id):
    if not ObjectId.is_valid(asset_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID актива")
    asset = await db.user_assets.find_one({"_id": ObjectId(asset_id), "userId": user_id})
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Актив не найден")
    return asset


@router.post("/{asset_id}/collect")
async def collect_income(
    asset_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Собрать накопленный доход (за вычетом расходов на содержание)."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    amount = _accrued(asset)
    # Экономические коэффициенты (админ): множитель доходов.
    econ = await get_econ(db)
    amount = round(amount * econ.get("income_mult", 1.0) * econ.get("economy_mult", 1.0), 2)
    # Влияние активных мировых событий на доход.
    try:
        from market_events import event_shifts
        amount = round(amount * (await event_shifts(db)).get("income", 1.0), 2)
    except Exception:
        pass
    # Бонус зданий «Крыши города»: +% к доходу с бизнеса/недвижимости.
    try:
        from cityroof import player_city_effect
        city_bonus = await player_city_effect(db, user_id, "asset_income")
        if city_bonus:
            amount = round(amount * (1 + city_bonus), 2)
    except Exception:
        pass
    await db.user_assets.update_one({"_id": asset["_id"]}, {"$set": {"last_collected": _now()}})
    if amount <= 0:
        return {"collected": 0.0, "balance": current_user.get("balance", 0.0)}
    new_balance = await adjust_balance(db, user_id, amount)
    cat = CAT_BUSINESS if asset["type"] == TYPE_BUSINESS else CAT_REALESTATE
    await record_transaction(
        db, user_id, INCOME, amount, cat,
        f"Доход: {asset['name']}", balance_after=new_balance,
        meta={"slug": asset.get("slug"), "assetId": asset_id},
    )
    return {"collected": amount, "balance": new_balance}


@router.post("/{asset_id}/upgrade")
async def upgrade_asset(
    asset_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Улучшить актив: повышает стоимость и доход."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    cost = _upgrade_cost(asset)
    new_balance = await adjust_balance(db, user_id, -cost)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
    await db.user_assets.update_one({"_id": asset["_id"]}, {"$inc": {"level": 1}})
    cat = CAT_BUSINESS if asset["type"] == TYPE_BUSINESS else CAT_REALESTATE
    await record_transaction(
        db, user_id, EXPENSE, cost, cat,
        f"Улучшение: {asset['name']} → ур.{asset.get('level', 1) + 1}",
        balance_after=new_balance, meta={"assetId": asset_id},
    )
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    return {"asset": _serialize(updated), "balance": new_balance}


@router.post("/{asset_id}/tune")
async def tune_asset(
    asset_id: str,
    payload: TuneBody,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Тюнинг автомобиля: улучшает деталь, повышает престиж и стоимость авто."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    if asset.get("type") != TYPE_CAR:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Тюнинг доступен только для автомобилей")

    part = payload.part
    tuning = dict(asset.get("tuning", {}))
    level = int(tuning.get(part, 0))
    if level >= TUNE_MAX_LEVEL:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Достигнут максимальный уровень детали")

    cost = _tune_cost(asset, level)
    new_balance = await adjust_balance(db, user_id, -cost)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

    tuning[part] = level + 1
    meta = dict(asset.get("meta", {}))
    meta["prestige"] = int(meta.get("prestige", 0)) + TUNE_PARTS[part]
    tuning_value = round(asset.get("tuning_value", 0.0) + cost * TUNE_VALUE_RETAIN, 2)
    await db.user_assets.update_one(
        {"_id": asset["_id"]},
        {"$set": {"tuning": tuning, "meta": meta, "tuning_value": tuning_value}},
    )
    await record_transaction(
        db, user_id, EXPENSE, cost, CAT_REALESTATE,
        f"Тюнинг: {asset.get('name')} — {part}", balance_after=new_balance,
        meta={"assetId": asset_id, "part": part, "level": level + 1},
    )
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    return {"asset": _serialize(updated), "balance": new_balance, "cost": cost}


@router.post("/{asset_id}/sell")
async def sell_asset(
    asset_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Продать актив обратно (70% текущей стоимости) + невыбранный доход."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    payout = round(_current_value(asset) * SELL_RATE + _accrued(asset), 2)
    await db.user_assets.delete_one({"_id": asset["_id"]})
    new_balance = await adjust_balance(db, user_id, payout)
    cat = CAT_BUSINESS if asset["type"] == TYPE_BUSINESS else CAT_REALESTATE
    await record_transaction(
        db, user_id, INCOME, payout, cat,
        f"Продажа: {asset['name']}", balance_after=new_balance,
        meta={"slug": asset.get("slug")},
    )
    # Продажа опускает рыночную цену этого товара.
    if asset.get("slug"):
        await _bump_demand(db, asset["slug"], -DEMAND_SELL)
    return {"sold": payout, "balance": new_balance}


@router.post("/{asset_id}/transfer-to-company")
async def transfer_to_company(
    asset_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Передать актив своей компании — доход с него начнёт получать компания."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    if asset.get("companyId"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Актив уже принадлежит компании")
    company = await db.companies.find_one({"ownerId": user_id})
    if not company:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Сначала создайте компанию")
    await db.user_assets.update_one(
        {"_id": asset["_id"]},
        {"$set": {"companyId": str(company["_id"]), "rental": None, "last_collected": _now()}},
    )
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    return {"ok": True, "asset": _serialize(updated)}


@router.post("/{asset_id}/rent/list")
async def rent_list(
    asset_id: str,
    payload: RentListing,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Выставить недвижимость/авто в аренду на фиксированный срок (см.
    RENT_DURATIONS_H). Арендатор появится через 1–48 часов. Цена всегда
    пересчитывается сервером от стоимости актива и срока — клиент выбирает
    только срок (см. _rent_price), поэтому её нельзя подделать.

    Работает и для личных активов, и для активов компании (владелец компании
    управляет ими) — в последнем случае выплата поступит в бюджет компании.
    """
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    if asset.get("type") not in RENTABLE_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Сдавать можно только недвижимость и авто")
    if asset.get("rental"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Объект уже сдаётся или ждёт арендатора")
    price = _rent_price(asset, payload.hours)
    wait_h = random.randint(RENT_MIN_WAIT_H, RENT_MAX_WAIT_H)
    rental = {
        "status": "listed",
        "price": price,
        "minHours": payload.hours,
        "tenant_at": _now() + timedelta(hours=wait_h),
        "ends_at": None,
        "listed_at": _now(),
    }
    await db.user_assets.update_one({"_id": asset["_id"]}, {"$set": {"rental": rental}})
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    return {"ok": True, "asset": _serialize(updated), "tenantInHours": wait_h}


@router.post("/{asset_id}/rent/cancel")
async def rent_cancel(
    asset_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Снять объявление об аренде (пока арендатор не заселился)."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    r = asset.get("rental")
    if not r or r.get("status") != "listed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Объект уже сдан или не выставлен")
    await db.user_assets.update_one({"_id": asset["_id"]}, {"$set": {"rental": None}})
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    return {"ok": True, "asset": _serialize(updated)}


# ── Материалы для бизнеса ────────────────────────────────────────────────────


async def _materials_unit_price(db: AsyncIOMotorDatabase) -> float:
    econ = await get_econ(db)
    mult = econ.get("economy_mult", 1.0)
    try:
        from market_events import event_shifts
        mult *= (await event_shifts(db)).get("materials", 1.0)
    except Exception:
        pass
    return round(MATERIALS_BASE_COST * mult, 2)


@router.get("/materials/price")
async def materials_price(
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Текущая цена материалов за единицу — зависит от активного мирового события."""
    return {
        "unitPrice": await _materials_unit_price(db),
        "boostPerUnit": MATERIALS_BOOST_PER_UNIT,
        "boostCap": MATERIALS_BOOST_CAP,
        "durationHours": MATERIALS_DURATION_H,
    }


@router.post("/{asset_id}/materials/buy")
async def buy_materials(
    asset_id: str,
    payload: MaterialsBuy,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Закупить материалы для бизнеса — временно (на MATERIALS_DURATION_H)
    поднимает его доход. Цена за единицу пересчитывается сервером от текущего
    мирового события — клиентская цена никогда не используется."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    if asset.get("type") != TYPE_BUSINESS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Материалы закупаются только для бизнеса")

    unit_price = await _materials_unit_price(db)
    total = round(unit_price * payload.qty, 2)
    new_balance = await adjust_balance(db, user_id, -total)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

    boost = min(MATERIALS_BOOST_CAP, _materials_boost(asset) + MATERIALS_BOOST_PER_UNIT * payload.qty)
    materials = {"boostPct": round(boost, 4), "expires_at": _now() + timedelta(hours=MATERIALS_DURATION_H)}
    await db.user_assets.update_one({"_id": asset["_id"]}, {"$set": {"materials": materials}})

    await record_transaction(
        db, user_id, EXPENSE, total, CAT_BUSINESS,
        f"Материалы: {asset.get('name')} ×{payload.qty}", balance_after=new_balance,
        meta={"assetId": asset_id, "qty": payload.qty, "unitPrice": unit_price},
    )
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    return {"asset": _serialize(updated), "balance": new_balance, "unitPrice": unit_price, "total": total}


# ── Aggregate value (для лидерборда/капитала) ────────────────────────────────


async def total_asset_value(db: AsyncIOMotorDatabase, user_id: str) -> float:
    total = 0.0
    async for a in db.user_assets.find({"userId": user_id}):
        total += _current_value(a)
    return round(total, 2)
