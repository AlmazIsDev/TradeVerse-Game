"""Крыша города — еженедельное PvP-событие за бизнесы на интерактивной карте.

Механика:
- Событие идёт ПН–ПТ (в проде гейтится по дню недели; для игры включено всегда).
- На карте — бизнесы; каждый принадлежит максимум одному игроку.
- «Завоевать» стоит 10 WarCoin (WC). Открывается мини-игра: угадать секретную
  комбинацию (в стиле «Быки и коровы»). Угадал — бизнес переходит игроку.
- Владелец покупает защиту (уровни 1–5, 100–500 WC): выше уровень — длиннее и
  сложнее комбинация. На максимальном уровне подбор практически невозможен за
  отведённые попытки, а при исчерпании попыток прогресс сбрасывается (нужно
  платить и начинать заново).
- WarCoin покупается за $, цена зависит от лиги игрока (настраивается в конфиге).
- Автоматизация: при смене ISO-недели прошлый сезон закрывается — определяется
  победитель (больше всего бизнесов), выдаётся награда, карта обнуляется, сезон
  сохраняется в историю. Триггерится лениво при обращении к карте.
"""
import random
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator

from auth import get_current_user, require_admin
from database import get_db, find_config_by_key, upsert_config
from ledger import INCOME, EXPENSE, CAT_CITYROOF, adjust_balance, record_transaction

router = APIRouter(prefix="/api/cityroof", tags=["cityroof"])

ATTACK_COST_WC = 10
MAX_ATTEMPTS = 8
PROTECTION_MAX = 5
WINNER_REWARD_WC = 500

# Фиксированная стоимость WarCoin: 1 WC = 50$ (настраивается админом).
WARCOIN_PRICE_DEFAULT = 50.0

# Стоимость уровней защиты (WC).
PROTECTION_COSTS = {1: 1000, 2: 3000, 3: 4000, 4: 6500, 5: 10000}

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
DEFAULT_WARCOIN_CONFIG = {
    # Единая цена WarCoin для всех игроков. Лиги — только косметический статус.
    "price": WARCOIN_PRICE_DEFAULT,
    "leagues": [
        {"name": "bronze", "minBalance": 0},
        {"name": "silver", "minBalance": 50000},
        {"name": "gold", "minBalance": 250000},
        {"name": "platinum", "minBalance": 1000000},
        {"name": "diamond", "minBalance": 5000000},
    ],
}


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


# ── Helpers ──────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _current_week() -> str:
    iso = _now().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _color_for(user_id: str) -> str:
    return OWNER_COLORS[sum(ord(c) for c in user_id) % len(OWNER_COLORS)]


def _interval_amount(daily: float) -> float:
    """Выплата за один 5-минутный интервал (доля от суточной ставки)."""
    return round(daily / DAILY_TO_INTERVAL_DIVISOR, 2)


def _aware(dt):
    if isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _seconds_since_collected(last_collected) -> float:
    lc = _aware(last_collected)
    if not isinstance(lc, datetime):
        return float("inf")
    return (_now() - lc).total_seconds()


def _business_ready(last_collected) -> bool:
    return _seconds_since_collected(last_collected) >= BONUS_CLAIM_INTERVAL_MIN * 60


def _make_secret(level: int) -> dict:
    length = 3 + level
    symbol_range = 4 + level
    return {
        "secret": [random.randint(0, symbol_range - 1) for _ in range(length)],
        "symbol_range": symbol_range,
        "length": length,
    }


async def _warcoin_config(db) -> dict:
    cfg = await find_config_by_key(db, WARCOIN_CONFIG_KEY)
    if cfg:
        import json
        try:
            return json.loads(cfg["value"])
        except Exception:
            pass
    return DEFAULT_WARCOIN_CONFIG


def _league_and_price(config: dict, balance: float) -> tuple[str, float]:
    """Цена WarCoin фиксированная; лига — только статус по балансу (косметика)."""
    price = float(config.get("price", WARCOIN_PRICE_DEFAULT))
    leagues = sorted(config.get("leagues", []), key=lambda l: l.get("minBalance", 0))
    name = leagues[0].get("name", "bronze") if leagues else "bronze"
    for l in leagues:
        if balance >= l.get("minBalance", 0):
            name = l.get("name", name)
    return name, price


async def ensure_seeded(db: AsyncIOMotorDatabase):
    if await db.cityroof_businesses.count_documents({}) == 0:
        for b in DEFAULT_BUSINESSES:
            secret = _make_secret(0)
            await db.cityroof_businesses.insert_one({
                **b,
                "ownerId": None,
                "ownerName": None,
                "ownerColor": None,
                "protection_level": 0,
                "last_captured": None,
                "last_collected": None,
                **secret,
            })
    if not await find_config_by_key(db, WARCOIN_CONFIG_KEY):
        import json
        await upsert_config(db, WARCOIN_CONFIG_KEY, json.dumps(DEFAULT_WARCOIN_CONFIG))
    if await db.cityroof_state.count_documents({"key": "current"}) == 0:
        await db.cityroof_state.insert_one({"key": "current", "week": _current_week(), "season": 1})


async def _ensure_season(db: AsyncIOMotorDatabase):
    """Ленивая недельная автоматизация: закрыть прошлый сезон при смене недели."""
    state = await db.cityroof_state.find_one({"key": "current"})
    if not state:
        return
    current = _current_week()
    if state.get("week") == current:
        return

    # Определяем победителя прошлого сезона — у кого больше всего бизнесов.
    counts: dict[str, dict] = {}
    async for b in db.cityroof_businesses.find({"ownerId": {"$ne": None}}):
        oid = b["ownerId"]
        counts.setdefault(oid, {"userId": oid, "name": b.get("ownerName"), "count": 0})
        counts[oid]["count"] += 1
    standings = sorted(counts.values(), key=lambda x: x["count"], reverse=True)
    winner = standings[0] if standings else None

    season_no = state.get("season", 1)
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
    await db.cityroof_state.update_one(
        {"key": "current"},
        {"$set": {"week": current, "season": season_no + 1}},
    )


def _event_active() -> bool:
    # ПН(0)–ПТ(4). Для MVP событие всегда доступно (см. описание модуля).
    return True


def _serialize_business(b: dict, user_id: str) -> dict:
    return {
        "id": str(b["_id"]),
        "slug": b.get("slug"),
        "name": b.get("name"),
        "x": b.get("x"),
        "y": b.get("y"),
        "reward": b.get("reward"),
        "ownerId": b.get("ownerId"),
        "ownerName": b.get("ownerName"),
        "ownerColor": b.get("ownerColor"),
        "protectionLevel": b.get("protection_level", 0),
        "lastCaptured": b["last_captured"].isoformat() if isinstance(b.get("last_captured"), datetime) else None,
        "isMine": b.get("ownerId") == user_id,
        "length": b.get("length", 3),
        "symbolRange": b.get("symbol_range", 4),
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


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/map")
async def get_map(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Карта бизнесов + состояние события и WarCoin игрока."""
    await ensure_seeded(db)
    await _ensure_season(db)
    user_id = str(current_user["_id"])
    businesses = [_serialize_business(b, user_id) async for b in db.cityroof_businesses.find({})]
    businesses.sort(key=lambda b: (b["y"], b["x"]))
    state = await db.cityroof_state.find_one({"key": "current"})
    config = await _warcoin_config(db)
    league, price = _league_and_price(config, current_user.get("balance", 0.0))
    return {
        "businesses": businesses,
        "isActive": _event_active(),
        "season": state.get("season", 1) if state else 1,
        "week": state.get("week") if state else _current_week(),
        "attackCost": ATTACK_COST_WC,
        "maxAttempts": MAX_ATTEMPTS,
        "protectionCosts": PROTECTION_COSTS,
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
    config = await _warcoin_config(db)
    league, price = _league_and_price(config, current_user.get("balance", 0.0))
    return {
        "balance": await _get_wc(db, str(current_user["_id"])),
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
    items = []
    total_daily = 0
    interval_s = BONUS_CLAIM_INTERVAL_MIN * 60
    async for b in db.cityroof_businesses.find({"ownerId": user_id}):
        bonus = BUSINESS_BONUS.get(b.get("slug"))
        if not bonus:
            continue
        total_daily += bonus["daily"]
        ready_in = max(0.0, interval_s - _seconds_since_collected(b.get("last_collected")))
        items.append({
            "slug": b.get("slug"), "name": b.get("name"),
            "daily": bonus["daily"], "effect": bonus["effect"], "mult": bonus["mult"],
            "amount": _interval_amount(bonus["daily"]),
            "readyInSec": round(ready_in),
        })
    return {
        "bonuses": items,
        "totalDaily": total_daily,
        "intervalSec": interval_s,
    }


async def sweep_business_income(db: AsyncIOMotorDatabase):
    """Автосбор: зачисляет владельцам доход по всем готовым бизнесам.

    Вызывается Scheduler'ом. КД — персональный у каждого бизнеса
    (last_collected на документе), поэтому захват одного здания никак не
    блокирует доход с остальных, а при смене владельца недособранный КД
    переходит по наследству (см. submit_guess).
    """
    interval_s = BONUS_CLAIM_INTERVAL_MIN * 60
    async for b in db.cityroof_businesses.find({"ownerId": {"$ne": None}}):
        try:
            bonus = BUSINESS_BONUS.get(b.get("slug"))
            if not bonus:
                continue
            elapsed = _seconds_since_collected(b.get("last_collected"))
            if elapsed < interval_s:
                continue
            intervals = 1 if elapsed == float("inf") else int(elapsed // interval_s)
            amount = _interval_amount(bonus["daily"]) * intervals
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
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Купить WarCoin за $ по цене лиги."""
    user_id = str(current_user["_id"])
    config = await _warcoin_config(db)
    _, price = _league_and_price(config, current_user.get("balance", 0.0))
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
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Оплатить попытку захвата (10 WC) и начать мини-игру."""
    if not _event_active():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Событие сейчас неактивно")
    if not ObjectId.is_valid(business_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID")
    user_id = str(current_user["_id"])
    business = await db.cityroof_businesses.find_one({"_id": ObjectId(business_id)})
    if not business:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Бизнес не найден")
    if business.get("ownerId") == user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Это уже ваш бизнес")

    if not await _spend_wc(db, user_id, ATTACK_COST_WC):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно WarCoin")

    # Закрываем старые сессии игрока по этому бизнесу и создаём новую.
    await db.cityroof_sessions.delete_many({"attackerId": user_id, "businessId": business_id})
    session = {
        "attackerId": user_id,
        "businessId": business_id,
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
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Проверить комбинацию. Возвращает подсказку (exact/present) и статус."""
    user_id = str(current_user["_id"])
    if not ObjectId.is_valid(payload.sessionId):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректная сессия")
    session = await db.cityroof_sessions.find_one({"_id": ObjectId(payload.sessionId)})
    if not session or session.get("attackerId") != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сессия не найдена или истекла")

    business = await db.cityroof_businesses.find_one({"_id": ObjectId(session["businessId"])})
    if not business:
        await db.cityroof_sessions.delete_one({"_id": session["_id"]})
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Бизнес не найден")

    secret = business.get("secret", [])
    guess = payload.guess
    if len(guess) != len(secret):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неверная длина комбинации")

    exact = sum(1 for i in range(len(secret)) if guess[i] == secret[i])
    # present: совпадения по мультимножеству минус точные
    from collections import Counter
    common = sum((Counter(secret) & Counter(guess)).values())
    present = common - exact

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
            captured_income = _interval_amount(bonus["daily"])
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
        return {"solved": True, "exact": exact, "present": present, "attempts": attempts,
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
        "attempts": attempts,
        "maxAttempts": session.get("maxAttempts", MAX_ATTEMPTS),
    }


@router.post("/protect/{business_id}")
async def protect_business(
    business_id: str,
    payload: ProtectBody,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Купить защиту бизнеса (уровни 1–5). Сбрасывает прогресс атакующих."""
    if not ObjectId.is_valid(business_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID")
    user_id = str(current_user["_id"])
    business = await db.cityroof_businesses.find_one({"_id": ObjectId(business_id)})
    if not business:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Бизнес не найден")
    if business.get("ownerId") != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Вы не владелец бизнеса")

    cost = PROTECTION_COSTS.get(payload.level, payload.level * 1000)
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
    _admin=Depends(require_admin),
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
