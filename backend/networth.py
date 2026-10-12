"""Чистый капитал игрока (net worth) и ограничение переводов для новичков.

Формула состояния синхронизирована с _compute_leaderboard_entries в main.py:
наличные + акции + крипта + личные активы + компания (бюджет + её активы,
засчитываются владельцу) + WarCoin. Держим в одном месте, чтобы гейт переводов
и лидерборд не разъехались.
"""
from __future__ import annotations

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

# Синхронизировано с WARCOIN_USD в main.py (импортируется оттуда).
WARCOIN_USD = 50.0

# Переводы (наличные и крипта, в обе стороны) доступны только игрокам
# с состоянием не ниже этого порога.
TRANSFER_MIN_NET_WORTH = 3_000_000.0


def _asset_value(a: dict) -> float:
    return a.get("price", 0) * (1 + 0.35 * (a.get("level", 1) - 1))


async def compute_net_worth(db: AsyncIOMotorDatabase, user_id: str) -> float:
    """Состояние одного игрока по текущим рыночным ценам."""
    user = await db.users.find_one(
        {"_id": ObjectId(user_id)}, {"balance": 1, "warcoin": 1}
    )
    if not user:
        return 0.0

    stock_prices = {
        s["symbol"]: float(s.get("price", 0.0))
        async for s in db.stocks.find({}, {"symbol": 1, "price": 1})
    }
    crypto_prices = {
        c["symbol"]: float(c.get("price", 0.0))
        async for c in db.crypto_assets.find({}, {"symbol": 1, "price": 1})
    }

    value = float(user.get("balance", 0.0) or 0.0)
    async for h in db.stock_holdings.find({"userId": user_id, "quantity": {"$gt": 0}}):
        value += h.get("quantity", 0) * stock_prices.get(h.get("symbol"), 0.0)
    async for h in db.crypto_holdings.find({"userId": user_id, "quantity": {"$gt": 0}}):
        value += h.get("quantity", 0.0) * crypto_prices.get(h.get("symbol"), 0.0)
    async for a in db.user_assets.find({"userId": user_id, "companyId": None}):
        value += _asset_value(a)

    # Компания засчитывается владельцу — как в лидерборде.
    company = await db.companies.find_one({"ownerId": user_id}, {"budget": 1})
    if company:
        value += float(company.get("budget", 0.0) or 0.0)
        async for a in db.user_assets.find({"companyId": str(company["_id"])}):
            value += _asset_value(a)

    value += float(user.get("warcoin", 0) or 0) * WARCOIN_USD
    return round(value, 2)


def _fmt(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ")


async def ensure_transfer_allowed(db: AsyncIOMotorDatabase, user: dict, *, recipient: bool = False) -> None:
    """Гейт новичка: переводы недоступны, пока состояние < TRANSFER_MIN_NET_WORTH.

    recipient=True — сообщение для случая, когда отправитель пытается перевести
    деньги «недозревшему» получателю.
    """
    nw = await compute_net_worth(db, str(user["_id"]))
    if nw >= TRANSFER_MIN_NET_WORTH:
        return
    threshold = _fmt(TRANSFER_MIN_NET_WORTH)
    if recipient:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=f"Получатель ещё не может принимать переводы: нужно состояние от {threshold} $",
        )
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        detail=(
            f"Переводы доступны при состоянии от {threshold} $ "
            f"(ваше состояние: {_fmt(nw)} $)"
        ),
    )
