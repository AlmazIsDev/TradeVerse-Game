"""
StockEngine Database Wrappers
==============================
Асинхронные обёртки для работы с коллекциями MongoDB, связанными с акциями.
"""

from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase


# ── Stock Collection ───────────────────────────────────────────────────────────


async def get_stock_collection(db: AsyncIOMotorDatabase):
    """Возвращает коллекцию stocks."""
    return db.stocks


async def find_stock_by_symbol(db: AsyncIOMotorDatabase, symbol: str) -> Optional[dict]:
    """Находит акцию по тикеру."""
    doc = await db.stocks.find_one({"symbol": symbol.upper()})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc


async def find_all_stocks(db: AsyncIOMotorDatabase) -> list[dict]:
    """Возвращает все акции."""
    stocks = []
    cursor = db.stocks.find({}).sort("symbol", 1)
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        stocks.append(doc)
    return stocks


async def create_stock(db: AsyncIOMotorDatabase, stock_data: dict) -> dict:
    """Создаёт новую акцию."""
    stock_data["symbol"] = stock_data["symbol"].upper()
    stock_data["created_at"] = datetime.now(timezone.utc)
    stock_data["updated_at"] = datetime.now(timezone.utc)
    stock_data["price_history"] = []
    # config_overrides — переопределения параметров модели для этой акции
    if "config_overrides" not in stock_data:
        stock_data["config_overrides"] = {}

    result = await db.stocks.insert_one(stock_data)
    return await find_stock_by_symbol(db, stock_data["symbol"])


async def update_stock_price(
    db: AsyncIOMotorDatabase,
    symbol: str,
    new_price: float,
    change: float,
    change_percent: float,
    event_label: Optional[str] = None,
) -> Optional[dict]:
    """Обновляет цену акции и добавляет запись в историю."""
    now = datetime.now(timezone.utc)

    update = {
        "$set": {
            "price": new_price,
            "change": change,
            "changePercent": change_percent,
            "updated_at": now,
            "last_event": event_label,
        },
        "$push": {
            "price_history": {
                "$each": [{"price": new_price, "timestamp": now, "event": event_label}],
                "$slice": -100,  # Храним последние 100 точек
            }
        },
    }

    await db.stocks.update_one({"symbol": symbol.upper()}, update)
    return await find_stock_by_symbol(db, symbol.upper())


async def update_free_shares(
    db: AsyncIOMotorDatabase,
    symbol: str,
    delta: int,
) -> Optional[dict]:
    """Обновляет количество свободных акций (положительное = выпуск, отрицательное = покупка)."""
    await db.stocks.update_one(
        {"symbol": symbol.upper()},
        {"$inc": {"free_shares": -delta}},
    )
    return await find_stock_by_symbol(db, symbol.upper())


async def update_stock_config(
    db: AsyncIOMotorDatabase,
    symbol: str,
    config_overrides: dict,
) -> Optional[dict]:
    """
    Обновляет переопределения конфига для конкретной акции.

    Пример:
        await update_stock_config(db, "AAPL", {
            "volatility_k": 0.2,
            "total_shares": 500_000_000,
            "price_drop_threshold": -0.03,
        })
    """
    # Валидация: разрешаем только определённые поля
    allowed_fields = {
        "total_shares", "volatility_k", "player_groups",
        "price_drop_threshold", "price_rise_threshold",
        "max_buy_probability", "max_sell_probability",
        "random_events", "min_order_size", "max_order_size_percent",
        "min_price", "max_price",
    }
    filtered = {k: v for k, v in config_overrides.items() if k in allowed_fields}

    await db.stocks.update_one(
        {"symbol": symbol.upper()},
        {"$set": {f"config_overrides.{k}": v for k, v in filtered.items()}},
    )
    return await find_stock_by_symbol(db, symbol.upper())


# ── Order Collection ───────────────────────────────────────────────────────────


async def get_order_collection(db: AsyncIOMotorDatabase):
    """Возвращает коллекцию stock_orders."""
    return db.stock_orders


async def create_order(db: AsyncIOMotorDatabase, order_data: dict) -> dict:
    """Создаёт ордер на покупку/продажу."""
    order_data["timestamp"] = datetime.now(timezone.utc)
    order_data["status"] = "completed"

    result = await db.stock_orders.insert_one(order_data)
    order_data["id"] = str(result.inserted_id)
    return order_data


async def find_orders_by_user(
    db: AsyncIOMotorDatabase,
    user_id: str,
    limit: int = 50,
) -> list[dict]:
    """Возвращает ордера пользователя."""
    orders = []
    cursor = (
        db.stock_orders.find({"userId": user_id})
        .sort("timestamp", -1)
        .limit(limit)
    )
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        orders.append(doc)
    return orders


# ── Portfolio Collection ───────────────────────────────────────────────────────


async def get_portfolio_collection(db: AsyncIOMotorDatabase):
    """Возвращает коллекцию portfolios."""
    return db.portfolios


async def find_portfolio(db: AsyncIOMotorDatabase, user_id: str) -> Optional[dict]:
    """Находит портфель пользователя."""
    doc = await db.portfolios.find_one({"userId": user_id})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc


async def upsert_portfolio_holding(
    db: AsyncIOMotorDatabase,
    user_id: str,
    symbol: str,
    name: str,
    quantity: int,
    price: float,
    is_buy: bool,
) -> dict:
    """
    Обновляет холдинг в портфеле.
    Для покупки: увеличиваем количество, пересчитываем среднюю цену.
    Для продажи: уменьшаем количество.
    """
    portfolio = await find_portfolio(db, user_id)

    if not portfolio:
        # Создаём новый портфель
        new_portfolio = {
            "userId": user_id,
            "holdings": [
                {
                    "symbol": symbol,
                    "name": name,
                    "quantity": quantity,
                    "average_buy_price": price,
                }
            ],
            "updated_at": datetime.now(timezone.utc),
        }
        result = await db.portfolios.insert_one(new_portfolio)
        new_portfolio["id"] = str(result.inserted_id)
        return new_portfolio

    # Ищем существующий холдинг
    holdings = portfolio.get("holdings", [])
    existing = None
    for h in holdings:
        if h["symbol"] == symbol:
            existing = h
            break

    if is_buy:
        if existing:
            # Пересчитываем среднюю цену покупки
            total_qty = existing["quantity"] + quantity
            if total_qty > 0:
                avg_price = (
                    (existing["average_buy_price"] * existing["quantity"])
                    + (price * quantity)
                ) / total_qty
            else:
                avg_price = 0
            existing["quantity"] = total_qty
            existing["average_buy_price"] = round(avg_price, 4)
            existing["name"] = name
        else:
            holdings.append({
                "symbol": symbol,
                "name": name,
                "quantity": quantity,
                "average_buy_price": price,
            })
    else:
        # Продажа
        if existing:
            existing["quantity"] = max(0, existing["quantity"] - quantity)
            if existing["quantity"] == 0:
                holdings = [h for h in holdings if h["symbol"] != symbol]

    await db.portfolios.update_one(
        {"userId": user_id},
        {"$set": {"holdings": holdings, "updated_at": datetime.now(timezone.utc)}},
    )

    return await find_portfolio(db, user_id)


# ── Event Log Collection ───────────────────────────────────────────────────────


async def get_event_collection(db: AsyncIOMotorDatabase):
    """Возвращает коллекцию stock_events."""
    return db.stock_events


async def log_event(
    db: AsyncIOMotorDatabase,
    symbol: str,
    event_type: str,
    event_label: str,
    multiplier: float,
    price_before: float,
    price_after: float,
) -> dict:
    """Записывает событие в лог."""
    event = {
        "symbol": symbol,
        "event_type": event_type,
        "event_label": event_label,
        "multiplier": multiplier,
        "price_before": price_before,
        "price_after": price_after,
        "timestamp": datetime.now(timezone.utc),
    }
    result = await db.stock_events.insert_one(event)
    event["id"] = str(result.inserted_id)
    return event


async def find_recent_events(
    db: AsyncIOMotorDatabase,
    symbol: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """Возвращает последние события."""
    query = {} if not symbol else {"symbol": symbol.upper()}
    events = []
    cursor = db.stock_events.find(query).sort("timestamp", -1).limit(limit)
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        events.append(doc)
    return events
