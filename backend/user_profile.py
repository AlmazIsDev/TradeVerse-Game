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

from auth import get_current_user, hash_password, verify_password, username_taken
from database import get_db
from levels import level_from_xp, xp_for_level, realestate_limit, MAX_LEVEL
from schemas import ProfileUpdate, PasswordChangeRequest, AvatarUpdate, BannerUpdate, BioUpdate, CountryUpdate

logger = logging.getLogger("tradeverse.profile")

router = APIRouter(prefix="/api/user", tags=["profile"])


@router.get("/achievements")
async def get_achievements(current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Список достижений игрока: открытые и закрытые."""
    from achievements import list_user_achievements
    return {"achievements": await list_user_achievements(db, str(current_user["_id"]))}


@router.get("/level")
async def get_level(current_user: dict = Depends(get_current_user)):
    """Уровень игрока, XP и прогресс до следующего уровня."""
    xp = int(current_user.get("xp", 0))
    level = level_from_xp(xp)
    current_floor = xp_for_level(level)
    next_floor = xp_for_level(level + 1) if level < MAX_LEVEL else current_floor
    return {
        "level": level,
        "xp": xp,
        "xpCurrentLevel": current_floor,
        "xpNextLevel": next_floor,
        "realestateLimit": realestate_limit(level),
    }


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

    # Регистронезависимая проверка уникальности (как в регистрации и админке)
    if await username_taken(db, new_username, exclude_id=user_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Пользователь с таким именем уже существует")

    await db.users.update_one({"_id": user_id}, {"$set": {"username": new_username}})
    logger.info("User %s renamed to '%s'", str(user_id), new_username)
    return {"username": new_username}


@router.patch("/bio")
async def update_bio(
    payload: BioUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Обновить описание профиля («о себе») — уже провалидировано схемой."""
    await db.users.update_one({"_id": current_user["_id"]}, {"$set": {"bio": payload.bio}})
    return {"bio": payload.bio}


@router.patch("/country")
async def update_country(
    payload: CountryUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Страна игрока (ISO alpha-2) — флаг отображается слева от ника."""
    await db.users.update_one({"_id": current_user["_id"]}, {"$set": {"country": payload.country}})
    return {"country": payload.country}


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


@router.patch("/banner")
async def update_banner(
    payload: BannerUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Загрузить/сменить баннер профиля (data URL, уже провалидирован схемой)."""
    await db.users.update_one({"_id": current_user["_id"]}, {"$set": {"banner": payload.banner}})
    return {"banner": payload.banner}


@router.delete("/banner")
async def delete_banner(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Удалить баннер — профиль возвращается к стандартному фону."""
    await db.users.update_one({"_id": current_user["_id"]}, {"$set": {"banner": None}})
    return {"banner": None}


@router.patch("/leaderboard-visibility")
async def toggle_leaderboard_visibility(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Переключает участие в публичной таблице лидеров (см. GET /api/leaderboard).

    Хранится в едином поле `hidden_from_leaderboard` — том же, что читают
    таблица лидеров (main.py) и админ-панель, поэтому обе системы всегда
    видят одно значение. В ответе — camelCase `hideFromLeaderboard` для фронта.
    """
    if current_user.get("leaderboard_lock"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Изменение этой настройки запрещено администратором")
    new_hidden = not current_user.get("hidden_from_leaderboard", False)
    await db.users.update_one({"_id": current_user["_id"]}, {"$set": {"hidden_from_leaderboard": new_hidden}})
    return {"hideFromLeaderboard": new_hidden}
