"""Криптовалюты: открытие криптосчёта, рынок, кошелёк, торговля, баланс.

Цены монет живут собственной жизнью — при чтении рынка применяется
троттлинг-обновление (случайное блуждание), что даёт динамику без внешнего
планировщика. Все денежные движения проходят через единый реестр (ledger).
"""
import random
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator

from auth import get_current_user
from database import get_db
from ledger import (
    INCOME, EXPENSE, CAT_CRYPTO,
    adjust_balance, record_transaction,
)

router = APIRouter(prefix="/api/crypto", tags=["crypto"])

# Как часто (сек) пересчитывать цену монеты при чтении рынка
PRICE_REFRESH_SECONDS = 30

DEFAULT_COINS = [
    {"symbol": "WVC", "name": "WarVerse Coin", "price": 120.0, "volatility": 0.04, "color": "#f7931a"},
    {"symbol": "TVX", "name": "TradeVerse X", "price": 45.5, "volatility": 0.05, "color": "#627eea"},
    {"symbol": "NEON", "name": "Neon Token", "price": 3.2, "volatility": 0.08, "color": "#22c55e"},
    {"symbol": "GLD", "name": "GoldChain", "price": 210.0, "volatility": 0.02, "color": "#eab308"},
    {"symbol": "MEME", "name": "MemeCoin", "price": 0.85, "volatility": 0.12, "color": "#ec4899"},
]


# ── Schemas ──────────────────────────────────────────────────────────────────


class CryptoTrade(BaseModel):
    symbol: str
    action: str  # "buy" | "sell"
    quantity: float

    @field_validator("action")
    @classmethod
    def action_valid(cls, v):
        if v not in ("buy", "sell"):
            raise ValueError("action должен быть 'buy' или 'sell'")
        return v

    @field_validator("quantity")
    @classmethod
    def qty_positive(cls, v):
        if v is None or v <= 0:
            raise ValueError("Количество должно быть положительным")
        return round(float(v), 8)


# ── Seed / market maintenance ────────────────────────────────────────────────


async def ensure_coins_seeded(db: AsyncIOMotorDatabase):
    if await db.crypto_assets.count_documents({}) == 0:
        for c in DEFAULT_COINS:
            await db.crypto_assets.insert_one({
                **c,
                "base_price": c["price"],
                "change24h": 0.0,
                "updated_at": datetime.utcnow(),
            })


def _walk_price(coin: dict) -> dict:
    """Случайное блуждание цены, ограниченное коридором [0.3x, 3x] от базовой."""
    base = coin.get("base_price", coin["price"])
    vol = coin.get("volatility", 0.05)
    old = coin["price"]
    new = old * (1 + random.gauss(0, vol))
    new = max(base * 0.3, min(base * 3, new))
    change = ((new - old) / old * 100) if old else 0.0
    coin["price"] = round(new, 6)
    coin["change24h"] = round(coin.get("change24h", 0.0) * 0.7 + change, 2)
    coin["updated_at"] = datetime.utcnow()
    return coin


async def _get_live_market(db: AsyncIOMotorDatabase) -> list[dict]:
    await ensure_coins_seeded(db)
    now = datetime.utcnow()
    coins = []
    async for coin in db.crypto_assets.find({}):
        updated = coin.get("updated_at")
        if not isinstance(updated, datetime) or (now - updated).total_seconds() >= PRICE_REFRESH_SECONDS:
            coin = _walk_price(coin)
            await db.crypto_assets.update_one(
                {"_id": coin["_id"]},
                {"$set": {
                    "price": coin["price"],
                    "change24h": coin["change24h"],
                    "updated_at": coin["updated_at"],
                }},
            )
        coin["id"] = str(coin.pop("_id"))
        coin.pop("updated_at", None)
        coins.append(coin)
    coins.sort(key=lambda c: c["symbol"])
    return coins


async def _price_of(db: AsyncIOMotorDatabase, symbol: str) -> float | None:
    coin = await db.crypto_assets.find_one({"symbol": symbol.upper()})
    return coin["price"] if coin else None


def _wallet_address(user_id: str) -> str:
    """Детерминированный адрес кошелька на основе id пользователя."""
    return "TVX-" + user_id[-12:].upper()


# ── Account ──────────────────────────────────────────────────────────────────


@router.post("/account/open", status_code=status.HTTP_201_CREATED)
async def open_crypto_account(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Открывает криптосчёт игроку. Идемпотентно возвращает уже открытый счёт."""
    user_id = str(current_user["_id"])
    if current_user.get("crypto_account_opened"):
        return {
            "opened": True,
            "wallet": current_user.get("crypto_wallet") or _wallet_address(user_id),
            "already": True,
        }
    wallet = _wallet_address(user_id)
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"crypto_account_opened": True, "crypto_wallet": wallet}},
    )
    return {"opened": True, "wallet": wallet, "already": False}


@router.get("/account")
async def get_crypto_account(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Состояние криптосчёта: открыт ли, кошелёк, холдинги и их оценка."""
    user_id = str(current_user["_id"])
    opened = bool(current_user.get("crypto_account_opened"))
    if not opened:
        return {"opened": False, "wallet": None, "holdings": [], "portfolioValue": 0.0}

    market = {c["symbol"]: c for c in await _get_live_market(db)}
    holdings = []
    portfolio_value = 0.0
    async for h in db.crypto_holdings.find({"userId": user_id}):
        symbol = h["symbol"]
        qty = h.get("quantity", 0.0)
        price = market.get(symbol, {}).get("price", 0.0)
        value = round(qty * price, 2)
        portfolio_value += value
        holdings.append({
            "symbol": symbol,
            "name": market.get(symbol, {}).get("name", symbol),
            "quantity": qty,
            "avgPrice": h.get("avg_price", 0.0),
            "price": price,
            "value": value,
            "color": market.get(symbol, {}).get("color", "#6366f1"),
        })
    holdings.sort(key=lambda x: x["value"], reverse=True)
    return {
        "opened": True,
        "wallet": current_user.get("crypto_wallet") or _wallet_address(user_id),
        "balance": current_user.get("balance", 0.0),
        "holdings": holdings,
        "portfolioValue": round(portfolio_value, 2),
    }


@router.get("/market")
async def get_crypto_market(
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Рынок криптовалют: список монет, цена, изменение за 24ч."""
    return await _get_live_market(db)


# ── Trade ────────────────────────────────────────────────────────────────────


@router.post("/trade")
async def trade_crypto(
    payload: CryptoTrade,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Покупка/продажа криптовалюты. Требует открытого криптосчёта."""
    if not current_user.get("crypto_account_opened"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Сначала откройте криптосчёт",
        )

    user_id = str(current_user["_id"])
    symbol = payload.symbol.upper()
    qty = payload.quantity

    price = await _price_of(db, symbol)
    if price is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Монета не найдена")

    total = round(qty * price, 2)
    holding = await db.crypto_holdings.find_one({"userId": user_id, "symbol": symbol})

    if payload.action == "buy":
        new_balance = await adjust_balance(db, user_id, -total)
        if new_balance is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Недостаточно средств")
        old_qty = holding.get("quantity", 0.0) if holding else 0.0
        old_avg = holding.get("avg_price", 0.0) if holding else 0.0
        new_qty = old_qty + qty
        new_avg = round((old_qty * old_avg + total) / new_qty, 6) if new_qty else price
        await db.crypto_holdings.update_one(
            {"userId": user_id, "symbol": symbol},
            {"$set": {"quantity": round(new_qty, 8), "avg_price": new_avg}},
            upsert=True,
        )
        await record_transaction(
            db, user_id, EXPENSE, total, CAT_CRYPTO,
            f"Покупка {qty:g} {symbol}", symbol=symbol, price=price,
            balance_after=new_balance, meta={"quantity": qty, "action": "buy"},
        )
        return {"message": "Покупка выполнена", "symbol": symbol, "quantity": qty,
                "price": price, "total": total, "balance": new_balance}

    # sell
    if not holding or holding.get("quantity", 0.0) < qty:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Недостаточно монет")
    remaining = round(holding["quantity"] - qty, 8)
    if remaining <= 0:
        await db.crypto_holdings.delete_one({"userId": user_id, "symbol": symbol})
    else:
        await db.crypto_holdings.update_one(
            {"userId": user_id, "symbol": symbol},
            {"$set": {"quantity": remaining}},
        )
    new_balance = await adjust_balance(db, user_id, total)
    await record_transaction(
        db, user_id, INCOME, total, CAT_CRYPTO,
        f"Продажа {qty:g} {symbol}", symbol=symbol, price=price,
        balance_after=new_balance, meta={"quantity": qty, "action": "sell"},
    )
    return {"message": "Продажа выполнена", "symbol": symbol, "quantity": qty,
            "price": price, "total": total, "balance": new_balance}
