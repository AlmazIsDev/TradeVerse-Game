"""Крыша города: еженедельное PvP-событие за бизнесы на карте и WarCoin."""
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator
from pymongo.errors import DuplicateKeyError

from admin_perms import get_current_user, require_admin, require_allowed
from database import get_db, find_config_by_key, upsert_config
from ledger import INCOME, EXPENSE, CAT_CITYROOF, adjust_balance, record_transaction
from notifications import push_notification
from game_config import ITSTUDIO_CONFIG
from timeutil import now_utc, to_aware
from networth import compute_net_worth

router = APIRouter(prefix="/api/cityroof", tags=["cityroof"])

ATTACK_COST_WC = 10
MAX_ATTEMPTS = 3
PROTECTION_MAX = 5
WINNER_REWARD_WC = 500

# Фиксированная стоимость WarCoin: 1 WC = 50$ (настраивается админом).
WARCOIN_PRICE_DEFAULT = 50.0

# Стоимость уровней защиты (WC).
PROTECTION_COSTS = {1: 1000, 2: 3000, 3: 4000, 4: 6500, 5: 10000}

# ── IT-студия: атака/защита силами собственного актива-студии ────────────────
# Игрок должен ВЛАДЕТЬ бизнесом «IT-студия» (assets.py, slug itstudio_*, 4
# тира) — атака/защита, материалы, стоимость, шанс успеха и опыт студии
# зависят от тира. Все числа — в одном месте, см. game_config.ITSTUDIO_CONFIG.
# Оплачивается в $ (не WC — отдельная услуга, не завязанная на PvP-экономику
# карты). Выполняется через 1–3ч реального времени (конфигурируемо).

BONUS_CLAIM_INTERVAL_MIN = 5    # КД дохода — свой у каждого бизнеса, раз в 5 минут
DAILY_TO_INTERVAL_DIVISOR = 288  # 24ч·60/5мин — делим дневную ставку на кол-во 5-минуток в сутках

# Уникальный игровой эффект каждого здания.
#   daily  — доход владельцу в пересчёте на сутки; фактически начисляется
#            автосбором каждые BONUS_CLAIM_INTERVAL_MIN минут по формуле
#            daily / DAILY_TO_INTERVAL_DIVISOR (см. _interval_amount).
#   effect — КАЖДЫЙ эффект влияет на реально существующую подсистему игры и
#            подключён в коде (см. player_city_effect ниже). Никаких «мёртвых»
#            бонусов вроде перевозок/логистики/медиа — только то, что работает:
#     rental_income    → выплата аренды недвижимости/авто (assets._process_rental)
#     asset_income     → сбор пассивного дохода активов (assets.collect_income)
#     company_income   → сбор прибыли компании (company.collect_profit)
#     mining_yield     → доход майнинг-фермы (mining._compute)
#     mining_energy    → скидка на электричество фермы (mining._compute)
#     shop_discount    → скидка на оборудование в магазине (shop)
#     warcoin_discount → скидка на покупку WarCoin (cityroof.buy_warcoin)
#     daily_cash       → только ежедневный доход (mult не используется)
# КД дохода — персональный у каждого бизнеса (last_collected на документе, а
# не на пользователе): захват одного здания не блокирует доход с остальных, а
# при смене владельца недособранный КД переходит по наследству.
# Баланс: WarCoin стоит 50$/шт, защита топ-объекта — до 10 000 WC (500 000$),
# поэтому крупные объекты приносят ≈100 000$/сутки, чтобы борьба за них и
# вложения в WarCoin окупались. Мелкие объекты — пропорционально меньше.
BUSINESS_BONUS = {
    "market":   {"daily": 55000,  "effect": "asset_income",     "mult": 0.05},
    "bank":     {"daily": 85000,  "effect": "company_income",   "mult": 0.05},
    "casino":   {"daily": 120000, "effect": "warcoin_discount", "mult": 0.10},
    "port":     {"daily": 70000,  "effect": "shop_discount",    "mult": 0.08},
    "mall":     {"daily": 60000,  "effect": "asset_income",     "mult": 0.05},
    "factory":  {"daily": 90000,  "effect": "mining_yield",     "mult": 0.10},
    "stadium":  {"daily": 50000,  "effect": "daily_cash",       "mult": 0.00},
    "airport":  {"daily": 110000, "effect": "shop_discount",    "mult": 0.10},
    "hotel":    {"daily": 45000,  "effect": "rental_income",    "mult": 0.15},
    "tower":    {"daily": 100000, "effect": "company_income",   "mult": 0.08},
    "studio":   {"daily": 48000,  "effect": "asset_income",     "mult": 0.05},
    "refinery": {"daily": 115000, "effect": "mining_energy",    "mult": 0.15},
}

OWNER_COLORS = [
    "#6366f1", "#22c55e", "#f97316", "#ec4899",
    "#eab308", "#06b6d4", "#a855f7", "#ef4444",
]

DEFAULT_BUSINESSES = [
    {"slug": "market", "name": "Центральный рынок", "x": 0, "y": 0, "reward": 250},
    {"slug": "bank", "name": "Городской банк", "x": 1, "y": 0, "reward": 400},
    {"slug": "casino", "name": "Казино «Роял»", "x": 2, "y": 0, "reward": 600},
    {"slug": "port", "name": "Морской порт", "x": 3, "y": 0, "reward": 500},
    {"slug": "mall", "name": "Торговый центр", "x": 0, "y": 1, "reward": 350},
    {"slug": "factory", "name": "Завод", "x": 1, "y": 1, "reward": 450},
    {"slug": "stadium", "name": "Стадион", "x": 2, "y": 1, "reward": 380},
    {"slug": "airport", "name": "Аэропорт", "x": 3, "y": 1, "reward": 700},
    {"slug": "hotel", "name": "Гранд-отель", "x": 0, "y": 2, "reward": 300},
    {"slug": "tower", "name": "Бизнес-башня", "x": 1, "y": 2, "reward": 550},
    {"slug": "studio", "name": "Киностудия", "x": 2, "y": 2, "reward": 320},
    {"slug": "refinery", "name": "Нефтебаза", "x": 3, "y": 2, "reward": 650},
]

WARCOIN_CONFIG_KEY = "warcoin_config"
ROOM_CAPACITY = 8
CITYROOF_LEAGUES = (
    ("novice", 0),
    ("bronze", 1_000_000),
    ("silver", 25_000_000),
    ("gold", 250_000_000),
    ("platinum", 1_000_000_000),
    ("diamond", 5_000_000_000),
)
LEAGUE_MULTIPLIERS = {
    "novice": 1, "bronze": 25, "silver": 250,
    "gold": 1_000, "platinum": 5_000, "diamond": 20_000,
}
LEAGUE_INCOME_MULTIPLIERS = {
    "novice": 1, "bronze": 10, "silver": 50,
    "gold": 250, "platinum": 1_000, "diamond": 6_100,
}
LEAGUE_WARCOIN_PRICES = {name: WARCOIN_PRICE_DEFAULT * multiplier for name, multiplier in LEAGUE_MULTIPLIERS.items()}
LEAGUE_ATTACK_COSTS = {name: 10 for name in LEAGUE_MULTIPLIERS}
WARCOIN_MIGRATION_KEY = "cityroof_warcoin_migration_v2"


def _migrate_warcoin_amount(amount: int, league: str) -> int:
    return max(0, int(int(amount or 0) / LEAGUE_MULTIPLIERS[league]))


def _business_bonus_view(slug: str, league: str) -> dict:
    bonus = BUSINESS_BONUS.get(slug, {})
    multiplier = LEAGUE_INCOME_MULTIPLIERS.get(league, 1)
    return {
        "daily": round(bonus.get("daily", 0) * multiplier, 2),
        "effect": bonus.get("effect"), "mult": bonus.get("mult", 0),
        "leagueMultiplier": multiplier,
    }


async def _migrate_warcoin_balances(db):
    if await find_config_by_key(db, WARCOIN_MIGRATION_KEY):
        return
    async for user in db.users.find({"warcoin": {"$gt": 0}}, {"warcoin": 1, "balance": 1}):
        league = _league_for_net_worth(await compute_net_worth(db, str(user["_id"])))
        await db.users.update_one(
            {"_id": user["_id"]},
            {"$set": {"warcoin": _migrate_warcoin_amount(user.get("warcoin", 0), league)}},
        )
    import json
    await upsert_config(db, WARCOIN_MIGRATION_KEY, json.dumps({"done": True, "version": 2}))


# Цены и награды масштабируются одинаково: долларовая стоимость PvP не меняется по лигам.
DEFAULT_WARCOIN_CONFIG = {
    "price": WARCOIN_PRICE_DEFAULT,
    "leagues": [
        {"name": name, "minNetWorth": minimum,
         "warcoinPrice": LEAGUE_WARCOIN_PRICES[name],
         "attackCost": LEAGUE_ATTACK_COSTS[name],
         "incomeMultiplier": LEAGUE_INCOME_MULTIPLIERS[name]}
        for name, minimum in CITYROOF_LEAGUES
    ],
}


def _league_for_net_worth(net_worth: float) -> str:
    league = CITYROOF_LEAGUES[0][0]
    for name, minimum in CITYROOF_LEAGUES:
        if float(net_worth or 0) >= minimum:
            league = name
    return league


def _cityroof_capital(net_worth_without_cityroof_wc: float, warcoin: int, warcoin_price: float) -> float:
    return round(float(net_worth_without_cityroof_wc or 0) + int(warcoin or 0) * float(warcoin_price), 2)


def _league_transition(league: str, capital: float) -> str:
    index = next(i for i, (name, _) in enumerate(CITYROOF_LEAGUES) if name == league)
    if index < len(CITYROOF_LEAGUES) - 1 and capital >= CITYROOF_LEAGUES[index + 1][1] * 1.25:
        return CITYROOF_LEAGUES[index + 1][0]
    if index > 0 and capital < CITYROOF_LEAGUES[index][1] * 0.75:
        return CITYROOF_LEAGUES[index - 1][0]
    return league


async def _cityroof_player_capital(db, user_id: str, league: str) -> float:
    user = await db.users.find_one({"_id": ObjectId(user_id)}, {"warcoin": 1}) or {}
    total = await compute_net_worth(db, user_id)
    global_wc_value = int(user.get("warcoin", 0) or 0) * WARCOIN_PRICE_DEFAULT
    price = LEAGUE_WARCOIN_PRICES[league]
    return _cityroof_capital(total - global_wc_value, user.get("warcoin", 0), price)


def _room_code(league: str, room_number: int) -> str:
    return f"{league[:3].upper()}-{room_number:02d}"


async def ensure_player_room(db, user_id: str, season: int, net_worth: float, league_override: str | None = None) -> dict:
    league = league_override or _league_for_net_worth(net_worth)
    existing = await db.cityroof_rooms.find_one({"season": season, "member_ids": user_id})
    if existing:
        return existing
    query = {"season": season, "league": league, "$expr": {"$lt": [{"$size": "$member_ids"}, ROOM_CAPACITY]}}
    room = await db.cityroof_rooms.find_one(query)
    if room and user_id not in room.get("member_ids", []):
        result = await db.cityroof_rooms.update_one(
            {
                "_id": room["_id"], "member_ids": {"$ne": user_id},
                "$expr": {"$lt": [{"$size": "$member_ids"}, ROOM_CAPACITY]},
            },
            {"$addToSet": {"member_ids": user_id}},
        )
        if result.modified_count:
            room["member_ids"] = [*room.get("member_ids", []), user_id]
            return room
        return await ensure_player_room(db, user_id, season, net_worth)
    if room:
        return room
    count = await db.cityroof_rooms.count_documents({"season": season, "league": league})
    room = {"season": season, "league": league, "room_code": _room_code(league, count + 1), "member_ids": [user_id]}
    try:
        await db.cityroof_rooms.insert_one(room)
    except DuplicateKeyError:
        return await ensure_player_room(db, user_id, season, net_worth)
    return room


async def _league_config(config: dict, league: str) -> dict:
    for item in config.get("leagues", []):
        if item.get("name") == league:
            return item
    return next(item for item in DEFAULT_WARCOIN_CONFIG["leagues"] if item["name"] == league)


def _league_income_multiplier(config: dict, league: str) -> float:
    item = next((x for x in config.get("leagues", []) if x.get("name") == league), None)
    return float((item or {}).get("incomeMultiplier", LEAGUE_INCOME_MULTIPLIERS.get(league, 1.0)))


async def _warcoin_config(db) -> dict:
    cfg = await find_config_by_key(db, WARCOIN_CONFIG_KEY)
    if cfg:
        import json
        try:
            stored = json.loads(cfg["value"])
        except Exception:
            stored = None
        if stored and all("minNetWorth" in item for item in stored.get("leagues", [])):
            return stored
    return DEFAULT_WARCOIN_CONFIG


def _league_and_price(config: dict, balance: float) -> tuple[str, float]:
    price = float(config.get("price", WARCOIN_PRICE_DEFAULT))
    leagues = sorted(config.get("leagues", []), key=lambda l: l.get("minNetWorth", l.get("minBalance", 0)))
    name = leagues[0].get("name", "novice") if leagues else "novice"
    for item in leagues:
        if balance >= item.get("minNetWorth", item.get("minBalance", 0)):
            name = item.get("name", name)
            price = float(item.get("warcoinPrice", price))
    return name, price


# ── Schemas ──────────────────────────────────────────────────────────────────


class BuyWarcoin(BaseModel):
    amount: int

    @field_validator("amount")
    @classmethod
    def amount_ok(cls, v):
        if v is None or v < 1:
            raise ValueError("Количество должно быть не меньше 1")
        if v > 1_000_000:
            raise ValueError("Слишком большое количество")
        return int(v)


class GuessBody(BaseModel):
    sessionId: str
    guess: list[int]

    @field_validator("guess")
    @classmethod
    def guess_ok(cls, v):
        if not v or len(v) > 12:
            raise ValueError("Некорректная комбинация")
        return v


class ProtectBody(BaseModel):
    level: int

    @field_validator("level")
    @classmethod
    def level_ok(cls, v):
        if v < 1 or v > PROTECTION_MAX:
            raise ValueError(f"Уровень защиты 1..{PROTECTION_MAX}")
        return v


class ItStudioOrder(BaseModel):
    assetId: str
    businessId: str
    type: str

    @field_validator("type")
    @classmethod
    def type_ok(cls, v):
        if v not in ("attack", "defense"):
            raise ValueError("type должен быть 'attack' или 'defense'")
        return v


class ItStudioMaterialsBuy(BaseModel):
    assetId: str
    qty: int

    @field_validator("qty")
    @classmethod
    def qty_ok(cls, v):
        if v is None or v < 1:
            raise ValueError("Количество должно быть не меньше 1")
        if v > 500:
            raise ValueError("Слишком большое количество")
        return int(v)


class AdminBusinessUpdate(BaseModel):
    """Правки бизнеса администратором — без ограничений, действующих на игрока."""
    name: Optional[str] = None
    reward: Optional[int] = None
    protection_level: Optional[int] = None

    @field_validator("protection_level")
    @classmethod
    def protection_level_ok(cls, v):
        if v is not None and (v < 0 or v > PROTECTION_MAX):
            raise ValueError(f"Уровень защиты 0..{PROTECTION_MAX}")
        return v


class AdminTransferBody(BaseModel):
    toUsername: str


# ── Helpers ──────────────────────────────────────────────────────────────────


_now = now_utc


def _current_week() -> str:
    iso = _now().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


async def _player_room(db, user_id: str, season: int) -> dict:
    user = await db.users.find_one({"_id": ObjectId(user_id)}, {"warcoin": 1}) or {}
    existing = await db.cityroof_rooms.find_one({"season": season, "member_ids": user_id})
    if existing:
        capital = await _cityroof_player_capital(db, user_id, existing["league"])
        target = _league_transition(existing["league"], capital)
        if target != existing["league"]:
            old_price = LEAGUE_WARCOIN_PRICES[existing["league"]]
            new_price = LEAGUE_WARCOIN_PRICES[target]
            new_wc = max(0, int(int(user.get("warcoin", 0) or 0) * old_price / new_price))
            await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"warcoin": new_wc}})
            await db.cityroof_rooms.update_one({"_id": existing["_id"]}, {"$pull": {"member_ids": user_id}})
            await db.cityroof_businesses.update_many(
                {"season": season, "room_code": existing["room_code"], "ownerId": user_id},
                {"$set": {"ownerId": None, "ownerName": None, "ownerColor": None, "protection_level": 0, "last_captured": None, "last_collected": None}},
            )
            await db.cityroof_sessions.delete_many({"attackerId": user_id, "season": season})
            await push_notification(
                db, user_id, "cityroof", "Лига изменена",
                f"Вы перешли в лигу {target}. Бизнесы освобождены, баланс WarCoin пересчитан.",
                {"league": target, "roomCode": None},
            )
            room = await ensure_player_room(db, user_id, season, capital, target)
        else:
            room = existing
    else:
        room = await ensure_player_room(db, user_id, season, await compute_net_worth(db, user_id))
    await _ensure_room_businesses(db, season, room["league"], room["room_code"])
    return room


async def _room_members_view(db, room: dict, season: int) -> list[dict]:
    owners = {b.get("ownerId") async for b in db.cityroof_businesses.find({"season": season, "room_code": room["room_code"], "ownerId": {"$ne": None}}, {"ownerId": 1})}
    members = []
    for user_id in room.get("member_ids", []):
        user = await db.users.find_one({"_id": ObjectId(user_id)}, {"username": 1})
        members.append({"id": user_id, "name": (user or {}).get("username", "Игрок"), "active": user_id in owners})
    return members


async def _ensure_room_businesses(db, season: int, league: str, room_code: str):
    if await db.cityroof_businesses.count_documents({"season": season, "room_code": room_code}):
        return
    legacy = await db.cityroof_businesses.find_one({"season": {"$exists": False}})
    if legacy:
        await db.cityroof_businesses.update_many(
            {"season": {"$exists": False}},
            {"$set": {"season": season, "league": league, "room_code": room_code}},
        )
        return
    for business in DEFAULT_BUSINESSES:
        await db.cityroof_businesses.insert_one({
            **business, "season": season, "league": league, "room_code": room_code,
            "ownerId": None, "ownerName": None, "ownerColor": None,
            "protection_level": 0, "last_captured": None, "last_collected": None,
            **_make_secret(0),
        })


def _color_for(user_id: str) -> str:
    return OWNER_COLORS[sum(ord(c) for c in user_id) % len(OWNER_COLORS)]


def _interval_amount(daily: float, league: str = "novice", config: Optional[dict] = None) -> float:
    multiplier = _league_income_multiplier(config or DEFAULT_WARCOIN_CONFIG, league)
    return round(daily * multiplier / DAILY_TO_INTERVAL_DIVISOR, 2)


_aware = to_aware


def _seconds_since_collected(last_collected) -> float:
    lc = _aware(last_collected)
    if not isinstance(lc, datetime):
        return float("inf")
    return (_now() - lc).total_seconds()


def _business_ready(last_collected) -> bool:
    return _seconds_since_collected(last_collected) >= BONUS_CLAIM_INTERVAL_MIN * 60


def _make_secret(level: int) -> dict:
    length = 3 + (level + 1) // 2
    symbol_range = 4 + level // 2
    return {
        "secret": [random.randint(0, symbol_range - 1) for _ in range(length)],
        "symbol_range": symbol_range,
        "length": length,
    }


def _guess_feedback(secret: list[int], guess: list[int]) -> list[str]:
    feedback = ["absent"] * len(secret)
    remaining = {}
    for i, value in enumerate(secret):
        if guess[i] == value:
            feedback[i] = "exact"
        else:
            remaining[value] = remaining.get(value, 0) + 1
    for i, value in enumerate(guess):
        if feedback[i] == "absent" and remaining.get(value, 0):
            feedback[i] = "present"
            remaining[value] -= 1
    return feedback


async def _dedupe_player_rooms(db):
    seen = set()
    async for room in db.cityroof_rooms.find({}).sort("_id", 1):
        keep = []
        removed = []
        for user_id in room.get("member_ids", []):
            if (room.get("season"), user_id) in seen:
                removed.append(user_id)
            else:
                seen.add((room.get("season"), user_id))
                keep.append(user_id)
        if removed:
            await db.cityroof_rooms.update_one({"_id": room["_id"]}, {"$set": {"member_ids": keep}})


async def ensure_seeded(db: AsyncIOMotorDatabase):
    if not await find_config_by_key(db, WARCOIN_CONFIG_KEY):
        import json
        await upsert_config(db, WARCOIN_CONFIG_KEY, json.dumps(DEFAULT_WARCOIN_CONFIG))
    if await db.cityroof_state.count_documents({"key": "current"}) == 0:
        await db.cityroof_state.insert_one({"key": "current", "week": _current_week(), "season": 1})
    await _dedupe_player_rooms(db)
    await db.cityroof_rooms.create_index(
        [("season", 1), ("league", 1), ("room_code", 1)], unique=True,
    )
    await db.cityroof_rooms.create_index(
        [("season", 1), ("member_ids", 1)], unique=True,
    )
    await _migrate_warcoin_balances(db)


async def _ensure_season(db: AsyncIOMotorDatabase):
    """Ленивая недельная автоматизация: закрыть прошлый сезон при смене недели."""
    state = await db.cityroof_state.find_one({"key": "current"})
    if not state:
        return
    current = _current_week()
    if state.get("week") == current:
        return

    season_no = state.get("season", 1)
    # Атомарно «захватываем» переход недели: продвигаем week/season условным
    # апдейтом по прочитанному week. Параллельные вызовы /map при смене недели
    # прочитают один week, но апдейт сработает лишь у одного — остальные выйдут.
    # Иначе победитель получал бы награду (WINNER_REWARD_WC) несколько раз, а
    # карта сбрасывалась бы дублями (гонка).
    claim = await db.cityroof_state.update_one(
        {"key": "current", "week": state.get("week")},
        {"$set": {"week": current, "season": season_no + 1}},
    )
    if claim.modified_count == 0:
        return  # переход уже выполнен параллельным запросом

    # Определяем победителя прошлого сезона — у кого больше всего бизнесов.
    counts: dict[str, dict] = {}
    async for b in db.cityroof_businesses.find({"ownerId": {"$ne": None}}):
        oid = b["ownerId"]
        counts.setdefault(oid, {"userId": oid, "name": b.get("ownerName"), "count": 0})
        counts[oid]["count"] += 1
    standings = sorted(counts.values(), key=lambda x: x["count"], reverse=True)
    winner = standings[0] if standings else None

    await db.cityroof_seasons.insert_one({
        "season": season_no,
        "week": state.get("week"),
        "closed_at": _now(),
        "winner": winner,
        "standings": standings,
    })

    # Награда победителю (WarCoin).
    if winner:
        await db.users.update_one(
            {"_id": ObjectId(winner["userId"])},
            {"$inc": {"warcoin": WINNER_REWARD_WC}},
        )

    # Обнуляем карту: снимаем владельцев и защиту, новые секреты.
    async for b in db.cityroof_businesses.find({}):
        secret = _make_secret(0)
        await db.cityroof_businesses.update_one(
            {"_id": b["_id"]},
            {"$set": {
                "ownerId": None, "ownerName": None, "ownerColor": None,
                "protection_level": 0, "last_captured": None, "last_collected": None,
                **secret,
            }},
        )
    await db.cityroof_sessions.delete_many({})


def _event_active() -> bool:
    # ПН(0)–ПТ(4). Для MVP событие всегда доступно (см. описание модуля).
    return True


def _shield_view(b: dict) -> Optional[dict]:
    """Активный щит защиты (см. ITSTUDIO_CONFIG['shield_*']) — None, если истёк/не ставился."""
    shield = b.get("shield")
    if not shield:
        return None
    expires = to_aware(shield.get("expires_at"))
    if not isinstance(expires, datetime) or _now() >= expires:
        return None
    return {"value": shield.get("value", 0.0), "expiresAt": expires.isoformat()}


def _scaled_protection_costs(league: str) -> dict:
    return dict(PROTECTION_COSTS)


def _serialize_business(b: dict, user_id: str) -> dict:
    shield = _shield_view(b)
    multiplier = LEAGUE_INCOME_MULTIPLIERS.get(b.get("league", "novice"), 1)
    return {
        "id": str(b["_id"]),
        "slug": b.get("slug"),
        "name": b.get("name"),
        "x": b.get("x"),
        "y": b.get("y"),
        "reward": (b.get("reward") or 0) * multiplier,
        "dailyIncome": round(BUSINESS_BONUS.get(b.get("slug"), {}).get("daily", 0) * multiplier, 2),
        "effect": BUSINESS_BONUS.get(b.get("slug"), {}).get("effect"),
        "effectMultiplier": BUSINESS_BONUS.get(b.get("slug"), {}).get("mult", 0),
        "ownerId": b.get("ownerId"),
        "ownerName": b.get("ownerName"),
        "ownerColor": b.get("ownerColor"),
        "protectionLevel": b.get("protection_level", 0),
        "lastCaptured": b["last_captured"].isoformat() if isinstance(b.get("last_captured"), datetime) else None,
        "isMine": b.get("ownerId") == user_id,
        "length": b.get("length", 3),
        "symbolRange": b.get("symbol_range", 4),
        "shieldActive": shield is not None,
        "shieldValue": shield.get("value") if shield else None,
        "shieldExpiresAt": shield.get("expiresAt") if shield else None,
    }


async def _get_wc(db, user_id: str) -> int:
    u = await db.users.find_one({"_id": ObjectId(user_id)}, {"warcoin": 1})
    return int((u or {}).get("warcoin", 0))


async def _spend_wc(db, user_id: str, amount: int) -> bool:
    res = await db.users.find_one_and_update(
        {"_id": ObjectId(user_id), "warcoin": {"$gte": amount}},
        {"$inc": {"warcoin": -amount}},
        return_document=True,
    )
    return res is not None


def _roll_itstudio_reduction() -> int:
    weights = ITSTUDIO_CONFIG["reduction_weights"]
    values = [v for v, _ in weights]
    w = [x for _, x in weights]
    return random.choices(values, weights=w, k=1)[0]


# ── IT-студия: тиры, опыт, шанс успеха ────────────────────────────────────────


def _studio_tier(slug: str) -> Optional[str]:
    if not slug or not slug.startswith("itstudio_"):
        return None
    tier = slug[len("itstudio_"):]
    return tier if tier in ITSTUDIO_CONFIG["tiers"] else None


def _studio_level_from_xp(xp: int) -> int:
    level = 1 + int(xp) // ITSTUDIO_CONFIG["xp_per_level"]
    return min(level, ITSTUDIO_CONFIG["max_level"])


def _level_bonus(level: int) -> float:
    return min(ITSTUDIO_CONFIG["level_success_cap"], (level - 1) * ITSTUDIO_CONFIG["level_success_bonus"])


def _success_chance(tier: str, level: int, op_type: str, shield_active: bool) -> float:
    cfg = ITSTUDIO_CONFIG["tiers"][tier]
    base = cfg["successBase"] if op_type == "attack" else cfg["defenseBase"]
    chance = base + _level_bonus(level)
    if op_type == "attack" and shield_active:
        chance -= ITSTUDIO_CONFIG["shield_penalty"]
    # Премиум-студия («имба») может пробивать даже щит — потолок шанса выше.
    cap = cfg.get("success_cap", 0.95)
    return round(max(0.05, min(cap, chance)), 4)


def studio_progress(tier: Optional[str], xp: int, materials: dict) -> Optional[dict]:
    """Публичный вид прокачки студии — используется и cityroof.py, и
    assets.py (см. _studio_view в assets.py, вызывается лениво)."""
    if tier not in ITSTUDIO_CONFIG["tiers"]:
        return None
    cfg = ITSTUDIO_CONFIG["tiers"][tier]
    xp = int(xp or 0)
    level = _studio_level_from_xp(xp)
    per_level = ITSTUDIO_CONFIG["xp_per_level"]
    xp_to_next = None if level >= ITSTUDIO_CONFIG["max_level"] else (level * per_level - xp)
    return {
        "tier": tier,
        "level": level,
        "maxLevel": ITSTUDIO_CONFIG["max_level"],
        "xp": xp,
        "xpToNext": xp_to_next,
        "xpPerLevel": per_level,
        "attackChance": _success_chance(tier, level, "attack", False),
        "defenseChance": _success_chance(tier, level, "defense", False),
        "material": {
            "key": cfg["material"],
            "name": cfg["materialName"],
            "unitCost": cfg["materialUnitCost"],
            "qty": int((materials or {}).get(cfg["material"], 0)),
        },
        "materialsPerAttack": ITSTUDIO_CONFIG["materials_per_attack"],
        "materialsPerDefense": ITSTUDIO_CONFIG["materials_per_defense"],
    }


def _serialize_itstudio_job(j: dict) -> dict:
    done = j.get("status") == "done"
    return {
        "id": str(j["_id"]),
        "studioAssetId": j.get("studioAssetId"),
        "type": j.get("type", "attack"),
        "businessId": j.get("businessId"),
        "businessName": j.get("businessName"),
        "cost": j.get("cost"),
        "status": j.get("status"),
        # Результат раскрывается только после завершения — до этого момента
        # игрок видит лишь факт, что заказ выполняется.
        "success": j.get("success") if done else None,
        "reduction": j.get("reduction") if done else None,
        "readyAt": j["ready_at"].isoformat() if isinstance(j.get("ready_at"), datetime) else None,
    }


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/map")
async def get_map(
    allRooms: bool = Query(False),
    roomCode: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Карта бизнесов + состояние события и WarCoin игрока."""
    await ensure_seeded(db)
    await _ensure_season(db)
    user_id = str(current_user["_id"])
    state = await db.cityroof_state.find_one({"key": "current"})
    season = state.get("season", 1) if state else 1
    room = await _player_room(db, user_id, season)
    config = await _warcoin_config(db)
    view_room = room
    read_only = False
    if roomCode and roomCode != room["room_code"]:
        view_room = await db.cityroof_rooms.find_one({"season": season, "room_code": roomCode})
        if not view_room:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Комната не найдена")
        read_only = True
    league = view_room["league"]
    league_cfg = await _league_config(config, league)
    price = float(league_cfg.get("warcoinPrice", config.get("price", WARCOIN_PRICE_DEFAULT)))
    businesses = [_serialize_business(b, user_id) async for b in db.cityroof_businesses.find({"season": season, "room_code": view_room["room_code"]})]
    businesses.sort(key=lambda b: (b["y"], b["x"]))
    rooms = []
    if allRooms:
        async for room_doc in db.cityroof_rooms.find({"season": season}):
            room_businesses = [_serialize_business(b, user_id) async for b in db.cityroof_businesses.find({"season": season, "room_code": room_doc["room_code"]})]
            room_businesses.sort(key=lambda b: (b["y"], b["x"]))
            rooms.append({
                "league": room_doc["league"], "roomCode": room_doc["room_code"],
                "roomMembers": len(room_doc.get("member_ids", [])), "roomCapacity": ROOM_CAPACITY,
                "members": await _room_members_view(db, room_doc, season),
                "businesses": room_businesses,
                "incomeMultiplier": _league_income_multiplier(config, room_doc["league"]),
            })
    return {
        "businesses": businesses,
        "rooms": rooms,
        "isActive": _event_active(),
        "season": season,
        "week": state.get("week") if state else _current_week(),
        "league": league,
        "roomCode": view_room["room_code"],
        "roomMembers": len(view_room.get("member_ids", [])),
        "roomCapacity": ROOM_CAPACITY,
        "members": await _room_members_view(db, view_room, season),
        "incomeMultiplier": _league_income_multiplier(config, league),
        "readOnly": read_only,
        "attackCost": int(league_cfg.get("attackCost", ATTACK_COST_WC)),
        "maxAttempts": MAX_ATTEMPTS,
        "protectionCosts": league_cfg.get("protectionCosts", _scaled_protection_costs(league)),
        "itstudio": {
            "costBase": ITSTUDIO_CONFIG["cost_base"],
            "costPerProtection": ITSTUDIO_CONFIG["cost_per_protection"],
            "minHours": ITSTUDIO_CONFIG["min_hours"],
            "maxHours": ITSTUDIO_CONFIG["max_hours"],
            "materialsPerAttack": ITSTUDIO_CONFIG["materials_per_attack"],
            "materialsPerDefense": ITSTUDIO_CONFIG["materials_per_defense"],
            "shieldPenalty": ITSTUDIO_CONFIG["shield_penalty"],
            "shieldDurationHours": ITSTUDIO_CONFIG["shield_duration_hours"],
            "tiers": ITSTUDIO_CONFIG["tiers"],
        },
        "warcoin": {
            "balance": await _get_wc(db, user_id),
            "price": price,
            "league": league,
        },
    }


@router.get("/warcoin")
async def get_warcoin(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Баланс и цена WarCoin по лиге игрока."""
    user_id = str(current_user["_id"])
    state = await db.cityroof_state.find_one({"key": "current"})
    room = await _player_room(db, user_id, state.get("season", 1))
    config = await _warcoin_config(db)
    league = room["league"]
    price = float((await _league_config(config, league)).get("warcoinPrice", config.get("price", WARCOIN_PRICE_DEFAULT)))
    return {
        "balance": await _get_wc(db, user_id),
        "price": price,
        "league": league,
        "leagues": config.get("leagues", []),
    }


# ── Бонусы зданий ────────────────────────────────────────────────────────────


async def _owned_slugs(db, user_id: str) -> list[str]:
    slugs = []
    async for b in db.cityroof_businesses.find({"ownerId": user_id}, {"slug": 1}):
        slugs.append(b.get("slug"))
    return slugs


async def player_city_effect(db: AsyncIOMotorDatabase, user_id: str, effect: str) -> float:
    """Суммарный множитель заданного эффекта от зданий во владении игрока.

    Например, effect='rental_income' от «Гранд-отеля» даёт +0.15 к доходу аренды.
    """
    total = 0.0
    for slug in await _owned_slugs(db, user_id):
        bonus = BUSINESS_BONUS.get(slug)
        if bonus and bonus.get("effect") == effect:
            total += bonus.get("mult", 0.0)
    return round(total, 4)


@router.get("/bonuses")
async def get_bonuses(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Бонусы зданий игрока + КД до следующего автосбора у каждого здания."""
    user_id = str(current_user["_id"])
    state = await db.cityroof_state.find_one({"key": "current"})
    room = await _player_room(db, user_id, state.get("season", 1))
    config = await _warcoin_config(db)
    items = []
    total_daily = 0
    interval_s = BONUS_CLAIM_INTERVAL_MIN * 60
    async for b in db.cityroof_businesses.find({"ownerId": user_id, "season": state.get("season", 1), "room_code": room["room_code"]}):
        bonus = BUSINESS_BONUS.get(b.get("slug"))
        if not bonus:
            continue
        daily = round(bonus["daily"] * _league_income_multiplier(config, room["league"]), 2)
        total_daily += daily
        ready_in = max(0.0, interval_s - _seconds_since_collected(b.get("last_collected")))
        items.append({
            "slug": b.get("slug"), "name": b.get("name"),
            "daily": daily, "effect": bonus["effect"], "mult": bonus["mult"],
            "amount": _interval_amount(daily),
            "readyInSec": round(ready_in),
        })
    return {
        "bonuses": items,
        "totalDaily": total_daily,
        "intervalSec": interval_s,
    }


# ── IT-студия ────────────────────────────────────────────────────────────────


async def _load_owned_studio(db, user_id: str, asset_id: str):
    """Загружает актив IT-студии, принадлежащий игроку. 404/400 иначе."""
    if not ObjectId.is_valid(asset_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID студии")
    asset = await db.user_assets.find_one({"_id": ObjectId(asset_id), "userId": user_id})
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Актив не найден")
    tier = _studio_tier(asset.get("slug", ""))
    if not tier:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Актив не является IT-студией")
    return asset, tier


@router.get("/itstudio/mystudios")
async def my_studios(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Собственные IT-студии игрока: тир, уровень/опыт, материалы, активный заказ."""
    user_id = str(current_user["_id"])
    pending_by_asset = {}
    async for j in db.cityroof_itstudio_jobs.find({"orderedBy": user_id, "status": "pending"}):
        pending_by_asset[j.get("studioAssetId")] = _serialize_itstudio_job(j)

    out = []
    async for a in db.user_assets.find({"userId": user_id, "type": "business"}):
        tier = _studio_tier(a.get("slug", ""))
        if not tier:
            continue
        progress = studio_progress(tier, a.get("studioXp", 0), a.get("itstudioMaterials", {}))
        out.append({
            "assetId": str(a["_id"]),
            "name": a.get("name"),
            **progress,
            "pendingJob": pending_by_asset.get(str(a["_id"])),
        })
    return out


@router.post("/itstudio/materials/buy")
async def buy_studio_materials(
    payload: ItStudioMaterialsBuy,
    current_user: dict = Depends(require_allowed("cityroof_purchase")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Закупить материалы тира студии — тип материала и цена всегда
    определяются сервером по тиру владельца студии, клиент выбирает только
    количество."""
    user_id = str(current_user["_id"])
    asset, tier = await _load_owned_studio(db, user_id, payload.assetId)
    cfg = ITSTUDIO_CONFIG["tiers"][tier]
    total = round(cfg["materialUnitCost"] * payload.qty, 2)
    new_balance = await adjust_balance(db, user_id, -total)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
    await db.user_assets.update_one(
        {"_id": asset["_id"]}, {"$inc": {f"itstudioMaterials.{cfg['material']}": payload.qty}},
    )
    await record_transaction(
        db, user_id, EXPENSE, total, CAT_CITYROOF,
        f"Материалы IT-студии: {cfg['materialName']} ×{payload.qty}", balance_after=new_balance,
        meta={"assetId": payload.assetId, "material": cfg["material"], "qty": payload.qty},
    )
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    progress = studio_progress(tier, updated.get("studioXp", 0), updated.get("itstudioMaterials", {}))
    return {"balance": new_balance, "total": total, "studio": progress}


@router.post("/itstudio/order")
async def order_itstudio(
    payload: ItStudioOrder,
    current_user: dict = Depends(require_allowed("cityroof_attack")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Заказать атаку или защиту силами собственной IT-студии. Через 1–3ч
    реального времени задание резолвится: при успехе атака снижает защиту
    цели, защита ставит временный щит. Шанс успеха/результат считаются
    сервером сразу при заказе, но скрыты от игрока до завершения (см.
    _serialize_itstudio_job) — клиент не может ни подделать, ни узнать
    заранее исход."""
    user_id = str(current_user["_id"])
    asset, tier = await _load_owned_studio(db, user_id, payload.assetId)
    asset_id = str(asset["_id"])

    if not ObjectId.is_valid(payload.businessId):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID бизнеса")
    business = await db.cityroof_businesses.find_one({"_id": ObjectId(payload.businessId)})
    if not business:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Бизнес не найден")

    op_type = payload.type
    if op_type == "attack":
        if not business.get("ownerId"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "У бизнеса нет владельца")
        if business.get("ownerId") == user_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя заказать атаку на свой бизнес")
        # Атака снижает уровень защиты — если защиты уже нет, снижать нечего.
        if business.get("protection_level", 0) <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "У бизнеса нет защиты — снижать нечего")
    else:
        if business.get("ownerId") != user_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Можно защищать только свой бизнес")

    if await db.cityroof_itstudio_jobs.find_one({"studioAssetId": asset_id, "status": "pending"}):
        raise HTTPException(status.HTTP_409_CONFLICT, "У этой студии уже есть активный заказ")

    cfg = ITSTUDIO_CONFIG["tiers"][tier]
    material_key = cfg["material"]
    needed = (
        ITSTUDIO_CONFIG["materials_per_attack"] if op_type == "attack"
        else ITSTUDIO_CONFIG["materials_per_defense"]
    )
    # Материалы списываются атомарно вместе с проверкой достаточности —
    # исключает гонку двух параллельных заказов с одной студии.
    consumed = await db.user_assets.find_one_and_update(
        {"_id": asset["_id"], f"itstudioMaterials.{material_key}": {"$gte": needed}},
        {"$inc": {f"itstudioMaterials.{material_key}": -needed}},
        return_document=True,
    )
    if consumed is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Недостаточно материалов: {cfg['materialName']}")

    cost = round(
        ITSTUDIO_CONFIG["cost_base"] + business.get("protection_level", 0) * ITSTUDIO_CONFIG["cost_per_protection"], 2
    )
    new_balance = await adjust_balance(db, user_id, -cost)
    if new_balance is None:
        # Денег не хватило — возвращаем уже списанные материалы, заказ не состоялся.
        await db.user_assets.update_one({"_id": asset["_id"]}, {"$inc": {f"itstudioMaterials.{material_key}": needed}})
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

    level = _studio_level_from_xp(asset.get("studioXp", 0))
    shield_active = op_type == "attack" and _shield_view(business) is not None
    chance = _success_chance(tier, level, op_type, shield_active)
    success = random.random() < chance

    # Премиум-студия («имба»): операция за 5–45 минут вместо часов; успешная
    # атака сносит ВСЮ защиту цели за раз (full_break), а не 1–5 уровней.
    min_min = cfg.get("min_minutes")
    max_min = cfg.get("max_minutes")
    if min_min is not None and max_min is not None:
        minutes = round(random.uniform(min_min, max_min), 1)
        ready_at = _now() + timedelta(minutes=minutes)
        ready_in_hours = round(minutes / 60.0, 3)
    else:
        minutes = None
        hours = round(random.uniform(ITSTUDIO_CONFIG["min_hours"], ITSTUDIO_CONFIG["max_hours"]), 2)
        ready_at = _now() + timedelta(hours=hours)
        ready_in_hours = hours

    if op_type == "attack" and success:
        if cfg.get("full_break"):
            reduction = int(business.get("protection_level", 0))   # снос всей защиты
        else:
            reduction = _roll_itstudio_reduction()
    else:
        reduction = None

    job = {
        "orderedBy": user_id, "studioAssetId": asset_id, "type": op_type, "tier": tier,
        "businessId": payload.businessId, "businessName": business.get("name"),
        "success": success, "reduction": reduction, "cost": cost,
        "status": "pending", "created_at": _now(), "ready_at": ready_at,
    }
    result = await db.cityroof_itstudio_jobs.insert_one(job)
    label = "атаку" if op_type == "attack" else "защиту"
    await record_transaction(
        db, user_id, EXPENSE, cost, CAT_CITYROOF,
        f"Заказ IT-студии ({label}): {business.get('name')}", balance_after=new_balance,
        meta={"businessId": payload.businessId, "assetId": asset_id, "type": op_type},
    )
    return {"ok": True, "jobId": str(result.inserted_id), "cost": cost,
            "readyInHours": ready_in_hours, "readyInMinutes": minutes, "balance": new_balance}


@router.get("/itstudio/jobs")
async def my_itstudio_jobs(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Заказы IT-студии текущего игрока (новые сверху)."""
    uid = str(current_user["_id"])
    out = []
    async for j in db.cityroof_itstudio_jobs.find({"orderedBy": uid}).sort("created_at", -1).limit(20):
        out.append(_serialize_itstudio_job(j))
    return out


async def sweep_itstudio_jobs(db: AsyncIOMotorDatabase):
    """Завершает готовые заказы IT-студии (атака/защита): применяет эффект
    при успехе, начисляет опыт студии, уведомляет участников. Устойчиво к
    удалённой цели и проданной студии — просто пропускает соответствующий
    шаг, не роняя обработку остальных заданий. Вызывается Scheduler'ом."""
    now = _now()
    async for j in db.cityroof_itstudio_jobs.find({"status": "pending", "ready_at": {"$lte": now}}):
        try:
            await db.cityroof_itstudio_jobs.update_one({"_id": j["_id"]}, {"$set": {"status": "done"}})

            business = None
            if ObjectId.is_valid(j.get("businessId", "")):
                business = await db.cityroof_businesses.find_one({"_id": ObjectId(j["businessId"])})
            op_type = j.get("type", "attack")
            success = bool(j.get("success"))
            applied = False

            if business and success:
                if op_type == "attack":
                    reduction = j.get("reduction") or 1
                    new_level = max(0, business.get("protection_level", 0) - reduction)
                    await db.cityroof_businesses.update_one(
                        {"_id": business["_id"]}, {"$set": {"protection_level": new_level}},
                    )
                    applied = True
                elif business.get("ownerId") == j.get("orderedBy"):
                    # Цель могла сменить владельца (захват) с момента заказа —
                    # щит ставим, только если бизнес всё ещё принадлежит заказчику.
                    # Премиум-студия ставит усиленный и более длительный щит.
                    tier_cfg = ITSTUDIO_CONFIG["tiers"].get(j.get("tier"), {})
                    shield_value = tier_cfg.get("shield_bonus_on_success", ITSTUDIO_CONFIG["shield_bonus_on_success"])
                    shield_hours = tier_cfg.get("shield_duration_hours", ITSTUDIO_CONFIG["shield_duration_hours"])
                    shield = {
                        "value": shield_value,
                        "expires_at": now + timedelta(hours=shield_hours),
                    }
                    await db.cityroof_businesses.update_one(
                        {"_id": business["_id"]}, {"$set": {"shield": shield}},
                    )
                    applied = True

            # Опыт студии — только если сам актив ещё существует (мог быть продан).
            if ObjectId.is_valid(j.get("studioAssetId", "")):
                cfg = ITSTUDIO_CONFIG
                if success:
                    xp_gain = cfg["xp_per_success_attack"] if op_type == "attack" else cfg["xp_per_success_defense"]
                else:
                    xp_gain = cfg["xp_per_fail"]
                await db.user_assets.update_one(
                    {"_id": ObjectId(j["studioAssetId"])}, {"$inc": {"studioXp": xp_gain}},
                )
                try:
                    from ws import push_to_user
                    await push_to_user(j["orderedBy"], {"type": "asset_update", "assetId": j.get("studioAssetId")})
                except Exception:
                    pass

            if not business:
                continue

            updated_doc = await db.cityroof_businesses.find_one({"_id": business["_id"]})
            from ws import broadcast
            await broadcast({"type": "cityroof_protected", "business": _serialize_business(updated_doc, "")})

            if op_type == "attack":
                if success:
                    await push_notification(
                        db, j["orderedBy"], "itstudio",
                        "Взлом удался",
                        f"Защита «{business.get('name')}» снижена на {j.get('reduction')}.",
                        data={"businessId": j["businessId"], "reduction": j.get("reduction"), "success": True},
                    )
                    if business.get("ownerId"):
                        await push_notification(
                            db, business["ownerId"], "itstudio_attack",
                            "Взлом системы защиты",
                            f"Защита «{business.get('name')}» снижена на {j.get('reduction')} неизвестными хакерами.",
                            data={"businessId": j["businessId"], "reduction": j.get("reduction")},
                        )
                else:
                    await push_notification(
                        db, j["orderedBy"], "itstudio",
                        "Взлом не удался",
                        f"Попытка взлома «{business.get('name')}» провалилась. Материалы и оплата потрачены впустую.",
                        data={"businessId": j["businessId"], "success": False},
                    )
            else:
                if applied:
                    tier_cfg = ITSTUDIO_CONFIG["tiers"].get(j.get("tier"), {})
                    shield_hours = tier_cfg.get("shield_duration_hours", ITSTUDIO_CONFIG["shield_duration_hours"])
                    await push_notification(
                        db, j["orderedBy"], "itstudio",
                        "Защита установлена",
                        f"IT-студия усилила защиту «{business.get('name')}» на {shield_hours:.0f}ч.",
                        data={"businessId": j["businessId"], "success": True},
                    )
                elif success:
                    await push_notification(
                        db, j["orderedBy"], "itstudio",
                        "Защита не применена",
                        f"«{business.get('name')}» больше не ваш бизнес — щит не установлен.",
                        data={"businessId": j["businessId"], "success": True},
                    )
                else:
                    await push_notification(
                        db, j["orderedBy"], "itstudio",
                        "Установка защиты провалена",
                        f"Не удалось усилить защиту «{business.get('name')}». Материалы и оплата потрачены впустую.",
                        data={"businessId": j["businessId"], "success": False},
                    )
        except Exception:
            continue


async def sweep_business_income(db: AsyncIOMotorDatabase):
    """Автосбор: зачисляет владельцам доход по всем готовым бизнесам.

    Вызывается Scheduler'ом. КД — персональный у каждого бизнеса
    (last_collected на документе), поэтому захват одного здания никак не
    блокирует доход с остальных, а при смене владельца недособранный КД
    переходит по наследству (см. submit_guess).
    """
    interval_s = BONUS_CLAIM_INTERVAL_MIN * 60
    config = await _warcoin_config(db)
    async for b in db.cityroof_businesses.find({"ownerId": {"$ne": None}}):
        try:
            bonus = BUSINESS_BONUS.get(b.get("slug"))
            if not bonus:
                continue
            elapsed = _seconds_since_collected(b.get("last_collected"))
            if elapsed < interval_s:
                continue
            intervals = 1 if elapsed == float("inf") else int(elapsed // interval_s)
            amount = _interval_amount(bonus["daily"], b.get("league", "novice"), config) * intervals
            if amount <= 0:
                continue
            user_id = b["ownerId"]
            new_balance = await adjust_balance(db, user_id, amount)
            if new_balance is None:
                continue
            await db.cityroof_businesses.update_one({"_id": b["_id"]}, {"$set": {"last_collected": _now()}})
            await record_transaction(
                db, user_id, INCOME, amount, CAT_CITYROOF,
                f"Автосбор дохода «{b.get('name')}»", balance_after=new_balance,
            )
            from ws import push_to_user
            await push_to_user(user_id, {
                "type": "cityroof_income", "businessId": str(b["_id"]), "slug": b.get("slug"),
                "amount": amount, "intervalSec": interval_s,
            })
        except Exception:
            continue


@router.post("/warcoin/buy")
async def buy_warcoin(
    payload: BuyWarcoin,
    current_user: dict = Depends(require_allowed("cityroof_purchase")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Купить WarCoin за $ по цене лиги."""
    user_id = str(current_user["_id"])
    config = await _warcoin_config(db)
    _, price = _league_and_price(config, await compute_net_worth(db, user_id))
    # Бонус зданий: скидка на покупку WarCoin (напр. «Казино»).
    discount = min(0.5, await player_city_effect(db, user_id, "warcoin_discount"))
    unit_price = round(price * (1 - discount), 2)
    cost = round(unit_price * payload.amount, 2)

    new_balance = await adjust_balance(db, user_id, -cost)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$inc": {"warcoin": payload.amount}})
    await record_transaction(
        db, user_id, EXPENSE, cost, CAT_CITYROOF,
        f"Покупка {payload.amount} WC", balance_after=new_balance,
        meta={"warcoin": payload.amount, "price": unit_price},
    )
    return {"warcoin": await _get_wc(db, user_id), "balance": new_balance, "bought": payload.amount}


@router.post("/attack/{business_id}")
async def attack_business(
    business_id: str,
    current_user: dict = Depends(require_allowed("cityroof_attack")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Оплатить попытку захвата (10 WC) и начать мини-игру."""
    if not _event_active():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Событие сейчас неактивно")
    if not ObjectId.is_valid(business_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID")
    user_id = str(current_user["_id"])
    state = await db.cityroof_state.find_one({"key": "current"})
    room = await _player_room(db, user_id, state.get("season", 1))
    business = await db.cityroof_businesses.find_one({
        "_id": ObjectId(business_id), "season": state.get("season", 1),
        "league": room["league"], "room_code": room["room_code"],
    })
    if not business:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Бизнес не найден в вашей комнате")
    if business.get("ownerId") == user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Это уже ваш бизнес")

    league_cfg = await _league_config(await _warcoin_config(db), room["league"])
    attack_cost = int(league_cfg.get("attackCost", ATTACK_COST_WC))
    if not await _spend_wc(db, user_id, attack_cost):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно WarCoin")

    # Закрываем старые сессии игрока по этому бизнесу и создаём новую.
    await db.cityroof_sessions.delete_many({"attackerId": user_id, "businessId": business_id})
    session = {
        "attackerId": user_id,
        "businessId": business_id,
        "season": state.get("season", 1),
        "league": room["league"],
        "room_code": room["room_code"],
        "attempts": 0,
        "maxAttempts": MAX_ATTEMPTS,
        "created_at": _now(),
    }
    result = await db.cityroof_sessions.insert_one(session)
    return {
        "sessionId": str(result.inserted_id),
        "length": business.get("length", 3),
        "symbolRange": business.get("symbol_range", 4),
        "maxAttempts": MAX_ATTEMPTS,
        "attempts": 0,
        "warcoin": await _get_wc(db, user_id),
    }


@router.post("/guess")
async def submit_guess(
    payload: GuessBody,
    current_user: dict = Depends(require_allowed("cityroof_capture")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Проверить комбинацию. Возвращает подсказку (exact/present) и статус."""
    user_id = str(current_user["_id"])
    if not ObjectId.is_valid(payload.sessionId):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректная сессия")
    session = await db.cityroof_sessions.find_one({"_id": ObjectId(payload.sessionId)})
    if not session or session.get("attackerId") != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сессия не найдена или истекла")

    business = await db.cityroof_businesses.find_one({
        "_id": ObjectId(session["businessId"]),
        "season": session.get("season"), "room_code": session.get("room_code"),
    })
    if not business:
        await db.cityroof_sessions.delete_one({"_id": session["_id"]})
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Бизнес не найден")

    secret = business.get("secret", [])
    guess = payload.guess
    if len(guess) != len(secret):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неверная длина комбинации")

    feedback = _guess_feedback(secret, guess)
    exact = feedback.count("exact")
    present = feedback.count("present")

    attempts = session.get("attempts", 0) + 1
    solved = exact == len(secret)

    if solved:
        # Захват: бизнес переходит атакующему, защита сбрасывается, новый секрет.
        new_secret = _make_secret(0)
        update_fields = {
            "ownerId": user_id,
            "ownerName": current_user.get("username"),
            "ownerColor": _color_for(user_id),
            "protection_level": 0,
            "last_captured": _now(),
            **new_secret,
        }
        # КД дохода — персональный у бизнеса. Если он уже истёк (или ещё не
        # собирался), новый владелец сразу получает выплату и КД стартует
        # заново. Если КД ещё активен (прошлый владелец недавно собирал) —
        # ничего не платим и не трогаем last_collected: оставшийся КД
        # переходит по наследству новому владельцу.
        bonus = BUSINESS_BONUS.get(business.get("slug"))
        captured_income = 0.0
        if bonus and _business_ready(business.get("last_collected")):
            captured_income = _interval_amount(bonus["daily"], business.get("league", "novice"), await _warcoin_config(db))
            update_fields["last_collected"] = _now()

        await db.cityroof_businesses.update_one({"_id": business["_id"]}, {"$set": update_fields})
        if captured_income > 0:
            new_balance = await adjust_balance(db, user_id, captured_income)
            if new_balance is not None:
                await record_transaction(
                    db, user_id, INCOME, captured_income, CAT_CITYROOF,
                    f"Доход при захвате «{business.get('name')}»", balance_after=new_balance,
                )
        await db.cityroof_sessions.delete_one({"_id": session["_id"]})
        updated_doc = await db.cityroof_businesses.find_one({"_id": business["_id"]})
        from ws import broadcast
        await broadcast({"type": "cityroof_captured", "business": _serialize_business(updated_doc, "")})
        return {"solved": True, "exact": exact, "present": present, "feedback": feedback, "attempts": attempts,
                "capturedIncome": captured_income,
                "business": _serialize_business(updated_doc, user_id)}

    exhausted = attempts >= session.get("maxAttempts", MAX_ATTEMPTS)
    if exhausted:
        # Прогресс сброшен — нужно платить и начинать заново.
        await db.cityroof_sessions.delete_one({"_id": session["_id"]})
    else:
        await db.cityroof_sessions.update_one({"_id": session["_id"]}, {"$set": {"attempts": attempts}})

    return {
        "solved": False,
        "exhausted": exhausted,
        "exact": exact,
        "present": present,
        "feedback": feedback,
        "attempts": attempts,
        "maxAttempts": session.get("maxAttempts", MAX_ATTEMPTS),
    }


@router.post("/protect/{business_id}")
async def protect_business(
    business_id: str,
    payload: ProtectBody,
    current_user: dict = Depends(require_allowed("cityroof_protect")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Купить защиту бизнеса (уровни 1–5). Сбрасывает прогресс атакующих."""
    if not ObjectId.is_valid(business_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID")
    user_id = str(current_user["_id"])
    state = await db.cityroof_state.find_one({"key": "current"})
    room = await _player_room(db, user_id, state.get("season", 1))
    business = await db.cityroof_businesses.find_one({
        "_id": ObjectId(business_id), "season": state.get("season", 1),
        "league": room["league"], "room_code": room["room_code"],
    })
    if not business:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Бизнес не найден в вашей комнате")
    if business.get("ownerId") != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Вы не владелец бизнеса")

    cost = _scaled_protection_costs(room["league"]).get(payload.level, payload.level * 1000)
    if not await _spend_wc(db, user_id, cost):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно WarCoin")

    new_secret = _make_secret(payload.level)
    await db.cityroof_businesses.update_one(
        {"_id": business["_id"]},
        {"$set": {"protection_level": payload.level, **new_secret}},
    )
    # Все текущие попытки по этому бизнесу аннулируются.
    await db.cityroof_sessions.delete_many({"businessId": business_id})
    updated_doc = await db.cityroof_businesses.find_one({"_id": business["_id"]})
    from ws import broadcast
    await broadcast({"type": "cityroof_protected", "business": _serialize_business(updated_doc, "")})
    return {
        "protectionLevel": payload.level,
        "cost": cost,
        "warcoin": await _get_wc(db, user_id),
        "business": _serialize_business(updated_doc, user_id),
    }


@router.get("/seasons")
async def get_seasons(
    limit: int = Query(10, ge=1, le=50),
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """История прошедших сезонов."""
    seasons = []
    cursor = db.cityroof_seasons.find({}).sort("closed_at", -1).limit(limit)
    async for s in cursor:
        seasons.append({
            "season": s.get("season"),
            "week": s.get("week"),
            "closedAt": s["closed_at"].isoformat() if isinstance(s.get("closed_at"), datetime) else None,
            "winner": s.get("winner"),
            "standings": s.get("standings", []),
        })
    return seasons


@router.post("/admin/season/close")
async def admin_close_season(
    _admin=Depends(require_admin("users_property")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Принудительно закрыть текущий сезон (admin)."""
    state = await db.cityroof_state.find_one({"key": "current"})
    if state:
        # Форсируем закрытие, откатив неделю на «прошлую».
        await db.cityroof_state.update_one({"key": "current"}, {"$set": {"week": "0000-W00"}})
        await _ensure_season(db)
        # Realtime-оповещение всех игроков: карта сброшена, нужно перечитать состояние.
        from ws import broadcast
        await broadcast({"type": "cityroof_season_closed"})
    return {"message": "Сезон закрыт"}


# ── Admin: управление бизнесами ───────────────────────────────────────────────


async def _load_any_business(db: AsyncIOMotorDatabase, business_id: str) -> dict:
    if not ObjectId.is_valid(business_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID бизнеса")
    business = await db.cityroof_businesses.find_one({"_id": ObjectId(business_id)})
    if not business:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Бизнес не найден")
    return business


@router.patch("/admin/businesses/{business_id}")
async def admin_update_business(
    business_id: str,
    payload: AdminBusinessUpdate,
    _admin=Depends(require_admin("users_property")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    business = await _load_any_business(db, business_id)
    update_fields = payload.model_dump(exclude_unset=True)
    if not update_fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет полей для обновления")
    if "protection_level" in update_fields:
        update_fields.update(_make_secret(update_fields["protection_level"]))
        await db.cityroof_sessions.delete_many({"businessId": business_id})
    await db.cityroof_businesses.update_one({"_id": business["_id"]}, {"$set": update_fields})
    updated = await db.cityroof_businesses.find_one({"_id": business["_id"]})
    from ws import broadcast
    await broadcast({"type": "cityroof_protected", "business": _serialize_business(updated, "")})
    return {"business": _serialize_business(updated, business.get("ownerId") or "")}


@router.post("/admin/businesses/{business_id}/vacate")
async def admin_vacate_business(
    business_id: str,
    _admin=Depends(require_admin("users_property")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Освободить бизнес: снять владельца и защиту (слот на карте не удаляется)."""
    business = await _load_any_business(db, business_id)
    old_owner_id = business.get("ownerId")
    new_secret = _make_secret(0)
    await db.cityroof_businesses.update_one(
        {"_id": business["_id"]},
        {"$set": {
            "ownerId": None, "ownerName": None, "ownerColor": None,
            "protection_level": 0, "last_captured": None, "last_collected": None,
            **new_secret,
        }},
    )
    await db.cityroof_sessions.delete_many({"businessId": business_id})
    updated = await db.cityroof_businesses.find_one({"_id": business["_id"]})
    from ws import broadcast
    await broadcast({"type": "cityroof_protected", "business": _serialize_business(updated, "")})
    if old_owner_id:
        await push_notification(
            db, old_owner_id, "cityroof", "Бизнес изъят администратором",
            f"Бизнес «{business.get('name')}» изъят администратором.",
            data={"businessId": business_id},
        )
    return {"message": f"Бизнес «{business.get('name')}» освобождён"}


@router.post("/admin/businesses/{business_id}/transfer")
async def admin_transfer_business(
    business_id: str,
    payload: AdminTransferBody,
    _admin=Depends(require_admin("users_property")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Передать бизнес другому игроку (защита и КД дохода сохраняются)."""
    business = await _load_any_business(db, business_id)
    target = await db.users.find_one({"username": payload.toUsername})
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Игрок не найден")
    new_owner_id = str(target["_id"])
    old_owner_id = business.get("ownerId")
    await db.cityroof_businesses.update_one(
        {"_id": business["_id"]},
        {"$set": {
            "ownerId": new_owner_id,
            "ownerName": target.get("username"),
            "ownerColor": _color_for(new_owner_id),
            "last_captured": _now(),
        }},
    )
    await db.cityroof_sessions.delete_many({"businessId": business_id})
    updated = await db.cityroof_businesses.find_one({"_id": business["_id"]})
    from ws import broadcast
    await broadcast({"type": "cityroof_protected", "business": _serialize_business(updated, "")})
    if old_owner_id:
        await push_notification(
            db, old_owner_id, "cityroof", "Бизнес передан",
            f"Бизнес «{business.get('name')}» передан другому игроку администратором.",
            data={"businessId": business_id},
        )
    await push_notification(
        db, new_owner_id, "cityroof", "Вы получили бизнес",
        f"Администратор передал вам бизнес «{business.get('name')}».",
        data={"businessId": business_id},
    )
    return {"business": _serialize_business(updated, new_owner_id)}
