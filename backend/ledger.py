"""Единый источник истины по деньгам: любое движение — через record_transaction."""
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from levels import record_trade
from timeutil import now_utc

INCOME = "income"
EXPENSE = "expense"

CAT_TRANSFER = "transfer"
CAT_TRADE = "trade"
CAT_CRYPTO = "crypto"
CAT_BUSINESS = "business"
CAT_REALESTATE = "realestate"
CAT_COMPANY = "company"
CAT_CITYROOF = "cityroof"
CAT_DIVIDEND = "dividend"
CAT_SHOP = "shop"
CAT_MINING = "mining"
CAT_SYSTEM = "system"
CAT_MARKET = "market"
# Инфраструктура рынка (заводы/источники/склады): те же /api/assets, но в
# реестре отдельно — дополняют CAT_BUSINESS/CAT_REALESTATE, не заменяют.
CAT_FACTORY = "factory"
CAT_SOURCE = "source"
CAT_WAREHOUSE = "warehouse"
# Ферма (см. farm.py): продажа культур со склада поля и покупка топлива.
CAT_FARM = "farm"
CAT_FUEL = "fuel"

VALID_DIRECTIONS = {INCOME, EXPENSE}
TRADE_XP_CATEGORIES = {CAT_TRADE, CAT_CRYPTO}


async def adjust_balance(
    db: AsyncIOMotorDatabase, user_id: str, delta: float
) -> Optional[float]:
    """Атомарный сдвиг баланса. Списать больше остатка нельзя (условие в БД —
    без гонок и минуса); None при недостатке средств / нет пользователя."""
    oid = ObjectId(user_id)
    # $inc по float накапливает пыль: клампим в 0 и округляем до сотых прямо в
    # атомарном апдейте — все идут через эту функцию, деньги в БД всегда в сотых.
    _rounded = [{"$set": {"balance": {"$round": [
        {"$max": [{"$add": ["$balance", delta]}, 0.0]}, 2]}}}]
    if delta < 0:
        result = await db.users.find_one_and_update(
            {"_id": oid, "balance": {"$gte": abs(delta)}},
            _rounded,
            return_document=True,  # pymongo.ReturnDocument.AFTER == True
        )
    else:
        result = await db.users.find_one_and_update(
            {"_id": oid},
            _rounded,
            return_document=True,
        )
    if not result:
        return None
    new_balance = result.get("balance", 0.0)
    # Единая WS-рассылка баланса отсюда: панель обновляется при любом изменении,
    # а не только в текущей вкладке. Ошибки проглатываем намеренно.
    try:
        from ws import push_to_user
        await push_to_user(user_id, {"type": "balance", "balance": round(float(new_balance), 2)})
    except Exception:
        pass
    return new_balance


async def record_transaction(
    db: AsyncIOMotorDatabase,
    user_id: str,
    direction: str,
    amount: float,
    category: str,
    label: str,
    *,
    counterparty: Optional[str] = None,
    balance_after: Optional[float] = None,
    symbol: Optional[str] = None,
    price: Optional[float] = None,
    meta: Optional[dict] = None,
) -> dict:
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"Invalid direction: {direction}")

    doc: dict[str, Any] = {
        "userId": str(user_id),
        "direction": direction,
        "category": category,
        "amount": round(float(amount), 2),
        "label": label,
        "counterparty": counterparty,
        "balance_after": balance_after,
        "meta": meta or {},
        # legacy-совместимые поля для старого UI/эндпоинтов
        "type": "income" if direction == INCOME else "expense",
        "symbol": symbol,
        "price": price,
        "timestamp": now_utc(),
    }
    result = await db.transactions.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    if category in TRADE_XP_CATEGORIES:
        await record_trade(db, str(user_id), amount, is_crypto=category == CAT_CRYPTO)
    return doc


def _normalize(doc: dict) -> dict:
    doc = dict(doc)
    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    ts = doc.get("timestamp")
    if isinstance(ts, datetime):
        doc["timestamp"] = ts.isoformat()
    # Гарантируем наличие обобщённых полей для старых trade-записей
    if "direction" not in doc:
        legacy = doc.get("type")
        doc["direction"] = INCOME if legacy == "sell" else EXPENSE
    if "category" not in doc:
        doc["category"] = CAT_TRADE if doc.get("symbol") else CAT_SYSTEM
    if not doc.get("label"):
        doc["label"] = doc.get("symbol") or doc.get("category", "operation")
    return doc


async def query_transactions(
    db: AsyncIOMotorDatabase,
    user_id: str,
    *,
    direction: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "date_desc",
    skip: int = 0,
    limit: int = 20,
    meta_filter: Optional[dict] = None,
) -> dict:
    """История операций: фильтры/поиск/сортировка/пагинация. meta_filter сужает
    до сущности по полям meta (companyId → meta.companyId).
    Возвращает {items, total, skip, limit}."""
    query: dict[str, Any] = {"userId": str(user_id)}
    if direction in VALID_DIRECTIONS:
        query["direction"] = direction
    if category:
        query["category"] = category
    if meta_filter:
        for k, v in meta_filter.items():
            query[f"meta.{k}"] = v
    if search:
        rx = {"$regex": search, "$options": "i"}
        query["$or"] = [
            {"label": rx},
            {"counterparty": rx},
            {"symbol": rx},
            {"category": rx},
        ]

    sort_map = {
        "date_desc": ("timestamp", -1),
        "date_asc": ("timestamp", 1),
        "amount_desc": ("amount", -1),
        "amount_asc": ("amount", 1),
    }
    sort_field, sort_dir = sort_map.get(sort, ("timestamp", -1))

    # Пагинация без count-скана по миллиону записей: limit+1 → hasMore.
    # total — оценка; фронт обязан смотреть totalExact/hasMore, а не строить
    # страницы по total.
    page_limit = max(1, min(limit, 100))
    cursor = (
        db.transactions.find(query)
        .sort(sort_field, sort_dir)
        .skip(max(0, skip))
        .limit(page_limit + 1)
    )
    raw_items = [_normalize(doc) async for doc in cursor]
    has_more = len(raw_items) > page_limit
    items = raw_items[:page_limit]
    # Если на первой странице и записей меньше лимита — total точный
    if skip == 0 and not has_more:
        total = len(items)
        total_exact = True
    else:
        total = skip + len(items) + (1 if has_more else 0)
        total_exact = False

    return {
        "items": items,
        "total": total,
        "totalExact": total_exact,
        "hasMore": has_more,
        "skip": skip,
        "limit": limit,
    }


# TTL-кэш: у кита неделя — сотни тысяч транзакций, агрегация ~20 с;
# вкладка аналитики перезапрашивает её чаще, чем данные реально меняются.
_WCACHE_TTL_S = 30.0
_wcache: dict[tuple, tuple[float, dict]] = {}


async def weekly_analytics(db: AsyncIOMotorDatabase, user_id: str, period: str = "week") -> dict:
    """Аналитика за period (today|yesterday|week|month|all): доход/расход/операции + посуточный ряд."""
    key = (user_id, period)
    hit = _wcache.get(key)
    mono = time.monotonic()
    if hit is not None and mono - hit[0] < _WCACHE_TTL_S:
        return dict(hit[1])   # копия: вызывающий кладёт balance поверх
    data = await _weekly_analytics_uncached(db, user_id, period)
    _wcache[key] = (mono, data)
    return dict(data)


async def _weekly_analytics_uncached(db: AsyncIOMotorDatabase, user_id: str, period: str) -> dict:
    now = now_utc()
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if period == "today":
        start, span_days = today0, 1
    elif period == "yesterday":
        start, span_days = today0 - timedelta(days=1), 1
    elif period == "month":
        start, span_days = today0 - timedelta(days=29), 30
    elif period == "all":
        first = await db.transactions.find({"userId": str(user_id)}).sort("timestamp", 1).limit(1).to_list(1)
        first_ts = first[0].get("timestamp") if first else None
        if isinstance(first_ts, datetime):
            start = first_ts.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start = today0
        span_days = (today0 - start).days + 1
    else:  # week (по умолчанию)
        start, span_days = today0 - timedelta(days=6), 7

    # Верхняя граница выборки: для «вчера» отсекаем сегодняшние транзакции.
    end = start + timedelta(days=span_days)

    days = []
    for i in range(span_days):
        d = start + timedelta(days=i)
        days.append({
            "date": d.strftime("%Y-%m-%d"),
            "weekday": d.weekday(),  # 0=Пн ... 6=Вс
            "income": 0.0,
            "expense": 0.0,
        })

    total_income = 0.0
    total_expense = 0.0
    operations = 0

    # Серверная агрегация: сотни тысяч транзакций в неделю (тик майнинга = 2
    # записи на ферму) через удалённую Mongo — выгрузка стоила >60 с.
    cursor = db.transactions.aggregate([
        {"$match": {"userId": str(user_id), "timestamp": {"$gte": start, "$lt": end}}},
        {"$group": {
            "_id": {"day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
                    "dir": {"$cond": [
                        {"$in": ["$direction", [INCOME, EXPENSE]]},
                        "$direction",
                        {"$cond": [{"$eq": ["$type", "sell"]}, INCOME, EXPENSE]},
                    ]}},
            "amount": {"$sum": "$amount"},
            "n": {"$sum": 1},
        }},
    ])
    day_by_date = {d["date"]: d for d in days}
    async for row in cursor:
        info = day_by_date.get(row["_id"]["day"])
        if not info:
            continue
        operations += row["n"]
        if row["_id"]["dir"] == INCOME:
            info["income"] += row["amount"]
            total_income += row["amount"]
        else:
            info["expense"] += row["amount"]
            total_expense += row["amount"]

    for d in days:
        d["income"] = round(d["income"], 2)
        d["expense"] = round(d["expense"], 2)

    return {
        "income": round(total_income, 2),
        "expense": round(total_expense, 2),
        "net": round(total_income - total_expense, 2),
        "operations": operations,
        "days": days,
        "period": period,
    }
