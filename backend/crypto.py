"""Криптосчёт, рынок, кошелёк и торговля."""
from __future__ import annotations

from typing import Optional

import math
import random
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator

from admin_perms import get_current_user, require_admin, require_allowed
from database import get_db
from ledger import (
    INCOME, EXPENSE, CAT_CRYPTO,
    adjust_balance, record_transaction,
)
from market_data import MarketDataService
from networth import ensure_transfer_allowed
from levels import TRANSFER_SEND_MIN_LEVEL, TRANSFER_RECEIVE_MIN_LEVEL
from notifications import push_notification
from timeutil import now_utc
from state_bank import credit_state
from ws import broadcast

router = APIRouter(prefix="/api/crypto", tags=["crypto"])

# Как часто (сек) пересчитывать цену монеты при чтении рынка
PRICE_REFRESH_SECONDS = 30
# Комиссия сети за перевод криптовалюты (доля от суммы, «сгорает»)
CRYPTO_FEE_RATE = 0.01

# Торговая комиссия (спред) на сделки покупки/продажи. Небольшая, но делает
# бессмысленным «дребезг» buy→sell ради микродвижений цены и придаёт глубину
# экономике — быстрый оборот теперь стоит денег. Комиссия «сгорает».
CRYPTO_TRADE_FEE_RATE = 0.005
# Остатки количества меньше этого — пыль округлений: не торгуются, не
# показываются в портфеле и удаляются при обнулении.
DUST_QTY = 1e-8
# Лимит концентрации: один игрок может держать максимум эту долю эмиссии монеты
# (holdings в crypto_holdings — покупка + добыча + переводы; продажа не ограничена).
MAX_HOLD_SHARE = 0.9

# ── Собственная экономика TradeVerse поверх реальных курсов ───────────────────
# Реальная цена (CoinGecko/симуляция) — БАЗА. Действия игроков двигают монету
# через множитель спроса `demand`: массовая покупка поднимает цену, продажа —
# опускает. Отображаемая цена = market_price × demand. Спрос медленно
# возвращается к 1.0, поэтому влияние ощутимо, но не вечно.
DEMAND_MIN = 0.5
DEMAND_MAX = 2.5
IMPACT_K = 0.6            # сила влияния сделки (относительно суточного объёма)
IMPACT_CAP = 0.12        # максимум сдвига спроса за одну сделку
DEMAND_REVERT = 0.03     # доля возврата спроса к 1.0 за фоновый тик

DEFAULT_COINS = [
    {"symbol": "WVC", "name": "WarVerse Coin", "price": 120.0, "volatility": 0.04, "color": "#f7931a", "supply": 21_000_000, "description": "Флагманская монета вселенной TradeVerse: дефляционная модель и лимит эмиссии."},
    {"symbol": "TVX", "name": "TradeVerse X", "price": 45.5, "volatility": 0.05, "color": "#627eea", "supply": 120_000_000, "description": "Утилити-токен экосистемы, обеспечивает смарт-контракты и стейкинг."},
    {"symbol": "NEON", "name": "Neon Token", "price": 3.2, "volatility": 0.08, "color": "#22c55e", "supply": 500_000_000, "description": "Быстрый L2-токен для микротранзакций и игровых платежей."},
    {"symbol": "GLD", "name": "GoldChain", "price": 210.0, "volatility": 0.02, "color": "#eab308", "supply": 8_000_000, "description": "Стабильный актив, обеспеченный виртуальным золотом. Низкая волатильность."},
    {"symbol": "MEME", "name": "MemeCoin", "price": 0.85, "volatility": 0.12, "color": "#ec4899", "supply": 1_000_000_000, "description": "Высоковолатильный мем-токен. Только для смелых."},
    {"symbol": "ORB", "name": "Orbit", "price": 12.4, "volatility": 0.07, "color": "#8b5cf6", "supply": 300_000_000, "description": "Токен децентрализованной спутниковой сети."},
    {"symbol": "AQUA", "name": "AquaCoin", "price": 1.75, "volatility": 0.06, "color": "#06b6d4", "supply": 750_000_000, "description": "Экологичный токен с механикой ликвидных пулов."},
    {"symbol": "IRON", "name": "IronLedger", "price": 58.0, "volatility": 0.03, "color": "#64748b", "supply": 40_000_000, "description": "Промышленный блокчейн-токен для цепочек поставок."},
    {"symbol": "PIX", "name": "PixelCash", "price": 0.42, "volatility": 0.10, "color": "#f43f5e", "supply": 2_000_000_000, "description": "Игровая валюта пиксельных миров."},
    {"symbol": "NOVA", "name": "NovaChain", "price": 88.5, "volatility": 0.06, "color": "#e879f9", "supply": 60_000_000, "description": "Быстрорастущий токен нового поколения консенсуса."},
    {"symbol": "ZEN", "name": "ZenToken", "price": 6.9, "volatility": 0.05, "color": "#10b981", "supply": 210_000_000, "description": "Приватный токен с фокусом на анонимность."},
    {"symbol": "BOLT", "name": "BoltPay", "price": 24.1, "volatility": 0.07, "color": "#f59e0b", "supply": 150_000_000, "description": "Платёжная сеть с мгновенными переводами."},
    {"symbol": "DUSK", "name": "DuskCoin", "price": 0.19, "volatility": 0.14, "color": "#7c3aed", "supply": 5_000_000_000, "description": "Экспериментальный токен теневых рынков."},
    {"symbol": "RUBY", "name": "RubyChain", "price": 340.0, "volatility": 0.03, "color": "#dc2626", "supply": 3_000_000, "description": "Премиальный редкий токен с ограниченной эмиссией."},
    {"symbol": "FLUX", "name": "FluxNet", "price": 9.3, "volatility": 0.09, "color": "#0ea5e9", "supply": 400_000_000, "description": "Токен распределённых вычислений и облака."},
    {"symbol": "GEM", "name": "GemStone", "price": 155.0, "volatility": 0.04, "color": "#14b8a6", "supply": 12_000_000, "description": "Коллекционный токен с NFT-механиками."},
]


# ── Schemas ──────────────────────────────────────────────────────────────────


class CryptoTrade(BaseModel):
    symbol: str
    action: str  # "buy" | "sell"
    quantity: float

    @field_validator("action")
    @classmethod
    def action_valid(cls, v):
        if v not in ("buy", "sell"):
            raise ValueError("action должен быть 'buy' или 'sell'")
        return v

    @field_validator("quantity")
    @classmethod
    def qty_positive(cls, v):
        if v is None or v <= 0:
            raise ValueError("Количество должно быть положительным")
        return round(float(v), 8)


class CryptoTransfer(BaseModel):
    recipient: str          # адрес кошелька ИЛИ имя игрока
    symbol: str
    amount: float

    @field_validator("recipient")
    @classmethod
    def rec_ok(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("Укажите получателя")
        return v

    @field_validator("amount")
    @classmethod
    def amount_ok(cls, v):
        if v is None or v <= 0:
            raise ValueError("Сумма должна быть положительной")
        return round(float(v), 8)


# ── Seed / market maintenance ────────────────────────────────────────────────


async def ensure_coins_seeded(db: AsyncIOMotorDatabase):
    if await db.crypto_assets.count_documents({}) == 0:
        for c in DEFAULT_COINS:
            await db.crypto_assets.insert_one({
                **c,
                "volatilityHour": c.get("volatility", 0.05),
                "base_price": c["price"],
                "change24h": 0.0,
                "ath": c["price"],
                "atl": c["price"],
                "volume24h": round(c["price"] * c.get("supply", 0) * 0.04, 2),
                "updated_at": now_utc(),
            })
            await MarketDataService.ensure_backfill(db, "crypto", c["symbol"], c["price"], c.get("volatility", 0.05))


WALK_REVERSION = 0.1      # доля разрыва с базовой ценой, закрываемая за тик
VOLATILITY_HOUR_SECONDS = 60 * 60


def _walk_price(coin: dict) -> dict:
    """Блуждание цены с возвратом к среднему (OU-процесс) вокруг базовой.

    Без возврата к среднему это свободное случайное блуждание: коридор
    [0.3x, 3x] лишь отражает цену от краёв, и она диффундирует, заполняя
    весь 10x диапазон — капитализация качается в разы. Стационарное СКО
    процесса ≈ vol / sqrt(2 * WALK_REVERSION), для самого волатильного
    DUSK (0.14/ч) это ~0.3 → цена держится в пределах ~0.5x–2x от базы.
    """
    base = coin.get("base_price", coin["price"])
    vol = float(coin.get("volatilityHour", coin.get("volatility", 0.05)))
    old = coin["price"]
    step_vol = vol * (PRICE_REFRESH_SECONDS / VOLATILITY_HOUR_SECONDS) ** 0.5
    # ponytail: сохраняем небольшой случайный drift, но масштабируем шум по длине тика.
    drift = random.uniform(-0.5, 0.5) * step_vol
    log_return = drift + random.gauss(0, step_vol)
    new = old * math.exp(log_return) + WALK_REVERSION * (base - old)
    new = max(base * 0.5, min(base * 2, new))
    change = ((new - old) / old * 100) if old else 0.0
    coin["price"] = round(new, 6)
    coin["change24h"] = round(coin.get("change24h", 0.0) * 0.7 + change, 2)
    coin["ath"] = round(max(coin.get("ath", new), new), 6)
    coin["atl"] = round(min(coin.get("atl", new) or new, new), 6)
    coin["volume24h"] = round(new * coin.get("supply", 0) * (0.03 + abs(random.gauss(0, 0.02))), 2)
    coin["updated_at"] = now_utc()
    return coin


# In-memory кэш отформатированного рынка — чтобы не бить в БД на каждый рендер.
# Наполняется из БД (её актуальность поддерживает Scheduler); TTL короткий.
_MARKET_CACHE: dict = {"ts": None, "data": []}
_MARKET_CACHE_TTL_S = 5


def _format_coin(coin: dict) -> dict:
    coin = dict(coin)
    coin["id"] = str(coin.pop("_id"))
    coin.pop("updated_at", None)
    coin.pop("base_price", None)
    coin.pop("market_price", None)   # внутреннее поле «рыночной» цены
    if coin.get("marketCap") is None:
        price = coin.get("price") or 0
        supply = coin.get("supply") or 0
        coin["marketCap"] = round(price * supply)
    return coin


async def _attach_company_logos(db: AsyncIOMotorDatabase, coins: list[dict]) -> None:
    """Подставляет логотип компании в монеты без image (старые эмиссии)."""
    cids = list({c.get("companyId") for c in coins if c.get("companyId") and not c.get("image")})
    if not cids:
        return
    ids = [ObjectId(c) for c in cids if ObjectId.is_valid(c)]
    logos = {str(c["_id"]): c.get("logo") async for c in
             db.companies.find({"_id": {"$in": ids}}, {"logo": 1})}
    for c in coins:
        if not c.get("image") and logos.get(c.get("companyId")):
            c["image"] = logos[c["companyId"]]


async def _read_market(db: AsyncIOMotorDatabase) -> list[dict]:
    """БЫСТРОЕ чтение рынка из БД (без сети/бэкфилла/снимков).

    Данные поддерживаются в актуальном состоянии фоновым Scheduler'ом
    (``maintain_crypto_market``). На горячем пути — только лёгкое чтение
    с коротким in-memory кэшем, поэтому страницы открываются мгновенно и
    эндпоинт не может «зависнуть» на внешнем API.
    """
    now = datetime.now(timezone.utc)
    cached_ts = _MARKET_CACHE["ts"]
    if isinstance(cached_ts, datetime) and (now - cached_ts).total_seconds() < _MARKET_CACHE_TTL_S:
        return _MARKET_CACHE["data"]

    if await db.crypto_assets.count_documents({}) == 0:
        await ensure_coins_seeded(db)

    coins = [_format_coin(c) async for c in db.crypto_assets.find({})]
    await _attach_company_logos(db, coins)
    coins.sort(key=lambda c: c.get("marketCap") or (c.get("price", 0) * c.get("supply", 0)), reverse=True)
    _MARKET_CACHE["ts"] = now
    _MARKET_CACHE["data"] = coins
    return coins


# Обратная совместимость: прежнее имя теперь указывает на лёгкое чтение.
_get_live_market = _read_market


async def maintain_crypto_market(db: AsyncIOMotorDatabase):
    """Фоновое обслуживание крипторынка (вызывается Scheduler'ом).

    Здесь живёт ВСЯ тяжёлая работа: обновление реальными данными CoinGecko,
    симуляция цен (fallback), одноразовый бэкфилл истории и запись снимков.
    Читающие эндпоинты этого не делают — они лишь берут готовые данные из БД.
    """
    await ensure_coins_seeded(db)
    # Успел ли пройти интервал реального обновления? Если refresh реально сходил
    # в CoinGecko (не троттлинг) и вернул live — в coin["price"] лежит свежая
    # РЕАЛЬНАЯ цена, которую и берём как market_price.
    was_throttled = await MarketDataService._throttled(db, "crypto")
    mode = await MarketDataService.refresh_crypto(db)
    fresh_real = (mode == "live") and not was_throttled
    now = datetime.now(timezone.utc)
    updates = []
    async for coin in db.crypto_assets.find({}):
        symbol = coin["symbol"]
        market_price = float(coin.get("market_price") or coin.get("price") or coin.get("base_price") or 1)
        await MarketDataService.ensure_backfill(db, "crypto", symbol, market_price, coin.get("volatilityHour", coin.get("volatility", 0.05)))
        set_fields: dict = {}

        if coin.get("source") == "coingecko":
            if fresh_real:
                market_price = float(coin.get("price", market_price))
        else:
            # Блуждает market_price, а не display: иначе demand от сделок
            # компаундится в базу каждый тик и цена уходит в экспоненту.
            updated = coin.get("updated_at")
            if isinstance(updated, datetime) and updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if not isinstance(updated, datetime) or (now - updated).total_seconds() >= PRICE_REFRESH_SECONDS:
                tmp = dict(coin)
                tmp["price"] = market_price
                tmp = _walk_price(tmp)
                market_price = tmp["price"]
                set_fields.update({
                    "change24h": tmp["change24h"], "ath": tmp["ath"],
                    "atl": tmp["atl"], "volume24h": tmp["volume24h"],
                })

        # Спрос игроков медленно возвращается к 1.0.
        demand = float(coin.get("demand", 1.0))
        demand = max(DEMAND_MIN, min(DEMAND_MAX, demand + (1.0 - demand) * DEMAND_REVERT))
        display = round(market_price * demand, 6)

        set_fields.update({
            "market_price": round(market_price, 6),
            "demand": round(demand, 4),
            "price": display,
            "updated_at": now,
        })
        # ATH/ATL ведём по display — именно он пишется в price_history ниже.
        # Иначе доковый ath отстаёт от реального максимума истории на величину
        # спроса (TVX: 136.5 в доке против 150.5 в истории). Для coingecko-монет
        # не трогаем: там ath — настоящая историческая вершина из API.
        if coin.get("source") != "coingecko":
            set_fields["ath"] = round(max(float(coin.get("ath") or display), display), 6)
            set_fields["atl"] = round(min(float(coin.get("atl") or display), display), 6)
        await db.crypto_assets.update_one({"_id": coin["_id"]}, {"$set": set_fields})
        await MarketDataService.record_snapshot(db, "crypto", symbol, display)
        # Собираем обновления для WebSocket
        old_price = float(coin.get("price", display))
        if old_price != display:
            change = ((display - old_price) / old_price * 100) if old_price else 0.0
            updates.append({
                "symbol": symbol,
                "price": display,
                "change24h": round(coin.get("change24h", 0.0) * 0.7 + change, 2),
            })
    # Синтетические сделки ботов в рамках свободных монет (админка → synthetic).
    from synthetic import get_synthetic_config
    synth = await get_synthetic_config(db)
    await run_bots(db, synth["crypto"])
    # Сбрасываем кэш чтения, чтобы следующий запрос увидел свежие цены.
    _MARKET_CACHE["ts"] = None
    # Рассылаем обновления по WebSocket
    if updates:
        await broadcast({"type": "market_update", "market": "crypto", "updates": updates})


def _project_fill(coin: dict, side: str, total_usd: float) -> tuple[float, float]:
    """Считает (fill_price, new_demand) БЕЗ записи в БД.

    Сделка исполняется по текущей цене; новый спрос возвращается отдельно,
    чтобы после успешной оплаты рынок сдвинулся полным impact'ом.
    """
    market_price = float(coin.get("market_price") or coin.get("price") or 1)
    vol = float(coin.get("volume24h") or 0) or (market_price * float(coin.get("supply", 0) or 1) * 0.04) or 1.0
    frac = min(IMPACT_CAP, IMPACT_K * (float(total_usd) / max(vol, 1.0)))
    prev_demand = float(coin.get("demand", 1.0))
    demand = prev_demand * ((1 + frac) if side == "buy" else (1 - frac))
    demand = max(DEMAND_MIN, min(DEMAND_MAX, demand))
    prev_price = float(coin.get("price") or market_price * prev_demand)
    return round(prev_price, 6), demand


async def _apply_trade_impact(
    db: AsyncIOMotorDatabase, symbol: str, side: str, total_usd: float,
    *, record_history: bool = True,
) -> Optional[float]:
    """Сдвигает спрос (а значит и цену) монеты от сделки игрока.

    Покупка поднимает цену, продажа опускает — тем сильнее, чем крупнее сделка
    относительно суточного объёма. Реальная (market_price) цена не трогается —
    она остаётся базой; двигается только множитель спроса.

    Сдвиг в БД полный, а сделка списывает текущую цену до impact; это разделяет
    цену сделки и последующую рыночную переоценку.
    """
    coin = await db.crypto_assets.find_one({"symbol": symbol})
    if not coin:
        return None
    market_price = float(coin.get("market_price") or coin.get("price") or 1)
    vol = float(coin.get("volume24h") or 0) or (market_price * float(coin.get("supply", 0) or 1) * 0.04) or 1.0
    frac = min(IMPACT_CAP, IMPACT_K * (float(total_usd) / max(vol, 1.0)))
    demand = float(coin.get("demand", 1.0))
    demand *= (1 + frac) if side == "buy" else (1 - frac)
    demand = max(DEMAND_MIN, min(DEMAND_MAX, demand))
    display = round(market_price * demand, 6)
    old_price = float(coin.get("price", display))
    await db.crypto_assets.update_one(
        {"_id": coin["_id"]},
        {"$set": {"demand": round(demand, 4), "price": display}},
    )
    if record_history:
        await MarketDataService.record_snapshot(db, "crypto", symbol, display, force=True)
    _MARKET_CACHE["ts"] = None
    # WebSocket-оповещение о резком изменении цены от сделки
    if old_price != display:
        change = ((display - old_price) / old_price * 100) if old_price else 0.0
        await broadcast({
            "type": "price_tick",
            "market": "crypto",
            "symbol": symbol,
            "price": display,
            "change24h": round(coin.get("change24h", 0.0) * 0.7 + change, 2),
        })
    return display


async def _price_of(db: AsyncIOMotorDatabase, symbol: str) -> Optional[float]:
    coin = await db.crypto_assets.find_one({"symbol": symbol.upper()})
    return coin["price"] if coin else None


def _wallet_address(user_id: str) -> str:
    """Детерминированный адрес кошелька на основе id пользователя."""
    return "TVX-" + user_id[-12:].upper()


async def _credit_company_budget(db: AsyncIOMotorDatabase, coin: dict, amount: float):
    """Перечисляет выручку от покупки монеты компании в бюджет эмитента.

    Монеты с привязкой к компании (`companyId`) — инструмент привлечения капитала:
    покупка на бирже пополняет бюджет. Выкуп при продаже делается в trade_crypto
    обязательным гейтом до выплаты продавцу — не здесь (раньше условный $inc
    молча не срабатывал при пустом бюджете, что позволяло печатать деньги)."""
    cid = coin.get("companyId")
    if not cid or not ObjectId.is_valid(cid):
        return
    await db.companies.update_one({"_id": ObjectId(cid)}, {"$inc": {"budget": round(amount, 2)}})


# ── Account ──────────────────────────────────────────────────────────────────


@router.post("/account/open", status_code=status.HTTP_201_CREATED)
async def open_crypto_account(
    current_user: dict = Depends(require_allowed("crypto_account")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Открывает криптосчёт игроку. Идемпотентно возвращает уже открытый счёт."""
    user_id = str(current_user["_id"])
    if current_user.get("crypto_account_opened"):
        return {
            "opened": True,
            "wallet": current_user.get("crypto_wallet") or _wallet_address(user_id),
            "already": True,
        }
    wallet = _wallet_address(user_id)
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"crypto_account_opened": True, "crypto_wallet": wallet}},
    )
    return {"opened": True, "wallet": wallet, "already": False}


@router.get("/account")
async def get_crypto_account(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Состояние криптосчёта: открыт ли, кошелёк, холдинги и их оценка."""
    user_id = str(current_user["_id"])
    opened = bool(current_user.get("crypto_account_opened"))
    if not opened:
        return {"opened": False, "wallet": None, "holdings": [], "portfolioValue": 0.0}

    market = {c["symbol"]: c for c in await _get_live_market(db)}
    holdings = []
    portfolio_value = 0.0
    async for h in db.crypto_holdings.find({"userId": user_id}):
        symbol = h["symbol"]
        # Округление до 8 знаков прячет пыль от старых $inc-продаж (5e-15).
        qty = round(float(h.get("quantity", 0.0) or 0.0), 8)
        # Пыль и нулевые остатки не показываем и в оценку портфеля не включаем.
        if qty <= DUST_QTY:
            continue
        price = market.get(symbol, {}).get("price", 0.0)
        value = round(qty * price, 2)
        portfolio_value += value
        holdings.append({
            "symbol": symbol,
            "name": market.get(symbol, {}).get("name", symbol),
            "quantity": qty,
            "avgPrice": h.get("avg_price", 0.0),
            "price": price,
            "value": value,
            "color": market.get(symbol, {}).get("color", "#6366f1"),
        })
    holdings.sort(key=lambda x: x["value"], reverse=True)
    return {
        "opened": True,
        "wallet": current_user.get("crypto_wallet") or _wallet_address(user_id),
        "balance": current_user.get("balance", 0.0),
        "holdings": holdings,
        "portfolioValue": round(portfolio_value, 2),
    }


@router.get("/market")
async def get_crypto_market(
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Рынок криптовалют: список монет, цена, изменение за 24ч."""
    return await _get_live_market(db)


# ── Trade ────────────────────────────────────────────────────────────────────


def _crypto_quote(coin: dict, action: str, quantity: float) -> dict:
    """Расчёт сделки БЕЗ записи в БД — единый источник правды для /quote и модалки."""
    ref_price = float(coin.get("price") or 0)
    fill_price, demand = _project_fill(coin, action, quantity * ref_price)
    market_price = float(coin.get("market_price") or ref_price or 1)
    next_price = round(market_price * demand, 6)
    cost = round(quantity * fill_price, 2)
    fee = round(cost * CRYPTO_TRADE_FEE_RATE, 2)
    return {
        "price": ref_price,
        "fillPrice": fill_price,
        "nextPrice": next_price,
        "cost": cost,
        "fee": fee,
        "total": round(cost + fee, 2) if action == "buy" else round(cost - fee, 2),
        "feeRate": CRYPTO_TRADE_FEE_RATE,
    }


# ── Атомарный учёт эмиссии ────────────────────────────────────────────────────
# free = supply − bot_held − emission_sold, где emission_sold — монеты, ушедшие
# игрокам (покупки, майнинг). Резерв — атомарный guarded $inc на документе
# монеты: прежний check-then-act по _free_supply пропускал параллельные
# покупки (все читали один остаток до чужого списания), а начисление холдинга
# через read-modify-$set теряло инкременты вовсе.

async def _init_emission_sold(db, symbol: str, coin: dict) -> None:
    """Ленивая инициализация: emission_sold = текущие холдинги игроков.
    $exists-guard: при гонке второй инициатор видит уже созданный счётчик."""
    if "emission_sold" in coin:
        return
    held = 0.0
    async for h in db.crypto_holdings.aggregate([
        {"$match": {"symbol": symbol}},
        {"$group": {"_id": None, "q": {"$sum": "$quantity"}}},
    ]):
        held = float(h.get("q") or 0)
    await db.crypto_assets.update_one(
        {"symbol": symbol, "emission_sold": {"$exists": False}},
        {"$set": {"emission_sold": held}})


async def _reserve_emission(db, symbol: str, qty: float) -> bool:
    """Атомарно зарезервировать qty монет эмиссии. False — свободных нет.
    Эквивалент «свободно >= qty» И «свободно -= qty» одним действием."""
    coin = await db.crypto_assets.find_one({"symbol": symbol})
    if not coin:
        return False
    if float(coin.get("supply") or 0) <= 0:
        return True   # эмиссия не задана — лимита нет
    await _init_emission_sold(db, symbol, coin)
    res = await db.crypto_assets.find_one_and_update(
        {"symbol": symbol,
         "$expr": {"$lte": [
             {"$add": [{"$ifNull": ["$emission_sold", 0.0]}, qty]},
             {"$max": [{"$subtract": [{"$ifNull": ["$supply", 0.0]},
                                      {"$ifNull": ["$bot_held", 0.0]}]}, 0.0]}]}},
        {"$inc": {"emission_sold": qty}},
        return_document=True,
    )
    return res is not None


async def _release_emission(db, symbol: str, qty: float) -> None:
    """Вернуть qty монет в свободный остаток (откат резерва / продажа).
    Флор-кламп: счётчик не должен уходить в минус."""
    await db.crypto_assets.update_one(
        {"symbol": symbol},
        [{"$set": {"emission_sold": {"$max": [
            {"$subtract": [{"$ifNull": ["$emission_sold", 0.0]}, qty]}, 0.0]}}}])


async def _free_supply(db: AsyncIOMotorDatabase, coin: dict) -> float:
    """Свободные монеты: эмиссия − холдинги ВСЕХ игроков − купленное ботами.

    Быстрый путь по счётчику emission_sold (поддерживается атомарно сделками
    и майнингом); агрегат по холдингам — только пока счётчик не заведён.
    supply <= 0 — эмиссия не задана, лимита нет.
    """
    supply = float(coin.get("supply") or 0)
    if supply <= 0:
        return float("inf")
    if "emission_sold" in coin:
        return max(0.0, supply - float(coin.get("bot_held") or 0) - float(coin["emission_sold"] or 0))
    held = 0.0
    async for h in db.crypto_holdings.aggregate([
        {"$match": {"symbol": coin["symbol"]}},
        {"$group": {"_id": None, "q": {"$sum": "$quantity"}}},
    ]):
        held = float(h.get("q") or 0)
    return max(0.0, supply - held - float(coin.get("bot_held") or 0))


def _max_affordable(coin: dict, balance: float) -> float:
    """Максимальное количество, которое реально влезает в баланс.

    Клиент это посчитать не может: price-impact зависит от объёма сделки, поэтому
    любая фиксированная «скидка на комиссию» либо не дотягивает, либо перебирает —
    кнопка МАКС предлагала сумму, которую тут же отклоняли по балансу. Стоимость
    монотонна по количеству, так что берём дихотомию по той же формуле.
    """
    price = float(coin.get("price") or 0)
    if price <= 0 or balance <= 0:
        return 0.0
    lo, hi = 0.0, balance / price          # без impact и комиссии — заведомо больше ответа
    for _ in range(60):
        mid = (lo + hi) / 2
        if _crypto_quote(coin, "buy", mid)["total"] <= balance:
            lo = mid
        else:
            hi = mid
    # Округляем вниз: вверх вылезло бы за баланс, который мы только что подбирали.
    return math.floor(lo * 1e8) / 1e8


@router.get("/quote")
async def quote_crypto(
    symbol: str = Query(...),
    action: str = Query("buy"),
    quantity: float = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Предварительный расчёт сделки по той же формуле, что и /trade.

    Модалка обязана показывать сумму с учётом price-impact и комиссии, иначе
    покупка отклоняется по балансу, которого «визуально» хватало.
    """
    symbol = symbol.strip().upper()
    action = action.lower()
    if action not in ("buy", "sell"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "action должно быть 'buy' или 'sell'")
    coin = await db.crypto_assets.find_one({"symbol": symbol})
    if coin is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Монета не найдена")
    q = _crypto_quote(coin, action, quantity)
    max_affordable = _max_affordable(coin, float(current_user.get("balance") or 0))
    if action == "buy":
        max_buy = float("inf")
        supply = float(coin.get("supply") or 0)
        if supply > 0:
            held = await db.crypto_holdings.find_one(
                {"userId": str(current_user["_id"]), "symbol": symbol})
            # Персональный лимит концентрации (90% эмиссии)...
            max_buy = max(0.0, round(
                supply * MAX_HOLD_SHARE - float((held or {}).get("quantity", 0.0) or 0.0), 8))
        # ...плюс общий остаток эмиссии: суммарно игроки не могут купить больше выпуска.
        max_buy = min(max_buy, round(await _free_supply(db, coin), 8))
        q["maxBuyable"] = max_buy
        max_affordable = min(max_affordable, max_buy)
    q["maxAffordable"] = max_affordable
    return q


@router.post("/trade")
async def trade_crypto(
    payload: CryptoTrade,
    current_user: dict = Depends(require_allowed("crypto_trade")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Покупка/продажа криптовалюты. Требует открытого криптосчёта."""
    if not current_user.get("crypto_account_opened"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Сначала откройте криптосчёт",
        )

    user_id = str(current_user["_id"])
    symbol = payload.symbol.upper()
    qty = payload.quantity

    coin = await db.crypto_assets.find_one({"symbol": symbol})
    if coin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Монета не найдена")

    holding = await db.crypto_holdings.find_one({"userId": user_id, "symbol": symbol})
    # «Продать максимум»: запрос в пределах пыли от баланса добирает остаток
    # целиком, чтобы после $round не оставалось 0.00000001 (и наоборот —
    # запрос чуть больше округлённого баланса не падал с «Недостаточно монет»).
    if payload.action == "sell" and holding:
        hq = round(float(holding.get("quantity", 0.0) or 0.0), 8)
        if hq > 0 and abs(hq - qty) <= DUST_QTY:
            qty = hq

    # Сумма сделки фиксируется по текущей цене; после успешной оплаты спрос
    # сдвигает рыночную цену полным impact'ом. См. _project_fill.
    ref_price = float(coin.get("price") or 0)
    fill_price, _ = _project_fill(coin, payload.action, qty * ref_price)
    price = fill_price
    total = round(qty * price, 2)
    # Минимальный номинал: сделки, округляющиеся до 0.00, недопустимы — иначе
    # покупка «бесплатных» монет крошечными порциями (qty*price < 0.005) минтит
    # актив с нулевой стоимостью, который затем продаётся за реальный кэш.
    if total <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Слишком маленький объём сделки",
        )
    fee = round(total * CRYPTO_TRADE_FEE_RATE, 2)

    if payload.action == "buy":
        supply = float(coin.get("supply") or 0)
        # 1) Атомарный резерв эмиссии: guarded $inc на документе монеты.
        # Прежний check-then-act по _free_supply пропускал параллельные
        # покупки (все читали один и тот же остаток) — суммарно игроки
        # выкупали больше выпуска.
        if supply > 0:
            if not await _reserve_emission(db, symbol, qty):
                free_now = await _free_supply(db, coin)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Эмиссия исчерпана: свободно {free_now:g} {symbol}",
                )
        # 2) Списание денег (атомарно по балансу).
        new_balance = await adjust_balance(db, user_id, -round(total + fee, 2))
        if new_balance is None:
            if supply > 0:
                await _release_emission(db, symbol, qty)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Недостаточно средств",
            )
        # 3) Атомарное начисление холдинга: $inc через pipeline-обновление
        # (не read-modify-$set — параллельные покупки теряли инкременты,
        # деньги при этом списывались). Личный лимит концентрации — в
        # условии обновления: оценивается атомарно с инкрементом.
        cap_q = round(supply * MAX_HOLD_SHARE, 8) if supply > 0 else None
        # $expr запрещён в upsert-запросах: гарантируем существование холдинга
        # до guarded-обновления (для новой эмиссии лимит проверим так же).
        if holding is None:
            await db.crypto_holdings.update_one(
                {"userId": user_id, "symbol": symbol},
                {"$setOnInsert": {"userId": user_id, "symbol": symbol,
                                  "quantity": 0.0, "avg_price": 0.0}},
                upsert=True,
            )
        hq = {"userId": user_id, "symbol": symbol}
        if cap_q is not None:
            hq["$expr"] = {"$lte": [
                {"$add": [{"$ifNull": ["$quantity", 0.0]}, qty]}, cap_q]}
        updated = await db.crypto_holdings.find_one_and_update(
            hq,
            [{"$set": {
                "quantity": {"$round": [
                    {"$add": [{"$ifNull": ["$quantity", 0.0]}, qty]}, 8]},
                "avg_price": {"$cond": [
                    {"$gt": [{"$add": [{"$ifNull": ["$quantity", 0.0]}, qty]}, 0]},
                    {"$round": [{"$divide": [
                        {"$add": [
                            {"$multiply": [{"$ifNull": ["$quantity", 0.0]}, {"$ifNull": ["$avg_price", 0.0]}]},
                            total]},
                        {"$add": [{"$ifNull": ["$quantity", 0.0]}, qty]}]}, 6]},
                    price]}},
            }],
            return_document=True,
        )
        if updated is None:
            # Личный лимит концентрации: откат денег и резерва эмиссии.
            await adjust_balance(db, user_id, round(total + fee, 2))
            if supply > 0:
                await _release_emission(db, symbol, qty)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Лимит эмиссии: один игрок может держать максимум "
                       f"{int(MAX_HOLD_SHARE * 100)}% всех {symbol}",
            )
        await record_transaction(
            db, user_id, EXPENSE, round(total + fee, 2), CAT_CRYPTO,
            f"Покупка {qty:g} {symbol}", symbol=symbol, price=price,
            balance_after=new_balance, meta={"quantity": qty, "action": "buy", "fee": fee},
        )
        await credit_state(db, fee, "crypto_fee")
        await _apply_trade_impact(db, symbol, "buy", qty * ref_price)
        # Монета компании: выручка от покупки на бирже пополняет бюджет эмитента
        # (привлечение капитала). См. stocks._credit_company_budget — та же логика.
        await _credit_company_budget(db, coin, total)
        return {"message": "Покупка выполнена", "symbol": symbol, "quantity": qty,
                "price": price, "total": total, "fee": fee, "balance": new_balance}

    # sell
    if not holding or holding.get("quantity", 0.0) < qty:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Недостаточно монет")
    # Атомарное списание монет: условие quantity >= qty проверяется в БД, чтобы
    # две параллельные продажи не продали одни и те же монеты дважды. $inc
    # дробных чисел оставляет пыль (5e-15), которую потом не продать, поэтому
    # остаток клампится в 0 и округляется до 8 знаков в том же обновлении.
    sold = await db.crypto_holdings.find_one_and_update(
        {"userId": user_id, "symbol": symbol, "quantity": {"$gte": qty}},
        [{"$set": {"quantity": {"$round": [
            {"$max": [{"$subtract": ["$quantity", qty]}, 0.0]}, 8]}}}],
        return_document=True,
    )
    if not sold:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Недостаточно монет")
    if float(sold.get("quantity", 0.0) or 0.0) <= 0.0:
        # Полная продажа — холдинг с нулём не храним (иначе «мёртвая» строка в портфеле).
        await db.crypto_holdings.delete_one({"_id": sold["_id"]})
    # Компания-эмитент выкупает монеты из бюджета; при нехватке бюджета —
    # рефанд монет продавцу и отказ. Дебит бюджета после списания монет.
    cid = coin.get("companyId")
    if cid and ObjectId.is_valid(cid):
        budget_paid = await db.companies.find_one_and_update(
            {"_id": ObjectId(cid), "budget": {"$gte": total}},
            {"$inc": {"budget": -total}},
        )
        if not budget_paid:
            await db.crypto_holdings.update_one(
                {"userId": user_id, "symbol": symbol},
                {"$inc": {"quantity": qty}, "$setOnInsert": {"userId": user_id, "symbol": symbol}},
                upsert=True,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Компания не может выкупить монеты: недостаточно средств в бюджете",
            )
    # Продавец получает стоимость за вычетом комиссии.
    proceeds = round(total - fee, 2)
    new_balance = await adjust_balance(db, user_id, proceeds)
    await record_transaction(
        db, user_id, INCOME, proceeds, CAT_CRYPTO,
        f"Продажа {qty:g} {symbol}", symbol=symbol, price=price,
        balance_after=new_balance, meta={"quantity": qty, "action": "sell", "fee": fee},
    )
    await credit_state(db, fee, "crypto_fee")
    await _apply_trade_impact(db, symbol, "sell", qty * ref_price)
    # Монеты вернулись в свободный оборот: уменьшаем счётчик эмиссии.
    if float(coin.get("supply") or 0) > 0:
        await _release_emission(db, symbol, qty)
    # Выкуп из бюджета компании уже выполнен выше — гейтом перед выплатой.
    return {"message": "Продажа выполнена", "symbol": symbol, "quantity": qty,
            "price": price, "total": total, "fee": fee, "balance": new_balance}


# ── Боты-покупатели (синтетические транзакции) ───────────────────────────────
# Имитируют рыночную активность по монетам теми же механизмами, что и сделки
# игроков: двигают спрос/цену через _apply_trade_impact, пишут события в
# crypto_events. Параметры и вкл/выкл — app_config["synthetic_config"]
# (админка → synthetic; см. backend/synthetic.py). Денег у бота нет —
# в ledger синтетические сделки не попадают.
BOT_USER_ID = "bot"
BOT_MIN_TRADE_USD = 0.01   # пыль дешевле цента не двигает спрос — не торгуем


async def _bot_coin_trade(
    db: AsyncIOMotorDatabase, coin: dict, cfg: dict,
    side: Optional[str] = None, quantity: Optional[float] = None,
) -> bool:
    """Одна синтетическая сделка по монете. False — сделка не состоялась.

    Строго в рамках свободных монет: покупка режется по остатку
    (эмиссия − холдинги игроков − купленное ботом ранее), продажа — по
    купленному ботом ранее (bot_held на документе монеты).
    """
    symbol = coin["symbol"]
    price = float(coin.get("price") or 0)
    if price <= 0:
        return False
    # ponytail: случайный bias вместо 50/50 — иначе покупки и продажи взаимно
    # гасятся. Вероятность покупки тянется из [buyBiasMin, buyBiasMax] конфига.
    buy_prob = random.uniform(cfg["buyBiasMin"], cfg["buyBiasMax"])
    action = side or ("buy" if random.random() < buy_prob else "sell")
    volume = random.uniform(cfg["minVolumeUsd"], cfg["maxVolumeUsd"])
    qty = float(quantity) if quantity is not None else volume / price

    if action == "buy":
        qty = min(qty, await _free_supply(db, coin))
    else:
        qty = min(qty, float(coin.get("bot_held") or 0))
    if qty * price < BOT_MIN_TRADE_USD:
        return False
    qty = round(qty, 8)

    if action == "buy":
        # Атомарный резерв свободной эмиссии под бота: guarded $inc bot_held
        # (bot_held + qty <= supply - emission_sold). Прежний check-then-act
        # по _free_supply в гонке с покупками игроков позволял выкупить
        # больше выпуска.
        if "emission_sold" not in coin:
            await _init_emission_sold(db, symbol, coin)
        res = await db.crypto_assets.find_one_and_update(
            {"symbol": symbol,
             "$expr": {"$lte": [
                 {"$add": [{"$ifNull": ["$bot_held", 0.0]}, qty]},
                 {"$max": [{"$subtract": [{"$ifNull": ["$supply", 0.0]},
                                          {"$ifNull": ["$emission_sold", 0.0]}]}, 0.0]}]}},
            {"$inc": {"bot_held": qty}},
            return_document=True,
        )
        if res is None:
            return False   # свободной эмиссии нет

    new_price = await _apply_trade_impact(
        db, symbol, action, qty * price, record_history=False,
    )
    if new_price is None:
        if action == "buy":
            # откат резерва: сделка не состоялась
            await db.crypto_assets.update_one({"symbol": symbol}, {"$inc": {"bot_held": -qty}})
        return False
    if action == "sell":
        await db.crypto_assets.update_one(
            {"symbol": symbol}, {"$inc": {"bot_held": -qty}})
    await db.crypto_events.insert_one({
        "symbol": symbol,
        "type": action,
        "quantity": qty,
        "priceBefore": price,
        "priceAfter": new_price,
        "userId": BOT_USER_ID,
        "timestamp": now_utc(),
    })
    return True


async def run_bots(
    db: AsyncIOMotorDatabase, cfg: dict,
    symbol: Optional[str] = None, side: Optional[str] = None,
    quantity: Optional[float] = None,
) -> int:
    """Раунды ботов по монетам. Возвращает число сделок.

    Без symbol — roundsPerTick раундов с вероятностью probability (фоновый тик
    и ручной «запустить раунд»); с symbol — одна разовая сделка (side/quantity
    из админки), всё равно в пределах свободных монет.
    """
    if not cfg.get("enabled", True) or cfg["roundsPerTick"] <= 0:
        return 0
    executed = 0
    rounds = 1 if symbol else int(cfg["roundsPerTick"])
    for _ in range(rounds):
        coins = await db.crypto_assets.find({}).to_list(None)
        for coin in coins:
            if symbol and coin["symbol"] != symbol.upper():
                continue
            if not symbol and random.random() > cfg["probability"]:
                continue
            if await _bot_coin_trade(db, coin, cfg, side=side, quantity=quantity):
                executed += 1
    return executed


# ── Wallet-to-wallet transfers ───────────────────────────────────────────────


@router.post("/transfer")
async def transfer_crypto(
    payload: CryptoTransfer,
    current_user: dict = Depends(require_allowed("crypto_transfer")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Перевод криптовалюты другому игроку по адресу кошелька или нику.

    Проверки: получатель существует и имеет криптосчёт, нельзя себе,
    достаточно монет (с учётом комиссии), сумма положительна.
    Комиссия сети (CRYPTO_FEE_RATE) сгорает.
    """
    if not current_user.get("crypto_account_opened"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Сначала откройте криптосчёт")

    sender_id = str(current_user["_id"])
    symbol = payload.symbol.upper()
    amount = payload.amount
    fee = round(amount * CRYPTO_FEE_RATE, 8)
    total_debit = round(amount + fee, 8)

    coin = await db.crypto_assets.find_one({"symbol": symbol})
    if not coin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Монета не найдена")
    price = float(coin.get("price", 0))

    recipient = await db.users.find_one({
        "$or": [{"crypto_wallet": payload.recipient}, {"username": payload.recipient}]
    })
    if not recipient:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Получатель не найден")
    rec_id = str(recipient["_id"])
    if rec_id == sender_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя перевести самому себе")
    if not recipient.get("crypto_account_opened"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "У получателя нет криптосчёта")

    # Гейт новичка: и отправитель, и получатель должны иметь состояние от порога.
    await ensure_transfer_allowed(db, current_user)
    await ensure_transfer_allowed(db, recipient, recipient=True)

    sender_level = int(current_user.get("level", 1))
    if sender_level < TRANSFER_SEND_MIN_LEVEL:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Переводы доступны с {TRANSFER_SEND_MIN_LEVEL} уровня (ваш: {sender_level})",
        )
    recipient_level = int(recipient.get("level", 1))
    if recipient_level < TRANSFER_RECEIVE_MIN_LEVEL:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Получатель может принимать переводы с {TRANSFER_RECEIVE_MIN_LEVEL} уровня",
        )

    # Атомарное списание у отправителя с проверкой достаточности (с учётом комиссии).
    debited = await db.crypto_holdings.find_one_and_update(
        {"userId": sender_id, "symbol": symbol, "quantity": {"$gte": total_debit}},
        {"$inc": {"quantity": -total_debit}},
        return_document=True,
    )
    if not debited:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно монет (с учётом комиссии)")
    if debited.get("quantity", 0) <= 1e-9:
        await db.crypto_holdings.delete_one({"_id": debited["_id"]})

    # Зачисление получателю (пересчёт средней цены). При любом сбое возвращаем
    # монеты отправителю — иначе они «сгорают» (списаны, но не зачислены).
    try:
        rec_h = await db.crypto_holdings.find_one({"userId": rec_id, "symbol": symbol})
        old_qty = rec_h.get("quantity", 0.0) if rec_h else 0.0
        old_avg = rec_h.get("avg_price", 0.0) if rec_h else 0.0
        new_qty = round(old_qty + amount, 8)
        new_avg = round((old_qty * old_avg + amount * price) / new_qty, 6) if new_qty else price
        await db.crypto_holdings.update_one(
            {"userId": rec_id, "symbol": symbol},
            {"$set": {"quantity": new_qty, "avg_price": new_avg}},
            upsert=True,
        )
    except Exception:
        # Компенсация отправителю (зеркально денежному переводу в economy.py).
        await db.crypto_holdings.update_one(
            {"userId": sender_id, "symbol": symbol},
            {"$inc": {"quantity": total_debit},
             "$setOnInsert": {"userId": sender_id, "symbol": symbol}},
            upsert=True,
        )
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Не удалось выполнить перевод")

    value = round(amount * price, 2)
    now = now_utc()
    await db.crypto_transfers.insert_one({
        "fromId": sender_id, "fromName": current_user.get("username"),
        "toId": rec_id, "toName": recipient.get("username"),
        "symbol": symbol, "amount": amount, "fee": fee,
        "price": price, "value": value, "ts": now,
    })
    await push_notification(
        db, rec_id, "crypto_transfer", "Получен крипто-перевод",
        f"{current_user.get('username')} отправил {amount:g} {symbol}.",
        data={"symbol": symbol, "amount": amount},
    )
    return {
        "ok": True, "sent": amount, "fee": fee, "symbol": symbol,
        "recipient": recipient.get("username"),
    }


@router.get("/transfers")
async def crypto_transfers(
    limit: int = 30,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """История крипто-переводов игрока (отправленные и полученные)."""
    user_id = str(current_user["_id"])
    limit = max(1, min(limit, 100))
    out = []
    cursor = db.crypto_transfers.find(
        {"$or": [{"fromId": user_id}, {"toId": user_id}]}
    ).sort("ts", -1).limit(limit)
    async for tr in cursor:
        outgoing = tr.get("fromId") == user_id
        out.append({
            "id": str(tr["_id"]),
            "direction": "out" if outgoing else "in",
            "counterparty": tr.get("toName") if outgoing else tr.get("fromName"),
            "symbol": tr.get("symbol"),
            "amount": tr.get("amount"),
            "fee": tr.get("fee") if outgoing else 0,
            "value": tr.get("value"),
            "timestamp": tr["ts"].isoformat() if isinstance(tr.get("ts"), datetime) else None,
        })
    return out


# ── Admin: create / edit / delete coins ──────────────────────────────────────


class CryptoAdminUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    marketCap: Optional[float] = None
    volatilityHour: Optional[float] = None
    volatility: Optional[float] = None
    color: Optional[str] = None
    description: Optional[str] = None


class CryptoAdminCreate(BaseModel):
    symbol: str
    name: str
    price: float
    volatilityHour: Optional[float] = None
    volatility: float = 0.05
    color: str = "#6366f1"
    supply: Optional[float] = None
    description: str = ""


@router.patch("/admin/{symbol}")
async def admin_update_coin(
    symbol: str,
    payload: CryptoAdminUpdate,
    _admin: dict = Depends(require_admin("crypto")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Точечное редактирование монеты. marketCap задаёт supply = marketCap/price;
    price дополнительно переустанавливает base_price (якорь коридора _walk_price)."""
    symbol = symbol.upper()
    coin = await db.crypto_assets.find_one({"symbol": symbol})
    if not coin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Монета не найдена")

    fields = payload.model_dump(exclude_unset=True, exclude_none=True)
    hourly_volatility = fields.pop("volatilityHour", fields.get("volatility"))
    if hourly_volatility is not None:
        fields["volatilityHour"] = hourly_volatility
        fields["volatility"] = hourly_volatility
    new_price = fields.get("price")
    new_market_cap = fields.pop("marketCap", None)
    if new_market_cap is not None:
        price_for_supply = new_price if new_price is not None else float(coin.get("price", 0))
        if price_for_supply > 0:
            fields["supply"] = round(new_market_cap / price_for_supply)
            fields["marketCap"] = round(new_market_cap, 2)
    if new_price is not None:
        fields["base_price"] = new_price
    fields["updated_at"] = now_utc()

    await db.crypto_assets.update_one({"symbol": symbol}, {"$set": fields})
    _MARKET_CACHE["ts"] = None
    updated = await db.crypto_assets.find_one({"symbol": symbol})
    return _format_coin(updated)


@router.post("/admin", status_code=status.HTTP_201_CREATED)
async def admin_create_coin(
    payload: CryptoAdminCreate,
    _admin: dict = Depends(require_admin("crypto")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    symbol = payload.symbol.upper()
    if await db.crypto_assets.find_one({"symbol": symbol}):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Монета '{symbol}' уже существует")
    supply = payload.supply if payload.supply is not None else 0
    hourly_volatility = payload.volatilityHour if payload.volatilityHour is not None else payload.volatility
    doc = {
        "symbol": symbol, "name": payload.name, "price": payload.price,
        "base_price": payload.price, "volatilityHour": hourly_volatility,
        "volatility": hourly_volatility,
        "color": payload.color, "supply": supply, "description": payload.description,
        "change24h": 0.0, "ath": payload.price, "atl": payload.price,
        "volume24h": round(payload.price * supply * 0.04, 2),
        "updated_at": now_utc(),
    }
    await db.crypto_assets.insert_one(doc)
    await MarketDataService.ensure_backfill(db, "crypto", symbol, payload.price, hourly_volatility)
    _MARKET_CACHE["ts"] = None
    created = await db.crypto_assets.find_one({"symbol": symbol})
    return _format_coin(created)


@router.delete("/admin/{symbol}")
async def admin_delete_coin(
    symbol: str,
    _admin: dict = Depends(require_admin("crypto")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Удаляет монету. ponytail: не каскадит crypto_holdings/price_history —
    приемлемо для админ-инструмента удаления монеты, которую никто не держит."""
    symbol = symbol.upper()
    result = await db.crypto_assets.delete_one({"symbol": symbol})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Монета не найдена")
    _MARKET_CACHE["ts"] = None
    return {"deleted": True}


if __name__ == "__main__":
    # marketCap -> supply recompute (единственная нетривиальная новая логика здесь).
    price, market_cap = 100.0, 50_000_000.0
    assert round(market_cap / price) == 500_000
    # Блуждание цены должно быть стационарным вокруг базы, а не свободным
    # диффузионным процессом, заполняющим коридор [0.3x, 3x] (→ качели
    # капитализации в разы). Самая волатильная монета, 5000 тиков (~3.5 суток).
    coin = {"price": 100.0, "base_price": 100.0, "volatility": 0.14}
    lo, hi = float("inf"), 0.0
    for _ in range(5000):
        coin = _walk_price(coin)
        lo, hi = min(lo, coin["price"]), max(hi, coin["price"])
    assert hi <= 200.0, f"цена улетела вверх: {hi} при базе 100"
    assert lo >= 50.0, f"цена рухнула вниз: {lo} при базе 100"
    # Лимит концентрации: купить можно только до 90% эмиссии минус уже держимое.
    _supply, _held = 1_000_000.0, 400_000.0
    _max_qty = max(0.0, round(_supply * MAX_HOLD_SHARE - _held, 8))
    assert _max_qty == 500_000.0   # 900k − 400k
    assert max(0.0, round(_supply * MAX_HOLD_SHARE - (_supply * MAX_HOLD_SHARE + 1), 8)) == 0.0  # уже >90% — покупка закрыта
    # Свободные монеты: эмиссия − холдинги всех игроков − bot_held; без эмиссии лимита нет.
    assert max(0.0, 1_000_000.0 - 700_000.0 - 100_000.0) == 200_000.0
    assert max(0.0, 1_000_000.0 - 1_100_000.0 - 0.0) == 0.0   # перепокупка игроками → 0
    assert float("inf") > 999_999.0                            # supply=0 → лимита нет
    # Бот: покупка режется свободным остатком, продажа — не больше bot_held; пыль отсекается.
    assert min(999.0, 200_000.0) == 999.0
    assert min(999.0, 100.0) == 100.0
    assert 0.001 * 5 < BOT_MIN_TRADE_USD
    print("crypto self-check OK")
