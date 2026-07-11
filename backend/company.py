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

from auth import get_current_user
from database import get_db
from ledger import (
    INCOME, EXPENSE, CAT_COMPANY,
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
    revenue = await company_income_per_hour(db, cid)   # реальный доход от активов
    payroll = round(sum(m.get("salary", 0) for m in members), 2)
    hours = _hours_since(company)
    owner_id = company["ownerId"]
    is_owner = viewer_id is not None and viewer_id == owner_id
    viewer_role = "owner" if is_owner else next(
        (m.get("role", "worker") for m in members if m["userId"] == viewer_id), None
    )
    owner_user = await db.users.find_one({"_id": ObjectId(owner_id)}) if ObjectId.is_valid(owner_id) else None

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
         "role": "owner", "salary": None},
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
        "profitPerHour": round(revenue - payroll, 2),
        "accrued": round(revenue * hours, 2),
        "memberCount": len(members) + 1,
        "assetCount": len(assets),
        "ownerId": owner_id,
        "ownerName": owner_user.get("username") if owner_user else None,
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


@router.delete("")
async def disband_company(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Распустить компанию (только владелец). Необратимо.

    Активы компании возвращаются владельцу в личную собственность, сотрудники
    уведомляются, все приглашения/заявки/сотрудники удаляются.
    """
    user_id = str(current_user["_id"])
    company = await _require_company(db, user_id)
    cid = str(company["_id"])
    name = company["name"]

    # Уведомить всех сотрудников о роспуске (realtime через WS + persist).
    members = await _members(db, cid)
    for m in members:
        await push_notification(
            db, m["userId"], "company", "Компания распущена",
            f"Компания «{name}» была распущена. Вы больше не сотрудник.",
            data={"companyId": cid},
        )

    # Вернуть активы компании владельцу в личную собственность.
    await db.user_assets.update_many({"companyId": cid}, {"$set": {"companyId": None}})

    # Удалить связанные записи и саму компанию.
    await db.company_members.delete_many({"companyId": cid})
    await db.company_invites.delete_many({"companyId": cid})
    await db.company_applications.delete_many({"companyId": cid})
    await db.companies.delete_one({"_id": company["_id"]})
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

    hours = _hours_since(company)
    revenue_per_h = await company_income_per_hour(db, cid)
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
    payroll_per_h = sum(m.get("salary", 0) for m in members)
    payroll_due = round(payroll_per_h * hours, 2)

    budget = round(company.get("budget", 0.0) + gross, 2)
    paid = 0.0
    if payroll_due > 0 and budget >= payroll_due:
        for m in members:
            amt = round(m.get("salary", 0) * hours, 2)
            if amt <= 0:
                continue
            mb = await adjust_balance(db, m["userId"], amt)
            await record_transaction(
                db, m["userId"], INCOME, amt, CAT_COMPANY,
                f"Зарплата: {company['name']}", balance_after=mb,
                meta={"companyId": cid},
            )
            await push_notification(
                db, m["userId"], "salary", "Зарплата начислена",
                f"«{company['name']}» выплатила ${amt:.2f}.", data={"companyId": cid},
            )
        budget = round(budget - payroll_due, 2)
        paid = payroll_due

    await db.companies.update_one(
        {"_id": company["_id"]},
        {"$set": {"budget": budget, "last_tick": _now()}},
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
    )
    return {"balance": new_balance, "company": await _serialize(db, updated, user_id)}


@router.get("/history")
async def company_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    return await query_transactions(
        db, str(current_user["_id"]),
        category=CAT_COMPANY, sort="date_desc", skip=skip, limit=limit,
    )
