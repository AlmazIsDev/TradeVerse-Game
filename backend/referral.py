"""Реферальный бонус: когда приглашённый игрок достигает REFERRAL_TARGET_NET_WORTH,
реферер получает REFERRAL_BONUS. Деньги — только через ledger.

Выплата одноразовая: флаг referral_bonus_paid захватывается атомарно, поэтому
параллельные тики планировщика не начислят бонус дважды.
"""
from __future__ import annotations

import logging

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from ledger import INCOME, CAT_SYSTEM, adjust_balance, record_transaction
from networth import compute_net_worth

logger = logging.getLogger("tradeverse.referral")

REFERRAL_TARGET_NET_WORTH = 1_000_000_000.0
REFERRAL_BONUS = 100_000_000.0


async def pay_referral_bonuses(db: AsyncIOMotorDatabase) -> int:
    """Выплачивает бонусы по всем рефералам, достигшим цели. Возвращает число выплат."""
    paid = 0
    cursor = db.users.find(
        {"referrer_id": {"$ne": None}, "referral_bonus_paid": False},
        {"_id": 1, "username": 1, "referrer_id": 1},
    )
    async for invitee in cursor:
        invitee_id = str(invitee["_id"])
        net_worth = await compute_net_worth(db, invitee_id)
        if net_worth < REFERRAL_TARGET_NET_WORTH:
            continue
        claim = await db.users.update_one(
            {"_id": invitee["_id"], "referral_bonus_paid": False},
            {"$set": {"referral_bonus_paid": True}},
        )
        if claim.modified_count == 0:
            continue
        referrer_id = str(invitee["referrer_id"])
        balance_after = await adjust_balance(db, referrer_id, REFERRAL_BONUS)
        if balance_after is None:
            # Реферер удалён: возвращаем флаг, чтобы не потерять выплату при восстановлении.
            await db.users.update_one(
                {"_id": invitee["_id"]}, {"$set": {"referral_bonus_paid": False}}
            )
            continue
        await record_transaction(
            db,
            referrer_id,
            INCOME,
            REFERRAL_BONUS,
            CAT_SYSTEM,
            f"Реферальный бонус: {invitee.get('username', '')}",
            balance_after=balance_after,
            meta={"referralUserId": invitee_id},
        )
        paid += 1
        logger.info("referral bonus paid: referrer=%s invitee=%s", referrer_id, invitee_id)
    return paid
