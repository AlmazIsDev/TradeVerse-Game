from __future__ import annotations

import logging
import random
import re
import time
from bson import ObjectId
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorDatabase

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("tradeverse")

from init_db import init as init_db
from networth import WARCOIN_USD

from auth import (
    get_current_user,
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    use_refresh_token,
    delete_refresh_token,
)
from admin_perms import (
    require_admin,
    get_admin_levels,
    save_admin_levels,
    admin_level_of,
    ban_active,
    PLAYER_FUNCTIONS,
    ADMIN_FUNCTIONS,
    FIXED_ADMIN_FUNCTIONS,
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
from market_lots import router as market_lots_router
from shop import router as shop_router, admin_router as shop_admin_router, alias_admin_router as shop_admin_alias_router
from mining import router as mining_router
from admin_db import router as admin_db_router
from media import router as media_router
from farm import router as farm_router
from production import router as production_router
from synthetic import router as synthetic_router
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
    delete_transaction,
    delete_stock_by_symbol,
)
from schemas import (
    UserCreate,
    UserLogin,
    UserResponse,
    AuthResponse,
    RefreshRequest,
    TokenPair,
    AdminUserUpdate,
    AdminPasswordReset,
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
    # timestamp — выборки «за 24ч» (аналитика экономики, profit за 7д);
    # (category, timestamp) — фильтр по категориям в админ-таблице транзакций
    # с сортировкой по времени: без него матч по category сканирует всю
    # коллекцию и блокирующе сортирует результат (секунды на ответ).
    await db.transactions.create_index("timestamp")
    await db.transactions.create_index([("category", 1), ("timestamp", -1)])
    await db.analytics.create_index("userId")
    await db.leaderboard.create_index("profit")
    await db.crypto_assets.create_index("symbol", unique=True)
    await db.crypto_holdings.create_index([("userId", 1), ("symbol", 1)], unique=True)
    await db.crypto_transfers.create_index("fromId")
    await db.crypto_transfers.create_index("toId")
    await db.stock_holdings.create_index([("userId", 1), ("symbol", 1)], unique=True)
    await db.stock_events.create_index("symbol")
    await db.stock_events.create_index("timestamp")
    await db.crypto_events.create_index("symbol")
    await db.crypto_events.create_index("timestamp")
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
    await db.market_lots.create_index("status")
    await db.market_lots.create_index([("itemId", 1), ("status", 1)])
    await db.user_hardware.create_index("userId")
    await db.user_hardware.create_index("farmId")
    await db.mining_farms.create_index("userId")
    await db.mining_farms.create_index("status")
    # Слот подвала занимает ровно одна ферма — закрывает check-then-insert
    # гонку в create_farm (двойной клик по «Создать ферму»). Частичный:
    # легаси-фермы ботов живут без houseId/slotIndex и в индекс не входят.
    await db.mining_farms.create_index(
        [("houseId", 1), ("slotIndex", 1)], unique=True,
        partialFilterExpression={"houseId": {"$type": "objectId"}},
    )
    await db.cityroof_sessions.create_index("attackerId")
    await db.cityroof_seasons.create_index("closed_at")
    await db.cityroof_itstudio_jobs.create_index("orderedBy")
    await db.cityroof_itstudio_jobs.create_index([("status", 1), ("ready_at", 1)])
    await db.cityroof_itstudio_jobs.create_index([("studioAssetId", 1), ("status", 1)])
    # Ферма: одно поле на (userId, assetId). Индексы для полей и занятости машин.
    await db.user_fields.create_index([("userId", 1), ("assetId", 1)], unique=True)
    await db.user_hardware.create_index("busy_until")
    # Refresh-токены: уникальный индекс по хешу + TTL для авто-очистки истёкших.
    await db.refresh_tokens.create_index("token_hash", unique=True)
    await db.refresh_tokens.create_index("expires_at", expireAfterSeconds=0)
    await init_db()
    await mining_module.soft_reset_farms(db)   # разовая миграция под новую экономику майнинга
    await mining_module.dismantle_orphan_farms(db)   # разбор ферм без дома (не видны в новой системе)
    await fix_missing_card_numbers(db.users)   # дозаполнить только ОТСУТСТВУЮЩие номера карт
    from production import migrate_owned_infra
    await migrate_owned_infra(db)   # синхронизация цен/meta купленных источников и складов
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
        "http://127.0.0.1:20300",          # алиас по IP (vite может открыть так)
        "http://localhost:20310",          # локальный vite (альтернативный порт)
        "http://127.0.0.1:20310",          # алиас по IP для альтернативного порта
        "http://localhost:5173",           # локальный vite (дефолтный порт)
        "http://127.0.0.1:5173",           # алиас по IP для дефолтного vite
        "http://localhost",                # бонус: origin без порта (на всякий случай)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Access-лог с таймингами ──────────────────────────────────────────────────


@app.middleware("http")
async def access_log_with_timing(request: Request, call_next):
    """Лог каждого HTTP-запроса: метод, путь, статус и время исполнения (мс).

    Заменяет стандартный access-лог uvicorn (тот не показывает длительность и
    потому глушится ниже). OPTIONS-preflight не логируем — это шум CORS.
    """
    if request.method == "OPTIONS":
        return await call_next(request)
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    logger.info("%s %s -> %s (%.0f ms)", request.method, path, response.status_code, elapsed_ms)
    return response


# Увирикний access-лог дублирует middleware выше, но без таймингов.
logging.getLogger("uvicorn.access").disabled = True

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
# Центральный рынок: лоты игроков (p2p торговля имуществом и железом).
app.include_router(market_lots_router)
app.include_router(shop_router)
# Админские цены магазина (редактор цен / PriceEditorTab).
app.include_router(shop_admin_router)
app.include_router(shop_admin_alias_router)   # алиас /api/admin/shop-prices (для совместимости)
app.include_router(mining_router)
app.include_router(admin_db_router)
app.include_router(media_router)
app.include_router(ws_router)
# Ферма: поле, культуры, машины (комбайн/трактор), топливо (см. backend/farm.py).
app.include_router(farm_router)
app.include_router(production_router)
app.include_router(synthetic_router)


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


async def fix_missing_card_numbers(users) -> None:
    """Дозаполняет ТОЛЬКО отсутствующие номера карт у старых аккаунтов.

    Любой существующий номер (включая «0000-0000-0000-00000») — осознанно
    выставленное значение (игрок/админ), его не трогаем: перезапись на старте
    меняла карту игрока при каждом рестарте бэкенда."""
    bad = [u async for u in users.find({"card_number": None}, {"_id": 1})]
    bad += [u async for u in users.find({"card_number": {"$exists": False}}, {"_id": 1})]
    for u in bad:
        card = await ensure_unique_card_number(users)
        await users.update_one({"_id": u["_id"]}, {"$set": {"card_number": card}})


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


def _client_ip(request: Request) -> str:
    """IP клиента: первый hop из X-Forwarded-For (за реверс-прокси), иначе прямой."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.post("/api/register", status_code=status.HTTP_201_CREATED, response_model=AuthResponse)
async def register_user(
    user_data: UserCreate,
    request: Request,
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

    now = datetime.now(timezone.utc)
    ip = _client_ip(request)
    new_user = {
        "username": user_data.username,
        "hashed_password": hash_password(user_data.password),
        "role": "user",
        "balance": STARTING_BALANCE,
        "card_number": card_number,
        "card_visible": True,
        "avatar": None,
        "created_at": now,
        # Все IP, с которых заходил пользователь: {ip: iso-время последнего входа}
        "login_ips": {ip: now.isoformat()},
        "last_login": now.isoformat(),
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
    request: Request,
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

    # История IP для админки: {ip: последнее время входа с этого адреса}.
    # ВАЖНО: ключ словаря содержит точки (IPv4) — путь "login_ips.1.2.3.4"
    # через $set Mongo развернул бы во вложенные документы, поэтому словарь
    # мержится в приложении и пишется целиком.
    now = datetime.now(timezone.utc)
    ip = _client_ip(request)
    # Заодно самолечение: битые записи (вложенные документы от старого
    # dotted-$set) выбрасываются — остаются только строковые метки времени.
    login_ips = {k: v for k, v in (user.get("login_ips") or {}).items() if isinstance(v, str)}
    login_ips[ip] = now.isoformat()
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"login_ips": login_ips, "last_login": now.isoformat()}},
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
async def get_me(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Возвращает полные данные текущего пользователя (из БД).

    Админам дополнительно отдаёт уровень и список разрешённых функций —
    фронтенд фильтрует по ним разделы/кнопки админки."""
    created_at = current_user.get("created_at")
    out = {
        "id": str(current_user["_id"]),
        "username": current_user["username"],
        "role": current_user.get("role", "user"),
        "balance": current_user.get("balance", 1000.0),
        "card_number": current_user.get("card_number"),
        "card_visible": current_user.get("card_visible", True),
        "crypto_account_opened": bool(current_user.get("crypto_account_opened", False)),
        "avatar": current_user.get("avatar"),
        "bio": current_user.get("bio", ""),
        "hideFromLeaderboard": bool(current_user.get("hidden_from_leaderboard", False)),
        "leaderboardLock": bool(current_user.get("leaderboard_lock", False)),
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else None,
    }
    if out["role"] == "admin":
        out["adminLevel"] = admin_level_of(current_user)
        levels = await get_admin_levels(db)
        out["adminFunctions"] = sorted(
            fid for fid, lvl in levels.items() if out["adminLevel"] >= lvl
        )
    return out


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
    _admin=Depends(require_admin("stocks")),
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
    _admin=Depends(require_admin("config")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    config = await upsert_config(db, config_data.key, config_data.value)
    return _format_config(config)


# ── Leaderboard Endpoints ────────────────────────────────────────────────────


STARTING_BALANCE = 15000.0

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


async def _compute_leaderboard_entries(db: AsyncIOMotorDatabase, user_query: Optional[dict] = None) -> list[dict]:
    """Полный обсчёт капитала всех игроков (наличные + акции + крипта + активы + компания + WC).

    user_query переопределяет фильтр по users — например {"_id": oid} для одного
    игрока (в т.ч. скрытого из таблицы лидеров, для его собственной статистики).
    """
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

    # Прибыль за период: реализованный чистый доход (income − expense) за 7 дней
    # из реестра операций. Раньше profit = net_worth − STARTING_BALANCE считался
    # «с момента регистрации» и был бессмысленным для давних игроков.
    # ponytail: скользящее окно 7д по ledger'у; для «за день/месяц» — параметризовать окно.
    period_net: dict[str, float] = {}
    since = datetime.now(timezone.utc) - timedelta(days=7)
    async for row in db.transactions.aggregate([
        {"$match": {"timestamp": {"$gte": since}}},
        {"$group": {"_id": {"u": "$userId", "d": "$direction"}, "sum": {"$sum": "$amount"}}},
    ]):
        uid = row["_id"]["u"]
        signed = row["sum"] if row["_id"]["d"] == "income" else -row["sum"]
        period_net[uid] = period_net.get(uid, 0.0) + signed

    entries = []
    async for u in db.users.find(user_query if user_query is not None else {"hidden_from_leaderboard": {"$ne": True}}):
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
            # profit = реализованная прибыль за 7 дней (см. period_net выше).
            # profitAllTime сохранён для профиля/ачивок как «рост с регистрации».
            "profit": round(period_net.get(uid, 0.0), 2),
            "profitAllTime": round(net_worth - STARTING_BALANCE, 2),
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
    profit — реализованная прибыль за 7 дней (не «с регистрации»).
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


@app.get("/api/leaderboard/companies")
async def get_company_leaderboard(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Рейтинг компаний по собственной стоимости (бюджет + активы компании).

    Отдельный от игрового рейтинг: ценит саму компанию, а не капитал владельца.
    ponytail: два скана коллекций без кэша — вызывается редко; кэш добавить, если станет горячим.
    """
    def _asset_value(a: dict) -> float:
        return a.get("price", 0) * (1 + 0.35 * (a.get("level", 1) - 1))

    comps: dict[str, dict] = {}
    async for c in db.companies.find({}):
        cid = str(c["_id"])
        comps[cid] = {
            "companyId": cid,
            "name": c.get("name", "—"),
            "logo": c.get("logo", ""),
            "ownerId": c.get("ownerId"),
            "budget": round(float(c.get("budget", 0.0)), 2),
            "assets": 0.0,
        }
    async for a in db.user_assets.find({"companyId": {"$ne": None}}):
        c = comps.get(a.get("companyId"))
        if c:
            c["assets"] += _asset_value(a)

    for c in comps.values():
        c["assets"] = round(c["assets"], 2)
        c["value"] = round(c["budget"] + c["assets"], 2)

    ranked = sorted(comps.values(), key=lambda c: c["value"], reverse=True)[:limit]
    return [{**c, "rank": i} for i, c in enumerate(ranked, start=1)]


@app.get("/api/user/stats")
async def get_my_stats(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Личная статистика игрока для профиля (тот же обсчёт, что и в таблице лидеров).

    Работает и для скрытых из таблицы лидеров — фильтр по своему _id, а не по
    флагу видимости. Ачивки выводятся из уже посчитанных цифр, без новых механик.
    """
    entries = await _compute_leaderboard_entries(db, {"_id": current_user["_id"]})
    stats = entries[0] if entries else {
        "cash": 0.0, "stocks": 0.0, "crypto": 0.0, "assets": 0.0,
        "company": 0.0, "warcoin": 0.0, "netWorth": 0.0, "profit": 0.0,
    }
    # ponytail: ачивки — производные пороги от текущих цифр, не отдельная система прогресса.
    achievements = [
        {"id": "networth_1m", "reached": stats["netWorth"] >= 1_000_000},
        {"id": "in_profit", "reached": stats["profit"] > 0},
        {"id": "diversified", "reached": sum(1 for k in ("stocks", "crypto", "assets", "company") if stats.get(k, 0) > 0) >= 3},
        {"id": "company_owner", "reached": stats.get("company", 0) > 0},
    ]
    return {"stats": stats, "achievements": achievements}


@app.get("/api/user/{user_id}/profile")
async def get_public_profile(
    user_id: str,
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Публичная карточка игрока (никнейм, аватар, «о себе», капитал, ачивки).

    Показывает только агрегированные цифры — те же, что видны в таблице лидеров.
    Работает и для скрытых из лидерборда: скрытие убирает из общего списка, но
    не запрещает открыть профиль по прямой ссылке из состава компании/крыши.
    """
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Игрок не найден")
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Игрок не найден")
    entries = await _compute_leaderboard_entries(db, {"_id": user["_id"]})
    stats = entries[0] if entries else {
        "cash": 0.0, "stocks": 0.0, "crypto": 0.0, "assets": 0.0,
        "company": 0.0, "warcoin": 0.0, "netWorth": 0.0, "profit": 0.0,
    }
    achievements = [
        {"id": "networth_1m", "reached": stats["netWorth"] >= 1_000_000},
        {"id": "in_profit", "reached": stats["profit"] > 0},
        {"id": "diversified", "reached": sum(1 for k in ("stocks", "crypto", "assets", "company") if stats.get(k, 0) > 0) >= 3},
        {"id": "company_owner", "reached": stats.get("company", 0) > 0},
    ]
    return {
        "userId": str(user["_id"]),
        "username": user.get("username", "—"),
        "avatar": user.get("avatar"),
        "bio": user.get("bio") or "",
        "createdAt": user.get("created_at"),
        "stats": stats,
        "achievements": achievements,
    }


# ── Admin Endpoints ──────────────────────────────────────────────────────────


@app.delete("/api/stocks/{symbol}")
async def admin_delete_stock(
    symbol: str,
    _admin=Depends(require_admin("stocks")),
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
    _admin=Depends(require_admin("users_view")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Список пользователей для админки + разбивка капитала (как в таблице лидеров).

    Сортировку делает клиент: список и так полный, а значит сортируется
    мгновенно без перезапроса. Аватары не отдаём — base64 на каждого
    пользователя раздувает ответ до мегабайт, в списке они не нужны.
    """
    by_uid = {e["userId"]: e for e in await _compute_leaderboard_entries(db, {})}
    out = []
    async for u in db.users.find({}, {"username": 1, "role": 1, "balance": 1, "created_at": 1,
                                      "card_number": 1, "hidden_from_leaderboard": 1, "leaderboard_lock": 1,
                                      "login_ips": 1, "last_login": 1,
                                      "admin_level": 1, "bans": 1}):
        e = by_uid.get(str(u["_id"]), {})
        # IP-история: свежие адреса первыми, максимум 20 — полный список не нужен,
        # а ответ не раздуваем. Фильтр по строке отсекает мусор от старых записей,
        # где точки в ключе развернулись во вложенные документы.
        ips = [{"ip": ip, "at": at} for ip, at in (u.get("login_ips") or {}).items()
               if isinstance(at, str)]
        ips.sort(key=lambda x: x["at"], reverse=True)
        out.append({
            "id": str(u["_id"]),
            "username": u.get("username", ""),
            "role": u.get("role", "user"),
            "admin_level": int(u.get("admin_level") or 4) if u.get("role") == "admin" else None,
            "bans": u.get("bans") or {},
            "balance": float(u.get("balance", 0.0) or 0.0),
            "created_at": u.get("created_at").isoformat() if isinstance(u.get("created_at"), datetime) else u.get("created_at"),
            "last_login": u.get("last_login"),
            "ips": ips[:20],
            "card_number": u.get("card_number"),
            "id": str(u["_id"]),
            "username": u.get("username", ""),
            "role": u.get("role", "user"),
            "admin_level": int(u.get("admin_level") or 4) if u.get("role") == "admin" else None,
            "bans": u.get("bans") or {},
            "balance": float(u.get("balance", 0.0) or 0.0),
            "created_at": u.get("created_at").isoformat() if isinstance(u.get("created_at"), datetime) else u.get("created_at"),
            "card_number": u.get("card_number"),
            "hidden_from_leaderboard": bool(u.get("hidden_from_leaderboard", False)),
            "leaderboard_lock": bool(u.get("leaderboard_lock", False)),
            "stocks": e.get("stocks", 0.0),
            "crypto": e.get("crypto", 0.0),
            "assets": e.get("assets", 0.0),
            "company": e.get("company", 0.0),
            "warcoin": e.get("warcoin", 0.0),
            "netWorth": e.get("netWorth", float(u.get("balance", 0.0) or 0.0)),
        })
    return out


@app.patch("/api/admin/users/{user_id}")
async def admin_update_user(
    user_id: str,
    update_data: AdminUserUpdate,
    _admin=Depends(require_admin("users_edit")),
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

    # Назначать админство и уровень админки может только админ 4 уровня.
    if ("role" in update_fields or "admin_level" in update_fields) and admin_level_of(_admin) < 4:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Изменять роль и уровень админки может только админ 4 уровня",
        )

    # Снятие админства — забираем уровень; новый админ без явного уровня = L4.
    if update_fields.get("role") == "user":
        update_fields["admin_level"] = None
    elif update_fields.get("role") == "admin" and "admin_level" not in update_fields:
        update_fields["admin_level"] = 4

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
    _admin=Depends(require_admin("users_delete")),
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


# ── Уровни админки и баны игроков ────────────────────────────────────────────


@app.get("/api/admin/permissions")
async def admin_get_permissions(
    _admin=Depends(require_admin("admin_perms")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Реестр админ-функций с текущими уровнями (только админ 4 уровня)."""
    levels = await get_admin_levels(db)
    return {
        "functions": [
            {"id": fid, "label": key, "default": lvl, "level": levels[fid], "fixed": False}
            for fid, lvl, key in ADMIN_FUNCTIONS
        ] + [
            {"id": fid, "label": "adminPerms.func_admin_perms", "default": 4,
             "level": 4, "fixed": True}
            for fid in FIXED_ADMIN_FUNCTIONS
        ]
    }


@app.post("/api/admin/permissions")
async def admin_set_permissions(
    payload: dict,
    _admin=Depends(require_admin("admin_perms")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Сохраняет распределение функций по уровням 1-4 (только админ 4 уровня). Body: {"levels": {func_id: 1..4}}."""
    levels = payload.get("levels")
    if not isinstance(levels, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ожидается {levels: {...}}")
    await save_admin_levels(db, levels)
    return {"message": "Права сохранены", "levels": await get_admin_levels(db)}


@app.patch("/api/admin/users/{user_id}/bans")
async def admin_set_user_bans(
    user_id: str,
    payload: dict,
    _admin=Depends(require_admin("bans")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Баны/отстранения игрока по функциям.

    Body: {"bans": {func: {reason, until}|None}} - полный срез банов юзера;
    отсутствующая функция = бан снят. `account` - полный бан аккаунта.
    """
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID пользователя")
    target = await db.users.find_one({"_id": ObjectId(user_id)})
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    if target.get("role") == "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Админов банить нельзя")
    bans_in = payload.get("bans")
    if not isinstance(bans_in, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ожидается {bans: {...}}")
    now = datetime.now(timezone.utc)
    clean = {}
    for func, b in bans_in.items():
        if not b:
            continue
        reason = str(b.get("reason") or "").strip() or None
        until = b.get("until") or None
        clean[func] = {"reason": reason, "until": until, "by": _admin.get("username"), "at": now.isoformat()}
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"bans": clean}})
    try:
        from ws import push_to_user, push_to_admins
        await push_to_user(user_id, {"type": "banned", "bans": {k: 1 for k in clean}})
        await push_to_admins(db, {"type": "admin_user_modified", "userId": user_id})
    except Exception:
        pass
    return {"message": "Баны обновлены", "bans": clean}


@app.post("/api/admin/broadcast")
async def admin_broadcast(
    payload: dict,
    _admin=Depends(require_admin("broadcast")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Глобальное объявление: уведомление каждому пользователю игры."""
    title = str(payload.get("title") or "").strip()
    message = str(payload.get("message") or "").strip()
    if not title:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Заголовок обязателен")
    now = datetime.now(timezone.utc)
    docs = [
        {
            "userId": str(u["_id"]),
            "type": "broadcast",
            "title": title,
            "body": message,
            "data": {"by": _admin.get("username")},
            "read": False,
            "created_at": now,
        }
        async for u in db.users.find({}, {"_id": 1})
    ]
    if docs:
        await db.notifications.insert_many(docs)
    # Realtime-попап всем подключённым (кто офлайн — увидит в списке уведомлений).
    try:
        from ws import broadcast
        await broadcast({"type": "notification", "notification": {
            "type": "broadcast", "title": title, "body": message,
        }})
    except Exception:
        pass
    logger.info("Admin '%s' broadcast to %d users: %s",
                _admin.get("username", "unknown"), len(docs), title)
    return {"sent": len(docs)}


@app.post("/api/admin/users/{user_id}/password")
async def admin_set_user_password(
    user_id: str,
    payload: AdminPasswordReset,
    _admin=Depends(require_admin("users_password")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Сброс пароля пользователя администратором."""
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID пользователя")
    result = await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"hashed_password": hash_password(payload.password)}},
    )
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    logger.info("Admin '%s' reset password of user %s",
                _admin.get("username", "unknown"), user_id)
    return {"message": "Пароль обновлён"}


@app.post("/api/admin/users/{user_id}/logout")
async def admin_logout_user(
    user_id: str,
    _admin=Depends(require_admin("users_logout")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Разлогинить пользователя: инвалидирует все refresh-токены.

    Access-токен доживает до своего короткого срока, после чего игрок
    автоматически выбрасывается на страницу входа.
    """
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID пользователя")
    result = await db.refresh_tokens.delete_many({"user_id": ObjectId(user_id)})
    logger.info("Admin '%s' logged out user %s (%d sessions)",
                _admin.get("username", "unknown"), user_id, result.deleted_count)
    return {"message": f"Сессий завершено: {result.deleted_count}"}


@app.get("/api/admin/users/{user_id}/property")
async def admin_get_user_property(
    user_id: str,
    _admin=Depends(require_admin("users_property")),
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


TX_SORT_FIELDS = {"timestamp", "direction", "label", "category", "username", "amount", "balanceAfter"}

# Дискретные фильтры и их сырые/вычисляемые поля. players → userId (индекс),
# direction/category вычисляются в $project — матчим $expr-эквивалентом до
# проекции, source — константа проекции, живёт в post-match.
_AMOUNT_OPS = {"amount_min": "$gte", "amount_max": "$lte"}


def _label_rx(pattern: str) -> dict:
    return {"$regex": pattern, "$options": "i"}


# Группы автоматических операций для фильтра транзакций. Условия по сырым
# полям документа реестра (до $project): метки генерируются модулями игры —
# см. record_transaction в company/cityroof/mining/assets.
AUTO_TX_GROUPS: dict[str, dict] = {
    # Зарплаты сотрудников (авто-выплаты из бюджета компании).
    "salary": {"category": "company", "label": _label_rx("Зарплата")},
    # Автосбор дохода бизнесов «Крыши города».
    "cityroof": {"category": "cityroof", "label": _label_rx("Автосбор")},
    # Добыча майнинг-ферм (весь доход категории mining).
    "mining": {"category": "mining", "direction": "income"},
    # Расходы ферм: электричество и ИИ-управляющий.
    "farm_expenses": {"category": "mining", "direction": "expense",
                      "label": _label_rx("Расходы фермы|ИИ-управляющий")},
    # Доход от бизнесов и домов (аренда/прибыль активов).
    "realestate": {"category": {"$in": ["realestate", "business"]}, "direction": "income"},
}
_TS_OPS = {"ts_from": "$gte", "ts_to": "$lte"}


def build_tx_filters(f: dict, names: dict) -> tuple[dict | None, dict]:
    """Фильтры админ-таблицы → (pre_match до $project, post_match после).

    f: players/exclude_players (id), categories, directions, sources (+exclude_),
    amount_min/amount_max, ts_from/ts_to. names: {uid_hex: username}.
    """
    raw: dict = {}
    raw_conds: list[dict] = []  # вычислимые поля → обычные предикаты через $or/$nor

    def uid_variants(uid: str) -> list:
        # userId хранится и ObjectId, и строкой; не-id (имя из строки поиска) — как есть.
        return [ObjectId(uid), uid] if ObjectId.is_valid(uid) else [uid]

    for uid in f.get("players") or []:
        raw.setdefault("userId", {"$in": []})["$in"] += uid_variants(uid)
    for uid in f.get("exclude_players") or []:
        raw.setdefault("userId", {"$nin": []})["$nin"] += uid_variants(uid)

    # Направление/категория вычисляются в $project из direction|type и
    # category|symbol. Выражения ($expr) запрещают индексы и гоняются на
    # каждом документе, поэтому раскладываем в запросные предикаты: ветка для
    # документов с полем + явные ветки $exists для вычисляемого фолбэка.
    def _dir_conds(d):
        conds = [{"direction": {"$in": d}}]
        if "income" in d:
            conds.append({"direction": {"$exists": False}, "type": "sell"})
        if "expense" in d:
            conds.append({"direction": {"$exists": False}, "type": {"$ne": "sell"}})
        return conds

    def _cat_conds(c):
        conds = [{"category": {"$in": c}}]
        if "trade" in c:
            conds.append({"category": {"$exists": False}, "symbol": {"$exists": True}})
        if "system" in c:
            conds.append({"category": {"$exists": False}, "symbol": {"$exists": False}})
        return conds

    if f.get("directions"):
        raw_conds.append({"$or": _dir_conds(f["directions"])})
    if f.get("exclude_directions"):
        raw_conds.append({"$nor": _dir_conds(f["exclude_directions"])})
    if f.get("categories"):
        raw_conds.append({"$or": _cat_conds(f["categories"])})
    if f.get("exclude_categories"):
        raw_conds.append({"$nor": _cat_conds(f["exclude_categories"])})

    for key, op in _AMOUNT_OPS.items():
        if f.get(key) is not None:
            raw.setdefault("amount", {})[op] = float(f[key])
    for key, op in _TS_OPS.items():
        if f.get(key):
            raw.setdefault("timestamp", {})[op] = f[key]

    # Автооперации и слова — условия по сырым полям (label/category/direction),
    # уходят в pre_match до $project вместе с остальными raw_conds.
    auto_in = [t for t in (f.get("auto") or []) if t in AUTO_TX_GROUPS]
    auto_ex = [t for t in (f.get("exclude_auto") or []) if t in AUTO_TX_GROUPS]
    if auto_in:
        raw_conds.append({"$or": [AUTO_TX_GROUPS[t] for t in auto_in]})
    if auto_ex:
        raw_conds.append({"$nor": [AUTO_TX_GROUPS[t] for t in auto_ex]})
    words_in = f.get("words") or []
    words_ex = f.get("exclude_words") or []
    if words_in:
        raw_conds.append({"$or": [{"label": _label_rx(re.escape(w))} for w in words_in]})
    if words_ex:
        raw_conds.append({"$nor": [{"label": _label_rx(re.escape(w))} for w in words_ex]})

    if raw_conds:
        raw = {"$and": [raw, *raw_conds]} if raw else (
            raw_conds[0] if len(raw_conds) == 1 else {"$and": raw_conds})

    post: dict = {}
    if f.get("sources"):
        post["source"] = {"$in": f["sources"]}
    if f.get("exclude_sources"):
        post["source"] = {"$nin": f["exclude_sources"]}

    if not raw:
        return None, post
    return raw, post


@app.get("/api/admin/transactions/filters")
async def admin_transaction_filter_options(
    _admin=Depends(require_admin("transactions_view")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Справочник значений для мультифильтров таблицы транзакций."""
    players = [{"id": str(u["_id"]), "username": u.get("username", "")}
               async for u in db.users.find({}, {"username": 1}).sort("username", 1)]
    categories = await db.transactions.distinct("category")
    return {
        "players": players,
        "categories": sorted(c for c in categories if c),
        "sources": ["user"],  # логи ботов вырезаны
    }


@app.get("/api/admin/transactions")
async def admin_get_all_transactions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    q: str = Query(None),
    field: str = Query(None),
    kind: str = Query("all"),
    players: str = Query(None), exclude_players: str = Query(None),
    categories: str = Query(None), exclude_categories: str = Query(None),
    directions: str = Query(None), exclude_directions: str = Query(None),
    sources: str = Query(None), exclude_sources: str = Query(None),
    auto: str = Query(None), exclude_auto: str = Query(None),
    words: str = Query(None), exclude_words: str = Query(None),
    amount_min: float = Query(None), amount_max: float = Query(None),
    ts_from: str = Query(None), ts_to: str = Query(None),
    sort: str = Query("timestamp"),
    order: int = Query(-1),
    _admin=Depends(require_admin("transactions_view")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Единый поток операций реестра и сделок ботов.

    Фильтрация/сортировка/пагинация выполняются в БД через $unionWith, иначе
    клиент видел бы только последние N записей и искал бы лишь внутри них.
    """
    # Пользователей единицы — карту имён дешевле развернуть в $switch, чем делать $lookup.
    names = {str(u["_id"]): u.get("username", "") async for u in db.users.find({}, {"username": 1})}
    username_expr = {"$switch": {
        "branches": [{"case": {"$eq": [{"$toString": "$userId"}, uid]}, "then": name}
                     for uid, name in names.items() if name],
        "default": {"$toString": {"$ifNull": ["$userId", ""]}},
    }} if names else {"$toString": {"$ifNull": ["$userId", ""]}}

    ledger_stage = [{"$project": {
        "source": "user",
        "direction": {"$ifNull": ["$direction", {"$cond": [{"$eq": ["$type", "sell"]}, "income", "expense"]}]},
        "category": {"$ifNull": ["$category", {"$cond": [{"$ifNull": ["$symbol", False]}, "trade", "system"]}]},
        "label": {"$ifNull": ["$label", {"$ifNull": ["$symbol", ""]}]},
        "username": username_expr,
        "amount": {"$ifNull": ["$amount", 0]},
        "balanceAfter": "$balance_after",
        "timestamp": 1,
    }}]
    # Глобальный топ-K лежит внутри объединения пер-веточных топ-K, поэтому
    # сортировку с лимитом проталкиваем в каждую ветку: так работают индексы
    # по timestamp и запрос идёт ~0.2с вместо ~3с на полном union.
    take = skip + limit + 1  # +1 — зонд следующей страницы вместо дорогого $count
    sort_key = sort if sort in TX_SORT_FIELDS else "timestamp"
    sort_stage = {"$sort": {sort_key: 1 if order >= 0 else -1, "_id": 1}}

    match: dict = {}
    post_match: dict = {}
    pre_match: dict | None = None   # матч по сырому полю ДО $project (индексируемый путь)
    if kind in ("income", "expense"):
        match["direction"] = kind

    # Мультифильтры: CSV-списки + диапазоны → pre/post-match через билдер.
    def _split_csv(s):
        return [v.strip() for v in s.split(",") if v.strip()] if s else None

    f_pre, f_post = build_tx_filters({
        "players": _split_csv(players), "exclude_players": _split_csv(exclude_players),
        "categories": _split_csv(categories), "exclude_categories": _split_csv(exclude_categories),
        "directions": _split_csv(directions), "exclude_directions": _split_csv(exclude_directions),
        "sources": _split_csv(sources), "exclude_sources": _split_csv(exclude_sources),
        "auto": _split_csv(auto), "exclude_auto": _split_csv(exclude_auto),
        "words": _split_csv(words), "exclude_words": _split_csv(exclude_words),
        "amount_min": amount_min, "amount_max": amount_max,
        "ts_from": ts_from, "ts_to": ts_to,
    }, names)
    if f_pre:
        # Слияние с pre_match от поиска по имени: оба условия по userId → $and.
        pre_match = {"$and": [pre_match, f_pre]} if pre_match else f_pre
    if f_post:
        post_match = f_post
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        if field == "username":
            # Поиск по имени разрешаем в приложении по карте имён и матчим по
            # индексируемому userId ДО $project. Иначе $regexMatch по
            # вычисленному в $project полю заставляет БД проектировать и
            # сканировать всю коллекцию на каждый запрос — минуты и 504.
            ql = q.casefold()
            uids = [uid for uid, name in names.items() if ql in name.casefold()]
            if uids:
                # userId в реестре бывает и ObjectId, и строкой — матчим оба вида.
                pre_match = {"userId": {"$in": [ObjectId(uid) for uid in uids] + uids}}
            else:
                # Имя не найдено среди известных: могут быть документы с
                # неизвестным userId — оставляем старый медленный путь.
                match["$expr"] = {"$regexMatch": {
                    "input": {"$toString": {"$ifNull": ["$username", ""]}},
                    "regex": re.escape(q), "options": "i",
                }}
        elif field in TX_SORT_FIELDS:
            # Через $toString, иначе точечный поиск по числам и датам
            # («Сумма: 100», «timestamp: 2026-07») не находил бы ничего.
            match["$expr"] = {"$regexMatch": {
                "input": {"$toString": {"$ifNull": [f"${field}", ""]}},
                "regex": re.escape(q), "options": "i",
            }}
        else:
            match["$or"] = [{"label": rx}, {"category": rx}, {"username": rx}]

    def branch(stages: list) -> list:
        # Глобальный топ-K лежит внутри объединения пер-веточных топ-K, поэтому
        # сортировку с лимитом можно протолкнуть в каждую ветку.
        out = list(stages)
        if pre_match is not None:
            out = [{"$match": pre_match}] + out
        tail = match | post_match if not ("$expr" in match and post_match) else {"$and": [match, post_match]}
        if tail:
            out.append({"$match": tail})
        out += [sort_stage, {"$limit": take}]
        return out

    def fast_branch(stages: list) -> list:
        # Быстрый путь: pre_match + сортировка ДО $project, ранний $limit.
        # Сортировка видит сырое поле timestamp и опирается на индекс
        # (userId/category+timestamp), top-K не требует блокирующей сортировки
        # всего матча. Корректно, только если после $project ничего не
        # фильтруется (tail пуст) — иначе подрезка до limit исказила бы результат.
        head = ([{"$match": pre_match}] if pre_match is not None else []) + stages[:-1]
        return head + [sort_stage, {"$limit": take}, stages[-1]]

    pick = fast_branch if (not match and not post_match and sort_key == "timestamp") else branch
    # Логи сделок ботов вырезаны — фильтр kind="bot" всегда пуст.
    pipeline: list = [{"$match": {"_id": None}}] if kind == "bot" else pick(ledger_stage)
    pipeline += [sort_stage, {"$skip": skip}, {"$limit": limit + 1}]

    rows = await db.transactions.aggregate(pipeline, allowDiskUse=True).to_list(limit + 1)
    has_more = len(rows) > limit
    items = []
    for d in rows[:limit]:
        d["id"] = str(d.pop("_id", ""))
        ts = d.get("timestamp")
        d["timestamp"] = ts.isoformat() if isinstance(ts, datetime) else (ts or "")
        items.append(d)
    return {"items": items, "has_more": has_more}


@app.delete("/api/admin/transactions/{tx_id}")
async def admin_delete_transaction(
    tx_id: str,
    _admin=Depends(require_admin("transactions_delete")),
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
    import sys

    if "--selfcheck" in sys.argv:
        # Профит = чистый доход (income − expense) за окно, а не «с регистрации».
        def _period_net(rows: list[dict]) -> float:
            net = 0.0
            for r in rows:
                net += r["amount"] if r["direction"] == "income" else -r["amount"]
            return round(net, 2)

        assert _period_net([
            {"direction": "income", "amount": 500.0},
            {"direction": "expense", "amount": 200.0},
            {"direction": "income", "amount": 50.0},
        ]) == 350.0
        assert _period_net([]) == 0.0
        assert _period_net([{"direction": "expense", "amount": 100.0}]) == -100.0
        print("leaderboard profit self-check OK")
        sys.exit(0)

    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=20301, reload=True)
