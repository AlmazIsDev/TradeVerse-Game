"""Управление экономикой (админ): аналитика и настраиваемые коэффициенты.

- get_econ(db) — единая точка чтения экономических коэффициентов; их читают
  подсистемы (доход активов/компаний, аренда, майнинг, WarCoin).
- /api/admin/economy/config  — просмотр/изменение коэффициентов.
- /api/admin/economy/analytics — сводка состояния экономики.
"""
from __future__ import annotations

from typing import Optional

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from admin_perms import require_admin
from database import get_db, find_config_by_key, upsert_config

router = APIRouter(prefix="/api/admin/economy", tags=["economy-admin"])

ECON_KEY = "economy_config"
STARTING_BALANCE = 15000.0
WARCOIN_USD = 50.0

DEFAULT_ECON = {
    "income_mult": 1.0,     # множитель доходов (активы/компании)
    "rent_mult": 1.0,       # множитель аренды
    "tax_rate": 0.0,        # налог на операции (0..0.5)
    "inflation": 0.0,       # инфляция (информационная)
    "energy_cost": 0.12,    # стоимость энергии ($/kWh) — для майнинга
    "wc_price": 50.0,       # цена WarCoin
    "economy_mult": 1.0,    # общий множитель экономики
    # ── Майнинг-подвал (улучшение «Майнинг» для домов, assets.py) ────────────
    "mining_basement_cost": 12000.0,    # цена улучшения за единицу ёмкости подвала
    "mining_basement_income": 35.0,     # пассивный доход $/ч за единицу подвала
    # ── Инфраструктура (заводы/источники/склады, assets.py) ──────────────────
    "infra_gpu_price": 250.0,       # $ за единицу продукции завода (meta.produces="gpu")
    "infra_metal_price": 60.0,      # $ за единицу ресурса
    "infra_food_price": 15.0,       # $ за единицу ресурса
    "infra_wood_price": 40.0,       # $ за единицу ресурса
    "infra_warehouse_rate": 0.15,   # $/ч за м² площади склада
    # ── Банк государства ─────────────────────────────────────────────────────
    "electricity_fee_rate": 0.05,   # доля комиссии с оплаты электроэнергии → счёт государства
    "loan_rate": 0.10,              # процент кредита (доля от суммы) → счёт государства
    "deposit_rate": 0.02,           # процент депозита (доля в сутки) → списывается со счёта государства
}


async def get_econ(db: AsyncIOMotorDatabase) -> dict:
    """Текущие экономические коэффициенты (дефолт + сохранённые overrides)."""
    doc = await find_config_by_key(db, ECON_KEY)
    cfg = dict(DEFAULT_ECON)
    if doc:
        try:
            cfg.update(json.loads(doc["value"]))
        except Exception:
            pass
    return cfg


class EconConfigUpdate(BaseModel):
    income_mult: Optional[float] = None
    rent_mult: Optional[float] = None
    tax_rate: Optional[float] = None
    inflation: Optional[float] = None
    energy_cost: Optional[float] = None
    wc_price: Optional[float] = None
    economy_mult: Optional[float] = None
    mining_basement_cost: Optional[float] = None
    mining_basement_income: Optional[float] = None
    infra_gpu_price: Optional[float] = None
    infra_metal_price: Optional[float] = None
    infra_food_price: Optional[float] = None
    infra_wood_price: Optional[float] = None
    infra_warehouse_rate: Optional[float] = None
    electricity_fee_rate: Optional[float] = None
    loan_rate: Optional[float] = None
    deposit_rate: Optional[float] = None


@router.get("/config")
async def get_config(_admin=Depends(require_admin("economy_view")), db: AsyncIOMotorDatabase = Depends(get_db)):
    return await get_econ(db)


@router.post("/config")
async def set_config(
    payload: EconConfigUpdate,
    _admin=Depends(require_admin("economy_config")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    cfg = await get_econ(db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            cfg[key] = round(float(value), 4)
    await upsert_config(db, ECON_KEY, json.dumps(cfg))
    return cfg


def _asset_value(a: dict) -> float:
    return a.get("price", 0) * (1 + 0.35 * (a.get("level", 1) - 1))


async def compute_analytics(db: AsyncIOMotorDatabase) -> dict:
    """Полная сводка состояния экономики проекта.

    Служебные аккаунты (роль admin, legacy-бот) из статистики исключены:
    их тестовые балансы и обороты раздували капитал, денежную массу и
    «объём сделок» синтетическими операциями на квадриллионы.
    """
    # Цены.
    stock_prices = {s["symbol"]: float(s.get("price", 0.0)) async for s in db.stocks.find({}, {"symbol": 1, "price": 1})}
    crypto_prices = {c["symbol"]: float(c.get("price", 0.0)) async for c in db.crypto_assets.find({}, {"symbol": 1, "price": 1})}

    # Служебные аккаунты — не игроки.
    admin_ids = {str(u["_id"]) async for u in db.users.find({"role": "admin"})}
    admin_ids.add("bot")  # legacy-идентификатор сделок ботов
    not_admin = {"userId": {"$nin": list(admin_ids)}}

    # Пользователи и наличные.
    users_count = 0
    total_cash = 0.0
    total_warcoin = 0.0
    async for u in db.users.find({}, {"balance": 1, "warcoin": 1, "role": 1}):
        if str(u["_id"]) in admin_ids:
            continue
        users_count += 1
        total_cash += float(u.get("balance", STARTING_BALANCE))
        total_warcoin += float(u.get("warcoin", 0) or 0)

    # Позиции.
    stock_value = 0.0
    stock_holdings = 0
    async for h in db.stock_holdings.find({"quantity": {"$gt": 0}, **not_admin}):
        stock_holdings += 1
        stock_value += h.get("quantity", 0) * stock_prices.get(h.get("symbol"), 0.0)
    crypto_value = 0.0
    async for h in db.crypto_holdings.find({"quantity": {"$gt": 0}, **not_admin}):
        crypto_value += h.get("quantity", 0.0) * crypto_prices.get(h.get("symbol"), 0.0)

    # Физические активы.
    counts = {"realestate": 0, "business": 0, "car": 0}
    asset_value = 0.0
    async for a in db.user_assets.find(not_admin):
        counts[a.get("type", "realestate")] = counts.get(a.get("type", "realestate"), 0) + 1
        asset_value += _asset_value(a)

    companies_count = await db.companies.count_documents({"ownerId": {"$nin": list(admin_ids)}})
    company_budgets = 0.0
    async for c in db.companies.find({"ownerId": {"$nin": list(admin_ids)}}, {"budget": 1}):
        company_budgets += float(c.get("budget", 0.0))

    # Объём сделок за 24ч (без синтетического оборота служебных аккаунтов).
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    daily_volume = 0.0
    daily_ops = 0
    async for tx in db.transactions.find({"timestamp": {"$gte": since}, **not_admin}, {"amount": 1}):
        daily_ops += 1
        daily_volume += float(tx.get("amount", 0.0))

    total_capital = round(total_cash + stock_value + crypto_value + asset_value + company_budgets + total_warcoin * WARCOIN_USD, 2)
    money_supply = round(total_cash + company_budgets, 2)

    return {
        "users": users_count,
        "moneySupply": money_supply,
        "totalCash": round(total_cash, 2),
        "totalCapital": total_capital,
        "avgCapital": round(total_capital / users_count, 2) if users_count else 0.0,
        "warcoin": round(total_warcoin, 2),
        "warcoinValue": round(total_warcoin * WARCOIN_USD, 2),
        "stocks": {"holdings": stock_holdings, "value": round(stock_value, 2)},
        "crypto": {"value": round(crypto_value, 2)},
        "assets": {
            "realestate": counts.get("realestate", 0),
            "business": counts.get("business", 0),
            "cars": counts.get("car", 0),
            "value": round(asset_value, 2),
        },
        "companies": {"count": companies_count, "budgets": round(company_budgets, 2)},
        "dailyVolume": round(daily_volume, 2),
        "dailyOperations": daily_ops,
    }


@router.get("/analytics")
async def analytics(_admin=Depends(require_admin("economy_view")), db: AsyncIOMotorDatabase = Depends(get_db)):
    return await compute_analytics(db)
