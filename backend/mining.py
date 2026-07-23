"""MiningService — полноценная система майнинг-ферм.

Переиспользует существующую инфраструктуру:
- MarketDataService/crypto_assets — реальные курсы криптовалют;
- econ (EconomyEngine) — стоимость энергии и общий множитель;
- shop (ShopService) — оборудование из user_hardware;
- ledger — все денежные движения (доход/электричество/зарплата/ремонт);
- ws — realtime-обновление показателей фермы;
- scheduler — фоновый тик добычи (без отдельных циклов).

Доход зависит от: числа и характеристик GPU, температуры, износа, стоимости
электроэнергии, курса крипты, эффективности охлаждения, разгона и БП.
"""
from __future__ import annotations

from typing import Optional

import math
import random
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator

from auth import get_current_user, require_admin
from database import get_db
from ledger import INCOME, EXPENSE, CAT_MINING, adjust_balance, record_transaction
from econ import get_econ
from shop import CATEGORY_ROLE
from notifications import push_notification

router = APIRouter(prefix="/api/mining", tags=["mining"])

# Обязательные компоненты для запуска добычи (psu проверяется отдельно — список).
REQUIRED_ROLES = ["motherboard", "cpu", "ram", "ssd", "cooling"]  # + хотя бы 1 gpu и 1 psu

# Ёмкость по вентиляторам, когда корпус/стойка не установлены (открытый стенд).
FAN_BASE_CAP = 6

ELEC_SCALE = 0.15           # масштаб счёта за электричество
BASE_POWER_W = 120          # накладное энергопотребление (без CPU/MB)
TEMP_AMBIENT = 25.0
TEMP_FACTOR = 30.0
OVERHEAT_TEMP = 85.0
MINING_MIN_ELAPSED_H = 300 / 3600.0   # тик добычи не чаще, чем раз в 5 минут
MAX_ACCRUAL_H = 6.0                    # cap накопления оффлайн
FEE = 0.01

# ── Экономика "доля от синтетической сложности сети" (см. design-спеку) ──
DIFF_EXP = 1.5              # сложность монеты растёт быстрее цены — самобалансировка выбора
DIFF_SCALE = 600.0          # откалибровано по каталогу: стартовая ферма (~500 хешрейта) конкурентна на монетах < $1
EMISSION = 14.0             # монето-USD-эквивалент/час при share=1.0; откалибровано под сегодняшний базовый доход
LIVE_WEIGHT = 0.05          # вклад живых игроков в сложность — второстепенный сигнал (~5 игроков), не механизм

# ── Эффективность компонентов (все клэмпятся в [EFF_FLOOR, 1.0]) ──
GPUS_PER_CORE = 1.0         # CPU: сколько GPU полноценно «кормит» одно ядро
RAM_PER_GPU = 4.0           # RAM: базовая потребность (ГБ) на один GPU
RAM_PRICE_REF = 340.0       # RAM: цена самой дорогой монеты каталога — якорь роста требований (memory-hard proxy)
SSD_PER_GPU = 50.0          # SSD: базовая потребность (ГБ) на один GPU (нода + DAG-кэш)
NET_PER_GPU = 100.0         # Network: базовая потребность (Мбит/с) на один GPU (пул/стейл-шары)
EFF_FLOOR = 0.15            # компоненты не гасят добычу до нуля — минимум 15% пропускной способности

# ── ИБП (см. tick_all: шанс просадки питания за тик) ──
BROWNOUT_CHANCE = 0.05      # шанс просадки питания за тик
UPS_WEAR_PENALTY = 5.0      # доп. износ (%) при незащённой просадке

MANAGER_BASE_COST = 25000.0
MANAGER_UPGRADE_COST = 15000.0
MANAGER_MAX_LEVEL = 5
MANAGER_SALARY_PER_H = 40.0            # × уровень
# ИИ-управляющий поддерживает ферму в рабочем состоянии, не дожидаясь
# критического износа. Порог ремонта растёт с уровнем: чем опытнее управляющий,
# тем в лучшем состоянии он держит оборудование (level 1 → ~56%, level 5 → 80%).
MANAGER_REPAIR_BASE = 50.0
MANAGER_REPAIR_PER_LEVEL = 6.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _psus(comp: dict) -> list:
    """Список БП фермы (совместимо со старым одиночным полем ``psu``)."""
    if comp.get("psus"):
        return comp["psus"]
    legacy = comp.get("psu")
    return [legacy] if legacy else []


def _psu_max(comp: dict) -> int:
    """Сколько БП можно установить: зависит от размещения (корпус/стойка).
    Открытый стенд — минимум 2; корпус/стойка дают ~1 БП на 3 посадочных места."""
    enclosure = _enclosure_slots(comp)
    if enclosure is not None:
        return max(2, enclosure // 3 + 1)
    return 2


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if isinstance(dt, datetime) and dt.tzinfo is None else dt


# ── Расчёт показателей фермы ─────────────────────────────────────────────────


def _clamp_eff(ratio: float) -> float:
    return max(EFF_FLOOR, min(1.0, ratio))


def _gpu_efficiency(cores: float, gpu_count: int) -> float:
    """CPU координирует GPU (PCIe/драйверы) — нехватка ядер душит хешрейт."""
    if gpu_count <= 0:
        return 1.0
    return _clamp_eff(cores * GPUS_PER_CORE / gpu_count)


def _ram_efficiency(ram_gb: float, gpu_count: int, price: float) -> float:
    """DAG должен помещаться в память; чем дороже монета — тем «тяжелее»
    алгоритм (proxy на memory-hardness). Единственная coin-зависимая
    эффективность — поэтому встроена в _coin_revenue_per_h (см. ниже),
    а не только в _compute, иначе выбор монеты и её реальная выплата разойдутся."""
    if gpu_count <= 0:
        return 1.0
    price_factor = min(1.0, max(0.0, price) / RAM_PRICE_REF)
    needed = gpu_count * RAM_PER_GPU * (1 + price_factor)
    return _clamp_eff(ram_gb / needed) if needed > 0 else 1.0


def _ssd_efficiency(ssd_gb: float, gpu_count: int) -> float:
    """Хранилище ноды/DAG-кэша — мало места означает постоянную пересинхронизацию."""
    if gpu_count <= 0:
        return 1.0
    return _clamp_eff(ssd_gb / (SSD_PER_GPU * gpu_count))


def _net_efficiency(net_speed: float, gpu_count: int) -> float:
    """Пропускная способность до пула — мало значит устаревшие/отклонённые шары."""
    if gpu_count <= 0:
        return 1.0
    return _clamp_eff(net_speed / (NET_PER_GPU * gpu_count))


def _farm_hashrate(farm: dict) -> float:
    """Эффективный хешрейт с учётом разгона и износа (вынесено из _compute
    для переиспользования при выборе монеты — см. _farm_hw_profile)."""
    comp = farm.get("components", {})
    gpus = comp.get("gpus", [])
    overclock = farm.get("overclock", 1.0)
    condition = farm.get("condition", 100.0)
    cond_factor = 0.5 + 0.5 * (condition / 100.0)
    base_hash = sum(g.get("specs", {}).get("hashrate", 0) for g in gpus)
    return round(base_hash * overclock * cond_factor, 1)


def _farm_hw_profile(farm: dict) -> dict:
    """Сводка параметров фермы для выбора монеты и расчёта эффективности."""
    comp = farm.get("components", {})
    return {
        "hashrate": _farm_hashrate(farm),
        "gpu_count": len(comp.get("gpus", [])),
        "cores": comp.get("cpu", {}).get("specs", {}).get("cores", 0),
        "ram_gb": comp.get("ram", {}).get("specs", {}).get("gb", 0),
        "ssd_gb": comp.get("ssd", {}).get("specs", {}).get("gb", 0),
        "net_speed": comp.get("network", {}).get("specs", {}).get("speed", 0),
        "ups_backup": comp.get("ups", {}).get("specs", {}).get("backup", 0),
    }


def _coin_difficulty(price: float, live_hashrate_on_coin: float = 0.0) -> float:
    """Синтетическая сложность = функция ЦЕНЫ монеты (не реального пула игроков —
    их слишком мало, см. design-спеку), плюс небольшой вклад живых майнеров."""
    base = (max(0.0, price) ** DIFF_EXP) * DIFF_SCALE
    return base + live_hashrate_on_coin * LIVE_WEIGHT


def _farm_share(hashrate: float, difficulty: float) -> float:
    """Доля фермы в «сети» — насыщающаяся кривая, никогда не превышает 1."""
    if hashrate <= 0:
        return 0.0
    return hashrate / (difficulty + hashrate)


def _coin_revenue_per_h(coin: Optional[dict], profile: dict, live_hashrate_on_coin: float = 0.0) -> float:
    """Выручка/час монеты для данного профиля фермы. ram_eff встроен сюда
    (не только в _compute), чтобы choose_best_coin ранжировал монеты по
    ТОЙ ЖЕ формуле, что и реальная выплата — иначе ИИ мог бы выбрать монету,
    которая ранжируется выше, но платит хуже после ram_eff."""
    if not coin or coin.get("price", 0) <= 0:
        return 0.0
    hashrate = profile.get("hashrate", 0.0)
    if hashrate <= 0:
        return 0.0
    price = float(coin["price"])
    difficulty = _coin_difficulty(price, live_hashrate_on_coin)
    share = _farm_share(hashrate, difficulty)
    ram_eff = _ram_efficiency(profile.get("ram_gb", 0), profile.get("gpu_count", 0), price)
    return share * EMISSION * price * ram_eff


async def _coin_market(db) -> dict:
    """Реальный рынок монет (обновляется MarketDataService из CoinGecko)."""
    try:
        from crypto import ensure_coins_seeded
        await ensure_coins_seeded(db)   # гарантируем наличие монет (fallback)
    except Exception:
        pass
    out = {}
    async for c in db.crypto_assets.find({}, {"symbol": 1, "price": 1, "change24h": 1, "name": 1, "color": 1}):
        out[c["symbol"]] = {"symbol": c["symbol"], "name": c.get("name"), "price": float(c.get("price", 0)),
                            "change24h": c.get("change24h", 0.0), "color": c.get("color")}
    return out


async def _city_bonus(db, user_id: str) -> dict:
    """Бонусы зданий «Крыши города», влияющие на майнинг (доход/электричество)."""
    try:
        from cityroof import player_city_effect
        return {
            "yield": await player_city_effect(db, user_id, "mining_yield"),
            "energy": await player_city_effect(db, user_id, "mining_energy"),
        }
    except Exception:
        return {}


def choose_best_coin(market: dict, profile: Optional[dict] = None,
                      live_hashrate_by_coin: Optional[dict] = None) -> Optional[str]:
    """Выбор монеты, дающей максимум ожидаемой выручки ИМЕННО этой ферме
    (не глобальный рейтинг — см. design-спеку). Без профиля (нет собранной
    фермы, ничего не с чем ранжировать) — откат на сортировку по цене."""
    if not profile or profile.get("hashrate", 0) <= 0:
        best, best_price = None, -1.0
        for sym, c in market.items():
            price = float(c.get("price", 0))
            if price > best_price:
                best, best_price = sym, price
        return best
    live = live_hashrate_by_coin or {}
    best, best_rev = None, -1.0
    for sym, c in market.items():
        rev = _coin_revenue_per_h(c, profile, live.get(sym, 0.0))
        if rev > best_rev:
            best, best_rev = sym, rev
    return best


def _compute(farm: dict, market: dict, energy_cost: float, economy_mult: float = 1.0,
             city: Optional[dict] = None, live_hashrate_on_coin: float = 0.0) -> dict:
    # city — бонусы зданий «Крыши города»: yield (+% к добыче), energy (−% к счёту за свет).
    city = city or {}
    yield_bonus = float(city.get("yield", 0.0))
    energy_discount = min(0.5, float(city.get("energy", 0.0)))
    comp = farm.get("components", {})
    gpus = comp.get("gpus", [])
    fans = comp.get("fans", [])
    overclock = farm.get("overclock", 1.0)
    condition = farm.get("condition", 100.0)

    hashrate = _farm_hashrate(farm)
    gpu_power = sum(g.get("specs", {}).get("power", 0) for g in gpus) * overclock
    cpu_power = comp.get("cpu", {}).get("specs", {}).get("power", 0)
    mb_power = comp.get("motherboard", {}).get("specs", {}).get("power", 0)
    total_power = round(gpu_power + cpu_power + mb_power + BASE_POWER_W, 1)

    cooling_cap = comp.get("cooling", {}).get("specs", {}).get("cooling", 0) + sum(f.get("specs", {}).get("cooling", 0) for f in fans)
    manager = farm.get("manager") or {"type": "player", "level": 0}
    ai_level = manager.get("level", 0) if manager.get("type") == "ai" else 0
    cool_bonus = min(0.5, ai_level * 0.06)
    temperature = round(TEMP_AMBIENT + (total_power / max(1, cooling_cap)) * TEMP_FACTOR * (1 - cool_bonus), 1)

    profile = _farm_hw_profile(farm)
    gpu_count = profile["gpu_count"]
    gpu_eff = _gpu_efficiency(profile["cores"], gpu_count)
    ssd_eff = _ssd_efficiency(profile["ssd_gb"], gpu_count)
    net_eff = _net_efficiency(profile["net_speed"], gpu_count)

    coin_sym = farm.get("coin")
    coin = market.get(coin_sym) if coin_sym else None
    ram_eff = _ram_efficiency(profile["ram_gb"], gpu_count, float(coin["price"])) if coin else 1.0
    base_revenue = _coin_revenue_per_h(coin, profile, live_hashrate_on_coin)
    revenue_per_h = round(base_revenue * gpu_eff * ssd_eff * net_eff * economy_mult * (1 + yield_bonus), 2)

    electricity_per_h = round(total_power * energy_cost * ELEC_SCALE * (1 - energy_discount), 2)
    salary_per_h = round(MANAGER_SALARY_PER_H * ai_level, 2) if manager.get("type") == "ai" else 0.0

    overclock_excess = max(0.0, overclock - 1.0)
    temp_wear = max(0.0, (temperature - 60) / 100.0)
    wear_per_h = round(0.3 + overclock_excess * 2 + temp_wear * 3, 4)

    profit_per_h = round(revenue_per_h - electricity_per_h - salary_per_h, 2)
    return {
        "hashrate": hashrate, "power": total_power, "temperature": temperature,
        "coolingCapacity": cooling_cap, "condition": round(condition, 1),
        "revenuePerHour": revenue_per_h, "electricityPerHour": electricity_per_h,
        "salaryPerHour": salary_per_h, "profitPerHour": profit_per_h,
        "wearPerHour": wear_per_h, "gpuCount": gpu_count,
        "overheating": temperature >= OVERHEAT_TEMP,
        "upsProtected": profile["ups_backup"] >= total_power,
        "efficiency": {"gpu": round(gpu_eff, 3), "ram": round(ram_eff, 3),
                       "ssd": round(ssd_eff, 3), "network": round(net_eff, 3)},
    }


def _mined_qty(revenue_usd: float, coin_price: float) -> float:
    """USD-выручка → количество добытых монет по текущему курсу (0 при price<=0)."""
    return round(revenue_usd / coin_price, 8) if (revenue_usd > 0.01 and coin_price > 0) else 0.0


def _repair_cost(farm: dict) -> float:
    gpus = len(farm.get("components", {}).get("gpus", []))
    missing = max(0.0, 100.0 - farm.get("condition", 100.0))
    return round(missing * (100 + 30 * gpus), 2)


def _ai_should_repair(ai: bool, ai_level: int, condition: float, profit_per_h: float) -> bool:
    """Решение ИИ-управляющего о ремонте: чинит, когда износ ниже порога уровня
    И когда ферма в принципе прибыльна (положительный доход в час). Достаточность
    средств проверяется отдельно при списании (adjust_balance) — здесь только
    целесообразность, чтобы управляющий не чинил заведомо убыточную ферму."""
    if not ai:
        return False
    threshold = min(80.0, MANAGER_REPAIR_BASE + ai_level * MANAGER_REPAIR_PER_LEVEL)
    if condition >= threshold:
        return False
    return profit_per_h > 0


def _serialize(farm: dict, stats: dict, capacity: Optional[dict] = None) -> dict:
    comp = farm.get("components", {})
    return {
        "id": str(farm["_id"]),
        "name": farm.get("name"),
        "status": farm.get("status", "idle"),
        "coin": farm.get("coin"),
        "overclock": farm.get("overclock", 1.0),
        "condition": round(farm.get("condition", 100.0), 1),
        "manager": farm.get("manager") or {"type": "player", "level": 0},
        "electricityOwed": round(farm.get("electricity_owed", 0.0), 2),
        "totalEarned": round(farm.get("total_earned", 0.0), 2),
        "totalSpent": round(farm.get("total_spent", 0.0), 2),
        "totalMinedUsd": round(farm.get("total_mined_usd", 0.0), 2),
        "totalMinedCoins": round(farm.get("total_mined_coins", 0.0), 8),
        "components": {
            "motherboard": comp.get("motherboard"),
            "cpu": comp.get("cpu"),
            "ram": comp.get("ram"), "ssd": comp.get("ssd"),
            "cooling": comp.get("cooling"), "case": comp.get("case"),
            "rack": comp.get("rack"), "ups": comp.get("ups"),
            "network": comp.get("network"),
            "gpus": comp.get("gpus", []), "fans": comp.get("fans", []),
            "psus": _psus(comp),
        },
        "repairCost": _repair_cost(farm),
        "capacity": capacity if capacity is not None else _capacity(farm),
        "stats": stats,
    }


def _missing_required(farm: dict) -> list[str]:
    comp = farm.get("components", {})
    missing = [r for r in REQUIRED_ROLES if not comp.get(r)]
    if not _psus(comp):
        missing.append("psu")
    if not comp.get("gpus"):
        missing.append("gpu")
    return missing


def _enclosure_slots(comp: dict) -> Optional[int]:
    """Число посадочных мест корпуса/стойки (None = размещение не выбрано —
    открытый стенд без жёсткого ограничения корпусом)."""
    for role in ("case", "rack"):
        node = comp.get(role)
        if node:
            slots = node.get("specs", {}).get("slots")
            if slots:
                return int(slots)
    return None


def _capacity(farm: dict, rack_used_elsewhere: int = 0) -> dict:
    """Максимум и остаток слотов для multi-компонентов (GPU, вентиляторы).

    Корпус/стойка задают общий лимит посадочных мест; для GPU он ещё и
    ограничен числом слотов материнской платы. Вентиляторы без корпуса
    ограничены открытым стендом (FAN_BASE_CAP).

    Стойка — ОБЩИЙ пул слотов на несколько ферм: доступное этой ферме место
    уменьшается на GPU, уже установленные на других фермах этой же стойки
    (rack_used_elsewhere). Корпус остаётся эксклюзивным (одна ферма)."""
    comp = farm.get("components", {})
    enclosure = _enclosure_slots(comp)
    # Если посадочные места даёт стойка (а не корпус) — вычитаем занятое на
    # других фермах: одна физическая стойка на N GPU делится между фермами.
    if enclosure is not None and comp.get("rack") and not comp.get("case"):
        enclosure = max(0, enclosure - rack_used_elsewhere)
    mb_slots = (comp.get("motherboard") or {}).get("specs", {}).get("gpuSlots", 0)

    gpu_max = mb_slots if mb_slots else 0
    if enclosure is not None:
        gpu_max = min(gpu_max, enclosure) if gpu_max else enclosure
    fan_max = enclosure if enclosure is not None else FAN_BASE_CAP

    gpu_used = len(comp.get("gpus", []))
    fan_used = len(comp.get("fans", []))
    psu_max = _psu_max(comp)
    psu_used = len(_psus(comp))
    return {
        "gpu": max(0, gpu_max - gpu_used),
        "fan": max(0, fan_max - fan_used),
        "psu": max(0, psu_max - psu_used),
        "gpuMax": gpu_max, "fanMax": fan_max, "psuMax": psu_max,
    }


def _shared_rack_id(farm: dict) -> Optional[str]:
    """hwId стойки фермы (стойка — общий пул слотов на несколько ферм)."""
    rack = (farm.get("components") or {}).get("rack")
    return rack.get("hwId") if rack else None


async def _rack_gpus_elsewhere(db, user_id: str, rack_hw_id: str, exclude_farm_id) -> int:
    """Сколько GPU этой стойки заняты на ДРУГИХ фермах игрока (общий пул слотов)."""
    if not rack_hw_id:
        return 0
    total = 0
    async for f in db.mining_farms.find(
        {"userId": user_id, "components.rack.hwId": rack_hw_id, "_id": {"$ne": exclude_farm_id}}
    ):
        total += len((f.get("components") or {}).get("gpus", []))
    return total


async def _capacity_for(db, farm: dict) -> dict:
    """_capacity с учётом GPU той же стойки на других фермах (общий пул)."""
    rack_id = _shared_rack_id(farm)
    used = await _rack_gpus_elsewhere(db, farm["userId"], rack_id, farm["_id"]) if rack_id else 0
    return _capacity(farm, used)


# ── Помощники доступа ────────────────────────────────────────────────────────


async def _serialize_with_stats(db, farm: dict, user_id: str) -> dict:
    """Сериализует ферму с ПОЛНЫМ пересчётом характеристик (для мгновенного отклика UI)."""
    cap = await _capacity_for(db, farm)
    missing = _missing_required(farm)
    if missing:
        # Ферма не собрана — не считаем показатели.
        item = _serialize(farm, {}, cap)
        item["missing"] = missing
        return item
    market = await _coin_market(db)
    econ = await get_econ(db)
    city = await _city_bonus(db, user_id)
    stats = _compute(farm, market, econ.get("energy_cost", 0.12), econ.get("economy_mult", 1.0), city)
    item = _serialize(farm, stats, cap)
    item["missing"] = missing
    return item


async def _load_farm(db, user_id, farm_id) -> dict:
    if not ObjectId.is_valid(farm_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID фермы")
    farm = await db.mining_farms.find_one({"_id": ObjectId(farm_id), "userId": user_id})
    if not farm:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ферма не найдена")
    return farm


# ── Schemas ──────────────────────────────────────────────────────────────────


class CreateFarm(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_ok(cls, v):
        v = (v or "").strip()
        if len(v) < 2:
            raise ValueError("Название слишком короткое")
        return v[:40]


class InstallBody(BaseModel):
    category: str
    hwId: Optional[str] = None   # конкретная деталь из инвентаря (игрок выбирает сам)


class InstallBatchBody(BaseModel):
    items: list[InstallBody]

    @field_validator("items")
    @classmethod
    def not_empty(cls, v):
        if not v:
            raise ValueError("Пустой список компонентов")
        return v[:100]   # разумный потолок на один batch


class CoinBody(BaseModel):
    symbol: str


class OverclockBody(BaseModel):
    value: float

    @field_validator("value")
    @classmethod
    def ok(cls, v):
        return max(0.8, min(1.5, round(float(v), 2)))


class ManagerBody(BaseModel):
    action: str  # hire | upgrade | fire


class AdminFarmUpdate(BaseModel):
    """Правки фермы администратором — без ограничений, действующих на игрока."""
    condition: Optional[float] = None
    overclock: Optional[float] = None
    electricity_owed: Optional[float] = None
    status: Optional[str] = None


class AdminTransferBody(BaseModel):
    toUsername: str


# ── Endpoints ────────────────────────────────────────────────────────────────


async def _best_farm_profile(db, user_id: str) -> Optional[dict]:
    """Профиль лучшей ПОЛНОСТЬЮ СОБРАННОЙ фермы игрока (не обязательно
    запущенной — чтобы можно было посмотреть рейтинг монет ДО старта добычи)."""
    best = None
    async for farm in db.mining_farms.find({"userId": user_id}):
        if _missing_required(farm):
            continue
        profile = _farm_hw_profile(farm)
        if best is None or profile["hashrate"] > best["hashrate"]:
            best = profile
    return best


@router.get("/market")
async def mining_market(current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Монеты для выбора добычи + рекомендация ИИ, ранжированные под хешрейт
    лучшей собранной фермы игрока (без собранной фермы — по цене, как раньше)."""
    market = await _coin_market(db)
    profile = await _best_farm_profile(db, str(current_user["_id"]))
    best = choose_best_coin(market, profile)
    if profile:
        coins = sorted(market.values(), key=lambda c: _coin_revenue_per_h(c, profile), reverse=True)
    else:
        coins = sorted(market.values(), key=lambda c: c.get("price", 0), reverse=True)
    return {"coins": coins, "best": best}


@router.get("/parts")
async def available_parts(current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Свободное оборудование игрока (не установленное ни в одну ферму),
    сгруппированное по категориям — для самостоятельного выбора комплектующих."""
    user_id = str(current_user["_id"])
    by_cat: dict[str, list] = {}
    async for hw in db.user_hardware.find({"userId": user_id, "farmId": None}):
        by_cat.setdefault(hw.get("category"), []).append({
            "hwId": str(hw["_id"]),
            "name": hw.get("name"),
            "specs": hw.get("specs", {}),
            "category": hw.get("category"),
        })
    # Стабильный порядок внутри категории (по названию).
    for items in by_cat.values():
        items.sort(key=lambda x: x.get("name") or "")
    return by_cat


@router.get("/farms")
async def get_farms(current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    market = await _coin_market(db)
    econ = await get_econ(db)
    ec, em = econ.get("energy_cost", 0.12), econ.get("economy_mult", 1.0)
    city = await _city_bonus(db, user_id)
    out = []
    async for farm in db.mining_farms.find({"userId": user_id}):
        missing = _missing_required(farm)
        # Пока ферма не собрана — показатели не рассчитываются (пустые).
        stats = {} if missing else _compute(farm, market, ec, em, city)
        item = _serialize(farm, stats, await _capacity_for(db, farm))
        item["missing"] = missing
        out.append(item)
    return out


@router.post("/farms", status_code=status.HTTP_201_CREATED)
async def create_farm(payload: CreateFarm, current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    doc = {
        "userId": user_id, "name": payload.name, "status": "idle", "coin": None,
        "components": {"gpus": [], "fans": []}, "overclock": 1.0, "condition": 100.0,
        "manager": {"type": "player", "level": 0}, "electricity_owed": 0.0,
        "total_earned": 0.0, "total_spent": 0.0, "last_tick": _now(), "created_at": _now(),
    }
    result = await db.mining_farms.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize(doc, {})


@router.delete("/farms/{farm_id}")
async def delete_farm(farm_id: str, current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Разобрать ферму — освобождает всё установленное оборудование."""
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    await db.user_hardware.update_many({"farmId": str(farm["_id"])}, {"$set": {"farmId": None}})
    await db.mining_farms.delete_one({"_id": farm["_id"]})
    return {"ok": True}


async def _install_one(db, user_id: str, farm: dict, category: str, hw_id: Optional[str]) -> None:
    """Установить один компонент в ферму (общая логика single/batch).

    Мутирует БД; farm — свежезагруженная ферма (при пакетной установке
    перезагружается между вызовами, т.к. ёмкость зависит от уже установленного).
    Бросает HTTPException при любой ошибке валидации."""
    meta = CATEGORY_ROLE.get(category)
    if not meta:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестная категория")
    role = meta["role"]
    multi = meta.get("multi", False)

    # Игрок может выбрать КОНКРЕТНУЮ деталь (hwId) — иначе берётся любая свободная.
    if hw_id:
        if not ObjectId.is_valid(hw_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID детали")
        hw = await db.user_hardware.find_one({
            "_id": ObjectId(hw_id), "userId": user_id,
            "category": category, "farmId": None,
        })
        if not hw:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Деталь недоступна (не найдена или уже установлена)")
    else:
        hw = await db.user_hardware.find_one({"userId": user_id, "category": category, "farmId": None})
        if not hw:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет свободного оборудования — купите в магазине")

    comp = farm.get("components", {})
    if multi:
        role_key = {"gpu": "gpus", "fan": "fans", "psu": "psus"}[role]
        cap = await _capacity_for(db, farm)
        if role == "gpu":
            mb = comp.get("motherboard")
            if not mb:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Сначала установите материнскую плату")
            if cap["gpu"] <= 0:
                # Различаем причину: не хватает слотов платы или мест в корпусе/стойке.
                if _enclosure_slots(comp) is not None and cap["gpuMax"] >= mb.get("specs", {}).get("gpuSlots", 0):
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет свободных слотов на материнской плате")
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет свободных мест в корпусе/стойке")
        elif role == "psu":
            if cap["psu"] <= 0:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет мест под БП (установите корпус/стойку большего размера)")
        else:  # fan
            if cap["fan"] <= 0:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет свободных мест для вентиляторов (установите корпус/стойку большего размера)")
        entry = {"hwId": str(hw["_id"]), "name": hw["name"], "specs": hw.get("specs", {}), "category": category}
        # Миграция старого одиночного поля psu → список psus при первой установке.
        if role == "psu" and comp.get("psu") and not comp.get("psus"):
            await db.mining_farms.update_one(
                {"_id": farm["_id"]},
                {"$set": {"components.psus": [comp["psu"]]}, "$unset": {"components.psu": ""}},
            )
        await db.mining_farms.update_one({"_id": farm["_id"]}, {"$push": {f"components.{role_key}": entry}})
    else:
        # Корпус и стойка — взаимоисключающие варианты размещения: можно
        # использовать только один. Установка одного снимает другой.
        PLACEMENT_ALT = {"case": "rack", "rack": "case"}
        alt = PLACEMENT_ALT.get(role)
        if alt and comp.get(alt) and comp[alt].get("hwId"):
            # Корпус эксклюзивен — освобождаем; стойку освобождать не нужно
            # (её farmId всегда None, это общий пул на несколько ферм).
            if alt == "case":
                await db.user_hardware.update_one({"_id": ObjectId(comp[alt]["hwId"])}, {"$set": {"farmId": None}})
            await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {f"components.{alt}": None}})
        # Освобождаем ранее установленный компонент этой роли (кроме стойки —
        # общий пул, farmId не занимаем).
        old = comp.get(role)
        if old and old.get("hwId") and role != "rack":
            await db.user_hardware.update_one({"_id": ObjectId(old["hwId"])}, {"$set": {"farmId": None}})
        entry = {"hwId": str(hw["_id"]), "name": hw["name"], "specs": hw.get("specs", {}), "category": category}
        await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {f"components.{role}": entry}})

    # Стойка — общий пул слотов на несколько ферм: НЕ привязываем её к ферме
    # (farmId остаётся None), чтобы она оставалась доступна другим фермам.
    if role != "rack":
        await db.user_hardware.update_one({"_id": hw["_id"]}, {"$set": {"farmId": str(farm["_id"])}})


@router.post("/farms/{farm_id}/install")
async def install_component(farm_id: str, payload: InstallBody, current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Установить в ферму свободное оборудование выбранной категории."""
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    await _install_one(db, user_id, farm, payload.category, payload.hwId)
    updated = await db.mining_farms.find_one({"_id": farm["_id"]})
    return await _serialize_with_stats(db, updated, user_id)


@router.post("/farms/{farm_id}/install-batch")
async def install_components_batch(farm_id: str, payload: InstallBatchBody, current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Установить несколько компонентов одним запросом.

    Каждый ставится по очереди (ёмкость зависит от уже установленного), ферма
    перезагружается между установками. Если какая-то деталь не проходит
    валидацию — прерываемся на ней, ранее установленные остаются."""
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    installed = 0
    error = None
    for item in payload.items:
        try:
            await _install_one(db, user_id, farm, item.category, item.hwId)
            installed += 1
            farm = await _load_farm(db, user_id, farm_id)   # ёмкость зависит от уже установленного
        except HTTPException as e:
            error = e.detail
            break
    updated = await db.mining_farms.find_one({"_id": farm["_id"]})
    result = await _serialize_with_stats(db, updated, user_id)
    result["installed"] = installed
    if error:
        result["error"] = error
    return result


@router.post("/farms/{farm_id}/uninstall")
async def uninstall_component(farm_id: str, body: dict, current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Снять компонент по hwId — оборудование возвращается в инвентарь."""
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    hw_id = body.get("hwId")
    if not hw_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не указан hwId")
    comp = farm.get("components", {})
    changed = False
    for role in ["motherboard", "cpu", "psu", "ram", "ssd", "cooling", "case", "rack", "ups", "network"]:
        if comp.get(role) and comp[role].get("hwId") == hw_id:
            await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {f"components.{role}": None}})
            changed = True
    for role_key in ["gpus", "fans", "psus"]:
        if any(x.get("hwId") == hw_id for x in comp.get(role_key, [])):
            await db.mining_farms.update_one({"_id": farm["_id"]}, {"$pull": {f"components.{role_key}": {"hwId": hw_id}}})
            changed = True
    if changed and ObjectId.is_valid(hw_id):
        await db.user_hardware.update_one({"_id": ObjectId(hw_id)}, {"$set": {"farmId": None}})
    updated = await db.mining_farms.find_one({"_id": farm["_id"]})
    return await _serialize_with_stats(db, updated, user_id)


@router.post("/farms/{farm_id}/start")
async def start_mining(farm_id: str, current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    missing = _missing_required(farm)
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Не хватает компонентов: {', '.join(missing)}")

    # Проверка мощности БП.
    market = await _coin_market(db)
    econ = await get_econ(db)
    city = await _city_bonus(db, user_id)
    stats = _compute(farm, market, econ.get("energy_cost", 0.12), econ.get("economy_mult", 1.0), city)
    psu_w = sum(p.get("specs", {}).get("power", 0) for p in _psus(farm.get("components", {})))
    if psu_w < stats["power"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Недостаточная мощность БП ({psu_w}W < {stats['power']}W)")

    coin = farm.get("coin")
    manager = farm.get("manager") or {}
    if not coin:
        if manager.get("type") == "ai":
            coin = choose_best_coin(market, _farm_hw_profile(farm))
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Выберите криптовалюту для добычи")

    await db.mining_farms.update_one(
        {"_id": farm["_id"]},
        {"$set": {"status": "mining", "coin": coin, "last_tick": _now()}},
    )
    updated = await db.mining_farms.find_one({"_id": farm["_id"]})
    return _serialize(updated, _compute(updated, market, econ.get("energy_cost", 0.12), econ.get("economy_mult", 1.0), city))


@router.post("/farms/{farm_id}/stop")
async def stop_mining(farm_id: str, current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"status": "idle"}})
    return {"ok": True}


@router.post("/farms/{farm_id}/coin")
async def set_coin(farm_id: str, payload: CoinBody, current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    coin = await db.crypto_assets.find_one({"symbol": payload.symbol.upper()})
    if not coin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Монета не найдена")
    await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"coin": coin["symbol"]}})
    return {"ok": True, "coin": coin["symbol"]}


@router.post("/farms/{farm_id}/overclock")
async def set_overclock(farm_id: str, payload: OverclockBody, current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"overclock": payload.value}})
    return {"ok": True, "overclock": payload.value}


@router.post("/farms/{farm_id}/repair")
async def repair_farm(farm_id: str, current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    cost = _repair_cost(farm)
    if cost <= 0:
        return {"ok": True, "cost": 0.0, "balance": current_user.get("balance", 0.0)}
    new_balance = await adjust_balance(db, user_id, -cost)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств на ремонт")
    await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"condition": 100.0}})
    await record_transaction(db, user_id, EXPENSE, cost, CAT_MINING, f"Ремонт фермы «{farm['name']}»", balance_after=new_balance)
    return {"ok": True, "cost": cost, "balance": new_balance}


@router.post("/farms/{farm_id}/manager")
async def manage_manager(farm_id: str, payload: ManagerBody, current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Нанять/повысить/уволить ИИ-управляющего."""
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    manager = farm.get("manager") or {"type": "player", "level": 0}

    if payload.action == "fire":
        await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"manager": {"type": "player", "level": 0}}})
        return {"ok": True, "manager": {"type": "player", "level": 0}}

    if payload.action == "hire":
        if manager.get("type") == "ai":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Управляющий уже нанят")
        # Нельзя нанять управляющего на несобранную ферму — управлять пока нечем.
        missing = _missing_required(farm)
        if missing:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Сначала соберите ферму (не хватает: {', '.join(missing)})",
            )
        cost = MANAGER_BASE_COST
        new_level = 1
    elif payload.action == "upgrade":
        if manager.get("type") != "ai":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Сначала наймите управляющего")
        if manager.get("level", 1) >= MANAGER_MAX_LEVEL:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Достигнут максимальный уровень")
        cost = MANAGER_UPGRADE_COST * manager.get("level", 1)
        new_level = manager.get("level", 1) + 1
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестное действие")

    new_balance = await adjust_balance(db, user_id, -cost)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
    new_manager = {"type": "ai", "level": new_level, "salary": round(MANAGER_SALARY_PER_H * new_level, 2)}
    await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"manager": new_manager}})
    await record_transaction(db, user_id, EXPENSE, cost, CAT_MINING, f"ИИ-управляющий (ур. {new_level})", balance_after=new_balance)
    return {"ok": True, "manager": new_manager, "balance": new_balance}


# ── Фоновый тик добычи (вызывается Scheduler'ом) ─────────────────────────────


async def tick_all(db: AsyncIOMotorDatabase):
    """Начисление добычи, электричества, зарплаты и износа по всем активным фермам."""
    market = await _coin_market(db)
    econ = await get_econ(db)
    ec, em = econ.get("energy_cost", 0.12), econ.get("economy_mult", 1.0)
    now = _now()

    # ИИ авто-перезапуск: ферму с управляющим, отключённую за неуплату, снова
    # запускаем, как только она собрана, прибыльна И у игрока есть кэш на тик
    # расходов. Проверка баланса обязательна: выручка идёт в монеты, а
    # электричество/зарплата списываются с кэша — без неё ферма «прибыльной»,
    # но безденежной, щёлкала бы off↔mining каждый тик со спамом уведомлений.
    async for farm in db.mining_farms.find({"status": "off", "manager.type": "ai"}):
        if _missing_required(farm):
            continue
        city = await _city_bonus(db, farm["userId"])
        stats = _compute(farm, market, ec, em, city)
        if stats.get("profitPerHour", 0) <= 0:
            continue
        # кэш на ~1 тик (60с планировщика) расходов; иначе не трогаем — пусть
        # ждёт пополнения, а не мигает статусом.
        tick_h = 60.0 / 3600.0
        tick_cost = (stats.get("electricityPerHour", 0.0) + stats.get("salaryPerHour", 0.0)) * tick_h
        owner = await db.users.find_one({"_id": ObjectId(farm["userId"])}, {"balance": 1}) if ObjectId.is_valid(farm["userId"]) else None
        if not owner or owner.get("balance", 0.0) < tick_cost:
            continue
        await db.mining_farms.update_one(
            {"_id": farm["_id"]},
            {"$set": {"status": "mining", "last_tick": now}},
        )
        await push_notification(db, farm["userId"], "mining", "Ферма перезапущена",
                                f"ИИ-управляющий возобновил добычу на «{farm.get('name')}».",
                                data={"farmId": str(farm["_id"])})

    # Живой вклад игроков в сложность (второстепенный сигнал, см. LIVE_WEIGHT):
    # суммарный хешрейт активных ферм по монетам, O(активных ферм) за тик.
    active_farms = await db.mining_farms.find({"status": "mining"}).to_list(length=None)
    live_hashrate_by_coin: dict = {}
    for farm in active_farms:
        sym = farm.get("coin")
        if sym:
            live_hashrate_by_coin[sym] = live_hashrate_by_coin.get(sym, 0.0) + _farm_hashrate(farm)

    for farm in active_farms:
        last = _aware(farm.get("last_tick"))
        elapsed_h = min(MAX_ACCRUAL_H, (now - last).total_seconds() / 3600.0) if isinstance(last, datetime) else 0.0
        if elapsed_h < MINING_MIN_ELAPSED_H:
            continue

        user_id = farm["userId"]
        manager = farm.get("manager") or {"type": "player", "level": 0}
        ai = manager.get("type") == "ai"
        ai_level = manager.get("level", 0) if ai else 0
        own_hashrate = _farm_hashrate(farm)

        # ИИ автоматически выбирает монету, максимизирующую ЕГО СОБСТВЕННУЮ выручку.
        if ai:
            profile = _farm_hw_profile(farm)
            live_excl_self = {sym: h - (own_hashrate if sym == farm.get("coin") else 0.0)
                               for sym, h in live_hashrate_by_coin.items()}
            best = choose_best_coin(market, profile, live_excl_self)
            if best and best != farm.get("coin"):
                farm["coin"] = best

        coin_sym_for_live = farm.get("coin")
        live_on_coin = max(0.0, live_hashrate_by_coin.get(coin_sym_for_live, 0.0) - own_hashrate) if coin_sym_for_live else 0.0

        city = await _city_bonus(db, user_id)
        stats = _compute(farm, market, ec, em, city, live_hashrate_on_coin=live_on_coin)

        # ИБП: шанс просадки питания за тик; без достаточного резерва — тик
        # без выручки и доп. износ (UPS — gate, не постоянный множитель).
        extra_wear = 0.0
        if random.random() < BROWNOUT_CHANCE and not stats.get("upsProtected", False):
            stats = dict(stats)
            stats["revenuePerHour"] = 0.0
            stats["profitPerHour"] = round(-stats["electricityPerHour"] - stats["salaryPerHour"], 2)
            extra_wear = UPS_WEAR_PENALTY

        revenue = round(stats["revenuePerHour"] * elapsed_h, 2)
        electricity = round(stats["electricityPerHour"] * elapsed_h, 2)
        salary = round(stats["salaryPerHour"] * elapsed_h, 2)
        wear = stats["wearPerHour"] * elapsed_h + extra_wear
        new_condition = max(0.0, farm.get("condition", 100.0) - wear)

        # ИИ авто-ремонт: держит ферму в рабочем состоянии, не дожидаясь
        # критического износа (порог растёт с уровнем управляющего). Ремонт
        # применяется только если добыча покрывает его стоимость — иначе
        # управляющий не загоняет игрока в минус ради обслуживания.
        repair_cost = 0.0
        worn_condition = new_condition   # износ без учёта возможного авто-ремонта
        if ai:
            farm["condition"] = new_condition   # _repair_cost считает по текущему износу
            candidate_cost = _repair_cost(farm)
            if _ai_should_repair(ai, ai_level, new_condition, stats["profitPerHour"]):
                repair_cost = candidate_cost
                new_condition = 100.0

        # Майнинг добывает МОНЕТУ, а не деньги: выручка (USD-эквивалент) конвертируется
        # в количество монет по текущему курсу и зачисляется в crypto_holdings.
        # Электричество/зарплата/ремонт — реальные РАСХОДЫ, списываются с баланса.
        coin_sym = farm.get("coin")
        coin_price = float((market.get(coin_sym) or {}).get("price", 0.0))
        coin_qty = _mined_qty(revenue, coin_price)
        costs = round(electricity + salary + repair_cost, 2)

        set_fields = {
            "condition": round(new_condition, 2),
            "last_tick": now,
            "coin": coin_sym,
            "total_earned": round(farm.get("total_earned", 0.0) + revenue, 2),
            "total_spent": round(farm.get("total_spent", 0.0) + costs, 2),
            "total_mined_usd": round(farm.get("total_mined_usd", 0.0) + (revenue if coin_qty > 0 else 0.0), 2),
            "total_mined_coins": round(farm.get("total_mined_coins", 0.0) + coin_qty, 8),
        }

        # 1) Списываем денежные расходы (если ферма их не тянет — отключаем).
        if costs > 0.01:
            nb = await adjust_balance(db, user_id, -costs)
            if nb is None:
                # Денег не хватило: откатываем авто-ремонт (не чиним бесплатно) и
                # отключаем ферму. Долг фиксируем без стоимости ремонта.
                owed = round(electricity + salary, 2)
                set_fields["condition"] = round(worn_condition, 2)
                set_fields["status"] = "off"
                set_fields["electricity_owed"] = round(farm.get("electricity_owed", 0.0) + owed, 2)
                set_fields["total_spent"] = round(farm.get("total_spent", 0.0), 2)
                await push_notification(db, user_id, "mining", "Ферма отключена",
                                        f"«{farm.get('name')}»: недостаточно денег на электричество.",
                                        data={"farmId": str(farm["_id"])})
                await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": set_fields})
                continue
            await record_transaction(db, user_id, EXPENSE, costs, CAT_MINING,
                                     f"Расходы фермы «{farm.get('name')}»", balance_after=nb)

        # 2) Зачисляем добытые монеты в холдинги (upsert по userId+symbol, как в crypto.py).
        if coin_qty > 0 and coin_sym:
            await db.crypto_holdings.update_one(
                {"userId": user_id, "symbol": coin_sym},
                {"$inc": {"quantity": coin_qty},
                 "$setOnInsert": {"userId": user_id, "symbol": coin_sym, "avg_price": round(coin_price, 6)}},
                upsert=True,
            )
            # В реестр пишем USD-эквивалент добытого (для аналитики), symbol = монета.
            await record_transaction(db, user_id, INCOME, revenue, CAT_MINING,
                                     f"Добыча {coin_qty:g} {coin_sym}", symbol=coin_sym,
                                     price=coin_price, meta={"quantity": coin_qty})

        await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": set_fields})

        # Realtime-обновление показателей владельцу.
        try:
            from ws import push_to_user
            await push_to_user(user_id, {"type": "mining", "farmId": str(farm["_id"]), "stats": stats,
                                         "condition": round(new_condition, 2), "status": set_fields.get("status", "mining")})
        except Exception:
            pass


# ── Admin ────────────────────────────────────────────────────────────────────


async def _load_any_farm(db: AsyncIOMotorDatabase, farm_id: str) -> dict:
    if not ObjectId.is_valid(farm_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID фермы")
    farm = await db.mining_farms.find_one({"_id": ObjectId(farm_id)})
    if not farm:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ферма не найдена")
    return farm


@router.patch("/admin/farms/{farm_id}")
async def admin_update_farm(
    farm_id: str,
    payload: AdminFarmUpdate,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    farm = await _load_any_farm(db, farm_id)
    update_fields = payload.model_dump(exclude_unset=True)
    if not update_fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет полей для обновления")
    await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": update_fields})
    updated = await db.mining_farms.find_one({"_id": farm["_id"]})
    result = await _serialize_with_stats(db, updated, farm["userId"])
    try:
        from ws import push_to_user
        await push_to_user(farm["userId"], {"type": "mining", "farmId": farm_id, "stats": result.get("stats", {}),
                                             "condition": result.get("condition"), "status": result.get("status")})
    except Exception:
        pass
    return result


@router.delete("/admin/farms/{farm_id}")
async def admin_delete_farm(
    farm_id: str,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    farm = await _load_any_farm(db, farm_id)
    await db.user_hardware.update_many({"farmId": str(farm["_id"])}, {"$set": {"farmId": None}})
    await db.mining_farms.delete_one({"_id": farm["_id"]})
    try:
        from ws import push_to_user
        await push_to_user(farm["userId"], {"type": "mining", "farmId": farm_id, "deleted": True})
    except Exception:
        pass
    return {"message": f"Ферма «{farm.get('name')}» удалена"}


@router.post("/admin/farms/{farm_id}/transfer")
async def admin_transfer_farm(
    farm_id: str,
    payload: AdminTransferBody,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    farm = await _load_any_farm(db, farm_id)
    target = await db.users.find_one({"username": payload.toUsername})
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Игрок не найден")
    new_owner_id = str(target["_id"])
    old_owner_id = farm["userId"]
    await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"userId": new_owner_id}})
    await db.user_hardware.update_many({"farmId": str(farm["_id"])}, {"$set": {"userId": new_owner_id}})
    updated = await db.mining_farms.find_one({"_id": farm["_id"]})
    result = await _serialize_with_stats(db, updated, new_owner_id)
    try:
        from ws import push_to_user
        await push_to_user(old_owner_id, {"type": "mining", "farmId": farm_id, "transferred": True})
        await push_to_user(new_owner_id, {"type": "mining", "farmId": farm_id, "transferred": True})
    except Exception:
        pass
    return result


if __name__ == "__main__":
    # Самопроверка решения ИИ о ремонте (см. _ai_should_repair / tick_all).
    # Без управляющего — не ремонтирует.
    assert _ai_should_repair(False, 0, 10.0, 100.0) is False
    # Уровень 1 → порог ~56%; износ 40% ниже порога, ферма прибыльна → чинит.
    assert _ai_should_repair(True, 1, 40.0, 85.0) is True
    # Ниже порога, но ферма убыточна (profit ≤ 0) — не чинит.
    assert _ai_should_repair(True, 1, 40.0, 0.0) is False
    assert _ai_should_repair(True, 1, 40.0, -5.0) is False
    # Состояние выше порога — чинить рано.
    assert _ai_should_repair(True, 5, 90.0, 1000.0) is False
    # Порог растёт с уровнем: level 5 → 80%, износ 70% уже требует ремонта.
    assert _ai_should_repair(True, 5, 70.0, 1000.0) is True

    # Майнинг добывает МОНЕТУ: qty = revenue_usd / price; расходы остаются в кэше.
    assert _mined_qty(100.0, 50.0) == 2.0           # 100$ по курсу 50 → 2 монеты
    assert _mined_qty(100.0, 0.0) == 0.0            # нет курса → ничего не добыто
    assert _mined_qty(0.0, 50.0) == 0.0             # нет выручки → 0 монет
    # Выручка идёт в монеты, а costs (эл-во+зарплата+ремонт) — отдельный кэш-расход.
    _rev, _price, _costs = 60.0, 30.0, 12.0
    assert _mined_qty(_rev, _price) == 2.0 and round(_costs, 2) == 12.0

    # Стойка — общий пул слотов на несколько ферм: место, занятое GPU на других
    # фермах той же стойки, уменьшает доступное этой ферме.
    _mb8 = {"specs": {"gpuSlots": 8}}
    _rack48 = {"specs": {"slots": 48}, "hwId": "r1"}
    _farm = {"components": {"motherboard": _mb8, "rack": _rack48, "gpus": [{}] * 3}}
    # Никто больше не занимает — упираемся в 8 слотов платы, стоит 3 → свободно 5.
    assert _capacity(_farm, 0)["gpu"] == 5
    # На других фермах занято 44 из 48 → стойка даёт лишь 4; стоит 3 → свободно 1.
    assert _capacity(_farm, 44)["gpu"] == 1
    # Стойка занята полностью на других фермах → 0 доступных мест.
    assert _capacity(_farm, 48)["gpu"] == 0

    # БП — multi-компонент: открытый стенд даёт 2 места, корпус/стойка больше;
    # старое одиночное поле psu совместимо со списком psus.
    assert _psu_max({}) == 2
    assert _psu_max({"case": {"specs": {"slots": 8}}}) == 3
    assert _psu_max({"rack": {"specs": {"slots": 48}}}) == 17
    assert _psus({"psu": {"hwId": "x"}}) == [{"hwId": "x"}]        # legacy single
    assert _psus({"psus": [{"hwId": "a"}], "psu": {"hwId": "x"}}) == [{"hwId": "a"}]
    _pf = {"components": {"psus": [{}], "case": {"specs": {"slots": 8}}}}
    assert _capacity(_pf)["psu"] == 2                              # 3 max − 1 used

    # ── Rebalance: выбор монеты зависит от фермы, а не только от цены ──
    _market = {
        "CHEAP": {"symbol": "CHEAP", "price": 0.85, "change24h": 0.0},
        "MID": {"symbol": "MID", "price": 12.4, "change24h": 0.0},
        "EXPENSIVE": {"symbol": "EXPENSIVE", "price": 340.0, "change24h": 0.0},
    }
    _weak = {"hashrate": 180.0, "gpu_count": 1, "cores": 4, "ram_gb": 8, "ssd_gb": 256, "net_speed": 1000, "ups_backup": 0}
    _strong = {"hashrate": 1_045_000.0, "gpu_count": 19, "cores": 32, "ram_gb": 128, "ssd_gb": 4096, "net_speed": 40000, "ups_backup": 0}
    _weak_best = choose_best_coin(_market, _weak)
    assert _weak_best != "EXPENSIVE", "слабая ферма не должна выбирать самую дорогую монету"
    assert _weak_best == "CHEAP", f"ожидали CHEAP, получили {_weak_best}"
    _strong_best = choose_best_coin(_market, _strong)
    assert _strong_best == "EXPENSIVE", f"сильная ферма должна тянуться к дорогим монетам, получили {_strong_best}"
    # Без профиля (нет собранной фермы) — откат на сортировку по цене.
    assert choose_best_coin(_market, None) == "EXPENSIVE"

    # ── _compute expone efficiency/upsProtected и использует новую формулу дохода ──
    _test_farm = {
        "components": {
            "motherboard": {"specs": {"gpuSlots": 8, "power": 60}},
            "cpu": {"specs": {"cores": 8, "power": 109}},
            "ram": {"specs": {"gb": 32, "power": 5}},
            "ssd": {"specs": {"gb": 512, "power": 6}},
            "cooling": {"specs": {"cooling": 1600, "power": 40}},
            "gpus": [{"specs": {"hashrate": 1887, "power": 214}}] * 8,
            "fans": [], "psus": [{"specs": {"power": 3000}}],
        },
        "overclock": 1.0, "condition": 100.0, "coin": "ORB",
        "manager": {"type": "player", "level": 0},
    }
    _test_market = {"ORB": {"symbol": "ORB", "price": 12.4, "change24h": 0.0}}
    _test_stats = _compute(_test_farm, _test_market, energy_cost=0.12, economy_mult=1.0)
    assert "efficiency" in _test_stats and set(_test_stats["efficiency"]) == {"gpu", "ram", "ssd", "network"}
    assert _test_stats["efficiency"]["gpu"] == 1.0        # 8 ядер / 8 GPU
    assert _test_stats["upsProtected"] is False            # нет установленного ИБП → backup=0
    assert _test_stats["revenuePerHour"] > 0
    assert _test_stats["gpuCount"] == 8

    # ── Эффективность компонентов: клэмп на границах [EFF_FLOOR, 1.0] ──
    assert _gpu_efficiency(8, 8) == 1.0                  # 8 ядер кормят 8 GPU — полная эффективность
    assert round(_gpu_efficiency(8, 19), 2) == 0.42       # тех же 8 ядер на 19 GPU — throttling
    assert _gpu_efficiency(1, 100) == EFF_FLOOR           # экстремальный недостаток ядер — пол, не ноль
    assert _ram_efficiency(32, 8, 0.85) > 0.99            # дешёвая монета — 32ГБ хватает почти полностью
    assert _ram_efficiency(32, 8, 340.0) == 0.5           # дорогая монета — тот же объём вдвое хуже
    assert _ram_efficiency(64, 8, 340.0) == 1.0           # апгрейд до 64ГБ полностью закрывает требование
    assert _ssd_efficiency(512, 8) == 1.0 and _ssd_efficiency(1, 8) == EFF_FLOOR
    assert _net_efficiency(10000, 19) == 1.0 and _net_efficiency(1, 100) == EFF_FLOOR

    # ── Синтетическая сложность растёт быстрее цены (DIFF_EXP > 1) ──
    assert _coin_difficulty(340.0) > _coin_difficulty(0.85) * 100   # дороже монета — непропорционально сложнее
    assert _farm_share(0.0, 100.0) == 0.0
    assert 0.0 < _farm_share(100.0, 100.0) < 1.0
    print("mining self-check OK")
