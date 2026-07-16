"""Биржа акций (v2): динамический рынок, торговля, портфель, ордера, события.

Цена акции реагирует на объём сделок:  ΔP = Price × K × (Quantity / TotalShares).
Покупка двигает цену вверх и уменьшает пул свободных акций, продажа — наоборот.
Все денежные движения проходят через единый реестр (ledger), поэтому сделки
видны в общей истории операций и аналитике.

Здесь же живут пользовательские акции (issuer != None) — их выпускают игроки
через company/эмиссию; торговая механика общая.
"""
from __future__ import annotations

from typing import Optional

import random
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator

from auth import get_current_user, require_admin
from database import get_db, find_all_stocks, find_stock_by_symbol
from ledger import (
    INCOME, EXPENSE, CAT_TRADE, CAT_DIVIDEND,
    adjust_balance, record_transaction,
)
from market_data import MarketDataService
from ws import broadcast

router = APIRouter(prefix="/api/v2/stocks", tags=["stocks"])

DEFAULT_STOCK_CONFIG = {
    "volatility_k": 0.1,
    "total_shares": 1_000_000_000,
    "price_drop_threshold": -0.05,
    "price_rise_threshold": 0.10,
    "max_order_size_percent": 0.01,
}

LISTING_FEE = 5000.0        # стоимость размещения пользовательской акции
FOUNDER_SHARE_PCT = 0.2     # доля основателя при эмиссии
TRADE_FEE_RATE = 0.005      # торговая комиссия (спред) на сделки — «сгорает»

# ── Боты-покупатели ──────────────────────────────────────────────────────────
# Заменяют реальный рыночный фид: на каждом тике планировщика с вероятностью
# BOT_TRADE_PROBABILITY каждая системная акция получает симулированную
# buy/sell-сделку, которая двигает цену той же формулой ΔP, что и игроки.
BOT_USER_ID = "bot"
BOT_TRADE_PROBABILITY = 0.4
BOT_MIN_SHARES = 10
BOT_MAX_ORDER_PERCENT = 0.003   # доля от total_shares за одну сделку бота


# ── Schemas ──────────────────────────────────────────────────────────────────


class StockTradeRequest(BaseModel):
    symbol: str
    action: str
    quantity: int

    @field_validator("symbol")
    @classmethod
    def symbol_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Не указан символ акции")
        return v.strip().upper()

    @field_validator("action")
    @classmethod
    def action_valid(cls, v):
        if v.lower() not in ("buy", "sell"):
            raise ValueError("action должно быть 'buy' или 'sell'")
        return v.lower()

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v):
        if v < 1:
            raise ValueError("Количество должно быть не меньше 1")
        return v


class StockConfigUpdate(BaseModel):
    volatility_k: Optional[float] = None
    total_shares: Optional[int] = None
    price_drop_threshold: Optional[float] = None
    price_rise_threshold: Optional[float] = None
    max_order_size_percent: Optional[float] = None


class StockIssue(BaseModel):
    name: str
    symbol: str
    description: str = ""
    totalShares: int
    price: float

    @field_validator("symbol")
    @classmethod
    def symbol_ok(cls, v):
        v = (v or "").strip().upper()
        if not (1 <= len(v) <= 6) or not v.isalnum():
            raise ValueError("Тикер: 1–6 латинских букв/цифр")
        return v

    @field_validator("name")
    @classmethod
    def name_ok(cls, v):
        v = (v or "").strip()
        if len(v) < 2:
            raise ValueError("Название слишком короткое")
        return v[:60]

    @field_validator("totalShares")
    @classmethod
    def shares_ok(cls, v):
        if v < 1000 or v > 10_000_000_000:
            raise ValueError("Количество акций: 1 000 – 10 млрд")
        return v

    @field_validator("price")
    @classmethod
    def price_ok(cls, v):
        if v <= 0 or v > 1_000_000:
            raise ValueError("Некорректная цена")
        return round(float(v), 2)


class DividendBody(BaseModel):
    perShare: float

    @field_validator("perShare")
    @classmethod
    def per_ok(cls, v):
        if v is None or v <= 0:
            raise ValueError("Дивиденд на акцию должен быть положительным")
        return round(float(v), 4)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _resolve_config(stock: dict) -> dict:
    cfg = dict(DEFAULT_STOCK_CONFIG)
    for key, value in (stock.get("config") or {}).items():
        if value is not None:
            cfg[key] = value
    return cfg


def _format_stock_v2(stock: dict) -> dict:
    cfg = _resolve_config(stock)
    price = float(stock.get("price", 0.0))
    total_shares = cfg["total_shares"]
    free_shares = stock.get("free_shares", total_shares)
    return {
        "id": stock.get("id", ""),
        "symbol": stock["symbol"],
        "name": stock["name"],
        "price": price,
        "change": stock.get("change", 0.0),
        "changePercent": stock.get("changePercent", 0.0),
        "currency": stock.get("currency", "USD"),
        "freeShares": free_shares,
        "totalShares": total_shares,
        "marketCap": round(price * total_shares, 2),
        "issuer": stock.get("issuer"),
        "issuerName": stock.get("issuer_name"),
        "configOverrides": stock.get("config") or {},
        "updated_at": _iso(stock.get("updated_at")),
    }


def _iso(dt) -> str:
    return dt.isoformat() if isinstance(dt, datetime) else ""


async def _holdings_map(db: AsyncIOMotorDatabase, user_id: str) -> dict:
    result = {}
    async for h in db.stock_holdings.find({"userId": user_id, "quantity": {"$gt": 0}}):
        result[h["symbol"]] = h
    return result


# ── Read endpoints ───────────────────────────────────────────────────────────


@router.get("")
async def list_stocks(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Список акций с рыночными данными и позицией текущего игрока.

    БЫСТРОЕ чтение: котировки/история поддерживаются фоновым Scheduler'ом
    (``maintain_stock_market``). На горячем пути — только чтение из БД, поэтому
    страница открывается мгновенно (никаких сетевых запросов и бэкфилла).
    """
    stocks = await find_all_stocks(db)
    holdings = await _holdings_map(db, str(current_user["_id"]))
    out = []
    for s in stocks:
        item = _format_stock_v2(s)
        held = holdings.get(s["symbol"])
        item["heldQuantity"] = held.get("quantity", 0) if held else 0
        out.append(item)
    return out


async def _run_bots(db: AsyncIOMotorDatabase, stocks: list[dict]):
    """Боты-покупатели: имитируют рыночную активность по системным акциям.

    Только для системных тикеров (issuer пуст) — пользовательские эмиссии
    двигают только реальные игроки. Сам бот не имеет баланса/портфеля: сделка
    просто двигает цену и пул свободных акций, как buy/sell от игрока.
    """
    for s in stocks:
        if s.get("issuer"):
            continue
        if random.random() > BOT_TRADE_PROBABILITY:
            continue

        cfg = _resolve_config(s)
        total_shares = cfg["total_shares"]
        price = float(s.get("price", 0))
        if total_shares <= 0 or price <= 0:
            continue
        free_shares = s.get("free_shares", total_shares)

        max_qty = max(BOT_MIN_SHARES, int(total_shares * BOT_MAX_ORDER_PERCENT))
        action = random.choice(["buy", "sell"])

        if action == "buy":
            qty = min(max_qty, free_shares)
            if qty < BOT_MIN_SHARES:
                continue
            delta = price * cfg["volatility_k"] * (qty / total_shares)
            new_price = round(price + delta, 2)
            update = {"$inc": {"free_shares": -qty}, "$set": {"price": new_price}}
        else:
            qty = min(max_qty, total_shares - free_shares)
            if qty < BOT_MIN_SHARES:
                continue
            delta = price * cfg["volatility_k"] * (qty / total_shares)
            new_price = round(max(0.01, price - delta), 2)
            update = {"$inc": {"free_shares": qty}, "$set": {"price": new_price}}

        update["$set"].update({
            "change": round(new_price - price, 2),
            "changePercent": round((new_price - price) / price * 100, 2) if price else 0.0,
            "updated_at": datetime.now(timezone.utc),
        })
        await db.stocks.update_one({"symbol": s["symbol"], "free_shares": free_shares}, update)
        await db.stock_events.insert_one({
            "symbol": s["symbol"],
            "type": action,
            "quantity": qty,
            "priceBefore": price,
            "priceAfter": new_price,
            "userId": BOT_USER_ID,
            "timestamp": datetime.now(timezone.utc),
        })
        await MarketDataService.record_snapshot(db, "stock", s["symbol"], new_price, force=True)
        change = ((new_price - price) / price * 100) if price else 0.0
        await broadcast({
            "type": "price_tick",
            "market": "stock",
            "symbol": s["symbol"],
            "price": new_price,
            "changePercent": round(change, 2),
        })


async def maintain_stock_market(db: AsyncIOMotorDatabase):
    """Фоновое обслуживание рынка акций (вызывается Scheduler'ом).

    Системные акции НЕ привязаны к реальным котировкам — цена двигается только
    объёмом сделок (игроки + боты), как и у пользовательских эмиссий. Здесь же
    делаем одноразовый бэкфилл истории и пишем периодические снимки — всё, что
    раньше выполнялось на каждом запросе списка.
    """
    stocks = await find_all_stocks(db)
    if not stocks:
        return
    await _run_bots(db, stocks)
    updates = []
    for s in await find_all_stocks(db):
        old_price = float(s.get("price", 0))
        await MarketDataService.ensure_backfill(db, "stock", s["symbol"], s.get("price", 1) or 1, 0.02)
        await MarketDataService.record_snapshot(db, "stock", s["symbol"], s.get("price", 0))
        new_price = float(s.get("price", 0))
        if old_price != new_price and old_price > 0:
            change = ((new_price - old_price) / old_price * 100)
            updates.append({
                "symbol": s["symbol"],
                "price": new_price,
                "changePercent": round(s.get("changePercent", 0.0) * 0.7 + change, 2),
            })
    # Рассылаем обновления по WebSocket
    if updates:
        await broadcast({"type": "market_update", "market": "stock", "updates": updates})


@router.get("/portfolio")
async def get_portfolio(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Позиции игрока с рыночной оценкой и P&L."""
    user_id = str(current_user["_id"])
    positions = []
    async for h in db.stock_holdings.find({"userId": user_id, "quantity": {"$gt": 0}}):
        stock = await db.stocks.find_one({"symbol": h["symbol"]})
        price = float(stock["price"]) if stock else 0.0
        qty = h.get("quantity", 0)
        invested = h.get("invested", 0.0)
        value = round(price * qty, 2)
        positions.append({
            "symbol": h["symbol"],
            "name": stock.get("name", h["symbol"]) if stock else h["symbol"],
            "quantity": qty,
            "avgPrice": round(invested / qty, 2) if qty else 0.0,
            "currentPrice": price,
            "value": value,
            "pnl": round(value - invested, 2),
        })
    positions.sort(key=lambda p: p["value"], reverse=True)
    return positions


@router.get("/orders")
async def get_orders(
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """История биржевых ордеров игрока."""
    user_id = str(current_user["_id"])
    orders = []
    cursor = (
        db.transactions.find({"userId": user_id, "category": CAT_TRADE})
        .sort("timestamp", -1)
        .limit(limit)
    )
    async for doc in cursor:
        orders.append({
            "id": str(doc["_id"]),
            "symbol": doc.get("symbol"),
            "type": doc.get("meta", {}).get("action") or ("sell" if doc.get("direction") == INCOME else "buy"),
            "quantity": doc.get("meta", {}).get("quantity"),
            "price": doc.get("price"),
            "amount": doc.get("amount"),
            "timestamp": _iso(doc.get("timestamp")),
        })
    return orders


@router.get("/bot-orders")
async def get_bot_orders(
    limit: int = Query(100, ge=1, le=500),
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Лента сделок ботов-покупателей (только для админов)."""
    orders = []
    cursor = (
        db.stock_events.find({"userId": BOT_USER_ID})
        .sort("timestamp", -1)
        .limit(limit)
    )
    async for e in cursor:
        orders.append({
            "id": str(e["_id"]),
            "symbol": e.get("symbol"),
            "action": e.get("type"),
            "quantity": e.get("quantity"),
            "pricePerShare": e.get("priceAfter"),
            "timestamp": _iso(e.get("timestamp")),
        })
    return orders


@router.get("/events")
async def get_events(
    symbol: str = Query(None),
    limit: int = Query(20, ge=1, le=100),
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Лента рыночных событий (движения цены от сделок)."""
    query = {"symbol": symbol.upper()} if symbol else {}
    events = []
    cursor = db.stock_events.find(query).sort("timestamp", -1).limit(limit)
    async for e in cursor:
        events.append({
            "id": str(e.pop("_id")),
            "symbol": e.get("symbol"),
            "type": e.get("type"),
            "quantity": e.get("quantity"),
            "priceBefore": e.get("priceBefore"),
            "priceAfter": e.get("priceAfter"),
            "timestamp": _iso(e.get("timestamp")),
        })
    return events


# ── Trade ────────────────────────────────────────────────────────────────────


@router.post("/trade")
async def trade_stock(
    trade: StockTradeRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Покупка/продажа акций с атомарным изменением баланса и цены."""
    symbol = trade.symbol
    action = trade.action
    quantity = trade.quantity

    stock = await db.stocks.find_one({"symbol": symbol})
    if not stock:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Акция '{symbol}' не найдена")

    cfg = _resolve_config(stock)
    total_shares = cfg["total_shares"]
    price = float(stock["price"])
    user_id = str(current_user["_id"])

    if "free_shares" not in stock:
        await db.stocks.update_one(
            {"symbol": symbol, "free_shares": {"$exists": False}},
            {"$set": {"free_shares": total_shares}},
        )

    max_qty = int(total_shares * cfg["max_order_size_percent"])
    if max_qty >= 1 and quantity > max_qty:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Ордер превышает максимальный размер ({max_qty} акций)",
        )

    delta = price * cfg["volatility_k"] * (quantity / total_shares) if total_shares else 0.0
    # Сделка исполняется по цене, уже сдвинутой собственным impact'ом: покупатель
    # платит price+delta, продавец получает price-delta. Иначе — безрисковый
    # арбитраж buy→sell на своём же движении цены (печать денег циклом).
    if action == "buy":
        fill_price = round(price + delta, 2)
    else:
        fill_price = round(max(0.01, price - delta), 2)
    cost = round(fill_price * quantity, 2)
    fee = round(cost * TRADE_FEE_RATE, 2)   # спред «сгорает»; делает churning невыгодным

    if action == "buy":
        charge = round(cost + fee, 2)
        new_balance = await adjust_balance(db, user_id, -charge)
        if new_balance is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

        new_price = fill_price
        updated_stock = await db.stocks.find_one_and_update(
            {"symbol": symbol, "free_shares": {"$gte": quantity}},
            {
                "$inc": {"free_shares": -quantity},
                "$set": {
                    "price": new_price,
                    "change": round(new_price - price, 2),
                    "changePercent": round((new_price - price) / price * 100, 2) if price else 0.0,
                    "updated_at": datetime.now(timezone.utc),
                },
            },
            return_document=True,
        )
        if not updated_stock:
            await adjust_balance(db, user_id, charge)  # компенсация (включая комиссию)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно свободных акций")

        await db.stock_holdings.update_one(
            {"userId": user_id, "symbol": symbol},
            {"$inc": {"quantity": quantity, "invested": cost},
             "$setOnInsert": {"userId": user_id, "symbol": symbol}},
            upsert=True,
        )
        await record_transaction(
            db, user_id, EXPENSE, charge, CAT_TRADE,
            f"Покупка {quantity} {symbol}", symbol=symbol, price=fill_price,
            balance_after=new_balance, meta={"quantity": quantity, "action": "buy", "fee": fee},
        )
    else:  # sell
        updated_holding = await db.stock_holdings.find_one_and_update(
            {"userId": user_id, "symbol": symbol, "quantity": {"$gte": quantity}},
            {"$inc": {"quantity": -quantity, "invested": -cost}},
            return_document=True,
        )
        if not updated_holding:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно акций для продажи")

        proceeds = round(cost - fee, 2)
        new_balance = await adjust_balance(db, user_id, proceeds)
        new_price = fill_price
        await db.stocks.update_one(
            {"symbol": symbol},
            {
                "$inc": {"free_shares": quantity},
                "$set": {
                    "price": new_price,
                    "change": round(new_price - price, 2),
                    "changePercent": round((new_price - price) / price * 100, 2) if price else 0.0,
                    "updated_at": datetime.now(timezone.utc),
                },
            },
        )
        await record_transaction(
            db, user_id, INCOME, proceeds, CAT_TRADE,
            f"Продажа {quantity} {symbol}", symbol=symbol, price=fill_price,
            balance_after=new_balance, meta={"quantity": quantity, "action": "sell", "fee": fee},
        )

    await db.stock_events.insert_one({
        "symbol": symbol,
        "type": action,
        "quantity": quantity,
        "priceBefore": price,
        "priceAfter": new_price,
        "userId": user_id,
        "timestamp": datetime.now(timezone.utc),
    })
    await MarketDataService.record_snapshot(db, "stock", symbol, new_price, force=True)
    # WebSocket-оповещение о сделке
    change = ((new_price - price) / price * 100) if price else 0.0
    await broadcast({
        "type": "price_tick",
        "market": "stock",
        "symbol": symbol,
        "price": new_price,
        "changePercent": round(change, 2),
    })

    return {
        "success": True,
        "symbol": symbol,
        "action": action,
        "quantity": quantity,
        "price": fill_price,
        "total": cost,
        "fee": fee,
        "newPrice": new_price,
        "balance": new_balance,
    }


# ── Admin config ─────────────────────────────────────────────────────────────


@router.patch("/{symbol}/config")
async def update_stock_config(
    symbol: str,
    config_update: StockConfigUpdate,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Обновляет overrides рыночной конфигурации акции (admin)."""
    symbol = symbol.upper()
    stock = await db.stocks.find_one({"symbol": symbol})
    if not stock:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Акция '{symbol}' не найдена")

    fields = config_update.model_dump(exclude_unset=True)
    if fields:
        set_ops = {f"config.{k}": v for k, v in fields.items()}
        set_ops["updated_at"] = datetime.now(timezone.utc)
        await db.stocks.update_one({"symbol": symbol}, {"$set": set_ops})

    updated = await find_stock_by_symbol(db, symbol)
    return _format_stock_v2(updated)


# ── Пользовательская эмиссия акций ───────────────────────────────────────────


@router.post("/issue", status_code=status.HTTP_201_CREATED)
async def issue_stock(
    payload: StockIssue,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Игрок выпускает собственную акцию (IPO).

    Списывается листинговый сбор. Основатель получает долю FOUNDER_SHARE_PCT,
    остальное поступает в свободный рыночный пул. Капитализация = цена × выпуск.
    """
    symbol = payload.symbol
    if await db.stocks.find_one({"symbol": symbol}):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Тикер '{symbol}' уже занят")

    user_id = str(current_user["_id"])

    founder_shares = int(payload.totalShares * FOUNDER_SHARE_PCT)
    free_shares = payload.totalShares - founder_shares
    # Основатель ОПЛАЧИВАЕТ свои акции по цене размещения (не получает бесплатно).
    # Иначе: бесплатные founder-акции → продажа за напечатанный кэш = money printer
    # (продажа акций кредитует продавца без контрагента). Оплата делает каждую
    # акцию обеспеченной реальными деньгами и естественно ограничивает абьюз
    # гигантских эмиссий (2 млрд бесплатных акций стоили бы недостижимую сумму).
    founder_cost = round(founder_shares * payload.price, 2)
    total_charge = round(LISTING_FEE + founder_cost, 2)
    new_balance = await adjust_balance(db, user_id, -total_charge)
    if new_balance is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Недостаточно средств: листинг ${LISTING_FEE:,.0f} + доля основателя ${founder_cost:,.0f}",
        )

    doc = {
        "symbol": symbol,
        "name": payload.name,
        "description": payload.description[:280],
        "price": payload.price,
        "change": 0.0,
        "changePercent": 0.0,
        "currency": "USD",
        "issuer": user_id,
        "issuer_name": current_user.get("username"),
        "config": {"total_shares": payload.totalShares},
        "free_shares": free_shares,
        "updated_at": datetime.now(timezone.utc),
    }
    result = await db.stocks.insert_one(doc)
    doc["id"] = str(result.inserted_id)

    if founder_shares > 0:
        await db.stock_holdings.update_one(
            {"userId": user_id, "symbol": symbol},
            {"$inc": {"quantity": founder_shares, "invested": round(founder_shares * payload.price, 2)},
             "$setOnInsert": {"userId": user_id, "symbol": symbol}},
            upsert=True,
        )

    await record_transaction(
        db, user_id, EXPENSE, total_charge, CAT_TRADE,
        f"Листинг акции {symbol}", symbol=symbol, balance_after=new_balance,
        meta={"action": "issue", "totalShares": payload.totalShares,
              "listingFee": LISTING_FEE, "founderCost": founder_cost},
    )
    return {"stock": _format_stock_v2(doc), "balance": new_balance, "founderShares": founder_shares}


@router.post("/{symbol}/dividend")
async def pay_dividend(
    symbol: str,
    payload: DividendBody,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Эмитент выплачивает дивиденды всем держателям (кроме себя)."""
    symbol = symbol.upper()
    stock = await db.stocks.find_one({"symbol": symbol})
    if not stock:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Акция '{symbol}' не найдена")
    user_id = str(current_user["_id"])
    if stock.get("issuer") != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Вы не эмитент этой акции")

    per = payload.perShare
    holders = [
        h async for h in db.stock_holdings.find(
            {"symbol": symbol, "quantity": {"$gt": 0}, "userId": {"$ne": user_id}}
        )
    ]
    total = round(sum(per * h.get("quantity", 0) for h in holders), 2)
    if total <= 0:
        return {"paid": 0.0, "holders": 0, "balance": current_user.get("balance", 0.0)}

    new_balance = await adjust_balance(db, user_id, -total)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств для выплаты дивидендов")

    for h in holders:
        amt = round(per * h.get("quantity", 0), 2)
        if amt <= 0:
            continue
        hb = await adjust_balance(db, h["userId"], amt)
        await record_transaction(
            db, h["userId"], INCOME, amt, CAT_DIVIDEND,
            f"Дивиденды {symbol}", symbol=symbol, balance_after=hb,
            meta={"perShare": per, "from": stock.get("issuer_name")},
        )
    await record_transaction(
        db, user_id, EXPENSE, total, CAT_DIVIDEND,
        f"Выплата дивидендов {symbol}", symbol=symbol, balance_after=new_balance,
        meta={"perShare": per, "holders": len(holders)},
    )
    return {"paid": total, "holders": len(holders), "balance": new_balance}


@router.get("/{symbol}")
async def get_stock_v2(
    symbol: str,
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    stock = await find_stock_by_symbol(db, symbol)
    if not stock:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Акция '{symbol}' не найдена")
    return _format_stock_v2(stock)
