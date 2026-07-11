from __future__ import annotations

from typing import Optional

import re

from pydantic import BaseModel, field_validator

USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
# data:image/<png|jpeg|jpg|webp>;base64,<...> — тот же формат, что отдаёт
# canvas.toDataURL() на клиенте (см. SettingsPage).
AVATAR_DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp);base64,([A-Za-z0-9+/]+={0,2})$")
AVATAR_MAX_BASE64_CHARS = 700_000  # ≈ 525 КБ декодированного изображения — с запасом


class UserCreate(BaseModel):
    username: str
    password: str
    confirm_password: str

    @field_validator("username")
    @classmethod
    def username_min_length(cls, v):
        if len(v) < 3:
            raise ValueError("Имя пользователя должно содержать минимум 3 символа")
        if len(v) > 32:
            raise ValueError("Имя пользователя должно содержать максимум 32 символа")
        if not USERNAME_RE.match(v):
            raise ValueError(
                "Имя пользователя может содержать только латинские буквы, цифры, _ и -"
            )
        return v

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v):
        if len(v) < 6:
            raise ValueError("Пароль долженминимум 6 символов")
        return v

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v, info):
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Пароли не совпадают")
        return v


class UserLogin(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def username_format(cls, v):
        if not USERNAME_RE.match(v):
            raise ValueError(
                "Имя пользователя может содержать только латинские буквы, цифры, _ и -"
            )
        return v


class UserResponse(BaseModel):
    id: str
    username: str
    role: str = "user"
    balance: float = 1000.0
    card_number: Optional[str] = None
    card_visible: bool = True
    avatar: str | None = None


class ProfileUpdate(BaseModel):
    """Самостоятельная смена никнейма (страница «Настройки»)."""
    username: str

    @field_validator("username")
    @classmethod
    def username_valid(cls, v):
        v = (v or "").strip()
        if len(v) < 3:
            raise ValueError("Имя пользователя должно содержать минимум 3 символа")
        if len(v) > 32:
            raise ValueError("Имя пользователя должно содержать максимум 32 символа")
        if not USERNAME_RE.match(v):
            raise ValueError(
                "Имя пользователя может содержать только латинские буквы, цифры, _ и -"
            )
        return v


class PasswordChangeRequest(BaseModel):
    """Смена пароля — требует подтверждения текущего пароля."""
    current_password: str
    new_password: str
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_min_length(cls, v):
        if len(v) < 6:
            raise ValueError("Новый пароль должен содержать минимум 6 символов")
        return v

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v, info):
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Пароли не совпадают")
        return v


class AvatarUpdate(BaseModel):
    """Аватар — data URL (canvas.toDataURL() на клиенте), хранится строкой в
    документе пользователя. Формат/размер валидируются здесь же."""
    avatar: str

    @field_validator("avatar")
    @classmethod
    def avatar_valid(cls, v):
        if not v or not AVATAR_DATA_URL_RE.match(v):
            raise ValueError("Некорректный формат изображения (нужны PNG/JPEG/WEBP)")
        if len(v) > AVATAR_MAX_BASE64_CHARS:
            raise ValueError("Изображение слишком большое — выберите файл поменьше")
        return v


class AuthResponse(UserResponse):
    """Ответ /api/register и /api/login: данные пользователя + пара токенов.

    response_model для этих эндпоинтов — гарантирует, что в ответ уходят
    только перечисленные здесь поля (например, hashed_password никогда не
    сможет случайно "утечь", даже если реализация эндпоинта изменится).
    """
    token: str
    refresh_token: str


class RefreshRequest(BaseModel):
    """Тело запроса для обновления/выхода: содержит сырой refresh-токен."""
    refresh_token: str


class TokenPair(BaseModel):
    """Ответ /api/auth/refresh: новая пара access + refresh токенов."""
    token: str
    refresh_token: str


class AdminUserUpdate(BaseModel):
    username: Optional[str] = None
    balance: Optional[float] = None
    role: Optional[str] = None
    card_number: Optional[str] = None

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v):
        if v is not None and v not in ("user", "admin"):
            raise ValueError("Роль может быть только 'user' или 'admin'")
        return v

    @field_validator("balance")
    @classmethod
    def balance_must_be_non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError("Баланс не может быть отрицательным")
        return v


# ── Stock Schemas ────────────────────────────────────────────────────────────


class StockCreate(BaseModel):
    symbol: str
    name: str
    price: float
    change: float = 0.0
    changePercent: float = 0.0
    currency: str = "USD"


class StockResponse(BaseModel):
    id: str
    symbol: str
    name: str
    price: float
    change: float
    changePercent: float
    currency: str
    updated_at: str


# ── Transaction Schemas ──────────────────────────────────────────────────────


class TransactionResponse(BaseModel):
    id: str
    userId: str
    type: str
    symbol: str
    amount: float
    price: float
    timestamp: str


# ── App Config Schemas ───────────────────────────────────────────────────────


class ConfigUpdate(BaseModel):
    key: str
    value: str


class ConfigResponse(BaseModel):
    key: str
    value: str
    updated_at: str


# ── Leaderboard Schemas ──────────────────────────────────────────────────────


class LeaderboardResponse(BaseModel):
    userId: str
    username: str
    avatar: Optional[str]
    profit: float
    rank: int


# ── Purchase Schemas ──────────────────────────────────────────────────────────


class PurchaseCreate(BaseModel):
    """Схема для создания покупки предмета в магазине."""

    item_id: str = ""
    item_name: str = ""
    item_category: str = "shop"
    price: float = 0.0
    quantity: int = 1

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_positive(cls, v):
        if v < 1:
            raise ValueError("Количество должно быть не менее 1")
        return v


class PurchaseResponse(BaseModel):
    id: str
    userId: str
    item_id: str
    item_name: str
    item_category: str
    price: float
    quantity: int
    total: float
    purchased_at: str


# ── Shop Price Schemas ───────────────────────────────────────────────────────


class ShopPriceUpdate(BaseModel):
    """Схема для обновления цен товаров."""
    prices: dict[str, Optional[float]]


class ShopPriceResponse(BaseModel):
    """Схема ответа с ценами товаров."""
    prices: dict[str, Optional[float]]
    updated_at: str
