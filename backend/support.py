"""Техническая поддержка: обращения игроков и их обработка админами.

Игрок создаёт обращение (тип: bug | loss | suggestion) и видит свои обращения.
Админ видит все обращения, меняет статус (pending | rejected | resolved)
и добавляет ответ.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from admin_perms import require_admin
from auth import get_current_user
from database import get_db

logger = logging.getLogger("tradeverse.support")

router = APIRouter(prefix="/api/support", tags=["support"])
admin_router = APIRouter(prefix="/api/admin/support", tags=["support-admin"])

TicketType = Literal["bug", "loss", "suggestion"]
TicketStatus = Literal["pending", "rejected", "resolved"]
MAX_TEXT = 2000


class TicketCreate(BaseModel):
    type: TicketType
    description: Optional[str] = Field(default=None, max_length=MAX_TEXT)
    lost_item: Optional[str] = Field(default=None, max_length=200)
    method: Optional[str] = Field(default=None, max_length=500)
    time: Optional[str] = Field(default=None, max_length=200)
    suggestion: Optional[str] = Field(default=None, max_length=MAX_TEXT)


class TicketAdminUpdate(BaseModel):
    status: Optional[TicketStatus] = None
    reply: Optional[str] = Field(default=None, max_length=MAX_TEXT)


def _clean(value: Optional[str]) -> str:
    return (value or "").strip()


def _validate(payload: TicketCreate) -> dict:
    """Проверяет обязательные поля для выбранного типа обращения."""
    if payload.type == "bug":
        text = _clean(payload.description)
        if not text:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Опишите баг")
        return {"description": text}
    if payload.type == "loss":
        lost, method, when = _clean(payload.lost_item), _clean(payload.method), _clean(payload.time)
        if not (lost and method and when):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Заполните все поля о потере имущества")
        return {"lost_item": lost, "method": method, "time": when}
    text = _clean(payload.suggestion)
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Опишите предложение")
    return {"suggestion": text}


def _serialize(doc: dict) -> dict:
    created = doc.get("created_at")
    return {
        "id": str(doc["_id"]),
        "user_id": str(doc.get("user_id", "")),
        "username": doc.get("username", ""),
        "type": doc.get("type"),
        "status": doc.get("status", "pending"),
        "description": doc.get("description"),
        "lost_item": doc.get("lost_item"),
        "method": doc.get("method"),
        "time": doc.get("time"),
        "suggestion": doc.get("suggestion"),
        "reply": doc.get("reply"),
        "created_at": created.isoformat() if created else None,
        "updated_at": doc["updated_at"].isoformat() if doc.get("updated_at") else None,
    }


@router.post("/tickets")
async def create_ticket(
    payload: TicketCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    doc = {
        "user_id": current_user["_id"],
        "username": current_user.get("username", ""),
        "type": payload.type,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "reply": None,
        **_validate(payload),
    }
    res = await db.support_tickets.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _serialize(doc)


@router.get("/tickets")
async def list_my_tickets(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    cursor = db.support_tickets.find({"user_id": current_user["_id"]}).sort("created_at", -1)
    return [_serialize(d) async for d in cursor]


@admin_router.get("/tickets")
async def admin_list_tickets(
    _admin=Depends(require_admin()),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    cursor = db.support_tickets.find({}).sort("created_at", -1)
    return [_serialize(d) async for d in cursor]


@admin_router.patch("/tickets/{ticket_id}")
async def admin_update_ticket(
    ticket_id: str,
    payload: TicketAdminUpdate,
    admin=Depends(require_admin()),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    try:
        oid = ObjectId(ticket_id)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный id обращения")

    update: dict = {"updated_at": datetime.now(timezone.utc)}
    if payload.status is not None:
        update["status"] = payload.status
    if payload.reply is not None:
        update["reply"] = payload.reply.strip() or None

    doc = await db.support_tickets.find_one_and_update(
        {"_id": oid}, {"$set": update}, return_document=True
    )
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Обращение не найдено")
    logger.info("Support ticket %s updated by admin %s", ticket_id, str(admin["_id"]))
    return _serialize(doc)
