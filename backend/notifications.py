"""Уведомления игрока.

Единый механизм: любой модуль вызывает push_notification(...), фронтенд
читает ленту и отмечает прочитанным. Используется, например, для приглашений
в компанию (с действиями accept/decline) и авто-начислений (аренда).
"""
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


async def push_notification(
    db: AsyncIOMotorDatabase,
    user_id: str,
    ntype: str,
    title: str,
    body: str = "",
    data: dict | None = None,
) -> str:
    """Создаёт уведомление для пользователя и возвращает его id."""
    doc = {
        "userId": str(user_id),
        "type": ntype,
        "title": title,
        "body": body,
        "data": data or {},
        "read": False,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.notifications.insert_one(doc)
    return str(result.inserted_id)


def _serialize(n: dict) -> dict:
    return {
        "id": str(n["_id"]),
        "type": n.get("type"),
        "title": n.get("title"),
        "body": n.get("body"),
        "data": n.get("data", {}),
        "read": bool(n.get("read", False)),
        "createdAt": n["created_at"].isoformat() if isinstance(n.get("created_at"), datetime) else None,
    }


@router.get("")
async def list_notifications(
    limit: int = Query(30, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Лента уведомлений текущего игрока (новые сверху) + счётчик непрочитанных."""
    user_id = str(current_user["_id"])
    items = [
        _serialize(n)
        async for n in db.notifications.find({"userId": user_id}).sort("created_at", -1).limit(limit)
    ]
    unread = await db.notifications.count_documents({"userId": user_id, "read": False})
    return {"items": items, "unread": unread}


@router.post("/{notif_id}/read")
async def mark_read(
    notif_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if not ObjectId.is_valid(notif_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID")
    await db.notifications.update_one(
        {"_id": ObjectId(notif_id), "userId": str(current_user["_id"])},
        {"$set": {"read": True}},
    )
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    await db.notifications.update_many(
        {"userId": str(current_user["_id"]), "read": False},
        {"$set": {"read": True}},
    )
    return {"ok": True}
