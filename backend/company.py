"""Компании игроков: создание, приглашения сотрудников (с согласия), зарплаты,
бюджет, прибыль из реальных источников, история.

Ключевые принципы (исправление логических ошибок):
- Сотрудник добавляется ТОЛЬКО после принятия приглашения (consent).
- Прибыль НЕ берётся из воздуха: доход компании = чистый доход принадлежащих
  ей активов (бизнесы/недвижимость, переданные владельцем). Зарплаты
  выплачиваются реальным игрокам-сотрудникам из бюджета компании.
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator

from auth import get_current_user, require_admin
from database import get_db
from ledger import (
    INCOME, EXPENSE, CAT_COMPANY, CAT_DIVIDEND, CAT_TRADE,
    adjust_balance, record_transaction, query_transactions,
)
from assets import company_income_per_hour, list_company_assets
from notifications import push_notification
from econ import get_econ

router = APIRouter(prefix="/api/company", tags=["company"])

FOUNDING_FEE = 10000.0
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


class CompanySettings(BaseModel):
    """Настройки компании (все поля опциональны — обновляем только присланные)."""
    name: Optional[str] = None
    description: Optional[str] = None
    logo: Optional[str] = None
    isOpen: Optional[bool] = None
    visibleInSearch: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def name_valid(cls, v):
        if v is None:
            return v
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Название компании слишком короткое")
        if len(v) > 40:
            raise ValueError("Название компании слишком длинное")
        return v

    @field_validator("description")
    @classmethod
    def desc_valid(cls, v):
        if v is None:
            return v
        v = v.strip()
        if len(v) > 200:
            raise ValueError("Описание слишком длинное")
        return v

    @field_validator("logo")
    @classmethod
    def logo_valid(cls, v):
        if v is None:
            return v
        v = v.strip()
        if len(v) > 300:
            raise ValueError("Слишком длинная ссылка на логотип")
        return v


class InviteCreate(BaseModel):
    username: str
    role: str = "worker"
    salary: float

    @field_validator("username")
    @classmethod
    def uname_ok(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("Укажите игрока")
        return v

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


class OwnerSalaryUpdate(BaseModel):
    """Зарплата владельца: допускается 0 (отключить выплату себе)."""
    salary: float

    @field_validator("salary")
    @classmethod
    def salary_ok(cls, v):
        if v is None or v < 0:
            raise ValueError("Зарплата не может быть отрицательной")
        if v > 1_000_000:
            raise ValueError("Слишком большая зарплата")
        return round(float(v), 2)


class AmountBody(BaseModel):
    amount: float

    @field_validator("amount")
    @classmethod
    def amount_ok(cls, v):
        if v is None or v <= 0:
            raise ValueError("Сумма должна быть положительной")
        return round(float(v), 2)


class AdminCompanyUpdate(BaseModel):
    """Правки компании администратором — без ограничений, действующих на владельца."""
    name: Optional[str] = None
    budget: Optional[float] = None
    isOpen: Optional[bool] = None
    visibleInSearch: Optional[bool] = None


class AdminTransferBody(BaseModel):
    toUsername: str


class CompanyIpo(BaseModel):
    symbol: str
    totalShares: int

    @field_validator("symbol")
    @classmethod
    def symbol_ok(cls, v):
        v = (v or "").strip().upper()
        if not (1 <= len(v) <= 6) or not v.isalnum():
            raise ValueError("Тикер: 1–6 латинских букв/цифр")
        return v

    @field_validator("totalShares")
    @classmethod
    def shares_ok(cls, v):
        if v < 1000 or v > 10_000_000_000:
            raise ValueError("Количество акций: 1 000 – 10 млрд")
        return int(v)


class CompanyDividend(BaseModel):
    perShare: float

    @field_validator("perShare")
    @classmethod
    def per_ok(cls, v):
        if v is None or v <= 0:
            raise ValueError("Дивиденд на акцию должен быть положительным")
        return round(float(v), 4)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _members(db, company_id) -> list[dict]:
    return [m async for m in db.company_members.find({"companyId": str(company_id)})]


def _hours_since(company: dict) -> float:
    last = company.get("last_tick")
    if not isinstance(last, datetime):
        return 0.0
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return min((_now() - last).total_seconds() / 3600.0, MAX_ACCRUAL_HOURS)


async def _serialize(db, company: dict, viewer_id: str = None) -> dict:
    cid = str(company["_id"])
    members = await _members(db, cid)
    assets = await list_company_assets(db, cid)
    # Репутационный множитель СМИ владельца — доход бизнесов компании отражает кризис.
    try:
        from media import active_owner_income_factor
        media_factor = await active_owner_income_factor(db, company["ownerId"])
    except Exception:
        media_factor = 1.0
    revenue = await company_income_per_hour(db, cid, media_factor)   # реальный доход от активов
    owner_salary = round(company.get("owner_salary", 0.0), 2)
    payroll = round(sum(m.get("salary", 0) for m in members) + owner_salary, 2)
    hours = _hours_since(company)
    owner_id = company["ownerId"]
    is_owner = viewer_id is not None and viewer_id == owner_id
    viewer_role = "owner" if is_owner else next(
        (m.get("role", "worker") for m in members if m["userId"] == viewer_id), None
    )
    owner_user = await db.users.find_one({"_id": ObjectId(owner_id)}) if ObjectId.is_valid(owner_id) else None

    # Биржевая акция компании (если размещена) — для секции «Акции компании».
    stock_info = None
    symbol = company.get("stockSymbol")
    if symbol:
        st = await db.stocks.find_one({"symbol": symbol})
        if st:
            cfg_total = (st.get("config") or {}).get("total_shares", 0)
            price = float(st.get("price", 0.0))
            stock_info = {
                "symbol": symbol,
                "price": round(price, 2),
                "changePercent": round(st.get("changePercent", 0.0), 2),
                "totalShares": cfg_total,
                "freeShares": st.get("free_shares", cfg_total),
                "marketCap": round(price * cfg_total, 2),
            }

    # Живой username/avatar по userId — не полагаемся на снапшот-поле "username"
    # в company_members (оно устаревает после смены никнейма в Настройках), а
    # avatar там и вовсе никогда не хранился.
    member_ids = [ObjectId(m["userId"]) for m in members if ObjectId.is_valid(m["userId"])]
    users_by_id: dict = {}
    if member_ids:
        async for u in db.users.find({"_id": {"$in": member_ids}}, {"username": 1, "avatar": 1}):
            users_by_id[str(u["_id"])] = u

    display_members = [
        {"id": owner_id, "userId": owner_id,
         "username": owner_user.get("username") if owner_user else "—",
         "avatar": owner_user.get("avatar") if owner_user else None,
         "role": "owner", "salary": owner_salary},
        *[
            {"id": str(m["_id"]), "userId": m["userId"],
             "username": users_by_id.get(m["userId"], {}).get("username", m.get("username")),
             "avatar": users_by_id.get(m["userId"], {}).get("avatar"),
             "role": m.get("role", "worker"), "salary": round(m.get("salary", 0.0), 2)}
            for m in members
        ],
    ]
    return {
        "id": cid,
        "name": company["name"],
        "description": company.get("description", ""),
        "logo": company.get("logo", ""),
        "isOpen": company.get("isOpen", True),
        "visibleInSearch": company.get("visibleInSearch", True),
        "budget": round(company.get("budget", 0.0), 2),
        "createdAt": company.get("created_at").isoformat() if isinstance(company.get("created_at"), datetime) else None,
        "revenuePerHour": revenue,
        "payrollPerHour": payroll,
        "ownerSalary": owner_salary,
        "reputationFactor": media_factor,
        "profitPerHour": round(revenue - payroll, 2),
        "accrued": round(revenue * hours, 2),
        "memberCount": len(members) + 1,
        "assetCount": len(assets),
        "ownerId": owner_id,
        "ownerName": owner_user.get("username") if owner_user else None,
        "stock": stock_info,
        "isOwner": is_owner,
        "viewerRole": viewer_role,
        "members": display_members,
        "assets": assets,
    }


async def _my_company(db, user_id):
    """Компания, которой владеет игрок (для операций управления — только владелец)."""
    return await db.companies.find_one({"ownerId": user_id})


async def _my_company_or_membership(db, user_id):
    """Компания игрока — как владельца, так и как сотрудника (для чтения)."""
    company = await _my_company(db, user_id)
    if company:
        return company
    member = await db.company_members.find_one({"userId": user_id})
    if member and ObjectId.is_valid(member["companyId"]):
        return await db.companies.find_one({"_id": ObjectId(member["companyId"])})
    return None


async def _require_company(db, user_id):
    company = await _my_company(db, user_id)
    if not company:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "У вас нет компании")
    return company


# ── Company CRUD ─────────────────────────────────────────────────────────────


@router.get("")
async def get_my_company(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    user_id = str(current_user["_id"])
    company = await _my_company_or_membership(db, user_id)
    if not company:
        return {"company": None, "foundingFee": FOUNDING_FEE, "roles": ROLES}
    return {"company": await _serialize(db, company, user_id), "roles": ROLES}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_company(
    payload: CompanyCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    user_id = str(current_user["_id"])
    if await _my_company(db, user_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "У вас уже есть компания")
    new_balance = await adjust_balance(db, user_id, -FOUNDING_FEE)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств для регистрации")
    doc = {"ownerId": user_id, "name": payload.name, "budget": 0.0,
           "description": "", "logo": "", "isOpen": True, "visibleInSearch": True,
           "created_at": _now(), "last_tick": _now()}
    result = await db.companies.insert_one(doc)
    doc["_id"] = result.inserted_id
    await record_transaction(
        db, user_id, EXPENSE, FOUNDING_FEE, CAT_COMPANY,
        f"Регистрация компании «{payload.name}»", balance_after=new_balance,
        meta={"companyId": str(doc["_id"])},
    )
    return {"company": await _serialize(db, doc, user_id), "balance": new_balance}


@router.patch("")
async def update_company(
    payload: CompanySettings,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Изменить настройки компании (только владелец)."""
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    updates = {}
    for field in ("name", "description", "logo", "isOpen", "visibleInSearch"):
        val = getattr(payload, field)
        if val is not None:
            updates[field] = val
    if updates:
        await db.companies.update_one({"_id": company["_id"]}, {"$set": updates})
    updated = await db.companies.find_one({"_id": company["_id"]})
    return {"company": await _serialize(db, updated, user_id)}


async def _disband(db: AsyncIOMotorDatabase, company: dict):
    """Распустить компанию: активы возвращаются владельцу, сотрудники уведомляются,
    все приглашения/заявки/сотрудники удаляются. Общая логика для владельца и админа."""
    cid = str(company["_id"])
    name = company["name"]

    members = await _members(db, cid)
    for m in members:
        await push_notification(
            db, m["userId"], "company", "Компания распущена",
            f"Компания «{name}» была распущена. Вы больше не сотрудник.",
            data={"companyId": cid},
        )

    await db.user_assets.update_many({"companyId": cid}, {"$set": {"companyId": None}})

    # Делистинг акции компании: замораживаем и удаляем тикер с биржи. Держателям
    # выкупаем позиции по последней цене из бюджета (если хватает) — иначе просто
    # снимаем акцию (позиции обесцениваются вместе с исчезнувшей компанией).
    symbol = company.get("stockSymbol")
    if symbol:
        st = await db.stocks.find_one({"symbol": symbol})
        if st:
            price = float(st.get("price", 0.0))
            budget = company.get("budget", 0.0)
            async for h in db.stock_holdings.find({"symbol": symbol, "quantity": {"$gt": 0}}):
                qty = h.get("quantity", 0)
                payout = round(price * qty, 2)
                if payout > 0 and budget >= payout and h["userId"] != company["ownerId"]:
                    budget -= payout
                    hb = await adjust_balance(db, h["userId"], payout)
                    await record_transaction(
                        db, h["userId"], INCOME, payout, CAT_DIVIDEND,
                        f"Делистинг {symbol}", symbol=symbol, balance_after=hb,
                        meta={"companyId": cid, "kind": "delisting"},
                    )
            await db.stock_holdings.delete_many({"symbol": symbol})
            await db.stocks.delete_one({"symbol": symbol})

    await db.company_debuffs.delete_many({"companyId": cid})

    await db.company_members.delete_many({"companyId": cid})
    await db.company_invites.delete_many({"companyId": cid})
    await db.company_applications.delete_many({"companyId": cid})
    await db.companies.delete_one({"_id": company["_id"]})


@router.delete("")
async def disband_company(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Распустить компанию (только владелец). Необратимо."""
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    await _disband(db, company)
    return {"ok": True}


# ── Invitations (consent-based hiring) ───────────────────────────────────────


@router.post("/invite", status_code=status.HTTP_201_CREATED)
async def invite_employee(
    payload: InviteCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Пригласить игрока в компанию (он должен принять приглашение)."""
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    cid = str(company["_id"])

    target = await db.users.find_one({"username": payload.username})
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Игрок не найден")
    tid = str(target["_id"])
    if tid == user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя пригласить самого себя")
    if await db.company_members.find_one({"userId": tid}):
        raise HTTPException(status.HTTP_409_CONFLICT, "Игрок уже работает в компании")
    if await db.company_invites.find_one({"companyId": cid, "toUserId": tid, "status": "pending"}):
        raise HTTPException(status.HTTP_409_CONFLICT, "Приглашение уже отправлено")

    invite = {
        "companyId": cid, "companyName": company["name"],
        "ownerId": user_id, "ownerName": current_user.get("username"),
        "toUserId": tid, "role": payload.role, "salary": payload.salary,
        "status": "pending", "created_at": _now(),
    }
    result = await db.company_invites.insert_one(invite)
    await push_notification(
        db, tid, "company_invite",
        f"Приглашение в «{company['name']}»",
        f"{current_user.get('username')} зовёт вас на роль «{payload.role}» "
        f"с зарплатой ${payload.salary:.2f}/ч.",
        data={"inviteId": str(result.inserted_id), "companyName": company["name"],
              "role": payload.role, "salary": payload.salary},
    )
    return {"ok": True, "inviteId": str(result.inserted_id)}


@router.get("/invites")
async def my_invites(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Входящие приглашения текущего игрока."""
    uid = str(current_user["_id"])
    out = []
    async for inv in db.company_invites.find({"toUserId": uid, "status": "pending"}).sort("created_at", -1):
        out.append({
            "id": str(inv["_id"]), "companyName": inv.get("companyName"),
            "ownerName": inv.get("ownerName"), "role": inv.get("role"),
            "salary": inv.get("salary"),
        })
    return out


async def _load_invite(db, invite_id, user_id):
    if not ObjectId.is_valid(invite_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID")
    inv = await db.company_invites.find_one({"_id": ObjectId(invite_id)})
    if not inv or inv.get("toUserId") != user_id or inv.get("status") != "pending":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Приглашение не найдено")
    return inv


@router.post("/invites/{invite_id}/accept")
async def accept_invite(
    invite_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Принять приглашение — стать сотрудником компании."""
    uid = str(current_user["_id"])
    inv = await _load_invite(db, invite_id, uid)
    if await db.company_members.find_one({"userId": uid}):
        raise HTTPException(status.HTTP_409_CONFLICT, "Вы уже работаете в компании")
    await db.company_members.insert_one({
        "companyId": inv["companyId"], "userId": uid,
        "username": current_user.get("username"),
        "role": inv.get("role", "worker"), "salary": inv.get("salary", 0.0),
        "joined_at": _now(),
    })
    await db.company_invites.update_one({"_id": inv["_id"]}, {"$set": {"status": "accepted"}})
    await push_notification(
        db, inv["ownerId"], "company",
        "Приглашение принято",
        f"{current_user.get('username')} вступил в «{inv.get('companyName')}».",
        data={"companyId": inv["companyId"]},
    )
    return {"ok": True}


@router.post("/invites/{invite_id}/decline")
async def decline_invite(
    invite_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Отклонить приглашение."""
    uid = str(current_user["_id"])
    inv = await _load_invite(db, invite_id, uid)
    await db.company_invites.update_one({"_id": inv["_id"]}, {"$set": {"status": "declined"}})
    await push_notification(
        db, inv["ownerId"], "company",
        "Приглашение отклонено",
        f"{current_user.get('username')} отклонил приглашение в «{inv.get('companyName')}».",
        data={"companyId": inv["companyId"]},
    )
    return {"ok": True}


@router.get("/my-jobs")
async def my_jobs(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Компании, где текущий игрок работает сотрудником."""
    uid = str(current_user["_id"])
    out = []
    async for m in db.company_members.find({"userId": uid}):
        comp = await db.companies.find_one({"_id": ObjectId(m["companyId"])}) if ObjectId.is_valid(m["companyId"]) else None
        out.append({
            "companyId": m["companyId"],
            "companyName": comp["name"] if comp else "—",
            "role": m.get("role"), "salary": round(m.get("salary", 0.0), 2),
        })
    return out


@router.patch("/members/{member_user_id}")
async def update_salary(
    member_user_id: str,
    payload: SalaryUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Изменить зарплату сотрудника (владелец)."""
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    res = await db.company_members.update_one(
        {"companyId": str(company["_id"]), "userId": member_user_id},
        {"$set": {"salary": payload.salary}},
    )
    if res.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    return {"company": await _serialize(db, company, user_id)}


@router.patch("/owner-salary")
async def update_owner_salary(
    payload: OwnerSalaryUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Установить/изменить зарплату владельца (платится из бюджета при сборе прибыли)."""
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    await db.companies.update_one(
        {"_id": company["_id"]}, {"$set": {"owner_salary": payload.salary}}
    )
    updated = await db.companies.find_one({"_id": company["_id"]})
    return {"company": await _serialize(db, updated, user_id)}


@router.delete("/members/{member_user_id}")
async def fire_member(
    member_user_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Уволить сотрудника (владелец)."""
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    res = await db.company_members.delete_one(
        {"companyId": str(company["_id"]), "userId": member_user_id}
    )
    if res.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    await push_notification(
        db, member_user_id, "company",
        "Увольнение", f"Вы больше не работаете в «{company['name']}».",
        data={"companyId": str(company["_id"])},
    )
    return {"company": await _serialize(db, company, user_id)}


@router.post("/leave")
async def leave_company(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Уйти из компании самостоятельно (сотрудник; владелец должен распустить компанию)."""
    user_id = str(current_user["_id"])
    member = await db.company_members.find_one({"userId": user_id})
    if not member:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вы не состоите в компании")
    company = await db.companies.find_one({"_id": ObjectId(member["companyId"])}) if ObjectId.is_valid(member["companyId"]) else None
    await db.company_members.delete_one({"_id": member["_id"]})
    if company:
        await push_notification(
            db, company["ownerId"], "company",
            "Сотрудник ушёл", f"{current_user.get('username')} покинул «{company['name']}».",
            data={"companyId": str(company["_id"])},
        )
    return {"ok": True}


# ── Companies directory + applications (заявки игроков) ──────────────────────


@router.get("/list")
async def list_companies(
    search: str = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Каталог компаний: поиск, число сотрудников, капитал. Для подачи заявок."""
    uid = str(current_user["_id"])
    # Скрытые из поиска компании не показываем (кроме собственной).
    query: dict = {"$or": [{"visibleInSearch": {"$ne": False}}, {"ownerId": uid}]}
    if search:
        query["name"] = {"$regex": search, "$options": "i"}
    out = []
    async for c in db.companies.find(query).limit(60):
        cid = str(c["_id"])
        members = await db.company_members.count_documents({"companyId": cid})
        assets = await list_company_assets(db, cid)
        capital = round(c.get("budget", 0.0) + sum(a["value"] for a in assets), 2)
        owner = await db.users.find_one({"_id": ObjectId(c["ownerId"])}, {"username": 1}) if ObjectId.is_valid(c["ownerId"]) else None
        applied = await db.company_applications.find_one(
            {"companyId": cid, "applicantId": uid, "status": "pending"}
        ) is not None
        out.append({
            "id": cid, "name": c["name"],
            "ownerName": owner.get("username") if owner else "—",
            "memberCount": members, "assetCount": len(assets),
            "capital": capital, "revenuePerHour": await company_income_per_hour(db, cid),
            "isMine": c.get("ownerId") == uid, "applied": applied,
            "isOpen": c.get("isOpen", True), "logo": c.get("logo", ""),
        })
    out.sort(key=lambda x: x["capital"], reverse=True)
    return out


@router.post("/apply/{company_id}")
async def apply_to_company(
    company_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Подать заявку на вступление в компанию (руководитель одобряет/отклоняет)."""
    uid = str(current_user["_id"])
    if not ObjectId.is_valid(company_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID")
    company = await db.companies.find_one({"_id": ObjectId(company_id)})
    if not company:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Компания не найдена")
    if company.get("ownerId") == uid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Это ваша компания")
    if not company.get("isOpen", True):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Компания закрыта для заявок")
    if await db.company_members.find_one({"userId": uid}):
        raise HTTPException(status.HTTP_409_CONFLICT, "Вы уже работаете в компании")
    if await db.company_applications.find_one({"companyId": company_id, "applicantId": uid, "status": "pending"}):
        raise HTTPException(status.HTTP_409_CONFLICT, "Заявка уже отправлена")

    result = await db.company_applications.insert_one({
        "companyId": company_id, "companyName": company["name"],
        "ownerId": company["ownerId"], "applicantId": uid,
        "applicantName": current_user.get("username"),
        "status": "pending", "created_at": _now(),
    })
    await push_notification(
        db, company["ownerId"], "company_application",
        f"Заявка в «{company['name']}»",
        f"{current_user.get('username')} хочет вступить в вашу компанию.",
        data={"applicationId": str(result.inserted_id), "applicantName": current_user.get("username")},
    )
    return {"ok": True}


@router.get("/applications")
async def my_applications(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Входящие заявки в компанию текущего игрока (он — руководитель)."""
    company = await _my_company(db, str(current_user["_id"]))
    if not company:
        return []
    out = []
    async for a in db.company_applications.find({"companyId": str(company["_id"]), "status": "pending"}).sort("created_at", -1):
        out.append({"id": str(a["_id"]), "applicantName": a.get("applicantName")})
    return out


async def _load_application(db, app_id, owner_id):
    if not ObjectId.is_valid(app_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID")
    app = await db.company_applications.find_one({"_id": ObjectId(app_id)})
    if not app or app.get("ownerId") != owner_id or app.get("status") != "pending":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    return app


@router.post("/applications/{app_id}/accept")
async def accept_application(
    app_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Принять заявку — игрок становится сотрудником (базовая зарплата, редактируется)."""
    owner_id = str(current_user["_id"])
    company = await _require_company(db, owner_id)
    app = await _load_application(db, app_id, owner_id)
    applicant_id = app["applicantId"]
    if await db.company_members.find_one({"userId": applicant_id}):
        await db.company_applications.update_one({"_id": app["_id"]}, {"$set": {"status": "declined"}})
        raise HTTPException(status.HTTP_409_CONFLICT, "Игрок уже в другой компании")
    await db.company_members.insert_one({
        "companyId": str(company["_id"]), "userId": applicant_id,
        "username": app.get("applicantName"), "role": "worker",
        "salary": 100.0, "joined_at": _now(),
    })
    await db.company_applications.update_one({"_id": app["_id"]}, {"$set": {"status": "accepted"}})
    await push_notification(
        db, applicant_id, "company", "Заявка одобрена",
        f"Вы приняты в «{company['name']}».", data={"companyId": str(company["_id"])},
    )
    return {"ok": True}


@router.post("/applications/{app_id}/decline")
async def decline_application(
    app_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    owner_id = str(current_user["_id"])
    await _require_company(db, owner_id)
    app = await _load_application(db, app_id, owner_id)
    await db.company_applications.update_one({"_id": app["_id"]}, {"$set": {"status": "declined"}})
    await push_notification(
        db, app["applicantId"], "company", "Заявка отклонена",
        f"Заявка в «{app.get('companyName')}» отклонена.",
    )
    return {"ok": True}


# ── Finance ──────────────────────────────────────────────────────────────────


@router.post("/collect")
async def collect_profit(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Начислить реальный доход от активов компании в бюджет и выплатить зарплаты.

    Доход берётся ИСКЛЮЧИТЕЛЬНО из активов компании (никакой генерации из воздуха).
    Зарплаты выплачиваются реальным игрокам-сотрудникам из бюджета.
    """
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    cid = str(company["_id"])

    # Атомарно «присваиваем» интервал начисления: сбрасываем last_tick на now
    # условным апдейтом по прочитанному значению. Два параллельных запроса
    # прочитают один last_tick, но апдейт сработает лишь у одного — второй
    # получит modified_count=0 и выйдет. Иначе оба выплатили бы зарплату всем
    # сотрудникам (TOCTOU-дублирование выплат).
    seen_tick = company.get("last_tick")
    claim = await db.companies.update_one(
        {"_id": company["_id"], "last_tick": seen_tick},
        {"$set": {"last_tick": _now()}},
    )
    if claim.modified_count == 0:
        updated = await db.companies.find_one({"_id": company["_id"]})
        return {"collected": 0.0, "payrollPaid": 0.0, "company": await _serialize(db, updated, user_id)}

    hours = _hours_since(company)
    # Репутационный множитель СМИ владельца бьёт по доходной части бизнесов компании.
    try:
        from media import active_owner_income_factor
        media_factor = await active_owner_income_factor(db, user_id)
    except Exception:
        media_factor = 1.0
    revenue_per_h = await company_income_per_hour(db, cid, media_factor)
    econ = await get_econ(db)
    gross = round(revenue_per_h * hours * econ.get("income_mult", 1.0) * econ.get("economy_mult", 1.0), 2)
    # Бонус зданий «Крыши города»: +% к доходу компании (напр. «Бизнес-башня», «Городской банк»).
    try:
        from cityroof import player_city_effect
        city_bonus = await player_city_effect(db, user_id, "company_income")
        if city_bonus:
            gross = round(gross * (1 + city_bonus), 2)
    except Exception:
        pass

    members = await _members(db, cid)
    members = await _members(db, cid)
    owner_salary = round(company.get("owner_salary", 0.0), 2)
    # ФОТ = зарплаты сотрудников + зарплата владельца (владелец платит её себе из
    # бюджета компании, ровно как сотрудникам). Список выплат единый.
    payouts = [(m["userId"], m.get("salary", 0)) for m in members]
    if owner_salary > 0:
        payouts.append((user_id, owner_salary))
    payroll_per_h = sum(s for _, s in payouts)
    payroll_due = round(payroll_per_h * hours, 2)

    # Бюджет после дохода — для проверки, хватает ли на зарплаты. Обновляем его
    # атомарными $inc-дельтами (доход, потом вычет ФОТ), а не $set из stale-чтения,
    # чтобы параллельный deposit/withdraw ($inc) не терялся.
    budget_after_gross = round(company.get("budget", 0.0) + gross, 2)
    paid = 0.0
    if payroll_due > 0 and budget_after_gross >= payroll_due:
        for member_id, salary in payouts:
            amt = round(salary * hours, 2)
            if amt <= 0:
                continue
            mb = await adjust_balance(db, member_id, amt)
            await record_transaction(
                db, member_id, INCOME, amt, CAT_COMPANY,
                f"Зарплата: {company['name']}", balance_after=mb,
                meta={"companyId": cid},
            )
            await push_notification(
                db, member_id, "salary", "Зарплата начислена",
                f"«{company['name']}» выплатила ${amt:.2f}.", data={"companyId": cid},
            )
        paid = payroll_due

    budget_delta = round(gross - paid, 2)
    if budget_delta:
        await db.companies.update_one(
            {"_id": company["_id"]},
            {"$inc": {"budget": budget_delta}},
        )
    updated = await db.companies.find_one({"_id": company["_id"]})
    return {"collected": gross, "payrollPaid": paid, "company": await _serialize(db, updated, user_id)}


@router.post("/deposit")
async def deposit_to_budget(
    payload: AmountBody,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    new_balance = await adjust_balance(db, user_id, -payload.amount)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
    await db.companies.update_one({"_id": company["_id"]}, {"$inc": {"budget": payload.amount}})
    await record_transaction(
        db, user_id, EXPENSE, payload.amount, CAT_COMPANY,
        f"Пополнение бюджета «{company['name']}»", balance_after=new_balance,
        meta={"companyId": str(company["_id"])},
    )
    updated = await db.companies.find_one({"_id": company["_id"]})
    return {"balance": new_balance, "company": await _serialize(db, updated, user_id)}


@router.post("/withdraw")
async def withdraw_from_budget(
    payload: AmountBody,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
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
        meta={"companyId": str(company["_id"])},
    )
    return {"balance": new_balance, "company": await _serialize(db, updated, user_id)}


async def _company_capital(db, company: dict) -> float:
    """Капитал компании = бюджет + суммарная стоимость её активов.

    Служит фундаменталом для цены акции («как в жизни»): цена = капитал / выпуск."""
    cid = str(company["_id"])
    assets = await list_company_assets(db, cid)
    return round(company.get("budget", 0.0) + sum(a["value"] for a in assets), 2)


# ── Company shares (IPO / дивиденды) ─────────────────────────────────────────

LISTING_FEE = 5000.0        # листинговый сбор (из бюджета компании)
FOUNDER_SHARE_PCT = 0.2     # доля владельца при размещении (оплачивается бюджетом)


@router.post("/ipo", status_code=status.HTTP_201_CREATED)
async def company_ipo(
    payload: CompanyIpo,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Разместить акцию компании на бирже (IPO).

    Стартовая цена = капитал / выпуск (фундаментал). Листинговый сбор и доля
    основателя оплачиваются ИЗ БЮДЖЕТА компании — каждая акция обеспечена реальными
    деньгами (см. economy-integrity: cash-backed shares). Тикер привязан к компании
    (companyId), поэтому цена в дальнейшем дрейфует к капиталу (stocks.maintain)."""
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    cid = str(company["_id"])

    if company.get("stockSymbol"):
        raise HTTPException(status.HTTP_409_CONFLICT, "У компании уже размещена акция")
    symbol = payload.symbol
    if await db.stocks.find_one({"symbol": symbol}):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Тикер «{symbol}» уже занят")

    capital = await _company_capital(db, company)
    if capital <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Нулевой капитал: пополните бюджет или передайте активы компании")
    price = round(max(0.01, capital / payload.totalShares), 2)

    founder_shares = int(payload.totalShares * FOUNDER_SHARE_PCT)
    free_shares = payload.totalShares - founder_shares
    founder_cost = round(founder_shares * price, 2)
    total_charge = round(LISTING_FEE + founder_cost, 2)

    # Оплата из бюджета — атомарно, с проверкой достаточности (не $set из stale-чтения).
    paid = await db.companies.find_one_and_update(
        {"_id": company["_id"], "budget": {"$gte": total_charge}, "stockSymbol": {"$exists": False}},
        {"$inc": {"budget": -total_charge}, "$set": {"stockSymbol": symbol}},
        return_document=True,
    )
    if not paid:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Недостаточно в бюджете: листинг ${LISTING_FEE:,.0f} + доля основателя ${founder_cost:,.0f}",
        )

    doc = {
        "symbol": symbol,
        "name": company["name"],
        "description": company.get("description", "")[:280],
        "price": price,
        "change": 0.0,
        "changePercent": 0.0,
        "currency": "USD",
        "issuer": user_id,
        "issuer_name": current_user.get("username"),
        "companyId": cid,
        "config": {"total_shares": payload.totalShares},
        "free_shares": free_shares,
        "updated_at": _now(),
    }
    await db.stocks.insert_one(doc)

    # Доля основателя зачисляется владельцу лично (он её оплатил из бюджета компании).
    if founder_shares > 0:
        await db.stock_holdings.update_one(
            {"userId": user_id, "symbol": symbol},
            {"$inc": {"quantity": founder_shares, "invested": founder_cost},
             "$setOnInsert": {"userId": user_id, "symbol": symbol}},
            upsert=True,
        )
    await record_transaction(
        db, user_id, EXPENSE, total_charge, CAT_COMPANY,
        f"IPO компании «{company['name']}» ({symbol})", balance_after=None,
        meta={"companyId": cid, "kind": "ipo", "symbol": symbol,
              "listingFee": LISTING_FEE, "founderCost": founder_cost},
    )
    updated = await db.companies.find_one({"_id": company["_id"]})
    return {
        "symbol": symbol, "price": price, "founderShares": founder_shares,
        "freeShares": free_shares, "totalShares": payload.totalShares,
        "company": await _serialize(db, updated, user_id),
    }


@router.post("/dividend")
async def company_pay_dividend(
    payload: CompanyDividend,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Выплатить дивиденды держателям акции компании ИЗ БЮДЖЕТА компании.

    Держатель-владелец исключается (он и так владеет компанией). Списание из
    бюджета атомарно (проверка достаточности) — дивиденды обеспечены реальными
    деньгами, не печатаются."""
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    symbol = company.get("stockSymbol")
    if not symbol:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "У компании нет размещённой акции")

    per = payload.perShare
    holders = [
        h async for h in db.stock_holdings.find(
            {"symbol": symbol, "quantity": {"$gt": 0}, "userId": {"$ne": user_id}}
        )
    ]
    total = round(sum(per * h.get("quantity", 0) for h in holders), 2)
    if total <= 0:
        return {"paid": 0.0, "holders": 0, "company": await _serialize(db, company, user_id)}

    paid_company = await db.companies.find_one_and_update(
        {"_id": company["_id"], "budget": {"$gte": total}},
        {"$inc": {"budget": -total}},
        return_document=True,
    )
    if not paid_company:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств в бюджете компании")

    for h in holders:
        amt = round(per * h.get("quantity", 0), 2)
        if amt <= 0:
            continue
        hb = await adjust_balance(db, h["userId"], amt)
        await record_transaction(
            db, h["userId"], INCOME, amt, CAT_DIVIDEND,
            f"Дивиденды {symbol}", symbol=symbol, balance_after=hb,
            meta={"perShare": per, "from": company["name"], "companyId": str(company["_id"])},
        )
    await record_transaction(
        db, user_id, EXPENSE, total, CAT_COMPANY,
        f"Выплата дивидендов {symbol}", balance_after=None,
        meta={"companyId": str(company["_id"]), "kind": "dividend", "perShare": per, "holders": len(holders)},
    )
    return {"paid": total, "holders": len(holders),
            "company": await _serialize(db, paid_company, user_id)}


@router.get("/history")
async def company_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    # История ТОЛЬКО текущей компании игрока. Раньше фильтр был лишь по
    # category=company, из-за чего после роспуска и пересоздания компании в логах
    # всплывали операции прошлой (реестр владельца хранит их вечно). Теперь все
    # company-операции помечены meta.companyId, и историю сужаем по нему.
    company = await _my_company_or_membership(db, str(current_user["_id"]))
    if not company:
        return {"items": [], "total": 0, "skip": skip, "limit": limit}
    return await query_transactions(
        db, str(current_user["_id"]),
        category=CAT_COMPANY, sort="date_desc", skip=skip, limit=limit,
        meta_filter={"companyId": str(company["_id"])},
    )


# ── Admin ────────────────────────────────────────────────────────────────────


async def _load_any_company(db: AsyncIOMotorDatabase, company_id: str) -> dict:
    if not ObjectId.is_valid(company_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID компании")
    company = await db.companies.find_one({"_id": ObjectId(company_id)})
    if not company:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Компания не найдена")
    return company


@router.patch("/admin/{company_id}")
async def admin_update_company(
    company_id: str,
    payload: AdminCompanyUpdate,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    company = await _load_any_company(db, company_id)
    update_fields = payload.model_dump(exclude_unset=True)
    if not update_fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет полей для обновления")
    await db.companies.update_one({"_id": company["_id"]}, {"$set": update_fields})
    updated = await db.companies.find_one({"_id": company["_id"]})
    result = await _serialize(db, updated, company["ownerId"])
    await push_notification(
        db, company["ownerId"], "company", "Компания изменена администратором",
        f"Администратор изменил параметры компании «{updated['name']}».",
        data={"companyId": company_id},
    )
    return {"company": result}


@router.delete("/admin/{company_id}")
async def admin_delete_company(
    company_id: str,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    company = await _load_any_company(db, company_id)
    name = company["name"]
    owner_id = company["ownerId"]
    await _disband(db, company)
    await push_notification(
        db, owner_id, "company", "Компания удалена администратором",
        f"Компания «{name}» была удалена администратором.",
        data={},
    )
    return {"message": f"Компания «{name}» удалена"}


@router.post("/admin/{company_id}/transfer")
async def admin_transfer_company(
    company_id: str,
    payload: AdminTransferBody,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Передать право владения компанией другому игроку."""
    company = await _load_any_company(db, company_id)
    target = await db.users.find_one({"username": payload.toUsername})
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Игрок не найден")
    new_owner_id = str(target["_id"])
    old_owner_id = company["ownerId"]
    if new_owner_id == old_owner_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Игрок уже владеет этой компанией")
    if await db.companies.find_one({"ownerId": new_owner_id}):
        raise HTTPException(status.HTTP_409_CONFLICT, "У целевого игрока уже есть своя компания")

    # Если целевой игрок был сотрудником этой же компании — снимаем устаревшую запись.
    await db.company_members.delete_one({"companyId": company_id, "userId": new_owner_id})

    await db.companies.update_one({"_id": company["_id"]}, {"$set": {"ownerId": new_owner_id}})
    updated = await db.companies.find_one({"_id": company["_id"]})
    result = await _serialize(db, updated, new_owner_id)

    await push_notification(
        db, old_owner_id, "company", "Компания передана",
        f"Владение компанией «{updated['name']}» передано другому игроку администратором.",
        data={"companyId": company_id},
    )
    await push_notification(
        db, new_owner_id, "company", "Вы стали владельцем компании",
        f"Администратор передал вам компанию «{updated['name']}».",
        data={"companyId": company_id},
    )
    return {"company": result}
