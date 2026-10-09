"""Синтетические транзакции (боты-маркетмейкеры): управление из админки.

Боты имитируют торговую активность на бирже акций и крипторынке, чтобы график
жил при малом онлайне. Сделки ботов не имеют баланса и не попадают в денежный
реестр (ledger): они двигают цену и пул свободного остатка той же механикой,
что и сделки игроков.

- get_synthetic_config(db) — единая точка чтения параметров (дефолты + overrides
  из app_config["synthetic_config"]); её читают stocks.py и crypto.py.
- /api/admin/synthetic/* — просмотр/правка конфига, ручной запуск, лента сделок.

Все синтетические сделки ограничены свободным остатком: бот покупает только
в пределах свободных акций (free_shares) / свободных монет (эмиссия минус
холдинги игроков и самого бота), продаёт — только то, что раньше купил.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from admin_perms import require_admin
from database import get_db, find_config_by_key, upsert_config
from timeutil import now_utc

router = APIRouter(prefix="/api/admin/synthetic", tags=["synthetic-admin"])

SYNTH_KEY = "synthetic_config"
BOT_USER_ID = "bot"

# Дефолты повторяют прежние константы ботов акций (stocks.py) и задают стартовые
# для крипты. Админ меняет их в админке, overrides хранятся в app_config.
DEFAULT_SYNTHETIC: dict = {
    "stocks": {
        "enabled": True,
        "probability": 0.4,      # вероятность сделки бота по акции за раунд
        "minShares": 1,
        "maxShares": 1_000_000,  # верхняя граница случайного объёма ордера
        "roundsPerTick": 6,      # раундов за тик планировщика (~торговля каждые 10с)
        "buyBiasMin": 0.3,       # вероятность покупки тянется из [min, max]
        "buyBiasMax": 0.7,
    },
    "crypto": {
        "enabled": True,
        "probability": 0.4,
        "minVolumeUsd": 100.0,    # объём сделки в $ (случайный в [min, max])
        "maxVolumeUsd": 25_000.0,
        "roundsPerTick": 2,
        "buyBiasMin": 0.3,
        "buyBiasMax": 0.7,
    },
}


async def get_synthetic_config(db: AsyncIOMotorDatabase) -> dict:
    """Текущие параметры ботов: дефолт + сохранённые overrides (по рынкам)."""
    cfg = json.loads(json.dumps(DEFAULT_SYNTHETIC))  # глубокая копия
    doc = await find_config_by_key(db, SYNTH_KEY)
    if doc:
        try:
            saved = json.loads(doc["value"])
            for market in cfg:
                if isinstance(saved.get(market), dict):
                    cfg[market].update({
                        k: v for k, v in saved[market].items() if k in cfg[market]
                    })
        except Exception:
            pass
    return cfg


# ── Schemas ──────────────────────────────────────────────────────────────────


class StocksBotConfig(BaseModel):
    enabled: bool = True
    probability: float
    minShares: int
    maxShares: int
    roundsPerTick: int
    buyBiasMin: float
    buyBiasMax: float


class CryptoBotConfig(BaseModel):
    enabled: bool = True
    probability: float
    minVolumeUsd: float
    maxVolumeUsd: float
    roundsPerTick: int
    buyBiasMin: float
    buyBiasMax: float


class SyntheticConfigUpdate(BaseModel):
    stocks: Optional[StocksBotConfig] = None
    crypto: Optional[CryptoBotConfig] = None


class TriggerBody(BaseModel):
    market: str = "all"          # stocks | crypto | all
    symbol: Optional[str] = None  # разовая сделка по конкретному тикеру/монете
    side: Optional[str] = None   # buy | sell (None — случайная сторона)
    quantity: Optional[float] = None  # объём; None — случайный по конфигу


def _validate_market(market: str, data: dict) -> None:
    """Инварианты параметров одного рынка (общие для акций и крипты)."""
    if not (0 <= data["probability"] <= 1):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{market}: probability вне [0, 1]")
    if not (0 <= data["buyBiasMin"] <= data["buyBiasMax"] <= 1):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{market}: buyBias 0 ≤ min ≤ max ≤ 1")
    if not (0 <= data["roundsPerTick"] <= 60):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{market}: roundsPerTick 0–60")
    if market == "stocks":
        if data["minShares"] < 1 or data["maxShares"] < data["minShares"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{market}: 1 ≤ minShares ≤ maxShares")
    else:
        if data["minVolumeUsd"] <= 0 or data["maxVolumeUsd"] < data["minVolumeUsd"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{market}: 0 < minVolumeUsd ≤ maxVolumeUsd")


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/config")
async def get_config(
    _admin: dict = Depends(require_admin("synthetic")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Конфиг ботов + объём синтетической активности за 24ч."""
    cfg = await get_synthetic_config(db)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    return {
        **cfg,
        "stats": {
            "stocks24h": await db.stock_events.count_documents(
                {"userId": BOT_USER_ID, "timestamp": {"$gte": since}}),
            "crypto24h": await db.crypto_events.count_documents(
                {"userId": BOT_USER_ID, "timestamp": {"$gte": since}}),
        },
    }


@router.post("/config")
async def set_config(
    payload: SyntheticConfigUpdate,
    _admin: dict = Depends(require_admin("synthetic")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Сохраняет overrides параметров (переданные рынки целиком)."""
    cfg = await get_synthetic_config(db)
    update = payload.model_dump(exclude_unset=True, exclude_none=True)
    for market in ("stocks", "crypto"):
        if market in update:
            _validate_market(market, update[market])
            cfg[market] = update[market]
    await upsert_config(db, SYNTH_KEY, json.dumps(cfg))
    return cfg


@router.post("/trigger")
async def trigger(
    body: TriggerBody,
    _admin: dict = Depends(require_admin("synthetic")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Ручной запуск: раунд ботов (market=all/stocks/crypto) или разовая сделка
    по symbol с заданными side/quantity (в пределах свободного остатка)."""
    if body.market not in ("all", "stocks", "crypto"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "market: stocks | crypto | all")
    if body.side and body.side not in ("buy", "sell"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "side: buy | sell")
    cfg = await get_synthetic_config(db)
    result = {"stocks": 0, "crypto": 0}
    # Ленивые импорты: stocks/crypto не импортируют synthetic на верхнем уровне.
    if body.market in ("all", "stocks"):
        import stocks as stocks_mod
        result["stocks"] = await stocks_mod.run_bots(
            db, cfg["stocks"], symbol=body.symbol, side=body.side, quantity=body.quantity)
    if body.market in ("all", "crypto"):
        import crypto as crypto_mod
        result["crypto"] = await crypto_mod.run_bots(
            db, cfg["crypto"], symbol=body.symbol, side=body.side, quantity=body.quantity)
    return {"executed": result}


@router.get("/orders")
async def orders(
    limit: int = Query(50, ge=1, le=500),
    _admin: dict = Depends(require_admin("synthetic")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Единая лента сделок ботов (акции + крипта), новые сверху."""
    feed = []
    async for e in db.stock_events.find({"userId": BOT_USER_ID}).sort("timestamp", -1).limit(limit):
        feed.append({
            "id": f"stock-{e['_id']}",
            "market": "stocks",
            "symbol": e.get("symbol"),
            "action": e.get("type"),
            "quantity": e.get("quantity"),
            "price": e.get("priceAfter"),
            "timestamp": _iso(e.get("timestamp")),
        })
    async for e in db.crypto_events.find({"userId": BOT_USER_ID}).sort("timestamp", -1).limit(limit):
        feed.append({
            "id": f"crypto-{e['_id']}",
            "market": "crypto",
            "symbol": e.get("symbol"),
            "action": e.get("type"),
            "quantity": e.get("quantity"),
            "price": e.get("priceAfter"),
            "timestamp": _iso(e.get("timestamp")),
        })
    feed.sort(key=lambda x: x["timestamp"], reverse=True)
    return feed[:limit]


def _iso(dt) -> str:
    return dt.isoformat() if isinstance(dt, datetime) else ""


if __name__ == "__main__":
    # Инварианты валидации конфига и мержа overrides.
    import asyncio
    import random

    base = dict(DEFAULT_SYNTHETIC["stocks"])
    _validate_market("stocks", base)
    _validate_market("crypto", dict(DEFAULT_SYNTHETIC["crypto"]))
    for _ in range(1000):
        p = random.uniform(0, 1)
        assert 0 <= p <= 1
        lo = random.uniform(0, 1)
        hi = random.uniform(0, 1)
        assert 0 <= min(lo, hi) <= max(lo, hi) <= 1
    # Объём сделки бота крипты всегда в пределах конфига.
    q = random.uniform(DEFAULT_SYNTHETIC["crypto"]["minVolumeUsd"],
                       DEFAULT_SYNTHETIC["crypto"]["maxVolumeUsd"])
    assert 100.0 <= q <= 25_000.0
    print("synthetic self-check OK")
