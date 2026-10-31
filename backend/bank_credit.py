"""Кредиты и депозиты банка.

- Кредит: до 1 млрд и не более 5× капитала игрока. Выдаётся только если на
  счёте государства есть деньги. Проценты кредита уходят на счёт государства.
- Депозит: вклад из основного счёта, проценты (ставка deposit_rate в сутки)
  выплачиваются со счёта государства. Если там нет денег — начисление пропускается.

Ставки читаются из econ.get_econ, поэтому админка меняет их без перезапуска.
"""
from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator

from admin_perms import get_current_user, require_allowed
from database import get_db
from econ import get_econ
from ledger import EXPENSE, INCOME, adjust_balance, record_transaction
from networth import compute_net_worth
from state_bank import credit_state, debit_state, get_state_balance

router = APIRouter(prefix="/api/bank", tags=["bank"])

LOAN_MAX_AMOUNT = 1_000_000_000.0
LOAN_MAX_CAPITAL_MULT = 5.0
CAT_CREDIT = "credit"
CAT_DEPOSIT = "deposit"


class AmountIn(BaseModel):
    amount: float

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v):
        if v is None or v <= 0:
            raise ValueError("Сумма должна быть положительной")
        return round(float(v), 2)


async def _active_loans(db: AsyncIOMotorDatabase, user_id: str) -> list[dict]:
    return await db.bank_loans.find({"userId": user_id, "status": "active"}).to_list(length=None)


async def _active_deposits(db: AsyncIOMotorDatabase, user_id: str) -> list[dict]:
    return await db.bank_deposits.find({"userId": user_id, "status": "open"}).to_list(length=None)


async def _loan_overview(db: AsyncIOMotorDatabase, user_id: str) -> dict:
    econ = await get_econ(db)
    capital = await compute_net_worth(db, user_id)
    limit = min(LOAN_MAX_AMOUNT, capital * LOAN_MAX_CAPITAL_MULT)
    loans = await _active_loans(db, user_id)
    debt = round(sum(l["amount"] + l["interest"] for l in loans), 2)
    return {
        "capital": capital,
        "loanLimit": round(max(0.0, limit - debt), 2),
        "loanRate": econ["loan_rate"],
        "debt": debt,
        "loans": [{"id": str(l["_id"]), "amount": l["amount"], "interest": l["interest"],
                   "createdAt": l["createdAt"].isoformat()} for l in loans],
    }


@router.get("/credit/overview")
async def credit_overview(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    user_id = str(current_user["_id"])
    overview = await _loan_overview(db, user_id)
    overview["stateBalance"] = await get_state_balance(db)
    overview["depositRate"] = (await get_econ(db))["deposit_rate"]
    deposits = await _active_deposits(db, user_id)
    overview["deposits"] = [{"id": str(d["_id"]), "amount": d["amount"], "rate": d["rate"],
                             "openedAt": d["openedAt"].isoformat()} for d in deposits]
    return overview


@router.post("/credit/take", status_code=status.HTTP_201_CREATED)
async def take_loan(
    payload: AmountIn,
    current_user: dict = Depends(require_allowed("transfer")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    user_id = str(current_user["_id"])
    overview = await _loan_overview(db, user_id)
    if payload.amount > overview["loanLimit"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Лимит кредита: {overview['loanLimit']:.2f} $")

    interest = round(payload.amount * overview["loanRate"], 2)
    # Сначала резерв в банке государства: без денег на счёте выдача запрещена.
    if not await debit_state(db, payload.amount, CAT_CREDIT):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "В банке государства недостаточно средств для выдачи кредита")

    new_balance = await adjust_balance(db, user_id, payload.amount)
    if new_balance is None:
        await credit_state(db, payload.amount, CAT_CREDIT)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не удалось зачислить кредит")

    loan = {
        "userId": user_id, "amount": payload.amount, "interest": interest,
        "status": "active", "createdAt": datetime.now(timezone.utc),
    }
    result = await db.bank_loans.insert_one(loan)
    await record_transaction(
        db, user_id, INCOME, payload.amount, CAT_CREDIT,
        f"Кредит (проценты {interest:.2f} $)", balance_after=new_balance,
        meta={"loanId": str(result.inserted_id), "interest": interest},
    )
    return {"balance": new_balance, "loanId": str(result.inserted_id), "interest": interest}


@router.post("/credit/repay/{loan_id}")
async def repay_loan(
    loan_id: str,
    current_user: dict = Depends(require_allowed("transfer")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if not ObjectId.is_valid(loan_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Кредит не найден")
    user_id = str(current_user["_id"])
    loan = await db.bank_loans.find_one({"_id": ObjectId(loan_id), "userId": user_id, "status": "active"})
    if not loan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Кредит не найден")

    total = round(loan["amount"] + loan["interest"], 2)
    new_balance = await adjust_balance(db, user_id, -total)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств для погашения")

    # Проценты уходят государству; основной долг возвращается в банк государства.
    await credit_state(db, total, CAT_CREDIT)
    await db.bank_loans.update_one({"_id": loan["_id"]}, {"$set": {"status": "repaid"}})
    await record_transaction(
        db, user_id, EXPENSE, total, CAT_CREDIT, "Погашение кредита",
        balance_after=new_balance, meta={"loanId": loan_id},
    )
    return {"balance": new_balance, "repaid": total}


@router.post("/deposit/open", status_code=status.HTTP_201_CREATED)
async def open_deposit(
    payload: AmountIn,
    current_user: dict = Depends(require_allowed("transfer")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    user_id = str(current_user["_id"])
    econ = await get_econ(db)
    new_balance = await adjust_balance(db, user_id, -payload.amount)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

    deposit = {
        "userId": user_id, "amount": payload.amount, "rate": econ["deposit_rate"],
        "status": "open", "openedAt": datetime.now(timezone.utc), "lastAccrual": datetime.now(timezone.utc),
    }
    result = await db.bank_deposits.insert_one(deposit)
    await credit_state(db, payload.amount, CAT_DEPOSIT)
    await record_transaction(
        db, user_id, EXPENSE, payload.amount, CAT_DEPOSIT, "Открытие депозита",
        balance_after=new_balance, meta={"depositId": str(result.inserted_id)},
    )
    return {"balance": new_balance, "depositId": str(result.inserted_id)}


@router.post("/deposit/close/{deposit_id}")
async def close_deposit(
    deposit_id: str,
    current_user: dict = Depends(require_allowed("transfer")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if not ObjectId.is_valid(deposit_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Депозит не найден")
    user_id = str(current_user["_id"])
    dep = await db.bank_deposits.find_one({"_id": ObjectId(deposit_id), "userId": user_id, "status": "open"})
    if not dep:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Депозит не найден")

    await accrue_deposit(db, dep)
    dep = await db.bank_deposits.find_one({"_id": dep["_id"]})
    principal = round(dep["amount"], 2)
    payout = round(principal + dep.get("accrued", 0.0), 2)
    # Тело вклада уже лежало у государства; проценты списаны при начислении.
    if not await debit_state(db, principal, CAT_DEPOSIT):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "В банке государства недостаточно средств для закрытия депозита")
    new_balance = await adjust_balance(db, user_id, payout)
    if new_balance is None:
        await credit_state(db, principal, CAT_DEPOSIT)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не удалось вернуть депозит")
    await db.bank_deposits.update_one({"_id": dep["_id"]}, {"$set": {"status": "closed"}})
    await record_transaction(
        db, user_id, INCOME, payout, CAT_DEPOSIT, "Закрытие депозита",
        balance_after=new_balance, meta={"depositId": deposit_id},
    )
    return {"balance": new_balance, "payout": payout}


async def accrue_deposit(db: AsyncIOMotorDatabase, dep: dict) -> float:
    """Начисляет проценты по депозиту за прошедшие сутки; выплата — со счёта государства."""
    now = datetime.now(timezone.utc)
    last = dep.get("lastAccrual") or dep["openedAt"]
    days = int((now - last).total_seconds() // 86400)
    if days <= 0:
        return 0.0
    interest = round(dep["amount"] * dep["rate"] * days, 2)
    if interest <= 0:
        return 0.0
    if not await debit_state(db, interest, CAT_DEPOSIT):
        return 0.0
    await db.bank_deposits.update_one(
        {"_id": dep["_id"]},
        {"$inc": {"accrued": interest}, "$set": {"lastAccrual": now}},
    )
    return interest
