"""Единый сервис рыночных данных (MarketDataService).

Отвечает за ИСТОРИЮ цен акций и криптовалют:
- хранит снимки цен в коллекции ``price_history`` (накапливается со временем);
- при первом обращении к символу делает ОДНОРАЗОВЫЙ бэкфилл (год истории),
  дальше история только дополняется реальными снимками — не пересоздаётся;
- отдаёт агрегированные свечи (OHLC) и линию по интервалам;
- считает изменение цены за 24ч / 7д / 1м / 1г, ATH/ATL.

Также здесь живёт роутер /api/market/* (история, детальная карточка актива)
и /api/favorites/* (избранное игрока).
"""
from __future__ import annotations

from typing import Optional

import logging
import os
import random
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from auth import get_current_user, require_admin
from database import get_db
from providers import CoinGeckoProvider

logger = logging.getLogger("tradeverse.market")

router = APIRouter(prefix="/api", tags=["market"])

MARKET_STOCK = "stock"
MARKET_CRYPTO = "crypto"
VALID_MARKETS = {MARKET_STOCK, MARKET_CRYPTO}

# Кэширование: как часто обновлять цены из внешнего API (сек).
REFRESH_INTERVAL_S = int(os.getenv("MARKET_REFRESH_SECONDS", "120"))
CRYPTO_COUNT = int(os.getenv("MARKET_CRYPTO_COUNT", "50"))

_COIN_COLORS = ["#f7931a", "#627eea", "#22c55e", "#eab308", "#ec4899",
                "#8b5cf6", "#06b6d4", "#64748b", "#f43f5e", "#10b981"]


def _coin_color(symbol: str) -> str:
    return _COIN_COLORS[sum(ord(c) for c in symbol) % len(_COIN_COLORS)]

# interval → (lookback, bucket_seconds).  None bucket = адаптивный (для "all").
INTERVALS: dict[str, tuple[Optional[timedelta], Optional[int]]] = {
    "1h": (timedelta(hours=1), 60),
    "24h": (timedelta(hours=24), 15 * 60),
    "7d": (timedelta(days=7), 60 * 60),
    "1m": (timedelta(days=30), 4 * 60 * 60),
    "3m": (timedelta(days=90), 12 * 60 * 60),
    "6m": (timedelta(days=180), 24 * 60 * 60),
    "1y": (timedelta(days=365), 2 * 24 * 60 * 60),
    "all": (None, None),
}

# Как часто минимум писать реальный снимок цены (антиспам).
SNAPSHOT_MIN_INTERVAL_S = 45


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    if isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _build_walk_docs(market: str, symbol: str, current_price: float, volatility: float = 0.03) -> list[dict]:
    """Строит историю случайным блужданием назад во времени от текущей цены.

    Год по дням + последние 3 суток плотнее (для интервалов 1h/24h). Чистая
    функция — не трогает БД, используется и одноразовым бэкфиллом, и
    принудительным regenerate.
    """
    symbol = symbol.upper()
    now = _now()
    docs: list[dict] = []

    def walk_back(points: int, step: timedelta, price: float, vol: float):
        seq = []
        p = price
        for i in range(points):
            seq.append((now - step * i, round(max(current_price * 0.15, min(current_price * 6, p)), 6)))
            p = p / (1 + random.gauss(0, vol))
        return seq

    for ts, p in walk_back(365, timedelta(days=1), current_price, volatility):
        docs.append({"market": market, "symbol": symbol, "price": p, "ts": ts})
    for ts, p in walk_back(144, timedelta(minutes=30), current_price, volatility * 0.4):
        docs.append({"market": market, "symbol": symbol, "price": p, "ts": ts})
    return docs


class MarketDataService:
    """Единая точка работы с историей цен."""

    @staticmethod
    async def record_snapshot(db, market: str, symbol: str, price: float, *, force: bool = False):
        """Добавляет снимок цены (с троттлингом, если не force)."""
        symbol = symbol.upper()
        if not force:
            last = await db.price_history.find_one(
                {"market": market, "symbol": symbol}, sort=[("ts", -1)]
            )
            if last and (_now() - _aware(last["ts"])).total_seconds() < SNAPSHOT_MIN_INTERVAL_S:
                return
        await db.price_history.insert_one({
            "market": market, "symbol": symbol,
            "price": round(float(price), 6), "ts": _now(),
        })

    @staticmethod
    async def ensure_backfill(db, market: str, symbol: str, current_price: float, volatility: float = 0.03):
        """Одноразовый бэкфилл истории (год), если её ещё нет. Не пересоздаёт."""
        symbol = symbol.upper()
        if await db.price_history.find_one({"market": market, "symbol": symbol}):
            return
        docs = _build_walk_docs(market, symbol, current_price, volatility)
        if docs:
            await db.price_history.insert_many(docs)

    @staticmethod
    async def regenerate(db, market: str, symbol: str, current_price: float, volatility: float = 0.03):
        """Принудительно пересоздаёт историю символа (сносит старую, строит заново)."""
        symbol = symbol.upper()
        await db.price_history.delete_many({"market": market, "symbol": symbol})
        docs = _build_walk_docs(market, symbol, current_price, volatility)
        if docs:
            await db.price_history.insert_many(docs)

    @staticmethod
    async def get_history(db, market: str, symbol: str, interval: str) -> dict:
        """Свечи OHLC + линия по интервалу."""
        symbol = symbol.upper()
        lookback, bucket = INTERVALS.get(interval, INTERVALS["7d"])
        query: dict = {"market": market, "symbol": symbol}
        if lookback:
            query["ts"] = {"$gte": _now() - lookback}
        rows = [r async for r in db.price_history.find(query).sort("ts", 1)]
        if not rows:
            return {"candles": [], "line": [], "interval": interval}

        if bucket is None:  # адаптивный размер для "all"
            span = (_aware(rows[-1]["ts"]) - _aware(rows[0]["ts"])).total_seconds()
            bucket = max(3600, int(span / 300)) if span > 0 else 3600

        buckets: dict[int, dict] = {}
        for r in rows:
            key = int(_aware(r["ts"]).timestamp() // bucket)
            p = r["price"]
            b = buckets.get(key)
            if not b:
                buckets[key] = {"t": key * bucket, "o": p, "h": p, "l": p, "c": p}
            else:
                b["h"] = max(b["h"], p)
                b["l"] = min(b["l"], p)
                b["c"] = p
        candles = [buckets[k] for k in sorted(buckets)]
        line = [{"t": c["t"], "p": c["c"]} for c in candles]
        return {"candles": candles, "line": line, "interval": interval}

    @staticmethod
    async def stats(db, market: str, symbol: str) -> dict:
        """Изменение за 24ч/7д/1м/1г, ATH/ATL по накопленной истории."""
        symbol = symbol.upper()
        rows = [r async for r in db.price_history.find({"market": market, "symbol": symbol}).sort("ts", 1)]
        if not rows:
            return {"ath": None, "atl": None, "changes": {}}
        prices = [(_aware(r["ts"]), r["price"]) for r in rows]
        latest = prices[-1][1]
        ath = max(p for _, p in prices)
        atl = min(p for _, p in prices)

        def change(window: timedelta) -> Optional[float]:
            cutoff = _now() - window
            base = None
            for ts, p in prices:
                if ts >= cutoff:
                    base = p
                    break
            if base is None or base == 0:
                return None
            return round((latest - base) / base * 100, 2)

        return {
            "ath": round(ath, 6), "atl": round(atl, 6),
            "changes": {
                "24h": change(timedelta(hours=24)),
                "7d": change(timedelta(days=7)),
                "1m": change(timedelta(days=30)),
                "1y": change(timedelta(days=365)),
            },
        }

    # ── Live data refresh (кэш + fallback) ────────────────────────────────────

    @staticmethod
    async def _throttled(db, market: str) -> bool:
        meta = await db.market_meta.find_one({"market": market})
        last = meta.get("last_refresh") if meta else None
        return isinstance(last, datetime) and (_now() - _aware(last)).total_seconds() < REFRESH_INTERVAL_S

    @staticmethod
    async def _mode(db, market: str) -> str:
        meta = await db.market_meta.find_one({"market": market})
        return (meta or {}).get("mode", "sim")

    @staticmethod
    async def _set_meta(db, market: str, mode: str):
        await db.market_meta.update_one(
            {"market": market},
            {"$set": {"last_refresh": _now(), "mode": mode}},
            upsert=True,
        )

    @staticmethod
    async def refresh_crypto(db) -> str:
        """Обновляет крипторынок реальными данными CoinGecko (раз в REFRESH_INTERVAL_S).

        Возвращает 'live' при успехе, 'sim' — если API недоступен (тогда цены
        остаются последними сохранёнными / двигаются симуляцией как fallback).
        """
        if await MarketDataService._throttled(db, "crypto"):
            return await MarketDataService._mode(db, "crypto")
        try:
            markets = await CoinGeckoProvider().get_markets(per_page=CRYPTO_COUNT)
            if not markets:
                raise RuntimeError("empty markets")
            for m in markets:
                await db.crypto_assets.update_one(
                    {"symbol": m["symbol"]},
                    {"$set": {
                        "symbol": m["symbol"], "name": m["name"], "image": m.get("image"),
                        "coingeckoId": m.get("coingeckoId"), "color": _coin_color(m["symbol"]),
                        "price": round(m["price"], 6), "change24h": round(m["change24h"], 2),
                        "marketCap": m["marketCap"], "volume24h": m["volume24h"],
                        "supply": m["supply"], "ath": m["ath"], "atl": m["atl"],
                        "source": "coingecko", "updated_at": _now(),
                    }},
                    upsert=True,
                )
                await MarketDataService.record_snapshot(db, "crypto", m["symbol"], m["price"], force=True)
            await MarketDataService._set_meta(db, "crypto", "live")
            logger.info("CoinGecko: обновлено %d монет", len(markets))
            return "live"
        except Exception as exc:
            logger.warning("CoinGecko недоступен (%s) — используются сохранённые данные", exc)
            await MarketDataService._set_meta(db, "crypto", "sim")
            return "sim"


# ── History endpoint ─────────────────────────────────────────────────────────


@router.get("/market/history")
async def market_history(
    market: str = Query(...),
    symbol: str = Query(...),
    interval: str = Query("7d"),
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if market not in VALID_MARKETS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный рынок")
    if interval not in INTERVALS:
        interval = "7d"
    return await MarketDataService.get_history(db, market, symbol, interval)


# ── Asset detail endpoint ────────────────────────────────────────────────────


STOCK_META = {
    "AAPL": {"sector": "Технологии", "sectorKey": "technology", "description": "Apple Inc. — производитель потребительской электроники, ПО и услуг."},
    "GOOGL": {"sector": "Технологии", "sectorKey": "technology", "description": "Alphabet (Google) — поиск, реклама, облако и ИИ."},
    "MSFT": {"sector": "Технологии", "sectorKey": "technology", "description": "Microsoft — ПО, облако Azure, игровое подразделение."},
    "TSLA": {"sector": "Автомобили / Энергетика", "sectorKey": "auto_energy", "description": "Tesla — электромобили и решения для хранения энергии."},
    "NVDA": {"sector": "Полупроводники", "sectorKey": "semiconductors", "description": "NVIDIA — графические и ИИ-ускорители."},
}


async def _is_favorite(db, user_id: str, market: str, symbol: str) -> bool:
    return await db.user_favorites.find_one(
        {"userId": user_id, "market": market, "symbol": symbol.upper()}
    ) is not None


@router.get("/market/asset")
async def market_asset(
    market: str = Query(...),
    symbol: str = Query(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Полная карточка актива: метаданные, цена, статистика, позиция игрока."""
    if market not in VALID_MARKETS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный рынок")
    symbol = symbol.upper()
    user_id = str(current_user["_id"])

    stats = await MarketDataService.stats(db, market, symbol)

    if market == MARKET_STOCK:
        stock = await db.stocks.find_one({"symbol": symbol})
        if not stock:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Акция не найдена")
        cfg = stock.get("config") or {}
        total_shares = cfg.get("total_shares", 1_000_000_000)
        price = float(stock.get("price", 0))
        # реальный объём торгов за 24ч из событий рынка
        vol_cursor = db.stock_events.find(
            {"symbol": symbol, "timestamp": {"$gte": _now() - timedelta(hours=24)}}
        )
        volume = 0.0
        async for e in vol_cursor:
            volume += (e.get("quantity", 0) or 0) * (e.get("priceAfter", price) or price)
        held = await db.stock_holdings.find_one({"userId": user_id, "symbol": symbol})
        meta = STOCK_META.get(symbol, {})
        logo_img = stock.get("logo")
        if not logo_img and stock.get("companyId") and ObjectId.is_valid(stock["companyId"]):
            comp = await db.companies.find_one({"_id": ObjectId(stock["companyId"])}, {"logo": 1})
            logo_img = comp.get("logo") if comp else None
        info = {
            "market": market, "symbol": symbol, "name": stock.get("name"),
            "logo": symbol[:1], "image": logo_img, "color": "#6366f1",
            "source": stock.get("source", "sim"),
            "sector": meta.get("sector") or ("Пользовательская эмиссия" if stock.get("issuer") else "—"),
            "sectorKey": meta.get("sectorKey") or ("user_emission" if stock.get("issuer") else None),
            "description": stock.get("description") or meta.get("description") or "",
            "issuerName": stock.get("issuer_name"),
            "price": price,
            "change": stock.get("change", 0.0),
            "changePercent": stock.get("changePercent", 0.0),
            "marketCap": round(price * total_shares, 2),
            "volume24h": round(volume, 2),
            "totalShares": total_shares,
            "freeShares": stock.get("free_shares", total_shares),
            "heldQuantity": held.get("quantity", 0) if held else 0,
        }
    else:  # crypto
        coin = await db.crypto_assets.find_one({"symbol": symbol})
        if not coin:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Монета не найдена")
        price = float(coin.get("price", 0))
        supply = coin.get("supply", 0)
        held = await db.crypto_holdings.find_one({"userId": user_id, "symbol": symbol})
        coin_img = coin.get("image")
        if not coin_img and coin.get("companyId") and ObjectId.is_valid(coin["companyId"]):
            comp = await db.companies.find_one({"_id": ObjectId(coin["companyId"])}, {"logo": 1})
            coin_img = comp.get("logo") if comp else None
        info = {
            "market": market, "symbol": symbol, "name": coin.get("name"),
            "logo": symbol[:2], "image": coin_img, "color": coin.get("color", "#6366f1"),
            "source": coin.get("source", "sim"),
            "sector": "Криптовалюта",
            "sectorKey": "crypto",
            "description": coin.get("description") or "",
            "price": price,
            "change": 0.0,
            "changePercent": coin.get("change24h", 0.0),
            "marketCap": round(price * supply, 2) if supply else None,
            "volume24h": coin.get("volume24h", round(price * (supply or 0) * 0.04, 2)),
            "supply": supply,
            "ath": coin.get("ath", stats.get("ath")),
            "atl": coin.get("atl", stats.get("atl")),
            "heldQuantity": held.get("quantity", 0.0) if held else 0.0,
        }

    info["stats"] = stats
    info["isFavorite"] = await _is_favorite(db, user_id, market, symbol)
    return info


# ── Favorites ────────────────────────────────────────────────────────────────


class FavoriteBody(BaseModel):
    market: str
    symbol: str


@router.get("/favorites")
async def list_favorites(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    user_id = str(current_user["_id"])
    items = []
    async for f in db.user_favorites.find({"userId": user_id}):
        items.append({"market": f.get("market"), "symbol": f.get("symbol")})
    return items


@router.post("/favorites/toggle")
async def toggle_favorite(
    payload: FavoriteBody,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if payload.market not in VALID_MARKETS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный рынок")
    user_id = str(current_user["_id"])
    symbol = payload.symbol.upper()
    existing = await db.user_favorites.find_one(
        {"userId": user_id, "market": payload.market, "symbol": symbol}
    )
    if existing:
        await db.user_favorites.delete_one({"_id": existing["_id"]})
        return {"favorite": False}
    await db.user_favorites.insert_one(
        {"userId": user_id, "market": payload.market, "symbol": symbol, "created_at": _now()}
    )
    return {"favorite": True}


# ── Admin: point-edit + regenerate price history ────────────────────────────────


class PricePointBody(BaseModel):
    market: str
    symbol: str
    price: float
    ts: Optional[datetime] = None


class PricePointUpdate(BaseModel):
    price: Optional[float] = None
    ts: Optional[datetime] = None


class RegenerateBody(BaseModel):
    market: str
    symbol: str
    price: Optional[float] = None
    volatility: Optional[float] = None


def _format_point(doc: dict) -> dict:
    return {"id": str(doc["_id"]), "ts": _aware(doc["ts"]).isoformat(), "price": doc["price"]}


@router.get("/admin/price-history")
async def admin_list_price_history(
    market: str = Query(...),
    symbol: str = Query(...),
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if market not in VALID_MARKETS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный рынок")
    rows = [r async for r in db.price_history.find(
        {"market": market, "symbol": symbol.upper()}
    ).sort("ts", 1)]
    return [_format_point(r) for r in rows]


@router.post("/admin/price-history", status_code=status.HTTP_201_CREATED)
async def admin_add_price_point(
    payload: PricePointBody,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if payload.market not in VALID_MARKETS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный рынок")
    doc = {
        "market": payload.market, "symbol": payload.symbol.upper(),
        "price": round(payload.price, 6), "ts": _aware(payload.ts) if payload.ts else _now(),
    }
    result = await db.price_history.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _format_point(doc)


@router.patch("/admin/price-history/{point_id}")
async def admin_update_price_point(
    point_id: str,
    payload: PricePointUpdate,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    fields = payload.model_dump(exclude_unset=True)
    if "price" in fields and fields["price"] is not None:
        fields["price"] = round(fields["price"], 6)
    if "ts" in fields and fields["ts"] is not None:
        fields["ts"] = _aware(fields["ts"])
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустое тело запроса")
    result = await db.price_history.update_one({"_id": ObjectId(point_id)}, {"$set": fields})
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Точка истории не найдена")
    doc = await db.price_history.find_one({"_id": ObjectId(point_id)})
    return _format_point(doc)


@router.delete("/admin/price-history/{point_id}")
async def admin_delete_price_point(
    point_id: str,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    result = await db.price_history.delete_one({"_id": ObjectId(point_id)})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Точка истории не найдена")
    return {"deleted": True}


@router.post("/admin/price-history/regenerate")
async def admin_regenerate_price_history(
    payload: RegenerateBody,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if payload.market not in VALID_MARKETS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный рынок")
    symbol = payload.symbol.upper()
    coll = db.stocks if payload.market == MARKET_STOCK else db.crypto_assets
    asset = await coll.find_one({"symbol": symbol})
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Актив не найден")
    price = payload.price if payload.price is not None else float(asset.get("price", 0))
    volatility = payload.volatility if payload.volatility is not None else float(asset.get("volatility", 0.03))
    await MarketDataService.regenerate(db, payload.market, symbol, price, volatility)
    return {"regenerated": True, "points": 365 + 144}


if __name__ == "__main__":
    docs = _build_walk_docs("stock", "test", 100.0, 0.03)
    assert len(docs) == 365 + 144, len(docs)
    for d in docs:
        assert 100.0 * 0.15 <= d["price"] <= 100.0 * 6, d["price"]
        assert d["symbol"] == "TEST"
    daily_leg = docs[:365]
    assert daily_leg[0]["ts"] > daily_leg[-1]["ts"]
    assert (daily_leg[0]["ts"] - daily_leg[-1]["ts"]).days == 364
    print("market_data self-check OK")
