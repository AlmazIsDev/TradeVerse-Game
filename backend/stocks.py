"""Биржа акций v2: рынок, торговля, портфель и ордера.

ΔP = Price × K × (Quantity / TotalShares); пользовательские акции используют ту же механику.
"""
from __future__ import annotations

from typing import Optional

import random
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator

from admin_perms import get_current_user, require_admin, require_allowed
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
    "volatility": 0.005,
}

# Абсолютный потолок размера одного ордера (акций). Дефолтная системная акция
# (1 млрд выпуск × 1%) и так даёт 10 млн, но для акций с меньшим выпуском этот
# потолок гарантирует, что игрок/бот может подать ордер до 10 млн (в пределах
# доступного количества). Ботам с их 1 млн он не мешает.
MAX_ORDER_SHARES = 10_000_000

LISTING_FEE = 5000.0        # стоимость размещения пользовательской акции
FOUNDER_SHARE_PCT = 0.2     # доля основателя при эмиссии
TRADE_FEE_RATE = 0.005      # торговая комиссия (спред) на сделки — «сгорает»

# ── Боты-покупатели ──────────────────────────────────────────────────────────
# Заменяют реальный рыночный фид: на каждом тике планировщика с настраиваемой
# вероятностью (admin: app_config["synthetic_config"]) каждая системная акция
# получает симулированную buy/sell-сделку, которая двигает цену той же формулой
# ΔP, что и игроки. Параметры и ручной запуск — backend/synthetic.py.
BOT_USER_ID = "bot"
# Сделка бота строго в рамках свободных акций: покупка режется по free_shares
# (бот не может выкупить больше выпуска), продажа — по купленному ботом ранее
# (total_shares − free_shares): бот продаёт только то, что сам купил.
# Планировщик тикает раз в 60с, но боты должны торговать ~каждые 10с, поэтому за
# тик прогоняется несколько раундов (roundsPerTick). Перед каждым раундом акции
# перечитываем — иначе условный update по free_shares не совпадёт и сделки не
# «наложатся».


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
    volatility: Optional[float] = None
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
        "image": stock.get("logo"),
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


async def _attach_company_logos(db: AsyncIOMotorDatabase, stocks: list[dict]) -> None:
    """Подставляет логотип компании в акции без сохранённого logo (старые эмиссии)."""
    cids = list({s.get("companyId") for s in stocks if s.get("companyId") and not s.get("logo")})
    if not cids:
        return
    ids = [ObjectId(c) for c in cids if ObjectId.is_valid(c)]
    logos = {str(c["_id"]): c.get("logo") async for c in
             db.companies.find({"_id": {"$in": ids}}, {"logo": 1})}
    for s in stocks:
        if not s.get("logo") and logos.get(s.get("companyId")):
            s["logo"] = logos[s["companyId"]]


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
    await _attach_company_logos(db, stocks)
    holdings = await _holdings_map(db, str(current_user["_id"]))
    out = []
    for s in stocks:
        item = _format_stock_v2(s)
        held = holdings.get(s["symbol"])
        item["heldQuantity"] = held.get("quantity", 0) if held else 0
        out.append(item)
    return out


async def _bot_stock_trade(
    db: AsyncIOMotorDatabase, s: dict, cfg: dict,
    side: Optional[str] = None, quantity: Optional[int] = None,
) -> bool:
    """Одна синтетическая сделка по акции. False — сделка не состоялась.

    Только для системных тикеров (issuer пуст) — пользовательские эмиссии
    двигают только реальные игроки. Сам бот не имеет баланса/портфеля: сделка
    просто двигает цену и пул свободных акций, как buy/sell от игрока.
    quantity/side фиксируются при ручном запуске из админки (synthetic.trigger);
    объём всегда режется по свободному остатку (см. константы блока ботов).
    """
    if s.get("issuer"):
        return False

    mcfg = _resolve_config(s)
    total_shares = mcfg["total_shares"]
    price = float(s.get("price", 0))
    if total_shares <= 0 or price <= 0:
        return False
    free_shares = s.get("free_shares", total_shares)

    max_qty = random.randint(int(cfg["minShares"]), max(int(cfg["minShares"]), int(cfg["maxShares"])))
    # ponytail: случайный bias вместо фиксированных 50/50 — иначе покупки и
    # продажи взаимно гасятся и цена стоит на месте. Каждый тик тянем свою
    # вероятность покупки из [buyBiasMin, buyBiasMax], поэтому возникают
    # трендовые серии. Диапазон подобран так, чтобы цена дрейфовала, не взрываясь.
    buy_prob = random.uniform(cfg["buyBiasMin"], cfg["buyBiasMax"])
    action = side or ("buy" if random.random() < buy_prob else "sell")

    if action == "buy":
        qty = int(min(quantity if quantity is not None else max_qty, max_qty, free_shares))
        if qty < 1:
            return False
        delta = price * mcfg["volatility_k"] * (qty / total_shares)
        new_price = round(price + delta, 2)
        update = {"$inc": {"free_shares": -qty}, "$set": {"price": new_price}}
    else:
        qty = int(min(quantity if quantity is not None else max_qty, max_qty, total_shares - free_shares))
        if qty < 1:
            return False
        delta = price * mcfg["volatility_k"] * (qty / total_shares)
        new_price = round(max(0.01, price - delta), 2)
        update = {"$inc": {"free_shares": qty}, "$set": {"price": new_price}}

    update["$set"].update({
        "change": round(new_price - price, 2),
        "changePercent": round((new_price - price) / price * 100, 2) if price else 0.0,
        "updated_at": datetime.now(timezone.utc),
    })
    res = await db.stocks.update_one({"symbol": s["symbol"], "free_shares": free_shares}, update)
    if not res.modified_count:
        return False
    await MarketDataService.record_snapshot(db, "stock", s["symbol"], new_price, force=True)
    change = ((new_price - price) / price * 100) if price else 0.0
    await db.stock_events.insert_one({
        "symbol": s["symbol"],
        "type": action,
        "quantity": qty,
        "priceBefore": price,
        "priceAfter": new_price,
        "userId": BOT_USER_ID,
        "timestamp": datetime.now(timezone.utc),
    })
    await broadcast({
        "type": "price_tick",
        "market": "stock",
        "symbol": s["symbol"],
        "price": new_price,
        "changePercent": round(change, 2),
    })
    return True


async def run_bots(
    db: AsyncIOMotorDatabase, cfg: dict,
    symbol: Optional[str] = None, side: Optional[str] = None,
    quantity: Optional[float] = None,
) -> int:
    """Раунды ботов по системным акциям. Возвращает число сделок.

    cfg — синтетическая конфигурация рынка акций (synthetic.get_synthetic_config).
    Без symbol — roundsPerTick раундов с вероятностью probability (фоновый тик и
    ручной «запустить раунд»); с symbol — одна разовая сделка (side/quantity
    из админки), всё равно в пределах свободных акций.
    """
    if not cfg.get("enabled", True) or cfg["roundsPerTick"] <= 0:
        return 0
    executed = 0
    qty = int(quantity) if quantity is not None else None
    rounds = 1 if symbol else int(cfg["roundsPerTick"])
    for _ in range(rounds):
        stocks_list = await find_all_stocks(db)
        for s in stocks_list:
            if symbol and s["symbol"] != symbol.upper():
                continue
            if not symbol and random.random() > cfg["probability"]:
                continue
            if await _bot_stock_trade(db, s, cfg, side=side, quantity=qty):
                executed += 1
    return executed


CATALOG_ANCHOR_PULL = 0.1   # доля сближения цены акции компании с фундаменталом за тик

# Доля разрыва с базовой ценой, закрываемая за тик (возврат к среднему, как
# WALK_REVERSION у крипты). Без неё блуждание — свободная диффузия: коридор
# [0.3x, 3x] лишь отражает цену от краёв, и капитализация качается в разы.
# 0.01: стационарное СКО ≈ vol/√(2θ) ≈ 3.5% — живой график (self-check ниже
# требует размах >2% за 240 тиков), но диффузия к краям коридора подавлена.
WALK_REVERSION = 0.01

# Коридор собственного блуждания цены вокруг базовой (как [0.3x,3x] у крипты).
WALK_FLOOR = 0.3
WALK_CEIL = 3.0

# Сигма для БЭКФИЛЛА истории — это шаг ЗА СУТКИ (market_data._build_walk_docs
# идёт назад по дням), а config["volatility"] — шаг за тик планировщика (60с).
# Числа с разных временных масштабов и не взаимозаменяемы: подстановка тиковой
# сигмы сюда сделала бы весь год истории почти плоской линией.
BACKFILL_DAILY_VOLATILITY = 0.02


def _walk_stock_price(stock: dict) -> Optional[float]:
    """Новая цена системной акции от собственного блуждания, или None.

    Раньше цена двигалась ТОЛЬКО объёмом сделок ботов, а их impact —
    price × volatility_k × (qty/total_shares) ≈ 0.005% за сделку при дефолтном
    выпуске в 1 млрд. Покупки и продажи взаимно гасились, график выходил
    плоской линией, и вся аналитика вырождалась: momentum ≈ 0 → probUp = 50%
    → тренд всегда «Держать». Здесь та же механика, что у крипты
    (crypto._walk_price): случайный дрейф задаёт направление на тик, gauss даёт
    шум, возврат к среднему + коридор не дают цене диффундировать к краям.
    """
    base = float(stock.get("base_price") or stock.get("price") or 0)
    old = float(stock.get("price") or 0)
    if base <= 0 or old <= 0:
        return None
    vol = float(_resolve_config(stock)["volatility"])
    drift = random.uniform(-0.5, 0.5) * vol
    new = old + WALK_REVERSION * (base - old) + old * (drift + random.gauss(0, vol))
    new = max(base * WALK_FLOOR, min(base * WALK_CEIL, new))
    new = round(max(0.01, new), 2)
    return new if new != old else None


async def _walk_system_stocks(db: AsyncIOMotorDatabase):
    """Двигает цены системных акций собственным блужданием.

    Пользовательские эмиссии (issuer) тоже ходят: их якорь — цена размещения
    (base_price ставится при первом тике), иначе при малом онлайне график
    мёртвая линия. Акции компаний (companyId) пропускаем: они дрейфуют к
    капиталу компании (см. _revalue_company_stocks) — блуждание боролось бы
    с этим якорем.
    """
    async for s in db.stocks.find({"companyId": None}):
        old = float(s.get("price") or 0)
        if "base_price" not in s and old > 0:
            await db.stocks.update_one({"_id": s["_id"]}, {"$set": {"base_price": old}})
            s["base_price"] = old
        new_price = _walk_stock_price(s)
        if new_price is None:
            continue
        change = (new_price - old) / old * 100
        await db.stocks.update_one(
            {"_id": s["_id"]},
            {"$set": {
                "price": new_price,
                "change": round(new_price - old, 2),
                "changePercent": round(s.get("changePercent", 0.0) * 0.7 + change, 2),
                "updated_at": datetime.now(timezone.utc),
            }},
        )
        await MarketDataService.record_snapshot(db, "stock", s["symbol"], new_price, force=True)


async def _revalue_company_stocks(db: AsyncIOMotorDatabase):
    """Акции компаний (companyId != None) дрейфуют к «справедливой» цене =
    капитал компании / выпуск. Это «как в жизни»: котировка следует за
    фундаменталом, но между тиками свободно колеблется от сделок игроков/ботов.

    За тик цена сдвигается на CATALOG_ANCHOR_PULL доли расстояния до якоря —
    плавно, без телепортов. Компании без активной записи пропускаются."""
    try:
        from company import _company_capital
    except Exception:
        return
    async for s in db.stocks.find({"companyId": {"$ne": None}}):
        cid = s.get("companyId")
        if not cid or not ObjectId.is_valid(cid):
            continue
        company = await db.companies.find_one({"_id": ObjectId(cid)})
        if not company:
            continue
        cfg = _resolve_config(s)
        total_shares = cfg["total_shares"]
        if total_shares <= 0:
            continue
        capital = await _company_capital(db, company)
        fair = max(0.01, round(capital / total_shares, 2))
        price = float(s.get("price", 0.0))
        if price <= 0:
            price = fair  # акция с нулевой ценой: якорим прямо к фундаменталу
        # OU-процесс вокруг fair: дрейф к фундаменталу + шум. Без шумового
        # члена цена сходилась к fair за ~7 тиков и замирала плоской линией —
        # боты акции компаний не торгуют (guard по issuer), игроки — редко.
        noise = price * cfg["volatility"] * random.gauss(0, 1)
        new_price = round(price + (fair - price) * CATALOG_ANCHOR_PULL + noise, 2)
        new_price = max(0.01, new_price)
        if new_price == price:
            continue
        await db.stocks.update_one(
            {"_id": s["_id"]},
            {"$set": {
                "price": new_price,
                "change": round(new_price - price, 2),
                "changePercent": round((new_price - price) / price * 100, 2) if price else 0.0,
                "updated_at": datetime.now(timezone.utc),
            }},
        )


async def maintain_stock_market(db: AsyncIOMotorDatabase):
    """Фоновое обслуживание рынка акций (вызывается Scheduler'ом).

    Системные акции НЕ привязаны к реальным котировкам: цена складывается из
    собственного блуждания (_walk_system_stocks, как у крипты) и объёма сделок
    игроков/ботов. Без блуждания impact ботов был слишком мал, чтобы создать
    тренд, и график выходил плоским. Акции компаний вместо блуждания дрейфуют к
    капиталу (см. _revalue_company_stocks). Здесь же одноразовый бэкфилл
    истории и периодические снимки.
    """
    stocks = await find_all_stocks(db)
    if not stocks:
        return
    # Цены ДО тика — чтобы поймать движение от блуждания и сделок ботов. Раньше
    # «до» и «до» читались из одного и того же документа, поэтому updates всегда
    # выходил пустым и market_update по акциям не рассылался вообще.
    before = {s["symbol"]: float(s.get("price", 0)) for s in stocks}
    await _walk_system_stocks(db)
    # Несколько раундов ботов за тик ≈ торговля каждые 10с (см. run_bots);
    # параметры и вкл/выкл — app_config["synthetic_config"] (админка → synthetic).
    from synthetic import get_synthetic_config
    synth = await get_synthetic_config(db)
    await run_bots(db, synth["stocks"])
    await _revalue_company_stocks(db)
    updates = []
    for s in await find_all_stocks(db):
        await MarketDataService.ensure_backfill(
            db, "stock", s["symbol"], s.get("price", 1) or 1, BACKFILL_DAILY_VOLATILITY)
        await MarketDataService.record_snapshot(db, "stock", s["symbol"], s.get("price", 0))
        old_price = before.get(s["symbol"], 0.0)
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
    _admin: dict = Depends(require_admin("transactions_view")),
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


async def _credit_company_budget(db, stock: dict, amount: float):
    """Перечисляет выручку от покупки акции компании в бюджет эмитента.

    Акции с привязкой к компании (`companyId`) — инструмент привлечения капитала:
    покупка на бирже пополняет бюджет. Выкуп при продаже делается в trade_stock
    обязательным гейтом до выплаты продавцу — не здесь (раньше условный $inc
    молча не срабатывал при пустом бюджете, что позволяло печатать деньги)."""
    cid = stock.get("companyId")
    if not cid or not ObjectId.is_valid(cid):
        return
    await db.companies.update_one({"_id": ObjectId(cid)}, {"$inc": {"budget": round(amount, 2)}})


def _quote_stock(stock: dict, action: str, quantity: int) -> dict:
    """Считает цену исполнения, стоимость и комиссию БЕЗ записи в БД.

    Единый источник правды для /trade и /quote: без него модалка показывала бы
    qty*price, а списывалось бы больше (impact + комиссия), и покупка падала с
    «Недостаточно средств» при внешне достаточном балансе.
    """
    cfg = _resolve_config(stock)
    total_shares = cfg["total_shares"]
    price = float(stock["price"])
    delta = price * cfg["volatility_k"] * (quantity / total_shares) if total_shares else 0.0
    fill_price = round(price, 2)
    next_price = round(price + delta, 2) if action == "buy" else round(max(0.01, price - delta), 2)
    cost = round(fill_price * quantity, 2)
    fee = round(cost * TRADE_FEE_RATE, 2)
    return {
        "price": price,
        "fillPrice": fill_price,
        "nextPrice": next_price,
        "cost": cost,
        "fee": fee,
        "total": round(cost + fee, 2) if action == "buy" else round(cost - fee, 2),
        "feeRate": TRADE_FEE_RATE,
    }


def _max_affordable_shares(stock: dict, balance: float) -> int:
    """Сколько акций реально влезает в баланс с учётом impact и комиссии.

    Клиент этого посчитать не может: impact растёт с размером ордера, поэтому
    фиксированная «скидка на комиссию» либо не дотягивает, либо перебирает —
    кнопка МАКС предлагала объём, который тут же отклоняли по балансу.
    """
    price = float(stock.get("price") or 0)
    if price <= 0 or balance <= 0:
        return 0
    lo, hi = 0, int(balance / price) + 1     # без impact и комиссии — заведомо больше ответа
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _quote_stock(stock, "buy", mid)["total"] <= balance:
            lo = mid
        else:
            hi = mid - 1
    return lo


@router.get("/quote")
async def quote_stock(
    symbol: str = Query(...),
    action: str = Query("buy"),
    quantity: int = Query(1, ge=0),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Предварительный расчёт сделки: сколько реально спишется/придёт."""
    symbol = symbol.strip().upper()
    action = action.lower()
    if action not in ("buy", "sell"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "action должно быть 'buy' или 'sell'")
    stock = await db.stocks.find_one({"symbol": symbol})
    if not stock:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Акция '{symbol}' не найдена")
    q = _quote_stock(stock, action, quantity)
    q["maxOrder"] = MAX_ORDER_SHARES
    free = stock.get("free_shares", _resolve_config(stock)["total_shares"])
    q["freeShares"] = free
    q["maxAffordable"] = min(
        _max_affordable_shares(stock, float(current_user.get("balance") or 0)),
        int(free), MAX_ORDER_SHARES,
    )
    return q


@router.post("/trade")
async def trade_stock(
    trade: StockTradeRequest,
    current_user: dict = Depends(require_allowed("stocks")),
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

    # Жёсткий потолок ордера — абсолютный (MAX_ORDER_SHARES), а не % от выпуска:
    # процентный порог для мелких эмиссий давал крошечный лимит. Одна сделка —
    # до 10 млн акций (в пределах доступного количества).
    if quantity > MAX_ORDER_SHARES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Ордер превышает максимальный размер ({MAX_ORDER_SHARES} акций)",
        )

    # Сумма сделки фиксируется по текущей цене; рынок после успешной оплаты
    # сдвигается на полный impact (nextPrice).
    q = _quote_stock(stock, action, quantity)
    fill_price = q["fillPrice"]
    cost = q["cost"]
    fee = q["fee"]   # спред «сгорает»; делает churning невыгодным

    if action == "buy":
        charge = round(cost + fee, 2)
        new_balance = await adjust_balance(db, user_id, -charge)
        if new_balance is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

        new_price = q["nextPrice"]
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
        # Акция компании: выручка от покупки на бирже идёт в БЮДЖЕТ компании
        # (привлечение капитала). Деньги не «сгорают», а перетекают эмитенту.
        await _credit_company_budget(db, stock, cost)
    else:  # sell
        # Компания-эмитент выкупает акции у продавца ИЗ БЮДЖЕТА. Списание
        # обязательное и идёт ДО выплаты продавцу: раньше оно было best-effort —
        # при пустом бюджете условный $inc молча не срабатывал, а продавцу деньги
        # начислялись. Цикл «купить свои акции → вывести бюджет → продать акции»
        # печатал деньги из воздуха.
        cid = stock.get("companyId")
        if cid and ObjectId.is_valid(cid):
            budget_paid = await db.companies.find_one_and_update(
                {"_id": ObjectId(cid), "budget": {"$gte": cost}},
                {"$inc": {"budget": -cost}},
            )
            if not budget_paid:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Компания не может выкупить акции: недостаточно средств в бюджете",
                )

        updated_holding = await db.stock_holdings.find_one_and_update(
            {"userId": user_id, "symbol": symbol, "quantity": {"$gte": quantity}},
            {"$inc": {"quantity": -quantity, "invested": -cost}},
            return_document=True,
        )
        if not updated_holding:
            if cid and ObjectId.is_valid(cid):
                # Страховка от гонки (должно быть поймано выше) — не теряем деньги бюджета.
                await db.companies.update_one({"_id": ObjectId(cid)}, {"$inc": {"budget": cost}})
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно акций для продажи")

        proceeds = round(cost - fee, 2)
        new_balance = await adjust_balance(db, user_id, proceeds)
        new_price = q["nextPrice"]
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
        # Выкуп из бюджета компании уже выполнен выше — гейтом перед выплатой.

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
    _admin=Depends(require_admin("stocks")),
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
    current_user: dict = Depends(require_allowed("stocks")),
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
    current_user: dict = Depends(require_allowed("stocks")),
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
    await _attach_company_logos(db, [stock])
    return _format_stock_v2(stock)


if __name__ == "__main__":
    # Мини-проверка новой математики объёмов/потолка (без БД, без сервера).
    # Объём ордера бота: случайный в [minShares, maxShares] и всегда ≥ 1.
    import synthetic as _synth
    scfg = _synth.DEFAULT_SYNTHETIC["stocks"]
    for _ in range(10_000):
        mx = random.randint(int(scfg["minShares"]), int(scfg["maxShares"]))
        assert 1 <= mx <= scfg["maxShares"], mx
        p = random.uniform(scfg["buyBiasMin"], scfg["buyBiasMax"])
        assert scfg["buyBiasMin"] <= p <= scfg["buyBiasMax"]
    # Сделка бота режется по свободному остатку: buy ≤ free, sell ≤ total−free.
    free, total, want = 100, 1_000, 10_000
    assert min(want, free) == free and min(want, total - free) == total - free
    # Потолок ордера пропускает до 10 млн и режет больше.
    assert MAX_ORDER_SHARES == 10_000_000
    assert 10_000_000 <= MAX_ORDER_SHARES         # ровно 10 млн проходит
    assert not (10_000_001 <= MAX_ORDER_SHARES)   # 10 млн + 1 — отбой

    # Блуждание цены: держится в коридоре и реально двигает цену (иначе график
    # плоский и аналитика всегда выдаёт «Держать» с probUp = 50%).
    stock = {"symbol": "T", "price": 100.0, "base_price": 100.0}
    moved = 0
    for _ in range(2000):
        new = _walk_stock_price(stock)
        if new is not None:
            assert 100.0 * WALK_FLOOR <= new <= 100.0 * WALK_CEIL, new
            stock["price"] = new
            moved += 1
    assert moved > 1900, f"цена почти не двигалась: {moved}/2000"

    # За серию тиков должен накапливаться заметный тренд, а не шум вокруг старта.
    # При дефолтной volatility средний размах за 4 часа (240 тиков) ≈ 6%; порог
    # 2% ловит регресс «цена снова стоит на месте», не цепляясь за случайность.
    swings = []
    for _ in range(200):
        s = {"symbol": "T", "price": 100.0, "base_price": 100.0}
        for _ in range(240):
            s["price"] = _walk_stock_price(s) or s["price"]
        swings.append(abs(s["price"] - 100.0) / 100.0)
    assert sum(swings) / len(swings) > 0.02, "тренда нет — график останется плоским"

    # Нулевая/битая цена не должна ломать тик.
    assert _walk_stock_price({"price": 0, "base_price": 0}) is None

    # Сигма бэкфилла (шаг за сутки) и тиковая сигма — разные масштабы времени.
    # Если их когда-нибудь «унифицируют», год истории станет плоским.
    assert BACKFILL_DAILY_VOLATILITY > DEFAULT_STOCK_CONFIG["volatility"] * 2
    print("stocks self-check OK")
