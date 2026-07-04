"""Единый денежный реестр (ledger).

Любое движение денег игрока проходит через record_transaction, что даёт
единую историю операций, аналитику и корректный баланс. Заменяет разрозненные
buy/sell-записи обобщённой моделью (direction + category), сохраняя обратную
совместимость со старыми полями (type/symbol/price).
"""
from datetime import datetime, timedelta
from typing import Any, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

# Направление движения денег с точки зрения владельца операции
INCOME = "income"
EXPENSE = "expense"

# Категории операций (расширяются по мере роста фич)
CAT_TRANSFER = "transfer"
CAT_TRADE = "trade"
CAT_CRYPTO = "crypto"
CAT_BUSINESS = "business"
CAT_REALESTATE = "realestate"
CAT_SHOP = "shop"
CAT_SYSTEM = "system"

VALID_DIRECTIONS = {INCOME, EXPENSE}


async def adjust_balance(
    db: AsyncIOMotorDatabase, user_id: str, delta: float
) -> Optional[float]:
    """Атомарно меняет баланс на delta.

    При списании (delta < 0) используется условие balance >= |delta|, чтобы
    исключить гонки и уход в минус. Возвращает новый баланс либо None, если
    средств недостаточно / пользователь не найден.
    """
    oid = ObjectId(user_id)
    if delta < 0:
        result = await db.users.find_one_and_update(
            {"_id": oid, "balance": {"$gte": abs(delta)}},
            {"$inc": {"balance": delta}},
            return_document=True,  # pymongo.ReturnDocument.AFTER == True
        )
    else:
        result = await db.users.find_one_and_update(
            {"_id": oid},
            {"$inc": {"balance": delta}},
            return_document=True,
        )
    if not result:
        return None
    return result.get("balance", 0.0)


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
    """Записывает операцию в реестр и возвращает сохранённый документ."""
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
        "timestamp": datetime.utcnow(),
    }
    result = await db.transactions.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    return doc


def _normalize(doc: dict) -> dict:
    """Приводит документ реестра к API-виду (id вместо _id, isoformat даты)."""
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
) -> dict:
    """Фильтрация / поиск / сортировка / пагинация истории операций.

    Возвращает {items, total, skip, limit}.
    """
    query: dict[str, Any] = {"userId": str(user_id)}
    if direction in VALID_DIRECTIONS:
        query["direction"] = direction
    if category:
        query["category"] = category
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

    total = await db.transactions.count_documents(query)
    cursor = (
        db.transactions.find(query)
        .sort(sort_field, sort_dir)
        .skip(max(0, skip))
        .limit(max(1, min(limit, 100)))
    )
    items = [_normalize(doc) async for doc in cursor]
    return {"items": items, "total": total, "skip": skip, "limit": limit}


async def weekly_analytics(db: AsyncIOMotorDatabase, user_id: str) -> dict:
    """Аналитика за последние 7 дней: доход, расход, изменение капитала,
    число операций и посуточный ряд для графика.
    """
    now = datetime.utcnow()
    start = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)

    # Посуточные корзины (индекс 0 = 6 дней назад ... 6 = сегодня)
    days = []
    for i in range(7):
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

    cursor = db.transactions.find({
        "userId": str(user_id),
        "timestamp": {"$gte": start},
    })
    async for doc in cursor:
        ts = doc.get("timestamp")
        if not isinstance(ts, datetime):
            continue
        idx = (ts.replace(hour=0, minute=0, second=0, microsecond=0) - start).days
        if idx < 0 or idx > 6:
            continue
        amount = float(doc.get("amount", 0.0))
        direction = doc.get("direction")
        if direction is None:
            direction = INCOME if doc.get("type") == "sell" else EXPENSE
        operations += 1
        if direction == INCOME:
            days[idx]["income"] += amount
            total_income += amount
        else:
            days[idx]["expense"] += amount
            total_expense += amount

    for d in days:
        d["income"] = round(d["income"], 2)
        d["expense"] = round(d["expense"], 2)

    return {
        "income": round(total_income, 2),
        "expense": round(total_expense, 2),
        "net": round(total_income - total_expense, 2),
        "operations": operations,
        "days": days,
    }
