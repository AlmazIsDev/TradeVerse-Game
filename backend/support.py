"""Чат технической поддержки: тикеты, сообщения и вложения."""
from __future__ import annotations

import base64
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
bug_router = APIRouter(prefix="/api/admin/bugs", tags=["bugs-admin"])
TicketType = Literal["bug", "loss", "suggestion"]
BugStatus = Literal["new", "in_progress", "fixed"]
TicketStatus = Literal["pending", "resolved", "rejected"]
MAX_TEXT = 10000
MAX_FILE_BYTES = 10 * 1024 * 1024

class Attachment(BaseModel):
    name: str = Field(..., max_length=255)
    type: str = Field(default="application/octet-stream", max_length=120)
    data: str = Field(..., max_length=14_000_000)

class TicketCreate(BaseModel):
    type: TicketType
    description: Optional[str] = Field(default=None, max_length=MAX_TEXT)
    lost_item: Optional[str] = Field(default=None, max_length=500)
    method: Optional[str] = Field(default=None, max_length=500)
    time: Optional[str] = Field(default=None, max_length=200)
    suggestion: Optional[str] = Field(default=None, max_length=MAX_TEXT)
    message: Optional[str] = Field(default=None, max_length=MAX_TEXT)
    attachments: list[Attachment] = Field(default_factory=list)

class TicketMessageCreate(BaseModel):
    message: str = Field(..., min_length=1, max_length=MAX_TEXT)
    attachments: list[Attachment] = Field(default_factory=list)

class BugCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=MAX_TEXT)

class BugUpdate(BaseModel):
    status: Optional[BugStatus] = None

class TicketAdminUpdate(BaseModel):
    status: Optional[TicketStatus] = None
    reply: Optional[str] = Field(default=None, max_length=MAX_TEXT)
    message: Optional[str] = Field(default=None, max_length=MAX_TEXT)
    attachments: list[Attachment] = Field(default_factory=list)

def _now(): return datetime.now(timezone.utc)
def _clean(v): return (v or "").strip()
def _check_files(files):
    for f in files:
        try: size = len(base64.b64decode(f.data.split(",", 1)[-1], validate=False))
        except Exception: raise HTTPException(400, "Некорректное вложение")
        if size > MAX_FILE_BYTES: raise HTTPException(400, "Размер файла не должен превышать 10 МБ")

def _initial(payload):
    if payload.type == "bug":
        text = _clean(payload.description or payload.message)
        if not text: raise HTTPException(400, "Опишите баг")
        return text
    if payload.type == "loss":
        values = [_clean(payload.lost_item), _clean(payload.method), _clean(payload.time)]
        if not all(values): raise HTTPException(400, "Заполните все поля о потере имущества")
        return "Что потерялось: %s\nКаким способом: %s\nПримерное время: %s" % tuple(values)
    text = _clean(payload.suggestion or payload.message)
    if not text: raise HTTPException(400, "Опишите предложение")
    return text

def _serialize(doc):
    return {"id": str(doc["_id"]), "number": doc.get("number"), "user_id": str(doc.get("user_id", "")),
            "username": doc.get("username", ""), "type": doc.get("type"), "status": doc.get("status", "pending"),
            "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
            "updated_at": doc.get("updated_at").isoformat() if doc.get("updated_at") else None,
            "messages": [{**m, "username": m.get("username") or (doc.get("username", "") if m.get("author") == "player" else "Администратор"), "created_at": m["created_at"].isoformat()} for m in doc.get("messages", [])]}

async def _next_number(db):
    result = await db.support_counters.find_one_and_update({"_id": "ticket"}, {"$inc": {"value": 1}}, upsert=True, return_document=True)
    return result.get("value", 1)

@router.post("/tickets")
async def create_ticket(payload: TicketCreate, current_user=Depends(get_current_user), db: AsyncIOMotorDatabase=Depends(get_db)):
    _check_files(payload.attachments)
    now = _now()
    doc = {"number": await _next_number(db), "user_id": current_user["_id"], "username": current_user.get("username", ""),
           "type": payload.type, "status": "pending", "created_at": now, "updated_at": now,
           "messages": [{"author": "player", "username": current_user.get("username", ""), "text": _initial(payload), "attachments": [f.model_dump() for f in payload.attachments], "created_at": now}]}
    res = await db.support_tickets.insert_one(doc); doc["_id"] = res.inserted_id
    return _serialize(doc)

@router.get("/tickets")
async def list_my_tickets(current_user=Depends(get_current_user), db: AsyncIOMotorDatabase=Depends(get_db)):
    return [_serialize(d) async for d in db.support_tickets.find({"user_id": current_user["_id"]}).sort("updated_at", -1)]

@router.post("/tickets/{ticket_id}/messages")
async def player_message(ticket_id: str, payload: TicketMessageCreate, current_user=Depends(get_current_user), db: AsyncIOMotorDatabase=Depends(get_db)):
    _check_files(payload.attachments)
    try: oid = ObjectId(ticket_id)
    except Exception: raise HTTPException(400, "Некорректный id обращения")
    now = _now(); msg = {"author": "player", "username": current_user.get("username", ""), "text": payload.message.strip(), "attachments": [f.model_dump() for f in payload.attachments], "created_at": now}
    result = await db.support_tickets.update_one({"_id": oid, "user_id": current_user["_id"], "status": "pending"}, {"$push": {"messages": msg}, "$set": {"updated_at": now}})
    if not result.modified_count: raise HTTPException(404, "Обращение не найдено или закрыто")
    return _serialize(await db.support_tickets.find_one({"_id": oid}))

@admin_router.get("/tickets")
async def admin_list_tickets(_admin=Depends(require_admin()), db: AsyncIOMotorDatabase=Depends(get_db)):
    return [_serialize(d) async for d in db.support_tickets.find({}).sort("updated_at", -1)]

@admin_router.patch("/tickets/{ticket_id}")
async def admin_update_ticket(ticket_id: str, payload: TicketAdminUpdate, admin=Depends(require_admin()), db: AsyncIOMotorDatabase=Depends(get_db)):
    _check_files(payload.attachments)
    try: oid = ObjectId(ticket_id)
    except Exception: raise HTTPException(400, "Некорректный id обращения")
    now = _now(); update = {"$set": {"updated_at": now}}; messages = []
    text = _clean(payload.message if payload.message is not None else payload.reply)
    if text or payload.attachments: messages.append({"author": "admin", "username": admin.get("username", "Администратор"), "text": text, "attachments": [f.model_dump() for f in payload.attachments], "created_at": now})
    if messages: update["$push"] = {"messages": {"$each": messages}}
    if payload.status is not None: update["$set"]["status"] = payload.status
    doc = await db.support_tickets.find_one_and_update({"_id": oid}, update, return_document=True)
    if not doc: raise HTTPException(404, "Обращение не найдено")
    return _serialize(doc)

@bug_router.get("")
async def list_bugs(_admin=Depends(require_admin()), db: AsyncIOMotorDatabase=Depends(get_db)):
    return [{"id": str(d["_id"]), "title": d.get("title", ""), "description": d.get("description", ""), "status": d.get("status", "new"), "created_by": d.get("created_by", ""), "created_at": d.get("created_at").isoformat() if d.get("created_at") else None} async for d in db.support_bugs.find({}).sort("created_at", -1)]

@bug_router.post("")
async def create_bug(payload: BugCreate, admin=Depends(require_admin()), db: AsyncIOMotorDatabase=Depends(get_db)):
    now = _now()
    doc = {"title": payload.title.strip(), "description": payload.description.strip(), "status": "new", "created_by": admin.get("username", "Администратор"), "created_at": now, "updated_at": now}
    result = await db.support_bugs.insert_one(doc); doc["_id"] = result.inserted_id
    return {"id": str(doc["_id"]), "title": doc["title"], "description": doc["description"], "status": doc["status"], "created_by": doc["created_by"], "created_at": now.isoformat()}

@bug_router.patch("/{bug_id}")
async def update_bug(bug_id: str, payload: BugUpdate, _admin=Depends(require_admin()), db: AsyncIOMotorDatabase=Depends(get_db)):
    try: oid = ObjectId(bug_id)
    except Exception: raise HTTPException(400, "Некорректный id бага")
    update = {"$set": {"updated_at": _now()}}
    if payload.status is not None: update["$set"]["status"] = payload.status
    doc = await db.support_bugs.find_one_and_update({"_id": oid}, update, return_document=True)
    if not doc: raise HTTPException(404, "Баг не найден")
    return {"id": str(doc["_id"]), "title": doc.get("title", ""), "description": doc.get("description", ""), "status": doc.get("status", "new"), "created_by": doc.get("created_by", ""), "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None}
