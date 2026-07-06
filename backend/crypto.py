"""Криптовалюты: открытие криптосчёта, рынок, кошелёк, торговля, баланс.

Цены монет живут собственной жизнью — при чтении рынка применяется
троттлинг-обновление (случайное блуждание), что даёт динамику без внешнего
планировщика. Все денежные движения проходят через единый реестр (ledger).
"""
import random
from datetime import datetime, timezone

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
from market_data import MarketDataService
from notifications import push_notification

router = APIRouter(prefix="/api/crypto", tags=["crypto"])

# Как часто (сек) пересчитывать цену монеты при чтении рынка
PRICE_REFRESH_SECONDS = 30
# Комиссия сети за перевод криптовалюты (доля от суммы, «сгорает»)
CRYPTO_FEE_RATE = 0.01

DEFAULT_COINS = [
    {"symbol": "WVC", "name": "WarVerse Coin", "price": 120.0, "volatility": 0.04, "color": "#f7931a", "supply": 21_000_000, "description": "Флагманская монета вселенной TradeVerse: дефляционная модель и лимит эмиссии."},
    {"symbol": "TVX", "name": "TradeVerse X", "price": 45.5, "volatility": 0.05, "color": "#627eea", "supply": 120_000_000, "description": "Утилити-токен экосистемы, обеспечивает смарт-контракты и стейкинг."},
    {"symbol": "NEON", "name": "Neon Token", "price": 3.2, "volatility": 0.08, "color": "#22c55e", "supply": 500_000_000, "description": "Быстрый L2-токен для микротранзакций и игровых платежей."},
    {"symbol": "GLD", "name": "GoldChain", "price": 210.0, "volatility": 0.02, "color": "#eab308", "supply": 8_000_000, "description": "Стабильный актив, обеспеченный виртуальным золотом. Низкая волатильность."},
    {"symbol": "MEME", "name": "MemeCoin", "price": 0.85, "volatility": 0.12, "color": "#ec4899", "supply": 1_000_000_000, "description": "Высоковолатильный мем-токен. Только для смелых."},
    {"symbol": "ORB", "name": "Orbit", "price": 12.4, "volatility": 0.07, "color": "#8b5cf6", "supply": 300_000_000, "description": "Токен децентрализованной спутниковой сети."},
    {"symbol": "AQUA", "name": "AquaCoin", "price": 1.75, "volatility": 0.06, "color": "#06b6d4", "supply": 750_000_000, "description": "Экологичный токен с механикой ликвидных пулов."},
    {"symbol": "IRON", "name": "IronLedger", "price": 58.0, "volatility": 0.03, "color": "#64748b", "supply": 40_000_000, "description": "Промышленный блокчейн-токен для цепочек поставок."},
    {"symbol": "PIX", "name": "PixelCash", "price": 0.42, "volatility": 0.10, "color": "#f43f5e", "supply": 2_000_000_000, "description": "Игровая валюта пиксельных миров."},
    {"symbol": "NOVA", "name": "NovaChain", "price": 88.5, "volatility": 0.06, "color": "#e879f9", "supply": 60_000_000, "description": "Быстрорастущий токен нового поколения консенсуса."},
    {"symbol": "ZEN", "name": "ZenToken", "price": 6.9, "volatility": 0.05, "color": "#10b981", "supply": 210_000_000, "description": "Приватный токен с фокусом на анонимность."},
    {"symbol": "BOLT", "name": "BoltPay", "price": 24.1, "volatility": 0.07, "color": "#f59e0b", "supply": 150_000_000, "description": "Платёжная сеть с мгновенными переводами."},
    {"symbol": "DUSK", "name": "DuskCoin", "price": 0.19, "volatility": 0.14, "color": "#7c3aed", "supply": 5_000_000_000, "description": "Экспериментальный токен теневых рынков."},
    {"symbol": "RUBY", "name": "RubyChain", "price": 340.0, "volatility": 0.03, "color": "#dc2626", "supply": 3_000_000, "description": "Премиальный редкий токен с ограниченной эмиссией."},
    {"symbol": "FLUX", "name": "FluxNet", "price": 9.3, "volatility": 0.09, "color": "#0ea5e9", "supply": 400_000_000, "description": "Токен распределённых вычислений и облака."},
    {"symbol": "GEM", "name": "GemStone", "price": 155.0, "volatility": 0.04, "color": "#14b8a6", "supply": 12_000_000, "description": "Коллекционный токен с NFT-механиками."},
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


class CryptoTransfer(BaseModel):
    recipient: str          # адрес кошелька ИЛИ имя игрока
    symbol: str
    amount: float

    @field_validator("recipient")
    @classmethod
    def rec_ok(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("Укажите получателя")
        return v

    @field_validator("amount")
    @classmethod
    def amount_ok(cls, v):
        if v is None or v <= 0:
            raise ValueError("Сумма должна быть положительной")
        return round(float(v), 8)


# ── Seed / market maintenance ────────────────────────────────────────────────


async def ensure_coins_seeded(db: AsyncIOMotorDatabase):
    if await db.crypto_assets.count_documents({}) == 0:
        for c in DEFAULT_COINS:
            await db.crypto_assets.insert_one({
                **c,
                "base_price": c["price"],
                "change24h": 0.0,
                "ath": c["price"],
                "atl": c["price"],
                "volume24h": round(c["price"] * c.get("supply", 0) * 0.04, 2),
                "updated_at": datetime.utcnow(),
            })
            await MarketDataService.ensure_backfill(db, "crypto", c["symbol"], c["price"], c.get("volatility", 0.05))


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
    coin["ath"] = round(max(coin.get("ath", new), new), 6)
    coin["atl"] = round(min(coin.get("atl", new) or new, new), 6)
    coin["volume24h"] = round(new * coin.get("supply", 0) * (0.03 + abs(random.gauss(0, 0.02))), 2)
    coin["updated_at"] = datetime.utcnow()
    return coin


async def _get_live_market(db: AsyncIOMotorDatabase) -> list[dict]:
    await ensure_coins_seeded(db)
    # Пытаемся обновить реальными данными CoinGecko (кэш + fallback внутри).
    mode = await MarketDataService.refresh_crypto(db)
    now = datetime.now(timezone.utc)
    coins = []
    async for coin in db.crypto_assets.find({}):
        symbol = coin["symbol"]
        await MarketDataService.ensure_backfill(db, "crypto", symbol, coin.get("price", 1) or 1, coin.get("volatility", 0.05))
        # Симуляция цены — только fallback, когда реальные данные недоступны.
        if mode == "sim":
            updated = coin.get("updated_at")
            if isinstance(updated, datetime) and updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if not isinstance(updated, datetime) or (now - updated).total_seconds() >= PRICE_REFRESH_SECONDS:
                coin = _walk_price(coin)
                await db.crypto_assets.update_one(
                    {"_id": coin["_id"]},
                    {"$set": {
                        "price": coin["price"],
                        "change24h": coin["change24h"],
                        "ath": coin["ath"],
                        "atl": coin["atl"],
                        "volume24h": coin["volume24h"],
                        "updated_at": coin["updated_at"],
                    }},
                )
                await MarketDataService.record_snapshot(db, "crypto", symbol, coin["price"])
        coin["id"] = str(coin.pop("_id"))
        coin.pop("updated_at", None)
        coins.append(coin)
    coins.sort(key=lambda c: c.get("marketCap") or (c.get("price", 0) * c.get("supply", 0)), reverse=True)
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


# ── Wallet-to-wallet transfers ───────────────────────────────────────────────


@router.post("/transfer")
async def transfer_crypto(
    payload: CryptoTransfer,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Перевод криптовалюты другому игроку по адресу кошелька или нику.

    Проверки: получатель существует и имеет криптосчёт, нельзя себе,
    достаточно монет (с учётом комиссии), сумма положительна.
    Комиссия сети (CRYPTO_FEE_RATE) сгорает.
    """
    if not current_user.get("crypto_account_opened"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Сначала откройте криптосчёт")

    sender_id = str(current_user["_id"])
    symbol = payload.symbol.upper()
    amount = payload.amount
    fee = round(amount * CRYPTO_FEE_RATE, 8)
    total_debit = round(amount + fee, 8)

    coin = await db.crypto_assets.find_one({"symbol": symbol})
    if not coin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Монета не найдена")
    price = float(coin.get("price", 0))

    recipient = await db.users.find_one({
        "$or": [{"crypto_wallet": payload.recipient}, {"username": payload.recipient}]
    })
    if not recipient:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Получатель не найден")
    rec_id = str(recipient["_id"])
    if rec_id == sender_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя перевести самому себе")
    if not recipient.get("crypto_account_opened"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "У получателя нет криптосчёта")

    # Атомарное списание у отправителя с проверкой достаточности (с учётом комиссии).
    debited = await db.crypto_holdings.find_one_and_update(
        {"userId": sender_id, "symbol": symbol, "quantity": {"$gte": total_debit}},
        {"$inc": {"quantity": -total_debit}},
        return_document=True,
    )
    if not debited:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно монет (с учётом комиссии)")
    if debited.get("quantity", 0) <= 1e-9:
        await db.crypto_holdings.delete_one({"_id": debited["_id"]})

    # Зачисление получателю (пересчёт средней цены).
    rec_h = await db.crypto_holdings.find_one({"userId": rec_id, "symbol": symbol})
    old_qty = rec_h.get("quantity", 0.0) if rec_h else 0.0
    old_avg = rec_h.get("avg_price", 0.0) if rec_h else 0.0
    new_qty = round(old_qty + amount, 8)
    new_avg = round((old_qty * old_avg + amount * price) / new_qty, 6) if new_qty else price
    await db.crypto_holdings.update_one(
        {"userId": rec_id, "symbol": symbol},
        {"$set": {"quantity": new_qty, "avg_price": new_avg}},
        upsert=True,
    )

    value = round(amount * price, 2)
    now = datetime.utcnow()
    await db.crypto_transfers.insert_one({
        "fromId": sender_id, "fromName": current_user.get("username"),
        "toId": rec_id, "toName": recipient.get("username"),
        "symbol": symbol, "amount": amount, "fee": fee,
        "price": price, "value": value, "ts": now,
    })
    await push_notification(
        db, rec_id, "crypto_transfer", "Получен крипто-перевод",
        f"{current_user.get('username')} отправил {amount:g} {symbol}.",
        data={"symbol": symbol, "amount": amount},
    )
    return {
        "ok": True, "sent": amount, "fee": fee, "symbol": symbol,
        "recipient": recipient.get("username"),
    }


@router.get("/transfers")
async def crypto_transfers(
    limit: int = 30,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """История крипто-переводов игрока (отправленные и полученные)."""
    user_id = str(current_user["_id"])
    limit = max(1, min(limit, 100))
    out = []
    cursor = db.crypto_transfers.find(
        {"$or": [{"fromId": user_id}, {"toId": user_id}]}
    ).sort("ts", -1).limit(limit)
    async for tr in cursor:
        outgoing = tr.get("fromId") == user_id
        out.append({
            "id": str(tr["_id"]),
            "direction": "out" if outgoing else "in",
            "counterparty": tr.get("toName") if outgoing else tr.get("fromName"),
            "symbol": tr.get("symbol"),
            "amount": tr.get("amount"),
            "fee": tr.get("fee") if outgoing else 0,
            "value": tr.get("value"),
            "timestamp": tr["ts"].isoformat() if isinstance(tr.get("ts"), datetime) else None,
        })
    return out
