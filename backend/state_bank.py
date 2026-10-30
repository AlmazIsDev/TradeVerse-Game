"""Банк государства: счёт, на который поступают комиссии, проценты и налоги игроков.

Документ счёта — одна запись в коллекции state_bank с _id=STATE_ACCOUNT_ID.
Все движения пишутся через credit_state/debit_state — баланс меняется
атомарным $inc, без read-modify-write.
"""
from __future__ import annotations

from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

STATE_ACCOUNT_ID = "state"


async def credit_state(db: AsyncIOMotorDatabase, amount: float, source: str) -> None:
    amount = round(float(amount), 2)
    if amount <= 0:
        return
    await db.state_bank.update_one(
        {"_id": STATE_ACCOUNT_ID},
        {
            "$inc": {"balance": amount, f"by_source.{source}": amount},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
        upsert=True,
    )


async def debit_state(db: AsyncIOMotorDatabase, amount: float, source: str) -> bool:
    """Списание со счёта государства (кредиты, проценты по депозитам). False — если денег нет."""
    amount = round(float(amount), 2)
    if amount <= 0:
        return True
    result = await db.state_bank.find_one_and_update(
        {"_id": STATE_ACCOUNT_ID, "balance": {"$gte": amount}},
        {
            "$inc": {"balance": -amount, f"by_source.{source}": -amount},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
    )
    return result is not None


async def get_state_balance(db: AsyncIOMotorDatabase) -> float:
    doc = await db.state_bank.find_one({"_id": STATE_ACCOUNT_ID}, {"balance": 1})
    return round(float((doc or {}).get("balance", 0.0)), 2)
