"""Достижения: выдаются один раз и остаются навсегда.

Каждое достижение: условие (metric + target), редкость и награда.
Награда: деньги (через ledger, категория system) и/или XP.
Уникальный индекс user_achievements (userId, achievementId) не даёт выдать дважды
даже при параллельных сделках.

Капитал (metric=capital) читается из users.networth_cache — поле должно
обновляться планировщиком при пересчёте капитала (networth.py), иначе не откроется.
"""
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError
from bson import ObjectId

from timeutil import now_utc

# Награда за редкость по умолчанию: (деньги, XP). Явная награда в записи важнее.
RARITY_REWARD = {
    "common": (1_000, 20),
    "uncommon": (5_000, 50),
    "rare": (50_000, 150),
    "epic": (500_000, 400),
    "legendary": (5_000_000, 1_000),
    "mythic": (100_000_000, 5_000),
}
RARITY_NAME = {
    "common": "Обычное", "uncommon": "Необычное", "rare": "Редкое",
    "epic": "Эпическое", "legendary": "Легендарное", "mythic": "Мифическое",
}


def _fmt(n: float) -> str:
    return f"{int(n):,}".replace(",", " ")


def _a(id_, name, desc, metric, target, rarity, reward=None) -> dict:
    money, xp = reward or RARITY_REWARD[rarity]
    return {"id": id_, "name": name, "desc": desc, "metric": metric, "target": target,
            "rarity": rarity, "reward": {"money": money, "xp": xp}}


def _build() -> list[dict]:
    items: list[dict] = []

    # ── Сделки (количество) ── 20
    trades = [
        (1, "Первая сделка", "common"), (3, "Осторожный старт", "common"), (5, "Пять ударов", "common"),
        (10, "Разогрев", "common"), (25, "Регулярный игрок", "uncommon"), (50, "Половина сотни", "uncommon"),
        (75, "На стабилье", "uncommon"), (100, "Трейдер", "rare"), (150, "Бывалый", "rare"),
        (250, "Завсегдатай биржи", "rare"), (400, "Тикер-зависимый", "epic"), (500, "Пятисотник", "epic"),
        (750, "Ритм рынка", "epic"), (1000, "Маркет-мейкер", "legendary"), (1500, "Биржевой мастер", "legendary"),
        (2500, "Старожил", "legendary"), (5000, "Машина сделок", "legendary"), (7500, "Неутомимый", "mythic"),
        (10000, "Легенда ордербука", "mythic"), (25000, "Бессмертный тикер", "mythic"),
    ]
    for n, name, r in trades:
        items.append(_a(f"trades_{n}", name, f"Совершите {n} сделок", "trades", n, r))

    # ── Оборот ── 15
    volume = [
        (10_000, "Десять тысяч", "common"), (100_000, "Сто тысяч", "uncommon"),
        (500_000, "Пол-миллиона", "uncommon"), (1_000_000, "Миллионер оборота", "rare"),
        (5_000_000, "Пять миллионов", "rare"), (10_000_000, "Десять миллионов", "epic"),
        (50_000_000, "Полсотни миллионов", "epic"), (100_000_000, "Сотня миллионов", "epic"),
        (500_000_000, "Полмиллиарда", "legendary"), (1_000_000_000, "Миллиард оборота", "legendary"),
        (5_000_000_000, "Пять миллиардов", "legendary"), (10_000_000_000, "Десять миллиардов", "mythic"),
        (50_000_000_000, "Пятьдесят миллиардов", "mythic"), (100_000_000_000, "Сто миллиардов", "mythic"),
        (1_000_000_000_000, "Триллионер оборота", "mythic"),
    ]
    for n, name, r in volume:
        items.append(_a(f"volume_{n}", name, f"Оборот торгов {_fmt(n)} $", "volume", n, r))

    # ── Уровень ── 15
    levels = [
        (5, "Освоился", "common"), (10, "Опытный", "uncommon"), (15, "Уверенный", "uncommon"),
        (20, "Знаток", "rare"), (25, "Ветеран", "rare"), (30, "Тренированный", "rare"),
        (35, "Профи", "epic"), (40, "Элита", "epic"), (50, "Легенда", "legendary"),
        (60, "Непобедимый", "legendary"), (70, "Владыка", "legendary"), (75, "Мифический", "mythic"),
        (80, "Рыночный оракул", "mythic"), (90, "Вечный", "mythic"), (100, "Абсолют", "mythic"),
    ]
    for n, name, r in levels:
        items.append(_a(f"level_{n}", name, f"Достигните {n} уровня", "level", n, r))

    # ── Капитал ── 25
    capital = [
        (10_000, "Первые деньги", "common"), (100_000, "Шестизначный", "common"),
        (1_000_000, "Миллионер", "uncommon"), (5_000_000, "Состоятельный", "uncommon"),
        (10_000_000, "Десятимиллионер", "rare"), (50_000_000, "Полсотни миллионов", "rare"),
        (100_000_000, "Стомиллионер", "rare"), (500_000_000, "Полумиллиардер", "epic"),
        (1_000_000_000, "Миллиардер", "epic"),
        (5_000_000_000, "Олигарх", "legendary"), (10_000_000_000, "Десятимиллиардер", "legendary"),
        (15_000_000_000, "Магнат рынка", "legendary"), (20_000_000_000, "Двадцатка", "legendary"),
        (25_000_000_000, "Финансовый титан", "legendary"), (30_000_000_000, "Тридцатка", "mythic"),
        (35_000_000_000, "Наследник", "mythic"), (40_000_000_000, "Сорокамиллиардер", "mythic"),
        (50_000_000_000, "Император рынка", "mythic"), (75_000_000_000, "Владелец экономики", "mythic"),
        (100_000_000_000, "Стомиллиардер", "mythic"), (250_000_000_000, "Инвестор масштаба", "mythic"),
        (500_000_000_000, "Полтриллиона", "mythic"), (1_000_000_000_000, "Триллионер", "mythic"),
    ]
    for n, name, r in capital:
        items.append(_a(f"capital_{n}", name, f"Капитал {_fmt(n)} $", "capital", n, r))

    # ── Разнообразные условия ── 25
    items += [
        _a("small_1", "Копейка", "Совершите 1 мелкую сделку (до 100 $)", "small_trades", 1, "common"),
        _a("small_200", "Грошовый игрок", "Совершите 200 мелких сделок", "small_trades", 200, "rare"),
        _a("small_1000", "Копилка", "Совершите 1000 мелких сделок", "small_trades", 1000, "epic"),
        _a("crypto_1", "Первый блок", "Совершите 1 сделку с криптой", "crypto_trades", 1, "common"),
        _a("crypto_50", "Криптоэнтузиаст", "Совершите 50 сделок с криптой", "crypto_trades", 50, "uncommon"),
        _a("crypto_vol_1m", "Крипто-миллион", "Оборот криптой 1 000 000 $", "crypto_volume", 1_000_000, "rare"),
        _a("crypto_vol_1b", "Крипто-кит", "Оборот криптой 1 000 000 000 $", "crypto_volume", 1_000_000_000, "mythic"),
        _a("big_trade_100k", "Крупный ордер", "Одна сделка на 100 000 $", "trade_max", 100_000, "uncommon"),
        _a("big_trade_10m", "Биржевой удар", "Одна сделка на 10 000 000 $", "trade_max", 10_000_000, "epic"),
        _a("big_trade_1b", "Слон в магазине", "Одна сделка на 1 000 000 000 $", "trade_max", 1_000_000_000, "mythic"),
        _a("realestate_1", "Первый дом", "Купите первую недвижимость", "realestate_owned", 1, "common"),
        _a("realestate_10", "Застройщик", "Владейте 10 объектами недвижимости", "realestate_owned", 10, "rare"),
        _a("realestate_30", "Домовладелец", "Владейте 30 объектами недвижимости", "realestate_owned", 30, "epic"),
        _a("business_1", "Свой бизнес", "Купите первый бизнес", "business_owned", 1, "uncommon"),
        _a("business_5", "Сеть бизнесов", "Владейте 5 бизнесами", "business_owned", 5, "rare"),
        _a("car_1", "Первая машина", "Купите первый автомобиль", "car_owned", 1, "common"),
        _a("car_10", "Автопарк", "Владейте 10 автомобилями", "car_owned", 10, "rare"),
        _a("diversified_cap", "Многогранность", "Владейте недвижимостью, бизнесом и автомобилем одновременно", "diversified", 3, "rare"),
    ]

    # ── Мета: коллекции достижений ── 15
    items += [
        _a("meta_10", "Коллекционер I", "Получите 10 достижений", "achievements_count", 10, "uncommon"),
        _a("meta_25", "Коллекционер II", "Получите 25 достижений", "achievements_count", 25, "rare"),
        _a("meta_50", "Коллекционер III", "Получите 50 достижений", "achievements_count", 50, "epic"),
        _a("meta_75", "Коллекционер IV", "Получите 75 достижений", "achievements_count", 75, "legendary"),
        _a("meta_99", "Почти всё", "Получите 99 достижений", "achievements_count", 99, "mythic"),
        _a("meta_rare_10", "Ценитель редкого", "Получите 10 редких достижений", "rarity_rare", 10, "rare"),
        _a("meta_epic_5", "Эпичный коллекционер", "Получите 5 эпических достижений", "rarity_epic", 5, "epic"),
        _a("meta_legend_3", "Легендарная троица", "Получите 3 легендарных достижения", "rarity_legendary", 3, "legendary"),
        _a("meta_myth_1", "Миф во плоти", "Получите хотя бы 1 мифическое достижение", "rarity_mythic", 1, "mythic"),
    ]

    # ── Пожертвования банку ── 9
    items += [
        _a("donate_1", "Щедрая рука", "Пожертвуйте банку в первый раз", "donation_count", 1, "common"),
        _a("donate_10", "Меценат", "Сделайте 10 пожертвований банку", "donation_count", 10, "uncommon"),
        _a("donate_50", "Филантроп", "Сделайте 50 пожертвований банку", "donation_count", 50, "rare"),
        _a("donate_sum_1k", "Первый взнос", "Пожертвуйте банку 1 000 $ суммарно", "donated", 1_000, "common"),
        _a("donate_sum_50k", "Благотворитель", "Пожертвуйте банку 50 000 $ суммарно", "donated", 50_000, "uncommon"),
        _a("donate_sum_500k", "Спонсор государства", "Пожертвуйте банку 500 000 $ суммарно", "donated", 500_000, "rare"),
        _a("donate_sum_5m", "Народный герой", "Пожертвуйте банку 5 000 000 $ суммарно", "donated", 5_000_000, "epic"),
        _a("donate_sum_50m", "Золотой фонд", "Пожертвуйте банку 50 000 000 $ суммарно", "donated", 50_000_000, "legendary"),
        _a("donate_sum_1b", "Благодетель нации", "Пожертвуйте банку 1 000 000 000 $ суммарно", "donated", 1_000_000_000, "mythic"),
    ]

    return items


ACHIEVEMENTS = _build()
ACHIEVEMENTS_BY_ID = {a["id"]: a for a in ACHIEVEMENTS}

_RARITY_TOTAL = {}
for _a_item in ACHIEVEMENTS:
    _RARITY_TOTAL[_a_item["rarity"]] = _RARITY_TOTAL.get(_a_item["rarity"], 0) + 1

# Реальные метрики, которые читаются из users; остальные (realestate_owned, …) считаются из коллекций.
_USER_FIELDS = {"trade_count", "trade_volume", "level", "networth_cache", "trade_max",
                "small_trades", "crypto_trades", "crypto_volume", "login_streak", "referrals"}


async def _count_owned(db: AsyncIOMotorDatabase, user_id: str, atype: str) -> int:
    return await db.user_assets.count_documents({"userId": user_id, "type": atype})


async def _metric_values(db: AsyncIOMotorDatabase, user_id: str, user: dict, owned_ids: set[str]) -> dict:
    earned = [ACHIEVEMENTS_BY_ID[i] for i in owned_ids if i in ACHIEVEMENTS_BY_ID]
    rarity_count = {r: 0 for r in RARITY_REWARD}
    for a in earned:
        rarity_count[a["rarity"]] += 1
    values = {
        "trades": int(user.get("trade_count", 0)),
        "volume": float(user.get("trade_volume", 0.0)),
        "level": int(user.get("level", 1)),
        "capital": float(user.get("networth_cache", 0.0)),
        "trade_max": float(user.get("trade_max", 0.0)),
        "small_trades": int(user.get("small_trades", 0)),
        "crypto_trades": int(user.get("crypto_trades", 0)),
        "crypto_volume": float(user.get("crypto_volume", 0.0)),
        "login_streak": int(user.get("login_streak", 0)),
        "referrals": int(user.get("referrals_count", 0)),
        "donated": float(user.get("donated_total", 0.0)),
        "donation_count": int(user.get("donation_count", 0)),
        "achievements_count": len(earned),
        "realestate_owned": await _count_owned(db, user_id, "realestate"),
        "business_owned": await _count_owned(db, user_id, "business"),
        "car_owned": await _count_owned(db, user_id, "car"),
        "diversified": int(
            (user.get("stocks_held", 0) > 0) + (user.get("crypto_trades", 0) > 0)
            + (await _count_owned(db, user_id, "realestate") > 0)
        ),
    }
    for r in RARITY_REWARD:
        values[f"rarity_{r}"] = rarity_count[r]
    for r in ("common", "uncommon", "rare", "epic"):
        values[f"rarity_all_{r}"] = 1 if rarity_count[r] >= _RARITY_TOTAL[r] else 0
    return values


async def _grant_reward(db: AsyncIOMotorDatabase, user_id: str, ach: dict) -> None:
    from ledger import INCOME, CAT_SYSTEM, adjust_balance, record_transaction
    reward = ach["reward"]
    if reward["money"] > 0:
        new_balance = await adjust_balance(db, user_id, reward["money"])
        await record_transaction(
            db, user_id, INCOME, reward["money"], CAT_SYSTEM,
            f"Достижение: {ach['name']}", balance_after=new_balance,
        )
    if reward["xp"] > 0:
        await db.users.update_one({"_id": ObjectId(user_id)}, {"$inc": {"xp": reward["xp"]}})


async def check_achievements(db: AsyncIOMotorDatabase, user_id: str) -> list[dict]:
    user = await db.users.find_one({"_id": ObjectId(user_id)}) or {}
    if not user:
        return []
    owned = {
        d["achievementId"]
        async for d in db.user_achievements.find({"userId": user_id}, {"achievementId": 1})
    }
    values = await _metric_values(db, user_id, user, owned)

    unlocked: list[dict] = []
    # Повторяем проход: награда (например, XP или коллекция) может открыть следующие достижения.
    progressed = True
    while progressed:
        progressed = False
        for a in ACHIEVEMENTS:
            if a["id"] in owned or values.get(a["metric"], 0) < a["target"]:
                continue
            try:
                await db.user_achievements.insert_one(
                    {"userId": user_id, "achievementId": a["id"], "rarity": a["rarity"], "unlockedAt": now_utc()}
                )
            except DuplicateKeyError:
                continue
            owned.add(a["id"])
            await _grant_reward(db, user_id, a)
            unlocked.append(a)
            progressed = True
            values = await _metric_values(db, user_id, user, owned)
    return unlocked


async def list_user_achievements(db: AsyncIOMotorDatabase, user_id: str) -> list[dict]:
    earned = {
        d["achievementId"]: d["unlockedAt"]
        async for d in db.user_achievements.find({"userId": user_id})
    }
    result = []
    for a in ACHIEVEMENTS:
        when = earned.get(a["id"])
        result.append({
            "id": a["id"],
            "name": a["name"],
            "desc": a["desc"],
            "rarity": a["rarity"],
            "rarityName": RARITY_NAME[a["rarity"]],
            "reward": a["reward"],
            "unlocked": when is not None,
            "unlockedAt": when.isoformat() if when else None,
        })
    return result
