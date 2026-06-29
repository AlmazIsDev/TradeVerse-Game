import re

from pydantic import BaseModel, field_validator

USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


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
    card_number: str | None = None
    card_visible: bool = True


class AdminUserUpdate(BaseModel):
    username: str | None = None
    balance: float | None = None
    role: str | None = None
    card_number: str | None = None

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
    avatar: str | None
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
