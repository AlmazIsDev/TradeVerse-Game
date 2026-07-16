import logging
import random
from bson import ObjectId
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from dotenv import load_dotenv
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorDatabase

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("tradeverse")

from init_db import init as init_db

from auth import (
    get_current_user,
    require_admin,
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    use_refresh_token,
    delete_refresh_token,
)
from economy import router as economy_router
from crypto import router as crypto_router
from stocks import router as stocks_router
from assets import router as assets_router
from company import router as company_router
from user_profile import router as user_profile_router
from cityroof import router as cityroof_router
from notifications import router as notifications_router
from market_data import router as market_router
from econ import router as econ_router
from market_events import router as events_router
from shop import router as shop_router
from mining import router as mining_router
from media import router as media_router
from ws import router as ws_router
from scheduler import start_scheduler, stop_scheduler

import assets as assets_module
import mining as mining_module
import company as company_module
import cityroof as cityroof_module

from database import (
    get_db,
    find_all_stocks,
    find_stock_by_symbol,
    upsert_stock,
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
    AuthResponse,
    RefreshRequest,
    TokenPair,
    AdminUserUpdate,
    StockCreate,
    StockResponse,
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
    await db.transactions.create_index([("userId", 1), ("timestamp", -1)])
    await db.analytics.create_index("userId")
    await db.leaderboard.create_index("profit")
    await db.crypto_assets.create_index("symbol", unique=True)
    await db.crypto_holdings.create_index([("userId", 1), ("symbol", 1)], unique=True)
    await db.crypto_transfers.create_index("fromId")
    await db.crypto_transfers.create_index("toId")
    await db.stock_holdings.create_index([("userId", 1), ("symbol", 1)], unique=True)
    await db.stock_events.create_index("symbol")
    await db.stock_events.create_index("timestamp")
    await db.user_assets.create_index("userId")
    await db.asset_market.create_index("slug", unique=True)
    await db.companies.create_index("ownerId", unique=True)
    await db.company_members.create_index([("companyId", 1), ("userId", 1)])
    await db.company_members.create_index("userId")
    await db.company_invites.create_index("toUserId")
    await db.company_applications.create_index("ownerId")
    await db.company_applications.create_index("applicantId")
    await db.notifications.create_index([("userId", 1), ("created_at", -1)])
    await db.price_history.create_index([("market", 1), ("symbol", 1), ("ts", 1)])
    await db.user_favorites.create_index([("userId", 1), ("market", 1), ("symbol", 1)])
    await db.market_meta.create_index("market", unique=True)
    await db.market_events.create_index("active")
    await db.user_hardware.create_index("userId")
    await db.user_hardware.create_index("farmId")
    await db.mining_farms.create_index("userId")
    await db.mining_farms.create_index("status")
    await db.cityroof_sessions.create_index("attackerId")
    await db.cityroof_seasons.create_index("closed_at")
    await db.cityroof_itstudio_jobs.create_index("orderedBy")
    await db.cityroof_itstudio_jobs.create_index([("status", 1), ("ready_at", 1)])
    await db.cityroof_itstudio_jobs.create_index([("studioAssetId", 1), ("status", 1)])
    # Refresh-токены: уникальный индекс по хешу + TTL для авто-очистки истёкших.
    await db.refresh_tokens.create_index("token_hash", unique=True)
    await db.refresh_tokens.create_index("expires_at", expireAfterSeconds=0)
    await init_db()
    start_scheduler()   # единый фоновый планировщик всех систем
    yield
    await stop_scheduler()


app = FastAPI(title="TradeVerse API", version="1.0.0", lifespan=lifespan)

# CORS — разрешаем запросы с frontend (прод-домен + локальная разработка)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://tradeverse.weissx.net",   # прод-фронтенд
        "http://localhost:20300",          # локальный vite (dev/preview)
        "http://localhost:5173",           # локальный vite (дефолтный порт)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Роутеры модулей
app.include_router(economy_router)
app.include_router(crypto_router)
app.include_router(stocks_router)
app.include_router(assets_router)
app.include_router(company_router)
app.include_router(user_profile_router)
app.include_router(cityroof_router)
app.include_router(notifications_router)
app.include_router(market_router)
app.include_router(econ_router)
app.include_router(events_router)
app.include_router(shop_router)
app.include_router(mining_router)
app.include_router(media_router)
app.include_router(ws_router)


# ── App-specific helpers ─────────────────────────────────────────────────────


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


async def issue_token_pair(db: AsyncIOMotorDatabase, user: dict) -> tuple[str, str]:
    """Выдаёт (access_token, refresh_token) для пользователя.

    Единая точка выдачи токенов — используется register/login/refresh, чтобы
    состав payload JWT не приходилось синхронизировать вручную в трёх местах.
    """
    token = create_access_token({
        "sub": str(user["_id"]),
        "username": user["username"],
        "role": user.get("role", "user"),
    })
    refresh_token = await create_refresh_token(db, user["_id"])
    return token, refresh_token


# ── Auth Endpoints ───────────────────────────────────────────────────────────


@app.post("/api/register", status_code=status.HTTP_201_CREATED, response_model=AuthResponse)
async def register_user(
    user_data: UserCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    users = db.users
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
        "balance": STARTING_BALANCE,
        "card_number": card_number,
        "card_visible": True,
        "avatar": None,
        "created_at": datetime.now(timezone.utc),
    }
    result = await users.insert_one(new_user)
    new_user["_id"] = result.inserted_id

    # Авто-логин: сразу выдаём access- и refresh-токены (та же форма, что у /api/login).
    token, refresh_token = await issue_token_pair(db, new_user)

    return {
        "id": str(result.inserted_id),
        "username": user_data.username,
        "role": "user",
        "balance": STARTING_BALANCE,
        "card_number": card_number,
        "card_visible": True,
        "token": token,
        "refresh_token": refresh_token,
    }


@app.post("/api/login", response_model=AuthResponse)
async def login_user(
    user_data: UserLogin,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    user = await db.users.find_one({"username": user_data.username})
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

    token, refresh_token = await issue_token_pair(db, user)

    return {
        "id": str(user["_id"]),
        "username": user["username"],
        "role": user.get("role", "user"),
        "balance": user.get("balance", 1000.0),
        "card_number": user.get("card_number"),
        "card_visible": user.get("card_visible", True),
        "avatar": user.get("avatar"),
        "token": token,
        "refresh_token": refresh_token,
    }


@app.post("/api/auth/refresh", response_model=TokenPair)
async def refresh_tokens(
    body: RefreshRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Ротация refresh-токена: выдаёт новую пару токенов, сбрасывая 30-дневный срок.

    Старый refresh-токен атомарно находится и удаляется одним запросом
    (см. use_refresh_token) — это гарантирует, что при двух параллельных
    запросах с одним и тем же refresh-токеном (например, две открытые вкладки)
    ротацию совершит только один из них, а не оба.
    """
    doc = await use_refresh_token(db, body.refresh_token)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или истёкший refresh-токен",
        )

    user = await db.users.find_one({"_id": doc["user_id"]})
    if not user:
        # Пользователь удалён, а осиротевший токен уже удалён выше.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден",
        )

    token, new_refresh = await issue_token_pair(db, user)

    return {"token": token, "refresh_token": new_refresh}


@app.post("/api/auth/logout")
async def logout(
    body: RefreshRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Выход: удаляет refresh-токен. Идемпотентно — 200 даже если токен не найден.

    Не требует валидного access-токена: пользователь может выходить с истёкшим.
    """
    await delete_refresh_token(db, body.refresh_token)
    return {"message": "Выход выполнен"}


@app.get("/api/user/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Возвращает полные данные текущего пользователя (из БД)."""
    created_at = current_user.get("created_at")
    return {
        "id": str(current_user["_id"]),
        "username": current_user["username"],
        "role": current_user.get("role", "user"),
        "balance": current_user.get("balance", 1000.0),
        "card_number": current_user.get("card_number"),
        "card_visible": current_user.get("card_visible", True),
        "crypto_account_opened": bool(current_user.get("crypto_account_opened", False)),
        "avatar": current_user.get("avatar"),
        "hideFromLeaderboard": bool(current_user.get("hidden_from_leaderboard", False)),
        "leaderboardLock": bool(current_user.get("leaderboard_lock", False)),
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else None,
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


# NOTE: история операций текущего пользователя теперь в economy.router
# (GET /api/account/transactions, JWT-scoped, с фильтром/поиском/пагинацией).


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


STARTING_BALANCE = 15000.0
WARCOIN_USD = 50.0

# Ключ сортировки → реальное имя поля в записи лидерборда (camelCase).
# ВАЖНО: 'networth' маппится на 'netWorth' — иначе e[sort_key] бросал KeyError,
# что и было причиной «ошибки подключения» в разделе «По капиталу».
_LEADERBOARD_SORT_FIELD = {
    "networth": "netWorth", "profit": "profit", "cash": "cash",
    "stocks": "stocks", "crypto": "crypto", "assets": "assets", "company": "company",
}


# Кэш рассчитанного лидерборда (общий для всех сортировок — сортировка/срез
# делаются на готовом списке). Тяжёлый обсчёт по всем игрокам не выполняется
# на каждый запрос, что ускоряет загрузку любого лидерборда.
_LB_CACHE: dict = {"ts": None, "entries": None}
_LB_CACHE_TTL_S = 12


async def _compute_leaderboard_entries(db: AsyncIOMotorDatabase) -> list[dict]:
    """Полный обсчёт капитала всех игроков (наличные + акции + крипта + активы + компания + WC)."""
    # Карты текущих цен.
    stock_prices: dict[str, float] = {}
    async for s in db.stocks.find({}, {"symbol": 1, "price": 1}):
        stock_prices[s["symbol"]] = float(s.get("price", 0.0))
    crypto_prices: dict[str, float] = {}
    async for c in db.crypto_assets.find({}, {"symbol": 1, "price": 1}):
        crypto_prices[c["symbol"]] = float(c.get("price", 0.0))

    # Стоимость позиций по игрокам.
    stock_val: dict[str, float] = {}
    async for h in db.stock_holdings.find({"quantity": {"$gt": 0}}):
        uid = h.get("userId")
        stock_val[uid] = stock_val.get(uid, 0.0) + h.get("quantity", 0) * stock_prices.get(h.get("symbol"), 0.0)
    crypto_val: dict[str, float] = {}
    async for h in db.crypto_holdings.find({"quantity": {"$gt": 0}}):
        uid = h.get("userId")
        crypto_val[uid] = crypto_val.get(uid, 0.0) + h.get("quantity", 0.0) * crypto_prices.get(h.get("symbol"), 0.0)

    # Стоимость личных физических активов (недвижимость/бизнес/авто), кроме переданных компании.
    def _asset_value(a: dict) -> float:
        return a.get("price", 0) * (1 + 0.35 * (a.get("level", 1) - 1))

    asset_val: dict[str, float] = {}
    async for a in db.user_assets.find({"companyId": None}):
        uid = a.get("userId")
        asset_val[uid] = asset_val.get(uid, 0.0) + _asset_value(a)

    # Компании: бюджет + рыночная стоимость активов компании → в капитал владельца.
    company_owner: dict[str, str] = {}
    company_val: dict[str, float] = {}
    async for c in db.companies.find({}):
        oid = c.get("ownerId")
        company_owner[str(c["_id"])] = oid
        company_val[oid] = company_val.get(oid, 0.0) + float(c.get("budget", 0.0))
    async for a in db.user_assets.find({"companyId": {"$ne": None}}):
        oid = company_owner.get(a.get("companyId"))
        if oid:
            company_val[oid] = company_val.get(oid, 0.0) + _asset_value(a)

    entries = []
    async for u in db.users.find({"hidden_from_leaderboard": {"$ne": True}}):
        uid = str(u["_id"])
        cash = float(u.get("balance", STARTING_BALANCE))
        stocks_value = round(stock_val.get(uid, 0.0), 2)
        crypto_value = round(crypto_val.get(uid, 0.0), 2)
        assets_value = round(asset_val.get(uid, 0.0), 2)
        company_value = round(company_val.get(uid, 0.0), 2)
        warcoin_value = round(float(u.get("warcoin", 0) or 0) * WARCOIN_USD, 2)
        net_worth = round(cash + stocks_value + crypto_value + assets_value + company_value + warcoin_value, 2)
        entries.append({
            "userId": uid,
            "username": u.get("username", "—"),
            "avatar": u.get("avatar"),
            "cash": round(cash, 2),
            "stocks": stocks_value,
            "crypto": crypto_value,
            "assets": assets_value,
            "company": company_value,
            "warcoin": warcoin_value,
            "netWorth": net_worth,
            "profit": round(net_worth - STARTING_BALANCE, 2),
        })
    return entries


@app.get("/api/leaderboard")
async def get_leaderboard(
    limit: int = Query(20, ge=1, le=100),
    sort: str = Query("networth"),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Живой рейтинг игроков по чистой стоимости активов.

    net worth = наличные + акции + крипта + активы + компания + WarCoin.
    Сортировки: networth | profit | cash | stocks | crypto | assets | company.
    Результат кэшируется на короткое время (см. _LB_CACHE_TTL_S).
    """
    sort_field = _LEADERBOARD_SORT_FIELD.get(sort, "netWorth")

    now_ts = datetime.now(timezone.utc)
    cached, cached_ts = _LB_CACHE["entries"], _LB_CACHE["ts"]
    if cached is not None and isinstance(cached_ts, datetime) and (now_ts - cached_ts).total_seconds() < _LB_CACHE_TTL_S:
        entries = cached
    else:
        entries = await _compute_leaderboard_entries(db)
        _LB_CACHE["entries"] = entries
        _LB_CACHE["ts"] = now_ts

    ranked = sorted(entries, key=lambda e: e.get(sort_field, 0.0), reverse=True)[:limit]
    # Копируем и проставляем ранг, не мутируя кэш.
    out = []
    for rank, entry in enumerate(ranked, start=1):
        out.append({**entry, "rank": rank})
    return out


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
    logger.info("Admin '%s' updating user %s: fields=%s",
                _admin.get("username", "unknown"), user_id, list(update_fields.keys()))

    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": update_fields},
    )

    # Возвращаем обновлённого пользователя
    updated_user = await db.users.find_one({"_id": ObjectId(user_id)})
    updated_user["id"] = str(updated_user.pop("_id"))
    updated_user.pop("hashed_password", None)
    updated_user["role"] = updated_user.get("role", "user")

    # Живое обновление списка пользователей у других открытых админ-панелей —
    # только админам, не всем игрокам (см. push_to_admins).
    try:
        from ws import push_to_admins
        await push_to_admins(db, {"type": "admin_user_modified", "userId": user_id})
    except Exception:
        pass

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

    logger.info("Admin '%s' deleting user %s (%s)",
                _admin.get("username", "unknown"), user_id, existing.get("username", "unknown"))

    await db.users.delete_one({"_id": ObjectId(user_id)})

    try:
        from ws import push_to_admins
        await push_to_admins(db, {"type": "admin_user_deleted", "userId": user_id})
    except Exception:
        pass

    return {"message": f"Пользователь {existing.get('username', user_id)} удалён"}


@app.get("/api/admin/users/{user_id}/property")
async def admin_get_user_property(
    user_id: str,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Полный список имущества игрока для админ-панели: активы, майнинг-фермы,
    компания (если владелец) и бизнесы «Крыши города» (если владелец)."""
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID пользователя")
    existing = await db.users.find_one({"_id": ObjectId(user_id)})
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

    assets = [assets_module._serialize(a) async for a in db.user_assets.find({"userId": user_id})]

    farms = []
    async for f in db.mining_farms.find({"userId": user_id}):
        farms.append(await mining_module._serialize_with_stats(db, f, user_id))

    company_doc = await db.companies.find_one({"ownerId": user_id})
    company = await company_module._serialize(db, company_doc, user_id) if company_doc else None

    businesses = [
        cityroof_module._serialize_business(b, user_id)
        async for b in db.cityroof_businesses.find({"ownerId": user_id})
    ]

    return {
        "assets": assets,
        "farms": farms,
        "company": company,
        "businesses": businesses,
    }


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
        "userId": tx.get("userId", ""),
        "type": tx.get("type", ""),
        "symbol": tx.get("symbol", ""),
        "amount": tx.get("amount", 0),
        "price": tx.get("price", 0),
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

    uvicorn.run("main:app", host="0.0.0.0", port=20301, reload=True)
