"""Уровни игрока: XP за торговлю, порог перехода lvl -> lvl+1 = lvl*400 XP,
лимит владения недвижимостью растёт с уровнем."""
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

XP_PER_LEVEL_STEP = 400
# Торговый оборот в рублях/валюте, дающий 1 XP. Калибровка: lvl 10 ≈ 1.8M оборота.
TRADE_VOLUME_PER_XP = 50.0
# Сделки меньше этого порога считаются «мелкими» (отдельное достижение).
SMALL_TRADE_LIMIT = 100.0
MAX_LEVEL = 100
# Переводы: отправлять можно со 2 уровня, получать — с 5.
TRANSFER_SEND_MIN_LEVEL = 2
TRANSFER_RECEIVE_MIN_LEVEL = 5
# Лимит недвижимости: BASE + level * PER_LEVEL, не выше REALESTATE_HARD_CAP.
REALESTATE_LIMIT_BASE = 2
REALESTATE_LIMIT_PER_LEVEL = 1
REALESTATE_HARD_CAP = 40


def xp_for_level(level: int) -> int:
    """Суммарный XP, нужный для достижения уровня (lvl -> lvl+1 стоит lvl*400)."""
    return XP_PER_LEVEL_STEP * (level - 1) * level // 2


def level_from_xp(xp: int) -> int:
    level = 1
    while level < MAX_LEVEL and xp >= xp_for_level(level + 1):
        level += 1
    return level


def realestate_limit(level: int) -> int:
    return min(REALESTATE_HARD_CAP, REALESTATE_LIMIT_BASE + level * REALESTATE_LIMIT_PER_LEVEL)


async def record_trade(db: AsyncIOMotorDatabase, user_id: str, volume: float, is_crypto: bool) -> list[dict]:
    """Учитывает сделку (XP, счётчики, максимум) и возвращает новые достижения."""
    volume = abs(float(volume))
    inc: dict = {
        "xp": int(volume / TRADE_VOLUME_PER_XP),
        "trade_count": 1,
        "trade_volume": volume,
    }
    if volume < SMALL_TRADE_LIMIT:
        inc["small_trades"] = 1
    if is_crypto:
        inc["crypto_trades"] = 1
        inc["crypto_volume"] = volume

    doc = await db.users.find_one_and_update(
        {"_id": ObjectId(user_id)},
        {"$inc": inc, "$max": {"trade_max": volume}},
        return_document=True,
        projection={"xp": 1, "level": 1},
    )
    if not doc:
        return []
    level = level_from_xp(int(doc.get("xp", 0)))
    if level != doc.get("level", 1):
        await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"level": level}})

    from achievements import check_achievements
    return await check_achievements(db, user_id)
