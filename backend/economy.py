"""Экономика: переводы между игроками, история операций, аналитика."""
from __future__ import annotations

from typing import Optional

import logging

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator

from auth import get_current_user
from database import get_db
from ledger import (
    EXPENSE,
    INCOME,
    CAT_TRANSFER,
    adjust_balance,
    query_transactions,
    record_transaction,
    weekly_analytics,
)

router = APIRouter(prefix="/api", tags=["economy"])
logger = logging.getLogger("tradeverse.economy")


# ── Schemas ──────────────────────────────────────────────────────────────────


class TransferCreate(BaseModel):
    recipient: str          # username или номер карты получателя
    amount: float
    note: Optional[str] = None

    @field_validator("recipient")
    @classmethod
    def recipient_not_empty(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("Укажите получателя")
        return v

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v):
        if v is None or v <= 0:
            raise ValueError("Сумма должна быть положительной")
        if v > 1_000_000_000:
            raise ValueError("Слишком большая сумма")
        return round(float(v), 2)


# ── Transfers ────────────────────────────────────────────────────────────────


@router.post("/transfers", status_code=status.HTTP_201_CREATED)
async def create_transfer(
    payload: TransferCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Банковский перевод денег другому игроку.

    Проверки: получатель существует, нельзя себе, достаточно средств,
    сумма положительна. Обе стороны получают запись в реестре, баланс
    меняется атомарно.
    """
    sender_id = str(current_user["_id"])
    amount = payload.amount

    # Находим получателя по username или по номеру карты
    recipient = await db.users.find_one({
        "$or": [
            {"username": payload.recipient},
            {"card_number": payload.recipient},
        ]
    })
    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Получатель не найден",
        )

    recipient_id = str(recipient["_id"])
    if recipient_id == sender_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя перевести деньги самому себе",
        )

    # Атомарное списание с проверкой достаточности средств
    new_sender_balance = await adjust_balance(db, sender_id, -amount)
    if new_sender_balance is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Недостаточно средств",
        )

    # Зачисление получателю. Если упадёт — откатываем списание отправителю.
    try:
        new_recipient_balance = await adjust_balance(db, recipient_id, amount)
        if new_recipient_balance is None:
            raise RuntimeError("credit failed")
    except Exception:
        await adjust_balance(db, sender_id, amount)  # компенсация
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось выполнить перевод, средства возвращены",
        )

    note = (payload.note or "").strip()
    sender_label = f"Перевод → {recipient['username']}" + (f": {note}" if note else "")
    recipient_label = f"Перевод ← {current_user['username']}" + (f": {note}" if note else "")

    await record_transaction(
        db, sender_id, EXPENSE, amount, CAT_TRANSFER, sender_label,
        counterparty=recipient["username"], balance_after=new_sender_balance,
        meta={"note": note},
    )
    await record_transaction(
        db, recipient_id, INCOME, amount, CAT_TRANSFER, recipient_label,
        counterparty=current_user["username"], balance_after=new_recipient_balance,
        meta={"note": note},
    )

    logger.info(
        "Transfer %s -> %s: %.2f (sender balance %.2f)",
        current_user["username"], recipient["username"], amount, new_sender_balance,
    )

    return {
        "message": "Перевод выполнен",
        "amount": amount,
        "recipient": recipient["username"],
        "balance": new_sender_balance,
    }


# ── History ──────────────────────────────────────────────────────────────────


@router.get("/account/transactions")
async def get_my_transactions(
    direction: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort: str = Query("date_desc"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """История операций текущего пользователя (JWT-scoped).

    Поддерживает фильтр (direction/category), поиск, сортировку, пагинацию.
    """
    return await query_transactions(
        db, str(current_user["_id"]),
        direction=direction, category=category, search=search,
        sort=sort, skip=skip, limit=limit,
    )


@router.get("/account/analytics/weekly")
async def get_weekly_analytics(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Аналитика за неделю: доход, расход, изменение капитала, операции, график."""
    data = await weekly_analytics(db, str(current_user["_id"]))
    data["balance"] = current_user.get("balance", 0.0)
    return data
