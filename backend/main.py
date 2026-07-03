import bcrypt
import jwt
import os
import random
import secrets
from bson import ObjectId
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorDatabase

load_dotenv()

from init_db import init as init_db

from database import (
    get_db,
    get_stocks_collection,
    get_transactions_collection,
    get_app_config_collection,
    get_leaderboard_collection,
    find_all_stocks,
    find_stock_by_symbol,
    upsert_stock,
    find_transactions_by_user,
    find_config_by_key,
    upsert_config,
    find_leaderboard,
    find_all_transactions,
    delete_transaction,
    delete_stock_by_symbol,
    find_all_users,
)
from schemas import (
    UserCreate,
    UserLogin,
    UserResponse,
    AdminUserUpdate,
    StockCreate,
    StockResponse,
    TransactionResponse,
    ConfigUpdate,
    ConfigResponse,
    LeaderboardResponse,
)


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = get_db()
    await db.users.create_index("username", unique=True)
    await db.stocks.create_index("symbol", unique=True)
    await db.app_config.create_index("key", unique=True)
    await db.transactions.create_index("userId")
    await db.analytics.create_index("userId")
    await db.leaderboard.create_index("profit")
    # Refresh token indexes
    await db.refresh_tokens.create_index("user_id")
    await db.refresh_tokens.create_index("expires_at")
    # StockEngine indexes
    await db.stock_orders.create_index("userId")
    await db.stock_orders.create_index("symbol")
    await db.portfolios.create_index("userId", unique=True)
    await db.stock_events.create_index("symbol")
    await init_db()
    # Lazy import to avoid circular dependency
    from stock_engine.router import router as stocks_router
    app.include_router(stocks_router)
    # Start bot trading system
    from stock_engine.bot_trader import start_bot_trading, stop_bot_trading
    await start_bot_trading(db)
    yield
    await stop_bot_trading()


app = FastAPI(title="TradeVerse API", version="1.0.0", lifespan=lifespan)

# CORS — разрешаем запросы с frontend (Vite на порту 5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── JWT / Auth Helpers ───────────────────────────────────────────────────────

JWT_SECRET = os.getenv("JWT_SECRET", "tradeverse-dev-secret-change-in-prod")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 1          # Access token: 1 hour
REFRESH_EXPIRE_DAYS = 30      # Refresh token: 30 days

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(data: dict) -> str:
    """Создаёт JWT access-токен с полезной нагрузкой и сроком действия."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Декодирует и валидирует JWT-токен. Бросает исключение при ошибке."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def generate_refresh_token() -> str:
    """Генерирует криптографически стойкий refresh token (opaque)."""
    return secrets.token_urlsafe(64)


def hash_token(token: str) -> str:
    """Хеширует refresh token для безопасного хранения в БД."""
    # bcrypt имеет ограничение 72 байта — используем SHA256 для урезания
    import hashlib
    token_hashed = hashlib.sha256(token.encode("utf-8")).hexdigest()[:72]
    return bcrypt.hashpw(token_hashed.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_token(token: str, hashed: str) -> bool:
    """Проверяет refresh token против хеша из БД."""
    import hashlib
    token_hashed = hashlib.sha256(token.encode("utf-8")).hexdigest()[:72]
    return bcrypt.checkpw(token_hashed.encode("utf-8"), hashed.encode("utf-8"))


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
    if not user_id:
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


def get_users_collection(db: AsyncIOMotorDatabase = Depends(get_db)):
    return db.users


def generate_card_number() -> str:
    """Генерирует номер карты формата XXXX-XXXX-XXXX-XXXXX."""
    parts = [str(random.randint(1000, 9999)) for _ in range(3)]
    last = str(random.randint(10000, 99999))
    return "-".join(parts) + "-" + last


async def ensure_unique_card_number(users) -> str:
    """Генерирует уникальный номер карты, проверяя его в БД."""
    while True:
        card = generate_card_number()
        existing = await users.find_one({"card_number": card})
        if not existing:
            return card


# ── Auth Endpoints ───────────────────────────────────────────────────────────


@app.post(
    "/api/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
    user_data: UserCreate,
    users=Depends(get_users_collection),
):
    existing = await users.find_one({"username": user_data.username})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким именем уже существует",
        )

    card_number = await ensure_unique_card_number(users)

    new_user = {
        "username": user_data.username,
        "hashed_password": hash_password(user_data.password),
        "role": "user",
        "balance": 1000.0,
        "card_number": card_number,
        "card_visible": True,
    }
    result = await users.insert_one(new_user)
    return UserResponse(
        id=str(result.inserted_id),
        username=user_data.username,
        balance=1000.0,
        card_number=card_number,
        card_visible=True,
    )


@app.post("/api/login")
async def login_user(
    user_data: UserLogin,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    users = db.users
    user = await users.find_one({"username": user_data.username})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль",
        )

    if not verify_password(user_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль",
        )

    # Создаём JWT access-токен с id, username и role
    access_token = create_access_token({
        "sub": str(user["_id"]),
        "username": user["username"],
        "role": user.get("role", "user"),
    })

    # Создаём opaque refresh-токен и сохраняем его хеш в БД
    refresh_token = generate_refresh_token()
    refresh_hashed = hash_token(refresh_token)
    refresh_expires = datetime.now(timezone.utc) + timedelta(days=REFRESH_EXPIRE_DAYS)
    await db.refresh_tokens.insert_one({
        "user_id": str(user["_id"]),
        "token_hash": refresh_hashed,
        "expires_at": refresh_expires,
    })

    return {
        "id": str(user["_id"]),
        "username": user["username"],
        "role": user.get("role", "user"),
        "balance": user.get("balance", 1000.0),
        "card_number": user.get("card_number"),
        "card_visible": user.get("card_visible", True),
        "token": access_token,
        "refresh_token": refresh_token,
    }


@app.post("/api/auth/refresh")
async def refresh_access_token(
    body: dict,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Обменивает refresh-токен на новую пару access + refresh токенов."""
    refresh_token = body.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Отсутствует refresh-токен",
        )

    now = datetime.now(timezone.utc)
    # Ищем хеш, соответствующий данному refresh-токену
    stored = None
    async for doc in db.refresh_tokens.find({"expires_at": {"$gt": now}}):
        if verify_token(refresh_token, doc["token_hash"]):
            stored = doc
            break

    if not stored:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или истёкший refresh-токен",
        )

    user_id = stored["user_id"]
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден",
        )

    # Удаляем старый refresh-токен (rotation — каждый токен используется один раз)
    await db.refresh_tokens.delete_one({"_id": stored["_id"]})

    # Генерируем новую пару
    access_token = create_access_token({
        "sub": str(user["_id"]),
        "username": user["username"],
        "role": user.get("role", "user"),
    })
    new_refresh = generate_refresh_token()
    new_hashed = hash_token(new_refresh)
    new_expires = now + timedelta(days=REFRESH_EXPIRE_DAYS)
    await db.refresh_tokens.insert_one({
        "user_id": str(user["_id"]),
        "token_hash": new_hashed,
        "expires_at": new_expires,
    })

    return {
        "token": access_token,
        "refresh_token": new_refresh,
    }


@app.post("/api/auth/logout")
async def logout_user(
    body: dict,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Инвалидирует refresh-токен (logout)."""
    refresh_token = body.get("refresh_token")
    if refresh_token:
        now = datetime.now(timezone.utc)
        async for doc in db.refresh_tokens.find({"expires_at": {"$gt": now}}):
            if verify_token(refresh_token, doc["token_hash"]):
                await db.refresh_tokens.delete_one({"_id": doc["_id"]})
                break
    return {"detail": "ok"}


@app.get("/api/user/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Возвращает полные данные текущего пользователя (из БД)."""
    return {
        "id": str(current_user["_id"]),
        "username": current_user["username"],
        "role": current_user.get("role", "user"),
        "balance": current_user.get("balance", 1000.0),
        "card_number": current_user.get("card_number"),
        "card_visible": current_user.get("card_visible", True),
    }


@app.patch("/api/user/card-visibility")
async def toggle_card_visibility(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Переключает видимость Tradeverse Card (сохраняет в БД)."""
    new_visible = not current_user.get("card_visible", True)
    await db.users.update_one(
        {"_id": ObjectId(current_user["_id"])},
        {"$set": {"card_visible": new_visible}},
    )
    return {"card_visible": new_visible}


# ── Stocks Endpoints ─────────────────────────────────────────────────────────


@app.get("/api/stocks", response_model=list[StockResponse])
async def get_stocks(db: AsyncIOMotorDatabase = Depends(get_db)):
    stocks = await find_all_stocks(db)
    return [_format_stock(s) for s in stocks]


@app.get("/api/stocks/{symbol}", response_model=StockResponse)
async def get_stock(
    symbol: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    stock = await find_stock_by_symbol(db, symbol)
    if not stock:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stock '{symbol}' not found",
        )
    return _format_stock(stock)


@app.post(
    "/api/stocks",
    response_model=StockResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_or_update_stock(
    stock_data: StockCreate,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    stock = await upsert_stock(db, stock_data.model_dump())
    return _format_stock(stock)


# ── Transactions Endpoints ───────────────────────────────────────────────────


@app.get("/api/account/transactions", response_model=list[TransactionResponse])
async def get_user_transactions(
    user_id: str = Query(None, description="User ID"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    transactions = await find_transactions_by_user(db, user_id, limit)
    return [_format_transaction(t) for t in transactions]


# ── App Config Endpoints ─────────────────────────────────────────────────────


DEFAULT_CONFIG = {
    "sidebar_menu": '{"items":["account","bank","shop","events","crypto","stocks","realestate","myhomes","mybusiness","mycompany","leaderboard"]}',
    "header_title": "TradeVerse",
    "app_version": "1.0.0",
}

@app.get("/api/config/{key}", response_model=ConfigResponse)
async def get_config(
    key: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    config = await find_config_by_key(db, key)
    if not config:
        if key in DEFAULT_CONFIG:
            return _format_config({"key": key, "value": DEFAULT_CONFIG[key], "updated_at": datetime.utcnow()})
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Config key '{key}' not found",
        )
    return _format_config(config)


@app.post("/api/config", response_model=ConfigResponse)
async def update_config(
    config_data: ConfigUpdate,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    config = await upsert_config(db, config_data.key, config_data.value)
    return _format_config(config)


# ── Leaderboard Endpoints ────────────────────────────────────────────────────


@app.get("/api/leaderboard", response_model=list[LeaderboardResponse])
async def get_leaderboard(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    entries = await find_leaderboard(db, limit)
    return [_format_leaderboard(e) for e in entries]


# ── Admin Endpoints ──────────────────────────────────────────────────────────


@app.delete("/api/stocks/{symbol}")
async def admin_delete_stock(
    symbol: str,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    deleted = await delete_stock_by_symbol(db, symbol)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stock '{symbol}' not found",
        )
    return {"message": f"Stock '{symbol}' deleted"}


@app.get("/api/admin/users")
async def admin_get_users(
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    users = await find_all_users(db)
    return users


@app.patch("/api/admin/users/{user_id}")
async def admin_update_user(
    user_id: str,
    update_data: AdminUserUpdate,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Редактирование пользователя администратором."""
    if not ObjectId.is_valid(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Некорректный ID пользователя",
        )

    existing = await db.users.find_one({"_id": ObjectId(user_id)})
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        )

    # Формируем $set только из переданных полей
    update_fields = update_data.model_dump(exclude_unset=True)

    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нет полей для обновления",
        )

    # Проверяем уникальность username, если он меняется
    if "username" in update_fields:
        duplicate = await db.users.find_one({
            "username": update_fields["username"],
            "_id": {"$ne": ObjectId(user_id)},
        })
        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Пользователь с таким именем уже существует",
            )

    # Запрещённые поля не попадут в update_fields благодаря схеме AdminUserUpdate
    print(f"[ADMIN] Updating user {user_id}: {update_fields} (by admin {_admin.get('username', 'unknown')})")

    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": update_fields},
    )

    # Возвращаем обновлённого пользователя
    updated_user = await db.users.find_one({"_id": ObjectId(user_id)})
    updated_user["id"] = str(updated_user.pop("_id"))
    updated_user.pop("hashed_password", None)
    updated_user["role"] = updated_user.get("role", "user")
    return updated_user


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(
    user_id: str,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Удаление пользователя администратором."""
    if not ObjectId.is_valid(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Некорректный ID пользователя",
        )

    existing = await db.users.find_one({"_id": ObjectId(user_id)})
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        )

    print(f"[ADMIN] Deleting user {user_id} ({existing.get('username', 'unknown')}) (by admin {_admin.get('username', 'unknown')})")

    await db.users.delete_one({"_id": ObjectId(user_id)})
    return {"message": f"Пользователь {existing.get('username', user_id)} удалён"}


@app.get("/api/admin/transactions")
async def admin_get_all_transactions(
    limit: int = Query(200, ge=1, le=500),
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    transactions = await find_all_transactions(db, limit)
    return [_format_transaction(t) for t in transactions]


@app.delete("/api/admin/transactions/{tx_id}")
async def admin_delete_transaction(
    tx_id: str,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    deleted = await delete_transaction(db, tx_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction '{tx_id}' not found",
        )
    return {"message": f"Transaction '{tx_id}' deleted"}


# ── Health Check ─────────────────────────────────────────────────────────────


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


# ── Formatters ───────────────────────────────────────────────────────────────


def _format_stock(stock: dict) -> dict:
    return {
        "id": stock.get("id", ""),
        "symbol": stock["symbol"],
        "name": stock["name"],
        "price": stock["price"],
        "change": stock.get("change", 0.0),
        "changePercent": stock.get("changePercent", 0.0),
        "currency": stock.get("currency", "USD"),
        "updated_at": _serialize_datetime(stock.get("updated_at")),
    }


def _format_transaction(tx: dict) -> dict:
    return {
        "id": tx.get("id", ""),
        "userId": tx["userId"],
        "type": tx["type"],
        "symbol": tx["symbol"],
        "amount": tx["amount"],
        "price": tx["price"],
        "timestamp": _serialize_datetime(tx.get("timestamp")),
    }


def _format_config(config: dict) -> dict:
    return {
        "key": config["key"],
        "value": config["value"],
        "updated_at": _serialize_datetime(config.get("updated_at")),
    }


def _format_leaderboard(entry: dict) -> dict:
    return {
        "userId": entry["userId"],
        "username": entry["username"],
        "avatar": entry.get("avatar"),
        "profit": entry.get("profit", 0.0),
        "rank": entry.get("rank", 0),
    }


def _serialize_datetime(dt: Optional[datetime]) -> str:
    if isinstance(dt, datetime):
        return dt.isoformat()
    return ""


# ── Entry Point ──────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
