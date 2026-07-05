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
from ledger import EXPENSE, CAT_CITYROOF, adjust_balance, record_transaction

router = APIRouter(prefix="/api/cityroof", tags=["cityroof"])

ATTACK_COST_WC = 10
MAX_ATTEMPTS = 8
PROTECTION_MAX = 5
PROTECTION_COST_WC = 100        # × уровень
WINNER_REWARD_WC = 500

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
    "leagues": [
        {"name": "bronze", "minBalance": 0, "price": 50},
        {"name": "silver", "minBalance": 50000, "price": 40},
        {"name": "gold", "minBalance": 250000, "price": 30},
        {"name": "platinum", "minBalance": 1000000, "price": 22},
        {"name": "diamond", "minBalance": 5000000, "price": 15},
    ]
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
    leagues = sorted(config.get("leagues", []), key=lambda l: l.get("minBalance", 0))
    chosen = leagues[0] if leagues else {"name": "bronze", "price": 50}
    for l in leagues:
        if balance >= l.get("minBalance", 0):
            chosen = l
    return chosen.get("name", "bronze"), float(chosen.get("price", 50))


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
                "protection_level": 0, "last_captured": None, **secret,
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
    cost = round(price * payload.amount, 2)

    new_balance = await adjust_balance(db, user_id, -cost)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$inc": {"warcoin": payload.amount}})
    await record_transaction(
        db, user_id, EXPENSE, cost, CAT_CITYROOF,
        f"Покупка {payload.amount} WC", balance_after=new_balance,
        meta={"warcoin": payload.amount, "price": price},
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
        await db.cityroof_businesses.update_one(
            {"_id": business["_id"]},
            {"$set": {
                "ownerId": user_id,
                "ownerName": current_user.get("username"),
                "ownerColor": _color_for(user_id),
                "protection_level": 0,
                "last_captured": _now(),
                **new_secret,
            }},
        )
        await db.cityroof_sessions.delete_one({"_id": session["_id"]})
        return {"solved": True, "exact": exact, "present": present, "attempts": attempts,
                "business": _serialize_business(await db.cityroof_businesses.find_one({"_id": business["_id"]}), user_id)}

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

    cost = payload.level * PROTECTION_COST_WC
    if not await _spend_wc(db, user_id, cost):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно WarCoin")

    new_secret = _make_secret(payload.level)
    await db.cityroof_businesses.update_one(
        {"_id": business["_id"]},
        {"$set": {"protection_level": payload.level, **new_secret}},
    )
    # Все текущие попытки по этому бизнесу аннулируются.
    await db.cityroof_sessions.delete_many({"businessId": business_id})
    return {
        "protectionLevel": payload.level,
        "cost": cost,
        "warcoin": await _get_wc(db, user_id),
        "business": _serialize_business(await db.cityroof_businesses.find_one({"_id": business["_id"]}), user_id),
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
    return {"message": "Сезон закрыт"}
