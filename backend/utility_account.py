"""Счёт «Электричество»: отдельный счёт игрока для оплаты электроэнергии дома.

Документ — одна запись на пользователя в коллекции utility_accounts
(поле userId, уникальный индекс). Пополнение — перевод с основного счёта,
списание — атомарный $inc с условием достаточности, как в ledger.adjust_balance.
Транзакции пишет вызывающий код: списание может откатиться, а запись уже нет.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from ledger import EXPENSE, adjust_balance, record_transaction

CAT_UTILITY = "utility"


async def get_utility_balance(db: AsyncIOMotorDatabase, user_id: str) -> float:
    doc = await db.utility_accounts.find_one({"userId": str(user_id)}, {"balance": 1})
    return round(float((doc or {}).get("balance", 0.0)), 2)


async def top_up(db: AsyncIOMotorDatabase, user_id: str, amount: float) -> Optional[dict]:
    """Перевод с основного счёта на «Электричество». None — если на основном счёте не хватает."""
    amount = round(float(amount), 2)
    if amount <= 0:
        return None
    main_balance = await adjust_balance(db, user_id, -amount)
    if main_balance is None:
        return None
    await db.utility_accounts.update_one(
        {"userId": str(user_id)},
        {"$inc": {"balance": amount}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    await record_transaction(
        db, user_id, EXPENSE, amount, CAT_UTILITY, "Пополнение счёта «Электричество»",
        balance_after=main_balance, meta={"account": "utility", "kind": "topup"},
    )
    return {"balance": main_balance, "utilityBalance": await get_utility_balance(db, user_id)}


async def debit(db: AsyncIOMotorDatabase, user_id: str, amount: float) -> bool:
    """Списание с «Электричество». False при нехватке — проверка условием в БД, без минуса."""
    amount = round(float(amount), 2)
    if amount <= 0:
        return True
    result = await db.utility_accounts.find_one_and_update(
        {"userId": str(user_id), "balance": {"$gte": amount}},
        {"$inc": {"balance": -amount}, "$set": {"updated_at": datetime.now(timezone.utc)}},
    )
    return result is not None


async def credit(db: AsyncIOMotorDatabase, user_id: str, amount: float) -> None:
    """Возврат с «Электричество» (откат неудачного пакетного списания)."""
    amount = round(float(amount), 2)
    if amount <= 0:
        return
    await db.utility_accounts.update_one(
        {"userId": str(user_id)},
        {"$inc": {"balance": amount}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
