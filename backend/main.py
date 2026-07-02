import bcrypt
import jwt
import logging
import os
import random
from bson import ObjectId
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("tradeverse")

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
    StockTradeRequest,
    StockConfigUpdate,
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
    # v2 trading engine
    await db.holdings.create_index([("userId", 1), ("symbol", 1)], unique=True)
    await db.stock_events.create_index("symbol")
    await db.stock_events.create_index("timestamp")
    await init_db()
    yield


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

_JWT_DEFAULT_SECRET = "tradeverse-dev-secret-change-in-prod"
JWT_SECRET = os.getenv("JWT_SECRET", _JWT_DEFAULT_SECRET)
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

if JWT_SECRET == _JWT_DEFAULT_SECRET:
    logger.warning(
        "JWT_SECRET не задан — используется небезопасное значение по умолчанию. "
        "Установите переменную окружения JWT_SECRET перед развёртыванием в production."
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
    users=Depends(get_users_collection),
):
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

    # Создаём JWT-токен с id, username и role
    token = create_access_token({
        "sub": str(user["_id"]),
        "username": user["username"],
        "role": user.get("role", "user"),
    })

    return {
        "id": str(user["_id"]),
        "username": user["username"],
        "role": user.get("role", "user"),
        "balance": user.get("balance", 1000.0),
        "card_number": user.get("card_number"),
        "card_visible": user.get("card_visible", True),
        "token": token,
    }


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


# ── Stocks V2: Trading Engine ────────────────────────────────────────────────
#
# Динамический рынок акций: цена реагирует на объём сделок по формуле
#   ΔP = Price × K × (Quantity / TotalShares)
# Покупка двигает цену вверх и уменьшает пул свободных акций, продажа — наоборот.
# Сделки атомарны: баланс и пул свободных акций защищены условными $inc-обновлениями.

DEFAULT_STOCK_CONFIG = {
    "volatility_k": 0.1,
    "total_shares": 1_000_000_000,
    "price_drop_threshold": -0.05,
    "price_rise_threshold": 0.10,
    "max_order_size_percent": 0.01,
}


def _resolve_stock_config(stock: dict) -> dict:
    """Сливает дефолтный конфиг с overrides конкретной акции."""
    cfg = dict(DEFAULT_STOCK_CONFIG)
    for key, value in (stock.get("config") or {}).items():
        if value is not None:
            cfg[key] = value
    return cfg


def _format_stock_v2(stock: dict) -> dict:
    cfg = _resolve_stock_config(stock)
    base = _format_stock(stock)
    base["freeShares"] = stock.get("free_shares", cfg["total_shares"])
    base["configOverrides"] = stock.get("config") or {}
    return base


@app.get("/api/v2/stocks")
async def get_stocks_v2(db: AsyncIOMotorDatabase = Depends(get_db)):
    stocks = await find_all_stocks(db)
    return [_format_stock_v2(s) for s in stocks]


@app.get("/api/v2/stocks/portfolio")
async def get_portfolio(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Текущие позиции пользователя с рыночной оценкой и P&L."""
    user_id = str(current_user["_id"])
    positions = []
    cursor = db.holdings.find({"userId": user_id, "quantity": {"$gt": 0}})
    async for h in cursor:
        stock = await db.stocks.find_one({"symbol": h["symbol"]})
        price = float(stock["price"]) if stock else 0.0
        qty = h.get("quantity", 0)
        invested = h.get("invested", 0.0)
        value = round(price * qty, 2)
        positions.append({
            "symbol": h["symbol"],
            "name": stock.get("name", h["symbol"]) if stock else h["symbol"],
            "quantity": qty,
            "avgPrice": round(invested / qty, 2) if qty else 0.0,
            "currentPrice": price,
            "value": value,
            "pnl": round(value - invested, 2),
        })
    return positions


@app.get("/api/v2/stocks/orders", response_model=list[TransactionResponse])
async def get_stock_orders(
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """История ордеров текущего пользователя (те же документы, что и транзакции)."""
    txs = await find_transactions_by_user(db, str(current_user["_id"]), limit)
    return [_format_transaction(t) for t in txs]


@app.get("/api/v2/stocks/events")
async def get_stock_events(
    symbol: str = Query(None, description="Фильтр по символу акции"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Лента рыночных событий (движения цены от сделок)."""
    query = {"symbol": symbol.upper()} if symbol else {}
    events = []
    cursor = db.stock_events.find(query).sort("timestamp", -1).limit(limit)
    async for e in cursor:
        events.append({
            "id": str(e.pop("_id")),
            "symbol": e.get("symbol"),
            "type": e.get("type"),
            "quantity": e.get("quantity"),
            "priceBefore": e.get("priceBefore"),
            "priceAfter": e.get("priceAfter"),
            "timestamp": _serialize_datetime(e.get("timestamp")),
        })
    return events


@app.post("/api/v2/stocks/trade")
async def trade_stock(
    trade: StockTradeRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Покупка/продажа акций с атомарным изменением баланса и цены."""
    symbol = trade.symbol  # уже .upper() из валидатора
    action = trade.action
    quantity = trade.quantity

    stock = await db.stocks.find_one({"symbol": symbol})
    if not stock:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Stock '{symbol}' not found")

    cfg = _resolve_stock_config(stock)
    total_shares = cfg["total_shares"]
    price = float(stock["price"])
    cost = round(price * quantity, 2)
    user_id = current_user["_id"]

    # Ленивая инициализация пула свободных акций для старых записей.
    if "free_shares" not in stock:
        await db.stocks.update_one(
            {"symbol": symbol, "free_shares": {"$exists": False}},
            {"$set": {"free_shares": total_shares}},
        )

    # Ограничение размера ордера (защита от манипуляций).
    max_qty = int(total_shares * cfg["max_order_size_percent"])
    if max_qty >= 1 and quantity > max_qty:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Ордер превышает максимальный размер ({max_qty} акций)",
        )

    # Движение цены от объёма сделки.
    delta = price * cfg["volatility_k"] * (quantity / total_shares) if total_shares else 0.0

    if action == "buy":
        # 1) Атомарно списываем средства только при достаточном балансе.
        updated_user = await db.users.find_one_and_update(
            {"_id": user_id, "balance": {"$gte": cost}},
            {"$inc": {"balance": -cost}},
            return_document=ReturnDocument.AFTER,
        )
        if not updated_user:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств на балансе")

        # 2) Атомарно резервируем акции из свободного пула + двигаем цену вверх.
        new_price = round(price + delta, 2)
        updated_stock = await db.stocks.find_one_and_update(
            {"symbol": symbol, "free_shares": {"$gte": quantity}},
            {
                "$inc": {"free_shares": -quantity},
                "$set": {
                    "price": new_price,
                    "change": round(new_price - price, 2),
                    "changePercent": round((new_price - price) / price * 100, 2) if price else 0.0,
                    "updated_at": datetime.now(timezone.utc),
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if not updated_stock:
            # Компенсируем списание, если акций не хватило.
            await db.users.update_one({"_id": user_id}, {"$inc": {"balance": cost}})
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно свободных акций")

        await db.holdings.update_one(
            {"userId": str(user_id), "symbol": symbol},
            {
                "$inc": {"quantity": quantity, "invested": cost},
                "$setOnInsert": {"userId": str(user_id), "symbol": symbol},
            },
            upsert=True,
        )
        new_balance = updated_user["balance"]

    else:  # sell
        # 1) Атомарно списываем акции из позиции пользователя.
        updated_holding = await db.holdings.find_one_and_update(
            {"userId": str(user_id), "symbol": symbol, "quantity": {"$gte": quantity}},
            {"$inc": {"quantity": -quantity, "invested": -cost}},
            return_document=ReturnDocument.AFTER,
        )
        if not updated_holding:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно акций для продажи")

        # 2) Начисляем выручку и возвращаем акции в свободный пул + двигаем цену вниз.
        updated_user = await db.users.find_one_and_update(
            {"_id": user_id},
            {"$inc": {"balance": cost}},
            return_document=ReturnDocument.AFTER,
        )
        new_price = round(max(0.01, price - delta), 2)
        await db.stocks.update_one(
            {"symbol": symbol},
            {
                "$inc": {"free_shares": quantity},
                "$set": {
                    "price": new_price,
                    "change": round(new_price - price, 2),
                    "changePercent": round((new_price - price) / price * 100, 2) if price else 0.0,
                    "updated_at": datetime.now(timezone.utc),
                },
            },
        )
        new_balance = updated_user["balance"] if updated_user else current_user.get("balance", 0.0)

    # История сделки (общая коллекция с v1-транзакциями → видна в Account/Bank).
    tx_result = await db.transactions.insert_one({
        "userId": str(user_id),
        "type": action,
        "symbol": symbol,
        "amount": quantity,
        "price": price,
        "timestamp": datetime.now(timezone.utc),
    })

    # Рыночное событие.
    await db.stock_events.insert_one({
        "symbol": symbol,
        "type": action,
        "quantity": quantity,
        "priceBefore": price,
        "priceAfter": new_price,
        "userId": str(user_id),
        "timestamp": datetime.now(timezone.utc),
    })

    return {
        "success": True,
        "orderId": str(tx_result.inserted_id),
        "symbol": symbol,
        "action": action,
        "quantity": quantity,
        "price": price,
        "total": cost,
        "newPrice": new_price,
        "balance": new_balance,
    }


@app.patch("/api/v2/stocks/{symbol}/config")
async def update_stock_config_v2(
    symbol: str,
    config_update: StockConfigUpdate,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Обновляет overrides конфигурации рынка для конкретной акции (admin)."""
    symbol = symbol.upper()
    stock = await db.stocks.find_one({"symbol": symbol})
    if not stock:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Stock '{symbol}' not found")

    fields = config_update.model_dump(exclude_unset=True)
    if fields:
        set_ops = {f"config.{k}": v for k, v in fields.items()}
        set_ops["updated_at"] = datetime.now(timezone.utc)
        await db.stocks.update_one({"symbol": symbol}, {"$set": set_ops})

    updated = await find_stock_by_symbol(db, symbol)
    return _format_stock_v2(updated)


@app.get("/api/v2/stocks/{symbol}")
async def get_stock_v2(
    symbol: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    stock = await find_stock_by_symbol(db, symbol)
    if not stock:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Stock '{symbol}' not found")
    return _format_stock_v2(stock)


# ── Transactions Endpoints ───────────────────────────────────────────────────


@app.get("/api/account/transactions", response_model=list[TransactionResponse])
async def get_user_transactions(
    user_id: str = Query(None, description="User ID (admins only; ignored for regular users)"),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    # Защита от IDOR: обычный пользователь видит только свои транзакции.
    # Администратор может явно запросить транзакции конкретного пользователя.
    if current_user.get("role") == "admin" and user_id:
        target_user_id = user_id
    else:
        target_user_id = str(current_user["_id"])
    transactions = await find_transactions_by_user(db, target_user_id, limit)
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
            return _format_config({"key": key, "value": DEFAULT_CONFIG[key], "updated_at": datetime.now(timezone.utc)})
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


STARTING_BALANCE = 1000.0


@app.get("/api/leaderboard", response_model=list[LeaderboardResponse])
async def get_leaderboard(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Живой рейтинг по чистой стоимости активов (баланс + рыночная стоимость позиций)."""
    # Карта текущих цен акций.
    price_map: dict[str, float] = {}
    async for s in db.stocks.find({}, {"symbol": 1, "price": 1}):
        price_map[s["symbol"]] = float(s.get("price", 0.0))

    # Суммарная рыночная стоимость позиций по каждому пользователю.
    holdings_value: dict[str, float] = {}
    async for h in db.holdings.find({"quantity": {"$gt": 0}}):
        uid = h.get("userId")
        holdings_value[uid] = holdings_value.get(uid, 0.0) + (
            h.get("quantity", 0) * price_map.get(h.get("symbol"), 0.0)
        )

    entries = []
    async for u in db.users.find({}):
        uid = str(u["_id"])
        balance = float(u.get("balance", STARTING_BALANCE))
        net_worth = round(balance + holdings_value.get(uid, 0.0), 2)
        entries.append({
            "userId": uid,
            "username": u.get("username", "—"),
            "avatar": None,
            "profit": round(net_worth - STARTING_BALANCE, 2),
            "netWorth": net_worth,
        })

    entries.sort(key=lambda e: e["netWorth"], reverse=True)
    entries = entries[:limit]
    for rank, entry in enumerate(entries, start=1):
        entry["rank"] = rank
    return entries


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
    logger.info(
        "Admin '%s' updating user %s: fields=%s",
        _admin.get("username", "unknown"), user_id, list(update_fields.keys()),
    )

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

    logger.info(
        "Admin '%s' deleting user %s (%s)",
        _admin.get("username", "unknown"), user_id, existing.get("username", "unknown"),
    )

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
