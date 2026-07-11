"""Аутентификация и общие зависимости.

Вынесено из main.py, чтобы модули-роутеры (economy, crypto, ...) могли
переиспользовать зависимости без циклических импортов.
"""
import hashlib
import logging
import os
import secrets

import bcrypt
import jwt
from bson import ObjectId
from datetime import datetime, timedelta, timezone
from pymongo.errors import DuplicateKeyError

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorDatabase

from database import get_db

logger = logging.getLogger("tradeverse.auth")

_JWT_DEFAULT_SECRET = "tradeverse-dev-secret-change-in-prod"
JWT_SECRET = os.getenv("JWT_SECRET", _JWT_DEFAULT_SECRET)
JWT_ALGORITHM = "HS256"

# Access-токен теперь короткоживущий (по умолчанию 30 минут). Долгую сессию
# держит refresh-токен со скользящим окном (см. REFRESH_TOKEN_EXPIRE_DAYS).
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

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
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Декодирует и валидирует JWT-токен. Бросает исключение при ошибке."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# ── Refresh-токены ────────────────────────────────────────────────────────────
#
# Refresh-токен — непрозрачная случайная строка (не JWT). В БД хранится только
# её SHA-256-хеш, сам токен нигде не сохраняется. Срок жизни — скользящее окно:
# при каждом обновлении токен ротируется, а его 30-дневный срок отсчитывается
# заново, поэтому активный пользователь фактически никогда не разлогинивается,
# а неактивный >30 дней — обязан войти заново.


def _hash_refresh_token(raw_token: str) -> str:
    """Возвращает SHA-256-хеш refresh-токена (hex) для хранения в БД."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


async def create_refresh_token(
    db: AsyncIOMotorDatabase, user_id: ObjectId, _max_attempts: int = 5
) -> str:
    """Создаёт refresh-токен, сохраняет его хеш и срок в БД, возвращает сырой токен.

    `token_hash` уникально индексирован — на случай коллизии (или любой другой
    причины конфликта уникальности) повторяем с новым случайным токеном вместо
    падения запроса с raw 500.
    """
    now = datetime.now(timezone.utc)
    for _ in range(_max_attempts):
        raw_token = secrets.token_urlsafe(48)
        try:
            await db.refresh_tokens.insert_one({
                "token_hash": _hash_refresh_token(raw_token),
                "user_id": user_id,
                "expires_at": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
                "created_at": now,
            })
            return raw_token
        except DuplicateKeyError:
            continue
    raise RuntimeError("Не удалось сгенерировать уникальный refresh-токен")


async def use_refresh_token(
    db: AsyncIOMotorDatabase, raw_token: str
) -> dict | None:
    """Атомарно находит и удаляет действующий refresh-токен по его хешу.

    find_one_and_delete в одном запросе объединяет проверку и инвалидацию токена,
    поэтому две параллельные ротации одного и того же токена не могут обе
    успешно завершиться — выигрывает только одна (защита от гонки при ротации).
    Заодно хеш вычисляется один раз, а не дважды (поиск + отдельное удаление).
    Возвращает документ токена или None, если он не найден или истёк. TTL-индекс
    удаляет просроченные токены не мгновенно, поэтому срок проверяется вручную.
    """
    doc = await db.refresh_tokens.find_one_and_delete(
        {"token_hash": _hash_refresh_token(raw_token)}
    )
    if not doc:
        return None
    expires_at = doc.get("expires_at")
    # Mongo возвращает naive-UTC datetime — приводим к tz-aware для сравнения.
    if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if not isinstance(expires_at, datetime) or expires_at <= datetime.now(timezone.utc):
        return None
    return doc


async def delete_refresh_token(db: AsyncIOMotorDatabase, raw_token: str) -> bool:
    """Удаляет refresh-токен по его хешу. Возвращает True, если что-то удалено."""
    result = await db.refresh_tokens.delete_one(
        {"token_hash": _hash_refresh_token(raw_token)}
    )
    return result.deleted_count > 0


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
