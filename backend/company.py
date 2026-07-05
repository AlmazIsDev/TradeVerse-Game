"""Компании игроков: создание, сотрудники, зарплаты, бюджет, прибыль, история.

Модель прибыли: каждый сотрудник приносит выручку = зарплата × 1.5, значит
чистая прибыль в час = сумма(зарплата × 0.5). Прибыль копится и собирается
в бюджет компании; из бюджета владелец выводит деньги на личный баланс.
"""
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator

from auth import get_current_user
from database import get_db
from ledger import (
    INCOME, EXPENSE, CAT_COMPANY,
    adjust_balance, record_transaction, query_transactions,
)

router = APIRouter(prefix="/api/company", tags=["company"])

FOUNDING_FEE = 10000.0        # стоимость регистрации компании
PRODUCTIVITY_MULT = 1.5       # выручка сотрудника = зарплата × 1.5
MAX_ACCRUAL_HOURS = 24

ROLES = ["intern", "worker", "manager", "engineer", "director"]


# ── Schemas ──────────────────────────────────────────────────────────────────


class CompanyCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_valid(cls, v):
        v = (v or "").strip()
        if len(v) < 2:
            raise ValueError("Название компании слишком короткое")
        if len(v) > 40:
            raise ValueError("Название компании слишком длинное")
        return v


class EmployeeCreate(BaseModel):
    name: str
    role: str = "worker"
    salary: float

    @field_validator("name")
    @classmethod
    def name_ok(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("Укажите имя сотрудника")
        return v[:40]

    @field_validator("role")
    @classmethod
    def role_ok(cls, v):
        return v if v in ROLES else "worker"

    @field_validator("salary")
    @classmethod
    def salary_ok(cls, v):
        if v is None or v <= 0:
            raise ValueError("Зарплата должна быть положительной")
        if v > 1_000_000:
            raise ValueError("Слишком большая зарплата")
        return round(float(v), 2)


class SalaryUpdate(BaseModel):
    salary: float

    @field_validator("salary")
    @classmethod
    def salary_ok(cls, v):
        if v is None or v <= 0:
            raise ValueError("Зарплата должна быть положительной")
        return round(float(v), 2)


class AmountBody(BaseModel):
    amount: float

    @field_validator("amount")
    @classmethod
    def amount_ok(cls, v):
        if v is None or v <= 0:
            raise ValueError("Сумма должна быть положительной")
        return round(float(v), 2)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _employees(db, company_id) -> list[dict]:
    return [e async for e in db.company_employees.find({"companyId": str(company_id)})]


def _stats(employees: list[dict]) -> dict:
    payroll = sum(e.get("salary", 0) for e in employees)
    revenue = payroll * PRODUCTIVITY_MULT
    return {
        "revenuePerHour": round(revenue, 2),
        "payrollPerHour": round(payroll, 2),
        "profitPerHour": round(revenue - payroll, 2),
    }


def _accrued(company: dict, profit_per_hour: float) -> float:
    last = company.get("last_tick")
    if not isinstance(last, datetime):
        return 0.0
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    hours = min((_now() - last).total_seconds() / 3600.0, MAX_ACCRUAL_HOURS)
    return round(max(0.0, profit_per_hour * hours), 2)


async def _serialize(db, company: dict) -> dict:
    employees = await _employees(db, company["_id"])
    stats = _stats(employees)
    return {
        "id": str(company["_id"]),
        "name": company["name"],
        "budget": round(company.get("budget", 0.0), 2),
        "createdAt": company.get("created_at").isoformat() if isinstance(company.get("created_at"), datetime) else None,
        **stats,
        "accrued": _accrued(company, stats["profitPerHour"]),
        "employeeCount": len(employees),
        "employees": [
            {
                "id": str(e["_id"]),
                "name": e["name"],
                "role": e.get("role", "worker"),
                "salary": round(e.get("salary", 0.0), 2),
                "revenue": round(e.get("salary", 0.0) * PRODUCTIVITY_MULT, 2),
            }
            for e in employees
        ],
    }


async def _my_company(db, user_id):
    return await db.companies.find_one({"ownerId": user_id})


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("")
async def get_my_company(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Компания текущего игрока или {company: null}."""
    company = await _my_company(db, str(current_user["_id"]))
    if not company:
        return {"company": None, "foundingFee": FOUNDING_FEE, "roles": ROLES}
    return {"company": await _serialize(db, company), "roles": ROLES}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_company(
    payload: CompanyCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Создать компанию (списывается регистрационный сбор)."""
    user_id = str(current_user["_id"])
    if await _my_company(db, user_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "У вас уже есть компания")

    new_balance = await adjust_balance(db, user_id, -FOUNDING_FEE)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств для регистрации")

    doc = {
        "ownerId": user_id,
        "name": payload.name,
        "budget": 0.0,
        "created_at": _now(),
        "last_tick": _now(),
    }
    result = await db.companies.insert_one(doc)
    doc["_id"] = result.inserted_id
    await record_transaction(
        db, user_id, EXPENSE, FOUNDING_FEE, CAT_COMPANY,
        f"Регистрация компании «{payload.name}»", balance_after=new_balance,
    )
    return {"company": await _serialize(db, doc), "balance": new_balance}


async def _require_company(db, user_id):
    company = await _my_company(db, user_id)
    if not company:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "У вас нет компании")
    return company


@router.post("/employees", status_code=status.HTTP_201_CREATED)
async def hire_employee(
    payload: EmployeeCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Нанять сотрудника."""
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    await db.company_employees.insert_one({
        "companyId": str(company["_id"]),
        "name": payload.name,
        "role": payload.role,
        "salary": payload.salary,
        "hired_at": _now(),
    })
    return {"company": await _serialize(db, company)}


@router.patch("/employees/{emp_id}")
async def update_salary(
    emp_id: str,
    payload: SalaryUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Изменить зарплату сотрудника."""
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    if not ObjectId.is_valid(emp_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID")
    res = await db.company_employees.update_one(
        {"_id": ObjectId(emp_id), "companyId": str(company["_id"])},
        {"$set": {"salary": payload.salary}},
    )
    if res.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    return {"company": await _serialize(db, company)}


@router.delete("/employees/{emp_id}")
async def fire_employee(
    emp_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Уволить сотрудника."""
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    if not ObjectId.is_valid(emp_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID")
    res = await db.company_employees.delete_one(
        {"_id": ObjectId(emp_id), "companyId": str(company["_id"])}
    )
    if res.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    return {"company": await _serialize(db, company)}


@router.post("/collect")
async def collect_profit(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Зачислить накопленную прибыль в бюджет компании."""
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    employees = await _employees(db, company["_id"])
    stats = _stats(employees)
    amount = _accrued(company, stats["profitPerHour"])
    await db.companies.update_one(
        {"_id": company["_id"]},
        {"$set": {"last_tick": _now()}, "$inc": {"budget": amount}},
    )
    updated = await db.companies.find_one({"_id": company["_id"]})
    return {"collected": amount, "company": await _serialize(db, updated)}


@router.post("/deposit")
async def deposit_to_budget(
    payload: AmountBody,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Пополнить бюджет компании с личного баланса."""
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    new_balance = await adjust_balance(db, user_id, -payload.amount)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
    await db.companies.update_one({"_id": company["_id"]}, {"$inc": {"budget": payload.amount}})
    await record_transaction(
        db, user_id, EXPENSE, payload.amount, CAT_COMPANY,
        f"Пополнение бюджета «{company['name']}»", balance_after=new_balance,
    )
    updated = await db.companies.find_one({"_id": company["_id"]})
    return {"balance": new_balance, "company": await _serialize(db, updated)}


@router.post("/withdraw")
async def withdraw_from_budget(
    payload: AmountBody,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Вывести прибыль из бюджета компании на личный баланс."""
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    updated = await db.companies.find_one_and_update(
        {"_id": company["_id"], "budget": {"$gte": payload.amount}},
        {"$inc": {"budget": -payload.amount}},
        return_document=True,
    )
    if not updated:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств в бюджете")
    new_balance = await adjust_balance(db, user_id, payload.amount)
    await record_transaction(
        db, user_id, INCOME, payload.amount, CAT_COMPANY,
        f"Вывод прибыли «{company['name']}»", balance_after=new_balance,
    )
    return {"balance": new_balance, "company": await _serialize(db, updated)}


@router.get("/history")
async def company_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """История операций компании игрока."""
    return await query_transactions(
        db, str(current_user["_id"]),
        category=CAT_COMPANY, sort="date_desc", skip=skip, limit=limit,
    )
