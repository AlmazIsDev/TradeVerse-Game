"""Уведомления игрока.

Единый механизм: любой модуль вызывает push_notification(...), фронтенд
читает ленту и отмечает прочитанным. Используется, например, для приглашений
в компанию (с действиями accept/decline) и авто-начислений (аренда).
"""
from __future__ import annotations

from typing import Optional

from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

CATEGORY_PATTERN = "^(automatic|announcement|company|market|mining|event|system)$"


_AUTO_TITLES = {
    "Появился арендатор", "Аренда компании завершена", "Аренда завершена",
    "Зарплата начислена", "Ферма перезапущена", "Ферма отключена",
    "Майнинг-ферма разобрана", "Взлом удался", "Взлом системы защиты",
    "Взлом не удался", "Защита установлена", "Защита не применена",
    "Установка защиты провалена", "Репутационный кризис",
    "Провальное разоблачение", "Разоблачение вышло", "Разоблачение провалилось",
}


def _category(ntype: str, title: str) -> str:
    if title in _AUTO_TITLES or ntype in {"rental", "salary"}:
        return "automatic"
    if ntype == "broadcast":
        return "announcement"
    if ntype in {"company", "company_invite", "company_application"}:
        return "company"
    if ntype in {"market", "crypto_transfer"}:
        return "market"
    if ntype in {"mining"}:
        return "mining"
    if ntype in {"media", "itstudio", "itstudio_attack", "cityroof"}:
        return "event"
    return "system"


async def push_notification(
    db: AsyncIOMotorDatabase,
    user_id: str,
    ntype: str,
    title: str,
    body: str = "",
    data: Optional[dict] = None,
) -> str:
    """Создаёт уведомление для пользователя и возвращает его id."""
    doc = {
        "userId": str(user_id),
        "type": ntype,
        "category": _category(ntype, title),
        "title": title,
        "body": body,
        "data": data or {},
        "read": False,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.notifications.insert_one(doc)
    doc["_id"] = result.inserted_id
    # Realtime-доставка через WebSocket (polling остаётся резервом).
    try:
        from ws import push_to_user
        await push_to_user(user_id, {"type": "notification", "notification": _serialize(doc)})
    except Exception:
        pass
    return str(result.inserted_id)


def _serialize(n: dict) -> dict:
    return {
        "id": str(n["_id"]),
        "type": n.get("type"),
        "category": n.get("category") or _category(n.get("type", ""), n.get("title", "")),
        "title": n.get("title"),
        "body": n.get("body"),
        "data": n.get("data", {}),
        "read": bool(n.get("read", False)),
        "createdAt": n["created_at"].isoformat() if isinstance(n.get("created_at"), datetime) else None,
    }


@router.get("")
async def list_notifications(
    limit: int = Query(30, ge=1, le=100),
    category: Optional[str] = Query(None, pattern=CATEGORY_PATTERN),
    exclude_category: Optional[str] = Query(None, pattern=CATEGORY_PATTERN),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Лента уведомлений игрока (новые сверху), с фильтром категории, + непрочитанные по категориям."""
    user_id = str(current_user["_id"])
    query = {"userId": user_id}
    if category:
        query["category"] = category
    elif exclude_category:
        query["category"] = {"$ne": exclude_category}
    items = [
        _serialize(n)
        async for n in db.notifications.find(query).sort("created_at", -1).limit(limit)
    ]
    unread_by_category: dict[str, int] = {}
    async for n in db.notifications.find(
        {"userId": user_id, "read": False}, {"type": 1, "title": 1, "category": 1},
    ):
        cat = n.get("category") or _category(n.get("type", ""), n.get("title", ""))
        if cat == exclude_category:
            continue
        unread_by_category[cat] = unread_by_category.get(cat, 0) + 1
    return {
        "items": items,
        "unread": sum(unread_by_category.values()),
        "unreadByCategory": unread_by_category,
    }


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
