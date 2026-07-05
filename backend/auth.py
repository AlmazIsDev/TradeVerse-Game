"""Аутентификация и общие зависимости.

Вынесено из main.py, чтобы модули-роутеры (economy, crypto, ...) могли
переиспользовать зависимости без циклических импортов.
"""
import logging
import os

import bcrypt
import jwt
from bson import ObjectId
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorDatabase

from database import get_db

logger = logging.getLogger("tradeverse.auth")

_JWT_DEFAULT_SECRET = "tradeverse-dev-secret-change-in-prod"
JWT_SECRET = os.getenv("JWT_SECRET", _JWT_DEFAULT_SECRET)
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

if JWT_SECRET == _JWT_DEFAULT_SECRET:
    logger.warning(
        "JWT_SECRET не задан — используется небезопасное значение по умолчанию. "
        "Установите переменную окружения JWT_SECRET перед деплоем в production."
    )

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(data: dict) -> str:
    """Создаёт JWT-токен с полезной нагрузкой и сроком действия."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Декодирует и валидирует JWT-токен. Бросает исключение при ошибке."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    """Dependency: извлекает текущего пользователя из JWT-токена."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
        )
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен истёк",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный токен",
        )

    user_id = payload.get("sub")
    if not user_id or not ObjectId.is_valid(user_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный токен",
        )

    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден",
        )
    return user


async def require_admin(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Dependency: требует, чтобы текущий пользователь имел роль 'admin'."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ запрещён: требуются права администратора",
        )
    return current_user
