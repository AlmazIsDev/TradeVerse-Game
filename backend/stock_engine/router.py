"""
StockEngine API Router
=======================
REST API эндпоинты для торговли акциями.

Endpoints:
    GET  /api/v2/stocks              — Список всех акций
    GET  /api/v2/stocks/{symbol}     — Детали акции
    POST /api/v2/stocks              — Создать акцию (admin)
    POST /api/v2/stocks/trade        — Купить/продать акции
    GET  /api/v2/stocks/portfolio    — Портфель текущего пользователя
    GET  /api/v2/stocks/orders       — История ордеров
    GET  /api/v2/stocks/events       — Последние события
    PATCH /api/v2/stocks/{symbol}/config — Обновить конфиг акции (admin)
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from database import get_db
from main import get_current_user, require_admin

from .schemas import (
    StockCreate,
    StockOrderRequest,
    StockOrderResponse,
    StockResponse,
    StockEventResponse,
    PortfolioResponse,
)
from .service import StockService


router = APIRouter(prefix="/api/v2/stocks", tags=["stocks"])


def get_stock_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> StockService:
    """Dependency: создаёт StockService."""
    return StockService(db)


# ── Public Endpoints ──────────────────────────────────────────────────────────


@router.get("", response_model=list[StockResponse])
async def list_stocks(
    service: StockService = Depends(get_stock_service),
):
    """Возвращает список всех доступных акций."""
    stocks = await service.get_all_stocks()
    return [_format_stock(s) for s in stocks]


@router.get("/{symbol}", response_model=StockResponse)
async def get_stock(
    symbol: str,
    service: StockService = Depends(get_stock_service),
):
    """Возвращает детали конкретной акции."""
    stock = await service.get_stock(symbol)
    if not stock:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Акция '{symbol}' не найдена",
        )
    return _format_stock(stock)


# ── Trading Endpoints ─────────────────────────────────────────────────────────


@router.post("/trade", response_model=StockOrderResponse)
async def trade_stock(
    order: StockOrderRequest,
    current_user: dict = Depends(get_current_user),
    service: StockService = Depends(get_stock_service),
):
    """
    Купить или продать акции.

    - **symbol**: Тикер акции (AAPL)
    - **action**: "buy" или "sell"
    - **quantity**: Количество акций (мин. 1)
    """
    try:
        result = await service.execute_trade(
            user_id=str(current_user["_id"]),
            symbol=order.symbol,
            action=order.action,
            quantity=order.quantity,
        )
        return _format_order(result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ── Portfolio Endpoints ───────────────────────────────────────────────────────


@router.get("/portfolio", response_model=PortfolioResponse)
async def get_portfolio(
    current_user: dict = Depends(get_current_user),
    service: StockService = Depends(get_stock_service),
):
    """Возвращает портфель текущего пользователя с текущей стоимостью."""
    portfolio = await service.get_portfolio(str(current_user["_id"]))
    if not portfolio:
        return {
            "user_id": str(current_user["_id"]),
            "total_value": 0.0,
            "total_invested": 0.0,
            "total_profit_loss": 0.0,
            "items": [],
        }

    return _format_portfolio(portfolio)


@router.get("/orders")
async def get_orders(
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    service: StockService = Depends(get_stock_service),
):
    """Возвращает историю ордеров текущего пользователя."""
    orders = await service.get_user_orders(str(current_user["_id"]), limit)
    return [_format_order(o) for o in orders]


@router.get("/bot-orders")
async def get_bot_orders(
    limit: int = Query(100, ge=1, le=500),
    _admin=Depends(require_admin),
    db=Depends(get_db),
):
    """Возвращает ордера ботов (только для администраторов)."""
    orders = []
    cursor = (
        db.stock_orders.find({"is_bot": True})
        .sort("timestamp", -1)
        .limit(limit)
    )
    async for doc in cursor:
        doc["id"] = str(doc["_id"])
        orders.append(_format_order(doc))
    return orders


# ── Events Endpoints ──────────────────────────────────────────────────────────


@router.get("/events")
async def get_events(
    symbol: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    service: StockService = Depends(get_stock_service),
):
    """Возвращает последние рыночные события."""
    events = await service.get_recent_events(symbol, limit)
    return [_format_event(e) for e in events]


# ── Admin Endpoints ───────────────────────────────────────────────────────────


@router.post("", response_model=StockResponse, status_code=status.HTTP_201_CREATED)
async def create_stock(
    stock_data: StockCreate,
    _admin=Depends(require_admin),
    service: StockService = Depends(get_stock_service),
):
    """Создаёт новую акцию (только для администраторов)."""
    existing = await service.get_stock(stock_data.symbol)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Акция '{stock_data.symbol}' уже существует",
        )

    stock = await service.create_new_stock(
        symbol=stock_data.symbol,
        name=stock_data.name,
        price=stock_data.price,
        total_shares=stock_data.total_shares,
        free_shares=stock_data.free_shares,
        config_overrides=stock_data.config_overrides,
    )
    return _format_stock(stock)


# ── Config Management (Admin) ─────────────────────────────────────────────────


@router.patch("/{symbol}/config", response_model=StockResponse)
async def update_stock_config(
    symbol: str,
    config_data: dict,
    _admin=Depends(require_admin),
    service: StockService = Depends(get_stock_service),
):
    """
    Обновляет переопределения конфига для конкретной акции.

    Доступные поля для переопределения:
    - **volatility_k**: Коэффициент волатильности [0.001, 1.0]
    - **total_shares**: Общее количество акций (> 0)
    - **player_groups**: Веса и чувствительности групп (сумма весов = 1.0)
    - **price_drop_threshold**: Порог падения для "ловли дно" [-0.5, 0]
    - **price_rise_threshold**: Порог роста для фиксации прибыли [0, 1.0]
    - **random_events**: Кастомные события с весами (сумма = 1.0)
    - **max_order_size_percent**: Макс. размер ордера [0.001, 0.5]
    - **min_price / max_price**: Границы цены (> 0)
    """
    try:
        stock = await service.update_stock_config(symbol, config_data)
        if not stock:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Акция '{symbol}' не найдена",
            )
        return _format_stock(stock)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ── Formatters ────────────────────────────────────────────────────────────────


def _format_stock(stock: dict) -> dict:
    """Форматирует акцию для API-ответа."""
    price_history = stock.get("price_history", [])
    chart_points = [p["price"] for p in price_history] if price_history else []

    return {
        "id": stock.get("id", ""),
        "symbol": stock["symbol"],
        "name": stock["name"],
        "price": stock["price"],
        "change": stock.get("change", 0.0),
        "change_percent": stock.get("changePercent", 0.0),
        "currency": stock.get("currency", "USD"),
        "total_shares": stock.get("total_shares", 1_000_000_000),
        "free_shares": stock.get("free_shares", 1_000_000_000),
        "market_cap": stock.get("market_cap", stock["price"] * stock.get("total_shares", 1_000_000_000)),
        "volatility_k": stock.get("volatility_k", 0.1),
        "updated_at": _serialize_datetime(stock.get("updated_at")),
        "last_event": stock.get("last_event"),
        "chart": chart_points,
    }


def _format_order(order: dict) -> dict:
    """Форматирует ордер для API-ответа."""
    return {
        "id": order.get("id", ""),
        "symbol": order["symbol"],
        "action": order["action"],
        "quantity": order["quantity"],
        "price_per_share": order.get("price_per_share", order.get("price", 0)),
        "total_cost": order.get("total_cost", order.get("total", 0)),
        "timestamp": _serialize_datetime(order.get("timestamp")),
        "new_stock_price": order.get("new_stock_price"),
        "event_applied": order.get("event_applied"),
        "is_bot": order.get("is_bot"),
    }


def _format_portfolio(portfolio: dict) -> dict:
    """Форматирует портфель для API-ответа."""
    items = []
    for item in portfolio.get("holdings", []):
        items.append({
            "symbol": item["symbol"],
            "name": item.get("name", ""),
            "quantity": item["quantity"],
            "average_buy_price": item["average_buy_price"],
            "current_price": item.get("current_price", item["average_buy_price"]),
            "total_value": item.get("total_value", 0),
            "profit_loss": item.get("profit_loss", 0),
            "profit_loss_percent": item.get("profit_loss_percent", 0),
        })

    return {
        "user_id": portfolio.get("userId", portfolio.get("user_id", "")),
        "total_value": portfolio.get("total_value", 0),
        "total_invested": portfolio.get("total_invested", 0),
        "total_profit_loss": portfolio.get("total_profit_loss", 0),
        "items": items,
    }


def _format_event(event: dict) -> dict:
    """Форматирует событие для API-ответа."""
    return {
        "id": event.get("id", ""),
        "symbol": event["symbol"],
        "event_type": event["event_type"],
        "event_label": event["event_label"],
        "multiplier": event["multiplier"],
        "price_before": event["price_before"],
        "price_after": event["price_after"],
        "timestamp": _serialize_datetime(event.get("timestamp")),
    }


def _serialize_datetime(dt) -> str:
    """Сериализация datetime в ISO формат."""
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return ""
