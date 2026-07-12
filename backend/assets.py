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

from auth import get_current_user, require_admin
from database import get_db
from ledger import (
    INCOME, EXPENSE, CAT_REALESTATE, CAT_BUSINESS,
    adjust_balance, record_transaction,
)
from notifications import push_notification
from econ import get_econ
from timeutil import now_utc, to_aware

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
RENT_MAX_HOURS = 720     # максимальный срок аренды (30 суток)
RENTABLE_TYPES = {"realestate", "car", "business"}

# ── Экономика аренды ─────────────────────────────────────────────────────────
# У каждого актива — своя суточная ставка аренды: она НЕ одинакова для всего
# имущества, а рассчитывается из совокупности факторов:
#   1) текущая стоимость актива (цена + уровень апгрейда + тюнинг, см. _current_value);
#   2) редкость/класс объекта (rarity) — определяет % от стоимости в сутки;
# Чем реже и роскошнее объект — тем выше именно ПРОЦЕНТ доходности (не только
# абсолютная сумма за счёт более высокой цены). Поэтому дешёвая недвижимость
# даёт скромный доход, а элитная — кратно выгоднее как в долларах, так и в %,
# и не бывает ситуации, когда дешёвый объект почти не уступает дорогому.
# Ориентир баланса: «хорошая» недвижимость редкости rare (напр. Вилла, $160k)
# должна приносить ≈$2000/сутки только за счёт аренды.
RARITY_RENT_PCT = {
    "common": 0.008,      # 0.8%/сутки — дешёвое имущество: небольшой доход
    "uncommon": 0.011,    # 1.1%/сутки — средний класс: заметный доход
    "rare": 0.013,        # 1.3%/сутки — хорошее имущество: высокий доход (~$2000/сутки для Виллы)
    "epic": 0.019,        # 1.9%/сутки — дорогое имущество: очень высокий доход
    "legendary": 0.026,   # 2.6%/сутки — элитное имущество: максимальная доходность
}
# Минимальный суточный доход по редкости — подстраховка от вырожденных случаев
# (например, сильно уценённый на рынке актив), а НЕ основной драйвер экономики,
# как было раньше (плоский пол в $2000 одинаковый для всех — тот самый баг,
# из-за которого дешёвая студия зарабатывала как элитная недвижимость).
RARITY_RENT_FLOOR = {
    "common": 40.0,
    "uncommon": 150.0,
    "rare": 500.0,
    "epic": 2000.0,
    "legendary": 6000.0,
}

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
# rarity — определяет и рыночный дрейф цены (RARITY_FLOOR), и ставку аренды
# (RARITY_RENT_PCT/RARITY_RENT_FLOOR) — есть у всех типов, включая бизнесы.

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
    # Бизнесы: доход и расходы, есть сотрудники. rarity — экономический класс
    # бизнеса (отдельно от category, которая отвечает только за тематику/иконку).
    {"slug": "shawarma", "type": TYPE_BUSINESS, "name": "Шаурмечная", "category": "retail", "rarity": "common",
     "price": 8000, "income_per_hour": 60, "upkeep_per_hour": 20, "employees": 2},
    {"slug": "coffee", "type": TYPE_BUSINESS, "name": "Кофейня", "category": "retail", "rarity": "uncommon",
     "price": 25000, "income_per_hour": 170, "upkeep_per_hour": 55, "employees": 4},
    {"slug": "carwash", "type": TYPE_BUSINESS, "name": "Автомойка", "category": "service", "rarity": "rare",
     "price": 60000, "income_per_hour": 380, "upkeep_per_hour": 110, "employees": 6},
    # IT-студия — 4 тира (slug = "itstudio_" + ключ тира в game_config.ITSTUDIO_CONFIG).
    # Владение экземпляром открывает заказ атаки/защиты «Крыши города»
    # (см. cityroof.py) — материалы, шанс успеха и опыт зависят от тира.
    {"slug": "itstudio_basic", "type": TYPE_BUSINESS, "name": "IT-студия: Базовая", "category": "tech", "rarity": "epic",
     "price": 200000, "income_per_hour": 1300, "upkeep_per_hour": 420, "employees": 12},
    {"slug": "itstudio_medium", "type": TYPE_BUSINESS, "name": "IT-студия: Средняя", "category": "tech", "rarity": "epic",
     "price": 450000, "income_per_hour": 2600, "upkeep_per_hour": 850, "employees": 20},
    {"slug": "itstudio_advanced", "type": TYPE_BUSINESS, "name": "IT-студия: Продвинутая", "category": "tech", "rarity": "legendary",
     "price": 900000, "income_per_hour": 5000, "upkeep_per_hour": 1700, "employees": 32},
    {"slug": "itstudio_premium", "type": TYPE_BUSINESS, "name": "IT-студия: Премиальная", "category": "tech", "rarity": "legendary",
     "price": 1800000, "income_per_hour": 9200, "upkeep_per_hour": 3200, "employees": 50},
    {"slug": "factory", "type": TYPE_BUSINESS, "name": "Завод", "category": "office", "rarity": "legendary",
     "price": 750000, "income_per_hour": 4600, "upkeep_per_hour": 1500, "employees": 40},
    # Автомобили: престиж (без дохода), учитываются в капитале, но сдаются в аренду
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
    minHours: int

    @field_validator("minHours")
    @classmethod
    def hours_ok(cls, v):
        if v < 1 or v > RENT_MAX_HOURS:
            raise ValueError(f"Срок аренды: 1–{RENT_MAX_HOURS} часов")
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


class AdminAssetUpdate(BaseModel):
    """Правки актива администратором — без ограничений, действующих на игрока."""
    level: Optional[int] = None
    price: Optional[float] = None
    income_per_hour: Optional[float] = None
    upkeep_per_hour: Optional[float] = None


class AdminTransferBody(BaseModel):
    toUsername: str


# ── Helpers ──────────────────────────────────────────────────────────────────


_now = now_utc


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


def _rent_rarity(asset: dict) -> str:
    """Редкость актива для расчёта аренды. Берётся из самого экземпляра (в него
    копируется при покупке из каталога — buy_asset), с запасным вариантом через
    каталог по slug — на случай активов, купленных до появления rarity у бизнесов."""
    rarity = asset.get("rarity")
    if rarity in RARITY_RENT_PCT:
        return rarity
    catalog_rarity = CATALOG_BY_SLUG.get(asset.get("slug"), {}).get("rarity")
    return catalog_rarity if catalog_rarity in RARITY_RENT_PCT else "common"


def _rent_daily_rate(asset: dict) -> float:
    """Суточная ставка аренды — СВОЯ для каждого объекта, а не единый коэффициент
    для всего имущества. Зависит от текущей стоимости актива (цена + апгрейды +
    тюнинг — см. _current_value) и его редкости/класса (RARITY_RENT_PCT): чем
    реже и роскошнее объект, тем выше именно % доходности, а не только сумма.
    RARITY_RENT_FLOOR — лишь подстраховка от вырожденно низких значений, а не
    основной регулятор (как было раньше с плоским полом в $2000 для всех)."""
    if asset.get("type") not in RENTABLE_TYPES:
        return 0.0
    rarity = _rent_rarity(asset)
    pct = RARITY_RENT_PCT[rarity]
    floor = RARITY_RENT_FLOOR[rarity]
    return round(max(floor, _current_value(asset) * pct), 2)


def _rent_rate_per_hour(asset: dict) -> float:
    """Ставка аренды в час — для отображения клиенту (не используется в расчёте
    итоговой суммы, чтобы округление ставки не накапливалось на длинных сроках)."""
    return round(_rent_daily_rate(asset) / 24, 2)


def _rent_total(asset: dict, hours: int) -> float:
    """Итоговая стоимость аренды за срок — линейно от часов, единая формула для
    клиента (превью) и сервера (авторитетный пересчёт при выставлении объявления)."""
    if asset.get("type") not in RENTABLE_TYPES:
        return 0.0
    return round(_rent_daily_rate(asset) * hours / 24, 2)


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

    # Заселение арендатора
    if r.get("status") == "listed":
        tenant_at = to_aware(r.get("tenant_at"))
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
        ends_at = to_aware(r.get("ends_at"))
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


def _studio_view(asset: dict) -> Optional[dict]:
    """Прокачка/материалы IT-студии (см. cityroof.py) — None для остальных активов."""
    slug = asset.get("slug") or ""
    if not slug.startswith("itstudio_"):
        return None
    tier = slug[len("itstudio_"):]
    try:
        from cityroof import studio_progress
    except Exception:
        return None
    return studio_progress(tier, asset.get("studioXp", 0), asset.get("itstudioMaterials", {}))


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
        "rentRatePerHour": _rent_rate_per_hour(asset),
        "tuning": asset.get("tuning", {}),
        "tuneMaxLevel": TUNE_MAX_LEVEL,
        "materialsBoostPct": _materials_boost(asset),
        "studio": _studio_view(asset),
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
    """Выставить недвижимость/авто/бизнес в аренду на произвольный срок (в часах).
    Арендатор появится через случайный диапазон часов. Цена всегда пересчитывается
    сервером от стоимости актива, его редкости и срока (см. _rent_total) —
    клиент выбирает только срок, поэтому её нельзя подделать.

    Работает и для личных активов, и для активов компании (владелец компании
    управляет ими) — в последнем случае выплата поступит в бюджет компании.
    """
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    if asset.get("type") not in RENTABLE_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Сдавать можно только недвижимость, авто и бизнесы")
    if asset.get("rental"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Объект уже сдаётся или ждёт арендатора")
    # Итоговая цена всегда пересчитывается сервером из срока — клиентской цене не доверяем.
    price = _rent_total(asset, payload.minHours)
    wait_h = random.randint(RENT_MIN_WAIT_H, RENT_MAX_WAIT_H)
    rental = {
        "status": "listed",
        "price": price,
        "minHours": payload.minHours,
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


# ── Admin ────────────────────────────────────────────────────────────────────


async def _load_any(db: AsyncIOMotorDatabase, asset_id: str) -> dict:
    if not ObjectId.is_valid(asset_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID актива")
    asset = await db.user_assets.find_one({"_id": ObjectId(asset_id)})
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Актив не найден")
    return asset


@router.patch("/admin/{asset_id}")
async def admin_update_asset(
    asset_id: str,
    payload: AdminAssetUpdate,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    asset = await _load_any(db, asset_id)
    update_fields = payload.model_dump(exclude_unset=True)
    if not update_fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет полей для обновления")
    await db.user_assets.update_one({"_id": asset["_id"]}, {"$set": update_fields})
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    try:
        from ws import push_to_user
        await push_to_user(asset["userId"], {"type": "asset_update", "assetId": asset_id})
    except Exception:
        pass
    return {"asset": _serialize(updated)}


@router.delete("/admin/{asset_id}")
async def admin_delete_asset(
    asset_id: str,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    asset = await _load_any(db, asset_id)
    await db.user_assets.delete_one({"_id": asset["_id"]})
    try:
        from ws import push_to_user
        await push_to_user(asset["userId"], {"type": "asset_update", "assetId": asset_id})
    except Exception:
        pass
    return {"message": f"Актив «{asset.get('name')}» удалён"}


@router.post("/admin/{asset_id}/transfer")
async def admin_transfer_asset(
    asset_id: str,
    payload: AdminTransferBody,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    asset = await _load_any(db, asset_id)
    target = await db.users.find_one({"username": payload.toUsername})
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Игрок не найден")
    new_owner_id = str(target["_id"])
    old_owner_id = asset["userId"]
    await db.user_assets.update_one(
        {"_id": asset["_id"]},
        {"$set": {"userId": new_owner_id, "companyId": None, "rental": None}},
    )
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    try:
        from ws import push_to_user
        await push_to_user(old_owner_id, {"type": "asset_update", "assetId": asset_id})
        await push_to_user(new_owner_id, {"type": "asset_update", "assetId": asset_id})
    except Exception:
        pass
    return {"asset": _serialize(updated)}


# ── Aggregate value (для лидерборда/капитала) ────────────────────────────────


async def total_asset_value(db: AsyncIOMotorDatabase, user_id: str) -> float:
    total = 0.0
    async for a in db.user_assets.find({"userId": user_id}):
        total += _current_value(a)
    return round(total, 2)


if __name__ == "__main__":
    # Санити-чек формулы аренды: цена обязана расти линейно со сроком (в часах)
    # и совпадать с той же формулой, что используется при выставлении объявления.
    demo_asset = {"type": "realestate", "price": 40000, "rarity": "uncommon", "level": 1, "tuning_value": 0.0}
    rate = _rent_rate_per_hour(demo_asset)
    assert rate > 0
    assert abs(_rent_total(demo_asset, 1) - rate) < 0.01
    assert abs(_rent_total(demo_asset, 6) - rate * 6) < 0.05
    assert _rent_total(demo_asset, RENT_MAX_HOURS) == round(_rent_daily_rate(demo_asset) * RENT_MAX_HOURS / 24, 2)
    # 1 час не должен стоить столько же, сколько 30 суток.
    assert _rent_total(demo_asset, 1) < _rent_total(demo_asset, RENT_MAX_HOURS)

    # «Хорошая» недвижимость (rare, напр. Вилла за $160k) должна приносить
    # примерно $2000/сутки только за счёт аренды — таков ориентир баланса.
    villa = {"type": "realestate", "price": 160000, "rarity": "rare", "level": 1, "tuning_value": 0.0}
    assert 1800 <= _rent_daily_rate(villa) <= 2200, _rent_daily_rate(villa)

    # Один и тот же тип актива с разной редкостью НЕ должен зарабатывать одинаково:
    # дешёвый/частый объект уступает дорогому/редкому и в % доходности, и в сумме.
    common_re = {"type": "realestate", "price": 160000, "rarity": "common", "level": 1, "tuning_value": 0.0}
    uncommon_re = {"type": "realestate", "price": 160000, "rarity": "uncommon", "level": 1, "tuning_value": 0.0}
    epic_re = {"type": "realestate", "price": 160000, "rarity": "epic", "level": 1, "tuning_value": 0.0}
    legendary_re = {"type": "realestate", "price": 160000, "rarity": "legendary", "level": 1, "tuning_value": 0.0}
    assert _rent_daily_rate(common_re) < _rent_daily_rate(uncommon_re) < _rent_daily_rate(villa) \
        < _rent_daily_rate(epic_re) < _rent_daily_rate(legendary_re)

    # Настоящий каталог: дешёвая студия НЕ должна почти совпадать по доходности
    # с элитным замком (старый баг — единый пол в $2000 для всех активов).
    studio_rate = _rent_daily_rate(CATALOG_BY_SLUG["studio"] | {"level": 1, "tuning_value": 0.0})
    castle_rate = _rent_daily_rate(CATALOG_BY_SLUG["castle"] | {"level": 1, "tuning_value": 0.0})
    assert studio_rate < 100, studio_rate
    assert castle_rate > 30000, castle_rate
    assert castle_rate / studio_rate > 100

    # Бизнесы и авто тоже сдаются в аренду — у каждого своя ставка через rarity,
    # добавленную в каталог (не одинаковый коэффициент для всего имущества).
    business_asset = {"type": "business", "price": 60000, "rarity": "rare", "level": 1, "tuning_value": 0.0}
    assert _rent_daily_rate(business_asset) > 0
    car_asset = {"type": "car", "price": 150000, "rarity": "rare", "level": 1, "tuning_value": 0.0}
    assert _rent_daily_rate(car_asset) > 0

    non_rentable = {"type": "crypto", "price": 40000, "rarity": "rare", "level": 1}
    assert _rent_rate_per_hour(non_rentable) == 0.0

    print("assets.py rent formula: OK")
    print(f"  studio(common,$5k)   = ${studio_rate}/сутки")
    print(f"  villa(rare,$160k)    = ${_rent_daily_rate(villa)}/сутки")
    print(f"  castle(legendary,$1.5M) = ${castle_rate}/сутки")
