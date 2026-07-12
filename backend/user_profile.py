"""Профиль пользователя: смена никнейма, пароля и аватара (страница «Настройки»).

Аватар хранится как data URL (base64) прямо в документе пользователя — без
отдельной инфраструктуры файлового хранилища (в проекте нет S3/статики), что
полностью укладывается в существующий JSON-стиль API. Клиент (SettingsPage)
сжимает изображение через canvas перед отправкой; сервер дополнительно
валидирует формат и размер (см. schemas.AvatarUpdate) — так что даже при
обходе клиентской компрессии сервер не примет мусор/слишком большой файл.
"""
from __future__ import annotations

import logging

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from auth import get_current_user, hash_password, verify_password
from database import get_db
from schemas import ProfileUpdate, PasswordChangeRequest, AvatarUpdate

logger = logging.getLogger("tradeverse.profile")

router = APIRouter(prefix="/api/user", tags=["profile"])


@router.patch("/profile")
async def update_profile(
    payload: ProfileUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Сменить никнейм. Уникальность проверяется так же, как в админ-панели."""
    user_id = current_user["_id"]
    new_username = payload.username
    if new_username == current_user.get("username"):
        return {"username": new_username}

    duplicate = await db.users.find_one({"username": new_username, "_id": {"$ne": user_id}})
    if duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, "Пользователь с таким именем уже существует")

    await db.users.update_one({"_id": user_id}, {"$set": {"username": new_username}})
    logger.info("User %s renamed to '%s'", str(user_id), new_username)
    return {"username": new_username}


@router.post("/password")
async def change_password(
    payload: PasswordChangeRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Сменить пароль — требует ввода текущего пароля."""
    if not verify_password(payload.current_password, current_user["hashed_password"]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Текущий пароль указан неверно")

    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"hashed_password": hash_password(payload.new_password)}},
    )
    logger.info("User %s changed password", str(current_user["_id"]))
    return {"ok": True}


@router.patch("/avatar")
async def update_avatar(
    payload: AvatarUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Загрузить/сменить аватар (data URL, уже провалидирован схемой)."""
    await db.users.update_one({"_id": current_user["_id"]}, {"$set": {"avatar": payload.avatar}})
    return {"avatar": payload.avatar}


@router.delete("/avatar")
async def delete_avatar(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Удалить аватар — пользователь возвращается к отображению инициалами."""
    await db.users.update_one({"_id": current_user["_id"]}, {"$set": {"avatar": None}})
    return {"avatar": None}


@router.patch("/leaderboard-visibility")
async def toggle_leaderboard_visibility(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Переключает участие в публичной таблице лидеров (см. GET /api/leaderboard)."""
    new_hidden = not current_user.get("hideFromLeaderboard", False)
    await db.users.update_one({"_id": current_user["_id"]}, {"$set": {"hideFromLeaderboard": new_hidden}})
    return {"hideFromLeaderboard": new_hidden}
