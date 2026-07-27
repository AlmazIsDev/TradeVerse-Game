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

UPGRADE_COST_PCT = 0.32  # доля базовой цены за уровень (см. _upgrade_cost)

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
# Ожидание арендатора НЕ оплачивается, поэтому оно работает как налог на аренду:
# при разбросе 1–48ч (в среднем 24.5ч) суточная сдача приносила лишь 49% ставки,
# а часовая — 4%. Диапазон 1–6ч (в среднем 3.5ч) поднимает те же сценарии до
# 87% и 22% — сдавать становится осмысленно и на короткий срок.
RENT_MAX_WAIT_H = 6      # максимум ожидания арендатора
RENT_MAX_HOURS = 720     # максимальный срок аренды (30 суток)
RENTABLE_TYPES = {"realestate", "car", "business"}
# Среди бизнесов в аренду сдаются только те, у кого есть полезная для арендатора
# механика: IT-студия (заказы «Крыши города», cityroof.py) и Медиахолдинг
# (разоблачения в СМИ, media.py). Остальные бизнесы (шаурмечная, кофейня, завод…)
# сдавать нельзя — арендовать в них нечего, кроме голого дохода.
RENTABLE_BUSINESS_SLUGS = {"media_holding"}   # + любые itstudio_* (по префиксу slug)


def _is_rentable(asset: dict) -> bool:
    """Можно ли выставить актив в аренду. Недвижимость и авто — всегда; бизнесы —
    только IT-студия и Медиахолдинг (см. RENTABLE_BUSINESS_SLUGS)."""
    atype = asset.get("type")
    if atype not in RENTABLE_TYPES:
        return False
    if atype == TYPE_BUSINESS:
        slug = asset.get("slug") or ""
        return slug.startswith("itstudio_") or slug in RENTABLE_BUSINESS_SLUGS
    return True

# ── Экономика аренды ─────────────────────────────────────────────────────────
# У каждого актива — своя суточная ставка аренды: она НЕ одинакова для всего
# имущества, а рассчитывается из совокупности факторов:
#   1) текущая стоимость актива (цена + уровень апгрейда + тюнинг, см. _current_value);
#   2) редкость/класс объекта (rarity) — определяет % от стоимости в сутки;
# Чем реже и роскошнее объект — тем выше именно ПРОЦЕНТ доходности (не только
# абсолютная сумма за счёт более высокой цены). Поэтому дешёвая недвижимость
# даёт скромный доход, а элитная — кратно выгоднее как в долларах, так и в %,
# и не бывает ситуации, когда дешёвый объект почти не уступает дорогому.
#
# Ориентир баланса (единый для всей экономики): суммарная доходность актива —
# 24–30% в сутки, то есть окупаемость 3.3–4.2 дня. Пассивный доход несёт 3/4
# этой цели, аренда — оставшуюся 1/4 (АКТИВНАЯ часть, её надо выставлять
# руками). Раньше пропорция была обратной, и сдаваемый актив в магазине
# выглядел втрое хуже несдаваемого той же цены — карточка показывает только
# пассивный доход. Прежние ставки 2.4–7.8%/сутки давали окупаемость 13–42 дня —
# «поставил и ушёл на месяц», из-за чего активы ощущались бесполезными.
RARITY_RENT_PCT = {
    "common": 0.060,      # 6.0%/сутки
    "uncommon": 0.0625,   # 6.2%/сутки
    "rare": 0.065,        # 6.5%/сутки
    "epic": 0.070,        # 7.0%/сутки
    "legendary": 0.075,   # 7.5%/сутки
}
# Автомобили не имеют пассивного дохода (см. _income_per_hour) — аренда для них
# единственный источник, поэтому она должна нести всю цель целиком, а не 1/4:
# без множителя авто окупались бы вчетверо дольше недвижимости той же редкости.
CAR_RENT_MULT = 4.0
# Минимальный суточный доход по редкости — подстраховка от вырожденных случаев
# (например, сильно уценённый на рынке актив), а НЕ основной драйвер экономики,
# как было раньше (плоский пол в $2000 одинаковый для всех — тот самый баг,
# из-за которого дешёвая студия зарабатывала как элитная недвижимость).
RARITY_RENT_FLOOR = {
    "common": 300.0,
    "uncommon": 850.0,
    "rare": 2500.0,
    "epic": 8500.0,
    "legendary": 22000.0,
}

# ── Материалы для бизнеса ────────────────────────────────────────────────────
# Цена за единицу = базовая × economy_mult × множитель текущего мирового
# события (см. market_events.EVENT_TYPES["materials"], настраивается через
# админ-панель — событие меняется, цена пересчитывается автоматически, без
# правки кода). Закупка временно поднимает доход бизнеса.
#
# Это ГЛАВНАЯ активная механика бизнеса: пассивный доход капает сам, а буст
# требует зайти и вложиться. Поэтому потолок высокий (+80%), а срок короткий
# (4ч) — активный игрок обгоняет пассивного примерно в 1.5 раза, но обязан
# возвращаться. Цена единицы — доля от часового дохода конкретного бизнеса
# (MATERIALS_COST_PER_INCOME_H), иначе буст премиальной IT-студии стоил бы
# столько же, сколько буст шаурмечной, то есть был бы бесплатным.
MATERIALS_BOOST_PER_UNIT = 0.02     # +2% к доходу за единицу
MATERIALS_BOOST_CAP = 0.80          # максимум +80%
MATERIALS_DURATION_H = 4            # действует 4 часа с момента закупки
# Единица материалов стоит столько же, сколько бизнес зарабатывает за этот
# процент дохода примерно за 1.6ч — полный буст окупается за ~2.5ч из 4ч срока.
MATERIALS_COST_PER_INCOME_H = 1.6

# ── Каталог рынка (сид) ──────────────────────────────────────────────────────
# income_per_hour — пассивный доход; upkeep_per_hour — расход (для бизнесов).
# rarity — определяет и рыночный дрейф цены (RARITY_FLOOR), и ставку аренды
# (RARITY_RENT_PCT/RARITY_RENT_FLOOR) — есть у всех типов, включая бизнесы.
#
# Баланс доходности: чистый пассивный доход (income − upkeep) подобран так,
# чтобы вместе с арендой актив выходил на 24–30% в сутки (окупаемость 3.3–4.2
# дня, растёт с редкостью). Пассив несёт 3/4 цели, аренда — 1/4; несдаваемые
# бизнесы (шаурмечная, кофейня, автомойка, завод) несут всю доходность в
# income_per_hour. Доход экземпляра масштабируется по уплаченной цене
# (см. buy_asset) — на пике рынка актив и стоит, и приносит больше.

CATALOG = [
    # Недвижимость: аренда как доход, налог как расход
    {"slug": "studio", "type": TYPE_REALESTATE, "name": "Студия", "rarity": "common",
     "price": 5000, "income_per_hour": 50, "upkeep_per_hour": 12, "rooms": 1, "meta": {"tax": 12}},
    {"slug": "flat2", "type": TYPE_REALESTATE, "name": "Двухкомнатная квартира", "rarity": "common",
     "price": 14000, "income_per_hour": 140, "upkeep_per_hour": 35, "rooms": 2, "meta": {"tax": 35}},
    {"slug": "townhouse", "type": TYPE_REALESTATE, "name": "Таунхаус", "rarity": "uncommon",
     "price": 45000, "income_per_hour": 469, "upkeep_per_hour": 117, "rooms": 4, "meta": {"tax": 117}},
    {"slug": "villa", "type": TYPE_REALESTATE, "name": "Вилла у моря", "rarity": "rare",
     "price": 160000, "income_per_hour": 1733, "upkeep_per_hour": 433, "rooms": 6, "meta": {"tax": 433}},
    {"slug": "penthouse", "type": TYPE_REALESTATE, "name": "Пентхаус", "rarity": "epic",
     "price": 480000, "income_per_hour": 5600, "upkeep_per_hour": 1400, "rooms": 8, "meta": {"tax": 1400}},
    {"slug": "castle", "type": TYPE_REALESTATE, "name": "Замок", "rarity": "legendary",
     "price": 1500000, "income_per_hour": 18750, "upkeep_per_hour": 4688, "rooms": 20, "meta": {"tax": 4688}},
    # Бизнесы: доход и расходы, есть сотрудники. rarity — экономический класс
    # бизнеса (отдельно от category, которая отвечает только за тематику/иконку).
    {"slug": "shawarma", "type": TYPE_BUSINESS, "name": "Шаурмечная", "category": "retail", "rarity": "common",
     "price": 8000, "income_per_hour": 119, "upkeep_per_hour": 39, "employees": 2},
    {"slug": "coffee", "type": TYPE_BUSINESS, "name": "Кофейня", "category": "retail", "rarity": "uncommon",
     "price": 25000, "income_per_hour": 389, "upkeep_per_hour": 128, "employees": 4},
    {"slug": "carwash", "type": TYPE_BUSINESS, "name": "Автомойка", "category": "service", "rarity": "rare",
     "price": 60000, "income_per_hour": 970, "upkeep_per_hour": 320, "employees": 6},
    # IT-студия — 4 тира (slug = "itstudio_" + ключ тира в game_config.ITSTUDIO_CONFIG).
    # Владение экземпляром открывает заказ атаки/защиты «Крыши города»
    # (см. cityroof.py) — материалы, шанс успеха и опыт зависят от тира.
    {"slug": "itstudio_basic", "type": TYPE_BUSINESS, "name": "IT-студия: Базовая", "category": "tech", "rarity": "epic",
     "price": 200000, "income_per_hour": 2612, "upkeep_per_hour": 862, "employees": 12},
    {"slug": "itstudio_medium", "type": TYPE_BUSINESS, "name": "IT-студия: Средняя", "category": "tech", "rarity": "epic",
     "price": 450000, "income_per_hour": 5877, "upkeep_per_hour": 1939, "employees": 20},
    {"slug": "itstudio_advanced", "type": TYPE_BUSINESS, "name": "IT-студия: Продвинутая", "category": "tech", "rarity": "legendary",
     "price": 900000, "income_per_hour": 12593, "upkeep_per_hour": 4156, "employees": 32},
    {"slug": "itstudio_premium", "type": TYPE_BUSINESS, "name": "IT-студия: Премиальная", "category": "tech", "rarity": "legendary",
     "price": 1800000, "income_per_hour": 25187, "upkeep_per_hour": 8312, "employees": 50},
    {"slug": "factory", "type": TYPE_BUSINESS, "name": "Завод", "category": "office", "rarity": "legendary",
     "price": 750000, "income_per_hour": 13993, "upkeep_per_hour": 4618, "employees": 40},
    # Медиахолдинг — открывает заказ разоблачений в СМИ (см. media.py): владелец
    # может ударить по доходам бизнесов конкурента и цене его акции.
    {"slug": "media_holding", "type": TYPE_BUSINESS, "name": "Медиахолдинг", "category": "media", "rarity": "legendary",
     "price": 1200000, "income_per_hour": 16791, "upkeep_per_hour": 5541, "employees": 45},
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


class TransferToPlayer(BaseModel):
    """Передача личного актива другому игроку по нику."""
    toUsername: str

    @field_validator("toUsername")
    @classmethod
    def name_ok(cls, v):
        v = (v or "").strip()
        if len(v) < 2:
            raise ValueError("Укажите ник игрока")
        return v[:40]


# ── Helpers ──────────────────────────────────────────────────────────────────


_now = now_utc


def _price_mult(asset: dict) -> float:
    """Во сколько раз экземпляр куплен дороже базовой цены каталога.

    Рынок гоняет цену в ×0.5…×2.5 (ASSET_MULT_MIN/MAX), и без этой привязки
    доход оставался бы базовым: купленный на пике актив окупался бы 8 дней
    вместо 3.3, а на просадке — 1.7. Доход масштабируется вместе с ценой,
    поэтому рыночный множитель решает, СКОЛЬКО вложить, а не насколько
    выгодна сделка. Активы, купленные до появления поля, считаются как ×1.0."""
    return float(asset.get("price_mult", 1.0) or 1.0)


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
    # Авто не приносят почасового пассивного дохода — только аренда (см. _is_rentable).
    # Их «уровень» не качается через upgrade, прогресс идёт через тюнинг/престиж.
    if asset.get("type") == TYPE_CAR:
        return 0.0
    base = asset.get("income_per_hour", 0)
    level = asset.get("level", 1)
    value = base * (1 + 0.25 * (level - 1)) * _price_mult(asset)
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
    Авто получают повышенную ставку (CAR_RENT_MULT) — у них нет пассивного дохода.
    RARITY_RENT_FLOOR — лишь подстраховка от вырожденно низких значений, а не
    основной регулятор (как было раньше с плоским полом в $2000 для всех).
    Как и пассивный доход, ставка масштабируется по уплаченной цене (_price_mult)."""
    if not _is_rentable(asset):
        return 0.0
    rarity = _rent_rarity(asset)
    pct = RARITY_RENT_PCT[rarity]
    floor = RARITY_RENT_FLOOR[rarity]
    if asset.get("type") == TYPE_CAR:
        pct *= CAR_RENT_MULT
        floor *= CAR_RENT_MULT
    return round(max(floor, _current_value(asset) * pct) * _price_mult(asset), 2)


def _rent_rate_per_hour(asset: dict) -> float:
    """Ставка аренды в час — для отображения клиенту (не используется в расчёте
    итоговой суммы, чтобы округление ставки не накапливалось на длинных сроках)."""
    return round(_rent_daily_rate(asset) / 24, 2)


def _rent_total(asset: dict, hours: int) -> float:
    """Итоговая стоимость аренды за срок — линейно от часов, единая формула для
    клиента (превью) и сервера (авторитетный пересчёт при выставлении объявления)."""
    if not _is_rentable(asset):
        return 0.0
    return round(_rent_daily_rate(asset) * hours / 24, 2)


def _upkeep_per_hour(asset: dict) -> float:
    # Масштабируется вместе с доходом (см. _price_mult), иначе купленный на пике
    # актив имел бы прежний расход при повышенном доходе — доходность в % росла бы.
    return round(asset.get("upkeep_per_hour", 0) * _price_mult(asset), 2)


def _upgrade_cost(asset: dict) -> float:
    """Улучшение стоит фиксированную долю базовой цены — НЕ растёт с уровнем.

    Прирост дохода за уровень плоский (+25% базы, см. _income_per_hour), поэтому
    цена вида base*0.4*level делала апгрейд всё хуже: L1→L2 окупался за 3.6 суток,
    а L5→L6 уже за 18 — качать актив было втрое невыгоднее, чем купить второй.
    При плоской доле окупаемость улучшения (2.9–4.0 суток) совпадает с покупкой
    нового актива (3.3–4.2), и уровень перестаёт быть ловушкой."""
    base = asset.get("price", 0)
    # Доход экземпляра масштабируется ценой покупки (_price_mult) — цена улучшения тоже,
    # иначе купленный на пике актив качался бы по базовой цене за повышенный доход.
    return round(base * UPGRADE_COST_PCT * _price_mult(asset), 2)


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


async def company_income_per_hour(db: AsyncIOMotorDatabase, company_id: str,
                                  media_factor: float = 1.0) -> float:
    """Чистый доход компании в час от принадлежащих ей активов.

    ``media_factor`` — репутационный множитель СМИ владельца: применяется только
    к доходной части бизнесов (расходы/содержание и небизнес-активы не трогаем)."""
    total = 0.0
    async for a in db.user_assets.find({"companyId": company_id}):
        income = _income_per_hour(a)
        if media_factor != 1.0 and a.get("type") == TYPE_BUSINESS:
            income = round(income * media_factor, 2)
        total += (income - _upkeep_per_hour(a))
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
        # Куплено дороже/дешевле базы → доход и расход экземпляра масштабируются
        # так же (см. _price_mult), иначе покупка на пике рынка была бы ловушкой.
        "price_mult": round(mult, 4),
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
    # Актив, переданный в компанию, приносит доход в бюджет компании (отдельный
    # last_tick). Личный сбор по нему запрещён — иначе один актив платит дважды
    # (владельцу лично И в бюджет компании).
    if asset.get("companyId"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Актив принадлежит компании — доход идёт в бюджет компании")
    econ = await get_econ(db)
    event_income = await _event_income_shift(db)
    city_bonus = await _city_asset_bonus(db, user_id)
    media_factor = await _media_income_factor(db, user_id)
    amount = await _collect_asset_income(db, user_id, asset, econ, event_income, city_bonus, media_factor)
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


async def _event_income_shift(db) -> float:
    try:
        from market_events import event_shifts
        return (await event_shifts(db)).get("income", 1.0)
    except Exception:
        return 1.0


async def _city_asset_bonus(db, user_id: str) -> float:
    try:
        from cityroof import player_city_effect
        return await player_city_effect(db, user_id, "asset_income")
    except Exception:
        return 0.0


async def _media_income_factor(db, user_id: str) -> float:
    """Репутационный множитель СМИ для бизнесов игрока (1.0 — нет эффектов)."""
    try:
        from media import active_owner_income_factor
        return await active_owner_income_factor(db, user_id)
    except Exception:
        return 1.0


async def _collect_asset_income(db, user_id: str, asset: dict, econ: dict,
                                event_income: float, city_bonus: float,
                                media_factor: float = 1.0) -> float:
    """Считает и применяет (обнуляет КД) доход одного актива, возвращает сумму.
    Множители (econ/событие/город/СМИ) передаются готовыми, чтобы при массовом
    сборе не пересчитывать их на каждый актив.

    ``media_factor`` — репутационный множитель СМИ (media.py): применяется только
    к бизнесам владельца (недвижимость/авто не затрагиваются разоблачением).

    Присвоение накопления атомарно: last_collected сбрасывается условным
    апдейтом по ТОМУ ЖЕ значению, что было прочитано. Если два параллельных
    запроса читают один last_collected, апдейт сработает лишь у одного —
    второй получит 0 (иначе доход дублировался бы, TOCTOU)."""
    seen = asset.get("last_collected")
    matched = await db.user_assets.update_one(
        {"_id": asset["_id"], "last_collected": seen},
        {"$set": {"last_collected": _now()}},
    )
    if matched.modified_count == 0:
        return 0.0  # накопление уже присвоено параллельным запросом
    amount = _accrued(asset)
    amount = round(amount * econ.get("income_mult", 1.0) * econ.get("economy_mult", 1.0), 2)
    amount = round(amount * event_income, 2)
    if city_bonus:
        amount = round(amount * (1 + city_bonus), 2)
    if media_factor != 1.0 and asset.get("type") == TYPE_BUSINESS:
        amount = round(amount * media_factor, 2)
    return amount


@router.post("/collect-all")
async def collect_all_income(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Собрать накопленный доход со всех личных активов игрока разом."""
    user_id = str(current_user["_id"])
    econ = await get_econ(db)
    event_income = await _event_income_shift(db)
    city_bonus = await _city_asset_bonus(db, user_id)
    media_factor = await _media_income_factor(db, user_id)

    total = 0.0
    count = 0
    async for asset in db.user_assets.find({"userId": user_id, "companyId": None}):
        if asset.get("income_per_hour", 0) <= 0:
            continue
        amount = await _collect_asset_income(db, user_id, asset, econ, event_income, city_bonus, media_factor)
        if amount <= 0:
            continue
        new_balance = await adjust_balance(db, user_id, amount)
        cat = CAT_BUSINESS if asset["type"] == TYPE_BUSINESS else CAT_REALESTATE
        await record_transaction(
            db, user_id, INCOME, amount, cat,
            f"Доход: {asset['name']}", balance_after=new_balance,
            meta={"slug": asset.get("slug"), "assetId": str(asset["_id"])},
        )
        total = round(total + amount, 2)
        count += 1

    balance = current_user.get("balance", 0.0)
    if count:
        u = await db.users.find_one({"_id": ObjectId(user_id)}, {"balance": 1})
        balance = (u or {}).get("balance", balance)
    return {"collected": round(total, 2), "count": count, "balance": balance}


@router.post("/{asset_id}/upgrade")
async def upgrade_asset(
    asset_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Улучшить актив: повышает стоимость и доход."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    # Авто не улучшаются через уровень — у них нет почасового дохода, а стоимость
    # растят тюнингом деталей (см. /tune). Поэтому уровень авто всегда 1.
    if asset.get("type") == TYPE_CAR:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Автомобиль не улучшается по уровню — используйте тюнинг деталей")
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
    # Стоимость продажи учитывает тот же рыночный множитель, что и покупка —
    # иначе при mult<0.7 возникает арбитраж (купил за 0.5×base, продал за
    # 0.7×base). Множитель применяется к базовой стоимости экземпляра; тюнинг
    # (tuning_value) и накопленный доход к рынку не привязаны.
    await _ensure_asset_market(db)
    mult = await _asset_mult(db, asset.get("slug"))
    base_value = round(_current_value(asset) - asset.get("tuning_value", 0.0), 2)
    market_value = round(base_value * mult + asset.get("tuning_value", 0.0), 2)
    payout = round(market_value * SELL_RATE + _accrued(asset), 2)
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


@router.post("/{asset_id}/transfer-to-player")
async def transfer_to_player(
    asset_id: str,
    payload: TransferToPlayer,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Подарить личный актив другому игроку по нику. Актив уходит целиком
    (со всеми улучшениями/материалами) — доход по нему начнёт получать новый
    владелец. Нельзя передавать активы, отданные компании или сдаваемые."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    if asset.get("companyId"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Актив принадлежит компании — сначала верните его себе")
    if asset.get("rental"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Актив сдаётся или ждёт арендатора — снимите с аренды")
    target = await db.users.find_one({"username": payload.toUsername})
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Игрок не найден")
    new_owner_id = str(target["_id"])
    if new_owner_id == user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя передать актив самому себе")
    # Копим доход у прежнего владельца обнуляется — новый владелец начинает с чистого КД.
    await db.user_assets.update_one(
        {"_id": asset["_id"]},
        {"$set": {"userId": new_owner_id, "companyId": None, "rental": None, "last_collected": _now()}},
    )
    try:
        from ws import push_to_user
        await push_to_user(user_id, {"type": "asset_update", "assetId": asset_id})
        await push_to_user(new_owner_id, {"type": "asset_update", "assetId": asset_id})
    except Exception:
        pass
    return {"ok": True, "toUsername": payload.toUsername}


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
    if not _is_rentable(asset):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Сдавать можно недвижимость, авто, а из бизнесов — только IT-студию и Медиахолдинг")
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


async def _materials_unit_price(db: AsyncIOMotorDatabase, asset: Optional[dict] = None) -> float:
    """Цена единицы материалов для конкретного бизнеса.

    Пропорциональна часовому доходу бизнеса: единица даёт +MATERIALS_BOOST_PER_UNIT
    к доходу, поэтому и стоить должна долю от того, что этот процент приносит.
    Без актива (общий прайс до выбора бизнеса) считаем по самому дешёвому
    бизнесу каталога — это нижняя граница, которую клиент показывает как «от».
    """
    econ = await get_econ(db)
    mult = econ.get("economy_mult", 1.0)
    try:
        from market_events import event_shifts
        mult *= (await event_shifts(db)).get("materials", 1.0)
    except Exception:
        pass
    if asset is not None:
        income_h = _income_per_hour(asset) / (1 + _materials_boost(asset))
    else:
        income_h = min(c["income_per_hour"] for c in CATALOG if c["type"] == TYPE_BUSINESS)
    unit = income_h * MATERIALS_BOOST_PER_UNIT * MATERIALS_COST_PER_INCOME_H
    return round(max(1.0, unit) * mult, 2)


@router.get("/materials/price")
async def materials_price(
    assetId: str = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Текущая цена материалов за единицу. Зависит от активного мирового события
    и от самого бизнеса (цена пропорциональна его доходу) — без assetId вернём
    нижнюю границу по каталогу."""
    asset = None
    if assetId:
        asset = await _load_owned(db, str(current_user["_id"]), assetId)
    return {
        "unitPrice": await _materials_unit_price(db, asset),
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

    unit_price = await _materials_unit_price(db, asset)
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

    # Ориентир баланса: вилла (rare, $160k) — аренда несёт 1/4 доходности,
    # остальное даёт пассивный доход (см. RARITY_RENT_PCT).
    villa = {"type": "realestate", "price": 160000, "rarity": "rare", "level": 1, "tuning_value": 0.0}
    assert 9000 <= _rent_daily_rate(villa) <= 12000, _rent_daily_rate(villa)

    # Суммарная доходность каждого актива каталога — 24–31%/сутки (окупаемость
    # 3.2–4.2 дня). Единый ориентир для всей экономики: активы, ферма и компании
    # должны отбиваться за сопоставимое время, иначе один класс обесценивает остальные.
    for _c in CATALOG:
        _inst = _c | {"level": 1, "tuning_value": 0.0}
        _daily = (_income_per_hour(_inst) - _upkeep_per_hour(_inst)) * 24 + _rent_daily_rate(_inst)
        _pct = _daily / _c["price"] * 100
        assert 23.0 <= _pct <= 31.0, f"{_c['slug']}: {_pct:.1f}%/сутки вне коридора 23–31"

    # Авто не имеют пассивного дохода, поэтому их аренда дороже недвижимости той
    # же редкости (CAR_RENT_MULT) — иначе машины были бы заведомо худшим активом.
    _car_epic = {"type": "car", "price": 600000, "rarity": "epic", "level": 1, "tuning_value": 0.0}
    _re_epic = {"type": "realestate", "price": 600000, "rarity": "epic", "level": 1, "tuning_value": 0.0}
    assert _rent_daily_rate(_car_epic) > _rent_daily_rate(_re_epic)

    # Ожидание арендатора не должно съедать короткую сдачу: при среднем ожидании
    # (RENT_MIN_WAIT_H+RENT_MAX_WAIT_H)/2 суточная аренда реализует >80% ставки.
    _avg_wait = (RENT_MIN_WAIT_H + RENT_MAX_WAIT_H) / 2
    assert 24 / (24 + _avg_wait) > 0.8, "мёртвое ожидание съедает суточную аренду"

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
    assert studio_rate < 1500, studio_rate
    assert castle_rate > 100000, castle_rate
    assert castle_rate / studio_rate > 100

    # Бизнесы и авто тоже сдаются в аренду — у каждого своя ставка через rarity,
    # добавленную в каталог (не одинаковый коэффициент для всего имущества).
    # НО из бизнесов сдаются только IT-студия и Медиахолдинг (у остальных нет
    # полезной арендатору механики), поэтому у бизнеса важен slug.
    studio_biz = CATALOG_BY_SLUG["itstudio_basic"] | {"level": 1, "tuning_value": 0.0}
    media_biz = CATALOG_BY_SLUG["media_holding"] | {"level": 1, "tuning_value": 0.0}
    plain_biz = CATALOG_BY_SLUG["coffee"] | {"level": 1, "tuning_value": 0.0}
    assert _is_rentable(studio_biz) and _rent_daily_rate(studio_biz) > 0
    assert _is_rentable(media_biz) and _rent_daily_rate(media_biz) > 0
    # Обычный бизнес (кофейня) сдавать нельзя — ставка 0.
    assert not _is_rentable(plain_biz)
    assert _rent_daily_rate(plain_biz) == 0.0
    car_asset = CATALOG_BY_SLUG["super"] | {"level": 1, "tuning_value": 0.0}
    assert _is_rentable(car_asset)
    assert _rent_daily_rate(car_asset) > 0
    # Авто НЕ приносят почасового дохода — только аренда (даже если в данные
    # просочилась ненулевая ставка income_per_hour).
    assert _income_per_hour(CATALOG_BY_SLUG["super"] | {"income_per_hour": 999}) == 0.0
    # Недвижимость по-прежнему сдаётся без всяких slug-ограничений.
    assert _is_rentable({"type": "realestate", "slug": "studio"})

    non_rentable = {"type": "crypto", "price": 40000, "rarity": "rare", "level": 1}
    assert _rent_rate_per_hour(non_rentable) == 0.0
    assert not _is_rentable(non_rentable)

    # Купленный на пике рынка актив окупается за то же время, что купленный на
    # просадке: доход, расход и аренда масштабируются вместе с ценой (_price_mult).
    # Иначе покупка при ×2.5 растягивала бы окупаемость с 3.3 до 8 суток.
    _base = CATALOG_BY_SLUG["itstudio_premium"] | {"level": 1, "tuning_value": 0.0}
    def _payback_pct(mult):
        _inst = _base | {"price_mult": mult}
        _daily = (_income_per_hour(_inst) - _upkeep_per_hour(_inst)) * 24 + _rent_daily_rate(_inst)
        return _daily / (_base["price"] * mult) * 100
    for _m in (ASSET_MULT_MIN, 1.0, ASSET_MULT_MAX):
        assert abs(_payback_pct(_m) - _payback_pct(1.0)) < 0.1, (_m, _payback_pct(_m))
    # Активы, купленные до появления поля, считаются как ×1.0.
    assert _income_per_hour(_base) == _income_per_hour(_base | {"price_mult": 1.0})

    # Качать актив должно быть не хуже, чем купить ещё один: окупаемость улучшения
    # не растёт с уровнем и держится в том же коридоре, что покупка нового.
    # (Старый баг: цена улучшения base*0.4*level при плоском приросте дохода —
    # L1→L2 окупался за 3.6 суток, L5→L6 за 18.)
    def _daily(asset):
        return (_income_per_hour(asset) - _upkeep_per_hour(asset)) * 24 + _rent_daily_rate(asset)
    for _c in CATALOG:
        if _c["type"] == TYPE_CAR:   # авто качаются тюнингом, а не уровнем
            continue
        _lvl1 = _c | {"level": 1, "tuning_value": 0.0}
        _buy_days = _c["price"] / _daily(_lvl1)
        for _lvl in (1, 5, 10):
            _inst = _c | {"level": _lvl, "tuning_value": 0.0}
            _gain = _daily(_c | {"level": _lvl + 1, "tuning_value": 0.0}) - _daily(_inst)
            _days = _upgrade_cost(_inst) / _gain
            assert _days <= _buy_days + 0.5, f"{_c['slug']} ур.{_lvl}: апгрейд {_days:.1f}д против покупки {_buy_days:.1f}д"
    # Цена улучшения следует за ценой покупки — как и доход экземпляра.
    assert _upgrade_cost(_base | {"price_mult": 2.5}) == _upgrade_cost(_base) * 2.5

    print("assets.py rent formula: OK")
    print(f"  studio(common,$5k)   = ${studio_rate}/сутки")
    print(f"  villa(rare,$160k)    = ${_rent_daily_rate(villa)}/сутки")
    print(f"  castle(legendary,$1.5M) = ${castle_rate}/сутки")
