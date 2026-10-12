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

from pymongo.errors import DuplicateKeyError
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator

from admin_perms import get_current_user, require_admin, require_allowed
from database import get_db, find_config_by_key, upsert_config
from ledger import INCOME, EXPENSE, CAT_MINING, adjust_balance, record_transaction
from econ import get_econ
from shop import CATALOG_BY_NAME, CATEGORY_ROLE
from notifications import push_notification

router = APIRouter(prefix="/api/mining", tags=["mining"])

# Обязательные компоненты для запуска добычи (psu проверяется отдельно — список).
REQUIRED_ROLES = ["motherboard", "cpu", "ram", "ssd", "cooling"]  # + хотя бы 1 gpu и 1 psu

# Ёмкость по вентиляторам, когда корпус не установлен (открытый стенд).
FAN_BASE_CAP = 6

# Лимит подвалов и корпусов:
#   - майнинг разрешён ТОЛЬКО в подвалах домов (basement > 0);
#   - в одном подвале можно установить столько корпусов/стоек, сколько его ёмкость;
#   - корпус — до 5 GPU; серверная стойка (rack) — общий пул слотов на несколько
#     ферм (сумма слотов материнок ферм ≤ слотов стойки, см. _rack_pool_check).
MAX_CASES_PER_BASEMENT_SLOT = 1   # один корпус/стойка = один слот подвала
CASE_MAX_GPUS = 5                # жёсткий лимит слотов корпуса
RACK_MAX_GPUS = 60               # потолок GPU на одну ферму на стойке (= MAX_MB_SLOTS)

HASH_YIELD = 0.001          # доход за единицу хешрейта × профитность монеты
ELEC_SCALE = 0.15           # масштаб счёта за электричество
BASE_POWER_W = 120          # накладное энергопотребление (без CPU/MB)
TEMP_AMBIENT = 25.0
TEMP_FACTOR = 30.0
OVERHEAT_TEMP = 85.0
MINING_MIN_ELAPSED_H = 300 / 3600.0   # тик добычи не чаще, чем раз в 5 минут

# Охлаждающая жидкость (расходник, заправляется в ферму).
COOLANT_MAX = 4                    # макс. шт. в ферме
COOLANT_DURATION_H = 12.0         # 1 шт. работает 12 часов
COOLANT_TEMP_REDUCTION = 0.25      # -25% к температуре, пока действует

# Реалистичный износ (детали ломаются только при высокой температуре).
WEAR_BASE_PER_H = 0.05            # базовый — ничтожный, просто «возраст»
WEAR_TEMP_START = 40.0            # с этой температуры начинается нарастающий износ
WEAR_TEMP_HOT = 60.0              # «горячо» — износ ощутимый
WEAR_TEMP_CRIT = 80.0             # критично — износ быстрый
WEAR_AT_HOT = 0.8                 # износ/ч при 60°С
WEAR_AT_CRIT = 4.0                # износ/ч при 80°С
WEAR_OVERCLOCK_FACTOR = 3.0       # множитель износа за разгон выше 1.0x
MAX_ACCRUAL_H = 6.0                    # cap накопления оффлайн
FEE = 0.01

# ── Экономика "доля от синтетической сложности сети" (см. design-спеку) ──
DIFF_EXP = 1.5              # сложность монеты растёт быстрее цены — самобалансировка выбора
DIFF_SCALE = 600.0          # калибрует градиент выбора монеты: слабая ферма тянется к дешёвым, сильная — к дорогим
EMISSION = 480.0            # монето-USD-эквивалент/час при share=1.0; калибровано так, чтобы ферма любого размера окупалась за ~4 дня — как активы (assets.py)
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

MIGRATION_KEY = "mining_rebalance_v1"

MANAGER_BASE_COST = 120000.0
MANAGER_UPGRADE_COST = 90000.0         # × текущий уровень
MANAGER_MAX_LEVEL = 5
MANAGER_SALARY_PER_H = 100.0           # × уровень
# ИИ-управляющий поддерживает ферму в рабочем состоянии, не дожидаясь
# критического износа. Порог ремонта растёт с уровнем: чем опытнее управляющий,
# тем в лучшем состоянии он держит оборудование (level 1 → ~56%, level 5 → 80%).
MANAGER_REPAIR_BASE = 50.0
MANAGER_REPAIR_PER_LEVEL = 6.0
# Переключатели автономности ИИ (farm.manager.settings, по умолчанию всё включено).
MANAGER_SETTINGS = ("autoRepair", "autoCoin", "autoRestart")

# Полное восстановление фермы с 0% износа стоит эту долю от цены её железа.
# Калибровано так, чтобы разгон 1.5× оставался выгодным на ферме любого размера
# (+14…+26% к чистой прибыли после ремонта) — см. _repair_cost.
# Цена за единицу износа от СТОИМОСТИ железа. Железо подорожало ×10
# (глобальная инфляция каталога), поэтому доля уменьшена /10 — ремонт
# остаётся той же долей дохода, что и до инфляции цен.
REPAIR_COST_PCT = 0.01


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

    def spec(role: str, key: str, default=0):
        # Снятый компонент хранится как None (см. uninstall_component) — не {}.
        return (comp.get(role) or {}).get("specs", {}).get(key, default)

    return {
        "hashrate": _farm_hashrate(farm),
        "gpu_count": len(comp.get("gpus", [])),
        "cores": spec("cpu", "cores"),
        "ram_gb": spec("ram", "gb"),
        "ssd_gb": spec("ssd", "gb"),
        "net_speed": spec("network", "speed"),
        "ups_backup": spec("ups", "backup"),
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
    cpu_power = (comp.get("cpu") or {}).get("specs", {}).get("power", 0)
    mb_power = (comp.get("motherboard") or {}).get("specs", {}).get("power", 0)
    total_power = round(gpu_power + cpu_power + mb_power + BASE_POWER_W, 1)

    cooling_cap = (comp.get("cooling") or {}).get("specs", {}).get("cooling", 0) + sum(f.get("specs", {}).get("cooling", 0) for f in fans)
    manager = farm.get("manager") or {"type": "player", "level": 0}
    ai_level = manager.get("level", 0) if manager.get("type") == "ai" else 0
    cool_bonus = min(0.5, ai_level * 0.06)
    base_temp = TEMP_AMBIENT + (total_power / max(1, cooling_cap)) * TEMP_FACTOR * (1 - cool_bonus)
    # Бонус охлаждающей жидкости: пока datetime coolant_until не наступила,
    # температура считается сниженной на 25%.
    coolant_until = farm.get("coolant_until")
    coolant_active = bool(coolant_until and coolant_until > _now())
    if coolant_active:
        # Снижение от дельты (превышения над TEMP_AMBIENT), сохраняя базу.
        base_temp = TEMP_AMBIENT + (base_temp - TEMP_AMBIENT) * (1 - COOLANT_TEMP_REDUCTION)
    temperature = round(base_temp, 1)

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
    # Реалистичный износ: при t < 40°C детали практически не изнашиваются,
    # при 40+ — линейный рост, при 80+ — критический. Бонус жидкости уже
    # уменьшает температуру, так что износ падает автоматически.
    if temperature < WEAR_TEMP_START:
        temp_wear = 0.0
    elif temperature < WEAR_TEMP_HOT:
        # 40..60 → 0..WEAR_AT_HOT
        temp_wear = (temperature - WEAR_TEMP_START) / (WEAR_TEMP_HOT - WEAR_TEMP_START) * WEAR_AT_HOT
    elif temperature < WEAR_TEMP_CRIT:
        # 60..80 → WEAR_AT_HOT..WEAR_AT_CRIT
        ratio = (temperature - WEAR_TEMP_HOT) / (WEAR_TEMP_CRIT - WEAR_TEMP_HOT)
        temp_wear = WEAR_AT_HOT + (WEAR_AT_CRIT - WEAR_AT_HOT) * ratio
    else:
        # 80+ — экстраполяция: быстрый износ
        temp_wear = WEAR_AT_CRIT + (temperature - WEAR_TEMP_CRIT) * 0.5
    wear_per_h = round(WEAR_BASE_PER_H + temp_wear + overclock_excess * WEAR_OVERCLOCK_FACTOR, 4)

    ups_coverage = min(1.0, profile["ups_backup"] / total_power) if total_power > 0 else 1.0
    profit_per_h = round(revenue_per_h - electricity_per_h - salary_per_h, 2)
    return {
        "hashrate": hashrate, "power": total_power, "temperature": temperature,
        "coolingCapacity": cooling_cap, "condition": round(condition, 1),
        "revenuePerHour": revenue_per_h, "electricityPerHour": electricity_per_h,
        "salaryPerHour": salary_per_h, "profitPerHour": profit_per_h,
        "wearPerHour": wear_per_h, "gpuCount": gpu_count,
        "overheating": temperature >= OVERHEAT_TEMP,
        "coolantActive": coolant_active,
        "coolantCount": int(farm.get("coolant", 0) or 0),
        "coolantMax": COOLANT_MAX,
        "coolantUntil": coolant_until.isoformat() if coolant_until else None,
        "tempWearThreshold": WEAR_TEMP_START,
    }


def _mined_qty(revenue_usd: float, coin_price: float) -> float:
    """USD-выручка → количество добытых монет по текущему курсу (0 при price<=0)."""
    return round(revenue_usd / coin_price, 8) if (revenue_usd > 0.01 and coin_price > 0) else 0.0


def _hardware_value(farm: dict) -> float:
    """Стоимость установленного железа по каталогу магазина (имена уникальны)."""
    total = 0.0
    for slot in (farm.get("components") or {}).values():
        items = slot if isinstance(slot, list) else ([slot] if slot else [])
        for it in items:
            total += CATALOG_BY_NAME.get((it or {}).get("name"), 0.0)
    return total


def _repair_cost(farm: dict) -> float:
    """Ремонт стоит долю от цены железа, а не фиксированную сумму за GPU:
    иначе восстановление фермы за $3 млн стоило бы как за $20 тыс., и износ
    был бы налогом на бедных — на маленькой ферме ремонт съедал ~30% прибыли,
    а на большой ~0.2%. Как следствие разгон окупался только у топовых сборок
    (см. REPAIR_COST_PCT)."""
    missing = max(0.0, 100.0 - farm.get("condition", 100.0))
    return round(_hardware_value(farm) * REPAIR_COST_PCT * missing / 100.0, 2)


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
        "houseId": str(farm["houseId"]) if farm.get("houseId") else None,
        "slotIndex": int(farm.get("slotIndex", 0)) if farm.get("slotIndex") is not None else None,
        "coolant": int(farm.get("coolant", 0) or 0),
        "coolantUntil": farm["coolant_until"].isoformat() if farm.get("coolant_until") else None,
        # Верхний уровень для UI (фронт читает farm.coolantActive/coolantMax,
        # а не farm.stats.*): без этого пилюля охлаждения всегда «off».
        "coolantActive": bool(farm.get("coolant_until") and farm["coolant_until"] > _now()),
        "coolantMax": COOLANT_MAX,
        "components": {
            "motherboard": comp.get("motherboard"),
            "cpu": comp.get("cpu"),
            "ram": comp.get("ram"), "ssd": comp.get("ssd"),
            "cooling": comp.get("cooling"), "case": comp.get("case"),
            "rack": comp.get("rack"),
            "ups": comp.get("ups"),
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
    """Число посадочных мест размещения (None = ничего не установлено —
    открытый стенд без жёсткого ограничения). Корпус — до CASE_MAX_GPUS (5),
    серверная стойка (rack) — до RACK_MAX_GPUS (60)."""
    node = comp.get("case") or comp.get("rack")
    if node:
        slots = (node.get("specs") or {}).get("slots")
        if slots:
            limit = CASE_MAX_GPUS if comp.get("case") else RACK_MAX_GPUS
            return min(int(slots), limit)
    return None


def _capacity(farm: dict) -> dict:
    """Максимум и остаток слотов для multi-компонентов (GPU, вентиляторы).

    Корпус задаёт общий лимит посадочных мест (не более 5 GPU); для GPU он
    ещё и ограничен числом слотов материнской платы (тоже ≤ 5). Вентиляторы
    без корпуса ограничены открытым стендом (FAN_BASE_CAP)."""
    comp = farm.get("components", {})
    enclosure = _enclosure_slots(comp)
    mb_slots = int((comp.get("motherboard") or {}).get("specs", {}).get("gpuSlots", 0) or 0)

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


async def _user_basement_capacity(db, user_id: str) -> int:
    """Суммарная ёмкость подвалов всех домов игрока. Каждый слот подвала
    вмещает один корпус (для майнинга). Без подвала майнинг запрещён."""
    total = 0
    async for a in db.user_assets.find(
        {"userId": user_id, "type": "realestate"}
    ):
        total += int(a.get("basement") or 0)
    return total


async def _user_installed_cases(db, user_id: str) -> int:
    """Сколько корпусов уже установлено во все фермы игрока (для контроля
    лимита подвала)."""
    cnt = 0
    async for f in db.mining_farms.find({"userId": user_id}):
        comp = f.get("components", {}) or {}
        if comp.get("case"):
            cnt += 1
    return cnt


# ── Помощники доступа ────────────────────────────────────────────────────────


async def _serialize_with_stats(db, farm: dict, user_id: str) -> dict:
    """Сериализует ферму с ПОЛНЫМ пересчётом характеристик (для мгновенного отклика UI)."""
    cap = _capacity(farm)
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
    # Ферма теперь привязана к дому (basement) и конкретному слоту корпуса.
    # houseId = id актива-недвижимости; slotIndex = номер слота (0..basement-1).
    houseId: str
    slotIndex: int

    @field_validator("name")
    @classmethod
    def name_ok(cls, v):
        v = (v or "").strip()
        if len(v) < 2:
            raise ValueError("Название слишком короткое")
        return v[:40]

    @field_validator("slotIndex")
    @classmethod
    def slot_ok(cls, v):
        if v is None or v < 0 or v > 1000:
            raise ValueError("Некорректный номер слота")
        return int(v)


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
    action: str  # hire | upgrade | fire | settings
    settings: Optional[dict] = None   # для action="settings": {autoRepair|autoCoin|autoRestart: bool}


class AdminFarmUpdate(BaseModel):
    """Правки фермы администратором — без ограничений, действующих на игрока."""
    condition: Optional[float] = None
    overclock: Optional[float] = None
    electricity_owed: Optional[float] = None
    status: Optional[str] = None


class AdminTransferBody(BaseModel):
    toUsername: str


BULK_ACTIONS = ("start", "stop", "repair", "coolant", "hire", "upgrade",
                "fire", "coin", "settings", "uninstall")


class BulkActionBody(BaseModel):
    """Bulk-действие над списком ферм. Действие — см. BULK_ACTIONS.
    symbol — для coin; settings — для settings (переключатели ИИ);
    qty — сколько канистр ОЖ заправить в каждую ферму (для coolant)."""
    action: str
    farmIds: list[str]
    symbol: Optional[str] = None
    settings: Optional[dict] = None
    qty: Optional[int] = None

    @field_validator("farmIds")
    @classmethod
    def ids_ok(cls, v):
        if not v:
            raise ValueError("Не выбрано ни одной фермы")
        return v[:100]


class BulkAssembleBody(BaseModel):
    """Авто-сборка нескольких ферм указанными комплектующими.
    items: [{category: str, hwIds: [str]}] — конкретные свободные экземпляры."""
    farmIds: list[str]
    items: list[dict]

    @field_validator("farmIds")
    @classmethod
    def ids_ok(cls, v):
        if not v:
            raise ValueError("Не выбрано ни одной фермы")
        return v[:100]

    @field_validator("items")
    @classmethod
    def items_ok(cls, v):
        if not v:
            raise ValueError("Не указаны комплектующие")
        return v[:60]


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


@router.get("/houses")
async def get_mining_houses(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Список домов игрока с подвалом, пригодных для майнинга.

    Возвращает массив объектов:
      {id, name, rarity, basement, slots: [{index, occupied, farmId, farmName}, ...]}

    Слоты заполняются по существующим фермам игрока, привязанным к этому дому.
    Дом показывается, даже если у него 0 basement — тогда массив slots пуст,
    а кнопка «Добавить ферму» недоступна (UI на неё реагирует).
    """
    from bson import ObjectId
    user_id = str(current_user["_id"])
    # Индекс существующих ферм по (houseId, slotIndex) для быстрого заполнения.
    farms_by_slot: dict[tuple[str, int], dict] = {}
    async for f in db.mining_farms.find({"userId": user_id}):
        hid = f.get("houseId")
        si = f.get("slotIndex")
        if hid is None or si is None:
            continue
        farms_by_slot[(str(hid), int(si))] = f

    out = []
    async for a in db.user_assets.find(
        {"userId": user_id, "type": "realestate", "basement": {"$gt": 0}}
    ).sort([("rarity", -1), ("created_at", 1)]):
        basement = int(a.get("basement") or 0)
        hid = str(a["_id"])
        slots = []
        for i in range(basement):
            farm = farms_by_slot.get((hid, i))
            slots.append({
                "index": i,
                "occupied": bool(farm),
                "farmId": str(farm["_id"]) if farm else None,
                "farmName": farm.get("name") if farm else None,
                "status": farm.get("status") if farm else None,
            })
        out.append({
            "id": hid,
            "name": a.get("name"),
            "slug": a.get("slug"),
            "rarity": a.get("rarity"),
            "basement": basement,
            "group": a.get("group"),
            "slots": slots,
        })
    return out


@router.post("/houses/{house_id}/group")
async def set_house_group(
    house_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Присвоить дому группу (произвольная строка ≤30 симв.) или снять (null).
    Группы — локальная организация игрока для bulk-выбора ферм по домам."""
    user_id = str(current_user["_id"])
    if not ObjectId.is_valid(house_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID дома")
    group = (body or {}).get("group")
    if group is not None:
        group = str(group).strip()[:30] or None
    res = await db.user_assets.update_one(
        {"_id": ObjectId(house_id), "userId": user_id, "type": "realestate"},
        {"$set": {"group": group}},
    )
    if res.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Дом не найден")
    return {"ok": True, "group": group}


@router.get("/farms")
async def get_farms(
    houseId: str = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Список ферм игрока. Опционально фильтруется по дому (houseId)."""
    user_id = str(current_user["_id"])
    market = await _coin_market(db)
    econ = await get_econ(db)
    ec, em = econ.get("energy_cost", 0.12), econ.get("economy_mult", 1.0)
    city = await _city_bonus(db, user_id)
    q: dict = {"userId": user_id}
    if houseId and ObjectId.is_valid(houseId):
        q["houseId"] = ObjectId(houseId)
    out = []
    async for farm in db.mining_farms.find(q):
        missing = _missing_required(farm)
        # Пока ферма не собрана — показатели не рассчитываются (пустые).
        stats = {} if missing else _compute(farm, market, ec, em, city)
        item = _serialize(farm, stats, _capacity(farm))
        item["missing"] = missing
        out.append(item)
    return out


@router.post("/farms", status_code=status.HTTP_201_CREATED)
async def create_farm(payload: CreateFarm, current_user: dict = Depends(require_allowed("mining")), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Создать ферму в конкретном слоте подвала выбранного дома.

    Дом должен принадлежать игроку и иметь подвал (basement > 0). Номер слота
    должен быть в диапазоне [0, basement). Слот ещё не должен быть занят
    существующей фермой — иначе 400."""
    from bson import ObjectId
    user_id = str(current_user["_id"])
    if not ObjectId.is_valid(payload.houseId):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID дома")
    house = await db.user_assets.find_one(
        {"_id": ObjectId(payload.houseId), "userId": user_id, "type": "realestate"}
    )
    if not house:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Дом не найден")
    basement = int(house.get("basement") or 0)
    if basement <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "У этого дома нет подвала — майнинг недоступен",
        )
    if payload.slotIndex < 0 or payload.slotIndex >= basement:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Слот {payload.slotIndex} вне диапазона (0..{basement - 1})",
        )
    # Слот свободен?
    existing = await db.mining_farms.find_one({
        "userId": user_id,
        "houseId": ObjectId(payload.houseId),
        "slotIndex": payload.slotIndex,
    })
    if existing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Слот {payload.slotIndex} уже занят другой фермой",
        )
    doc = {
        "userId": user_id, "name": payload.name, "status": "idle", "coin": None,
        "houseId": ObjectId(payload.houseId), "slotIndex": payload.slotIndex,
        "components": {"gpus": [], "fans": []}, "overclock": 1.0, "condition": 100.0,
        "coolant": 0, "coolant_until": None,
        "manager": {"type": "player", "level": 0}, "electricity_owed": 0.0,
        "total_earned": 0.0, "total_spent": 0.0, "last_tick": _now(), "created_at": _now(),
    }
    try:
        result = await db.mining_farms.insert_one(doc)
    except DuplicateKeyError:
        # Гонка check-then-insert: слот заняла параллельная вставка
        # (уникальный индекс (houseId, slotIndex)).
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Слот {payload.slotIndex} уже занят другой фермой",
        )
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


async def _rack_pool_check(db, user_id: str, rack_hw_id: str, rack_slots: int,
                           extra: int, exclude_farm_id: Optional[str] = None) -> None:
    """Стойка — общий пул слотов на несколько ферм: сумма слотов материнок
    (потребность каждой фермы) не должна превышать слотов стойки.

    extra — потребность текущей фермы (gpuSlots её материнки), exclude_farm_id
    исключает саму ферму (при замене платы/стойки). Бросает HTTPException."""
    used = 0
    q: dict = {"userId": user_id, "components.rack.hwId": rack_hw_id}
    if exclude_farm_id and ObjectId.is_valid(exclude_farm_id):
        q["_id"] = {"$ne": ObjectId(exclude_farm_id)}
    async for f in db.mining_farms.find(q, {"components.motherboard": 1}):
        mb = (f.get("components") or {}).get("motherboard") or {}
        used += int((mb.get("specs") or {}).get("gpuSlots", 0) or 0)
    if used + extra > rack_slots:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"В стойке занято {used} из {rack_slots} слотов — для этой фермы нужно ещё {extra}",
        )


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
        cap = _capacity(farm)
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
        # Корпус или серверная стойка — единый вариант размещения в слоте
        # подвала (см. create_farm): ферма должна быть привязана к дому.
        if role in ("case", "rack"):
            if not farm.get("houseId"):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Ферма не привязана к дому - корпус нельзя установить",
                )
        # Совместимость материнской платы и корпуса:
        #   - при установке материнки: в корпусе должно быть >= слотов;
        #   - при установке корпуса: в материнке должно быть >= слотов;
        #   - в обоих случаях нельзя превышать жёсткий лимит CASE_MAX_GPUS (5).
        if role == "motherboard":
            mb_slots = int(hw.get("specs", {}).get("gpuSlots", 0) or 0)
            if mb_slots <= 0:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Материнская плата не имеет слотов для GPU")
            enclosure_slots = _enclosure_slots(comp)
            limit = enclosure_slots if enclosure_slots is not None else RACK_MAX_GPUS
            if mb_slots > limit:
                kind = "в корпусе" if enclosure_slots is not None else "максимум на ферму"
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Нельзя установить материнскую плату на {mb_slots} GPU: {kind} только {limit} слотов",
                )
            # Стойка — общий пул слотов: потребность этой фермы не должна
            # превышать остаток пула (другие фермы уже могут занимать слоты).
            rack = comp.get("rack")
            if rack and rack.get("hwId"):
                await _rack_pool_check(
                    db, user_id, rack["hwId"],
                    int((rack.get("specs") or {}).get("slots", 0) or 0),
                    mb_slots, exclude_farm_id=str(farm["_id"]),
                )
        elif role == "case":
            case_slots = int(hw.get("specs", {}).get("slots", 0) or 0)
            if case_slots <= 0:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Корпус не имеет посадочных мест")
            if case_slots > CASE_MAX_GPUS:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Корпус рассчитан на {case_slots} GPU - это больше максимума ({CASE_MAX_GPUS})",
                )
            mb = comp.get("motherboard")
            if mb:
                mb_slots = int(mb.get("specs", {}).get("gpuSlots", 0) or 0)
                if mb_slots > case_slots:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        f"Нельзя установить корпус на {case_slots} GPU: материнская плата требует {mb_slots} слотов",
                    )
        elif role == "rack":
            rack_slots = int(hw.get("specs", {}).get("slots", 0)  or 0)
            if rack_slots <= 0:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Стойка обслуживает несколько ферм (общий пул слотов) и не может быть пустой")
            mb = comp.get("motherboard")
            my_mb_slots = 0
            if mb:
                my_mb_slots = int(mb.get("specs", {}).get("gpuSlots", 0) or 0)
                if my_mb_slots > rack_slots:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        f"Материнка этой фермы требует {my_mb_slots} слотов - больше, чем в стойке ({rack_slots})",
                    )
            # Пул: другие фермы уже могут занимать слоты этой стойки.
            await _rack_pool_check(
                db, user_id, str(hw["_id"]), rack_slots, my_mb_slots,
                exclude_farm_id=str(farm["_id"]),
            )
        # Освобождаем ранее установленный компонент этой роли; при замене
        # размещения (корпус <-> стойка) освобождаем и второе.
        roles_to_free = [role]
        if role in ("case", "rack"):
            roles_to_free.append("rack" if role == "case" else "case")
        for r in roles_to_free:
            old = comp.get(r)
            if old and old.get("hwId"):
                await db.user_hardware.update_one({"_id": ObjectId(old["hwId"])}, {"$set": {"farmId": None}})
            if r != role:
                await db.mining_farms.update_one({"_id": farm["_id"]}, {"$unset": {f"components.{r}": ""}})
        entry = {"hwId": str(hw["_id"]), "name": hw["name"], "specs": hw.get("specs", {}), "category": category}
        await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {f"components.{role}": entry}})


@router.post("/farms/{farm_id}/install")
async def install_component(farm_id: str, payload: InstallBody, current_user: dict = Depends(require_allowed("mining")), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Установить в ферму свободное оборудование выбранной категории."""
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    await _install_one(db, user_id, farm, payload.category, payload.hwId)
    updated = await db.mining_farms.find_one({"_id": farm["_id"]})
    return await _serialize_with_stats(db, updated, user_id)


@router.post("/farms/{farm_id}/install-batch")
async def install_components_batch(farm_id: str, payload: InstallBatchBody, current_user: dict = Depends(require_allowed("mining")), db: AsyncIOMotorDatabase = Depends(get_db)):
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


async def _uninstall_all(db, farm: dict) -> None:
    """Снять ВСЁ оборудование фермы в инвентарь (bulk-uninstall).
    Добыча останавливается — без компонентов ферма собранной не считается."""
    comp = farm.get("components") or {}
    hw_ids = []
    for role in ("motherboard", "cpu", "ram", "ssd", "cooling", "case", "rack", "ups", "network", "psu"):
        node = comp.get(role)
        if isinstance(node, dict) and node.get("hwId"):
            hw_ids.append(node["hwId"])
    for key in ("gpus", "fans", "psus"):
        hw_ids += [x.get("hwId") for x in (comp.get(key) or [])
                   if isinstance(x, dict) and x.get("hwId")]
    await db.mining_farms.update_one(
        {"_id": farm["_id"]},
        {"$set": {"components": {"gpus": [], "fans": []}, "status": "idle", "coin": None}},
    )
    valid = [ObjectId(h) for h in hw_ids if h and ObjectId.is_valid(h)]
    if valid:
        await db.user_hardware.update_many({"_id": {"$in": valid}}, {"$set": {"farmId": None}})


@router.post("/bulk/action")
async def bulk_action(
    payload: BulkActionBody,
    current_user: dict = Depends(require_allowed("mining")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Массовое действие над выбранными фермами — полный паритет с одиночным
    управлением: start | stop | repair | coolant | hire | upgrade | fire |
    coin | settings | uninstall. Ошибка одной фермы не мешает остальным."""
    if payload.action not in BULK_ACTIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown action")
    user_id = str(current_user["_id"])
    symbol = (payload.symbol or "").upper()
    if payload.action == "coin" and not await db.crypto_assets.find_one({"symbol": symbol}):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Монета не найдена")
    market = await _coin_market(db)
    econ = await get_econ(db)
    city = await _city_bonus(db, user_id)
    results = []
    for fid in payload.farmIds:
        item = {"farmId": fid, "ok": False, "error": None}
        try:
            farm = await _load_farm(db, user_id, fid)
            if payload.action == "start":
                await _start_one(db, user_id, farm, market, econ, city)
            elif payload.action == "stop":
                await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"status": "idle"}})
            elif payload.action == "repair":
                cost = _repair_cost(farm)
                if cost > 0:
                    nb = await adjust_balance(db, user_id, -cost)
                    if nb is None:
                        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств на ремонт")
                    await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"condition": 100.0}})
                    await record_transaction(db, user_id, EXPENSE, cost, CAT_MINING,
                                             "Farm repair", balance_after=nb)
            elif payload.action == "coolant":
                qty = max(1, min(int(payload.qty or 1), COOLANT_MAX))
                for _ in range(qty):
                    fresh = await db.mining_farms.find_one({"_id": farm["_id"]})
                    await _take_coolant(db, user_id, fresh)
            elif payload.action == "coin":
                await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"coin": symbol}})
            elif payload.action == "settings":
                mgr = farm.get("manager") or {}
                if mgr.get("type") != "ai":
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Управляющий не нанят")
                cur = dict(mgr.get("settings") or {})
                for k, v in (payload.settings or {}).items():
                    if k in MANAGER_SETTINGS:
                        cur[k] = bool(v)
                await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"manager.settings": cur}})
            elif payload.action == "uninstall":
                await _uninstall_all(db, farm)
            elif payload.action in ("hire", "upgrade"):
                mgr = farm.get("manager") or {}
                if payload.action == "hire":
                    missing = _missing_required(farm)
                    if missing:
                        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                            f"Не хватает компонентов: {', '.join(missing)}")
                    if mgr.get("type") == "ai":
                        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Управляющий уже нанят")
                    cost, new_level = MANAGER_BASE_COST, 1
                else:
                    if mgr.get("type") != "ai":
                        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Сначала наймите управляющего")
                    lvl = int(mgr.get("level", 1))
                    if lvl >= MANAGER_MAX_LEVEL:
                        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Достигнут максимальный уровень")
                    cost, new_level = MANAGER_UPGRADE_COST * lvl, lvl + 1
                nb = await adjust_balance(db, user_id, -cost)
                if nb is None:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
                new_manager = {"type": "ai", "level": new_level,
                               "salary": round(MANAGER_SALARY_PER_H * new_level, 2)}
                await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"manager": new_manager}})
                await record_transaction(db, user_id, EXPENSE, cost, CAT_MINING,
                                         f"ИИ-управляющий (ур. {new_level}) — «{farm.get('name')}»",
                                         balance_after=nb)
            else:  # fire
                await db.mining_farms.update_one(
                    {"_id": farm["_id"]}, {"$set": {"manager": {"type": "player", "level": 0}}})
            item["ok"] = True
        except HTTPException as e:
            item["error"] = e.detail
        results.append(item)
    return {"results": results}


async def _uninstall_hw(db, farm: dict, hw_id: str) -> bool:
    """Снять деталь по hwId: uninstall из фермы + возврат в инвентарь.
    Общая логика uninstall-эндпоинта и отката bulk-сборки."""
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
    return changed


@router.post("/bulk/assemble")
async def bulk_assemble(
    payload: BulkAssembleBody,
    current_user: dict = Depends(require_allowed("mining")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Авто-сборка нескольких ферм указанными комплектующими.

    Фермы заполняются по очереди. Если на очередной ферме что-то не встало —
    уже установленные в неё детали снимаются обратно в инвентарь и работа
    останавливается: остаток железа сохраняется для следующей сборки."""
    user_id = str(current_user["_id"])
    norm_items = []
    for it in payload.items:
        cat = str(it.get("category") or "").strip()
        if not CATEGORY_ROLE.get(cat):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown category: {cat}")
        hw_ids = [str(x) for x in (it.get("hwIds") or []) if str(x).strip()]
        if not hw_ids:
            hw_ids = [None] * max(1, min(int(it.get("qty") or 1), 50))
        norm_items.append((cat, hw_ids))
    results = []
    stop = False
    for fid in payload.farmIds:
        if stop:
            break
        farm = await db.mining_farms.find_one(
            {"_id": ObjectId(fid), "userId": user_id}) if ObjectId.is_valid(fid) else None
        if not farm:
            results.append({"farmId": fid, "ok": False, "error": "Ферма не найдена"})
            stop = True
            continue
        installed_now = []
        err = None
        for cat, hw_ids in norm_items:
            for hw_id in hw_ids:
                try:
                    fresh = await db.mining_farms.find_one({"_id": farm["_id"]})
                    await _install_one(db, user_id, fresh, cat, hw_id)
                    installed_now.append(hw_id)
                except HTTPException as e:
                    err = f"{cat}: {e.detail}"
                    break
            if err:
                break
        if err:
            fresh = await db.mining_farms.find_one({"_id": farm["_id"]})
            for hw_id in installed_now:
                await _uninstall_hw(db, fresh, hw_id)
            results.append({"farmId": fid, "ok": False, "error": err})
            stop = True
        else:
            results.append({"farmId": fid, "ok": True})
    return {"results": results, "assembled": sum(1 for r in results if r["ok"])}


class BulkCreateBody(BaseModel):
    """Массовое создание ферм: во всех свободных слотах одного дома (houseId)
    или сразу всех домов игрока (houseId=None). qty — создать не больше N ферм."""
    houseId: Optional[str] = None
    prefix: str = "Ферма"
    qty: Optional[int] = None

    @field_validator("prefix")
    @classmethod
    def prefix_ok(cls, v):
        v = (v or "").strip()
        return (v or "Ферма")[:30]

    @field_validator("qty")
    @classmethod
    def qty_ok(cls, v):
        if v is None:
            return None
        return max(1, min(int(v), 1000))


@router.post("/bulk/create")
async def bulk_create_farms(
    payload: BulkCreateBody,
    current_user: dict = Depends(require_allowed("mining")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Создать фермы в свободных слотах подвала (одного дома или всех домов).
    qty — лимит количества; ответ несёт remaining — сколько свободных слотов
    осталось после создания."""
    user_id = str(current_user["_id"])
    hq: dict = {"userId": user_id, "type": "realestate", "basement": {"$gt": 0}}
    if payload.houseId:
        if not ObjectId.is_valid(payload.houseId):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID дома")
        hq["_id"] = ObjectId(payload.houseId)
    houses = await db.user_assets.find(hq).to_list(None)
    if not houses:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Подходящих домов не найдено")

    occupied = set()
    async for f in db.mining_farms.find({"userId": user_id}, {"houseId": 1, "slotIndex": 1}):
        if f.get("houseId") is not None:
            occupied.add((str(f["houseId"]), int(f.get("slotIndex") or 0)))

    free_before = 0
    for h in houses:
        for i in range(int(h.get("basement") or 0)):
            if (str(h["_id"]), i) not in occupied:
                free_before += 1
    cap = min(payload.qty, free_before) if payload.qty else free_before

    created = 0
    for h in houses:
        if created >= cap:
            break
        hid = str(h["_id"])
        for i in range(int(h.get("basement") or 0)):
            if created >= cap:
                break
            if (hid, i) in occupied:
                continue
            doc = {
                "userId": user_id, "name": f"{payload.prefix} #{i + 1}",
                "houseId": h["_id"], "slotIndex": i,
                "components": {"gpus": [], "fans": []},
                "overclock": 1.0, "condition": 100.0, "coolant": 0, "coolant_until": None,
                "manager": {"type": "player", "level": 0}, "electricity_owed": 0.0,
                "total_earned": 0.0, "total_spent": 0.0, "last_tick": _now(),
                "created_at": _now(),
            }
            try:
                await db.mining_farms.insert_one(doc)
                created += 1
            except DuplicateKeyError:
                pass   # слот заняли параллельно
    return {"ok": True, "created": created, "remaining": free_before - created}


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
async def start_mining(farm_id: str, current_user: dict = Depends(require_allowed("mining")), db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    market = await _coin_market(db)
    econ = await get_econ(db)
    city = await _city_bonus(db, user_id)
    await _start_one(db, user_id, farm, market, econ, city)
    updated = await db.mining_farms.find_one({"_id": farm["_id"]})
    return _serialize(updated, _compute(updated, market, econ.get("energy_cost", 0.12), econ.get("economy_mult", 1.0), city))


async def _start_one(db, user_id: str, farm: dict, market: dict, econ: dict, city: dict) -> None:
    """Запустить добычу на одной ферме (общая логика single/bulk start).

    Бросает HTTPException при ошибке; статус/coin/last_tick обновляет в БД."""
    missing = _missing_required(farm)
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Не хватает компонентов: {', '.join(missing)}")

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


@router.post("/farms/{farm_id}/stop")
async def stop_mining(farm_id: str, current_user: dict = Depends(require_allowed("mining")), db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"status": "idle"}})
    return {"ok": True}


@router.post("/farms/{farm_id}/coin")
async def set_coin(farm_id: str, payload: CoinBody, current_user: dict = Depends(require_allowed("mining")), db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    coin = await db.crypto_assets.find_one({"symbol": payload.symbol.upper()})
    if not coin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Монета не найдена")
    await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"coin": coin["symbol"]}})
    return {"ok": True, "coin": coin["symbol"]}


@router.post("/farms/{farm_id}/overclock")
async def set_overclock(farm_id: str, payload: OverclockBody, current_user: dict = Depends(require_allowed("mining")), db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"overclock": payload.value}})
    return {"ok": True, "overclock": payload.value}


async def _take_coolant(db, user_id: str, farm: dict) -> None:
    """Списать 1 канистру ОЖ из инвентаря и продлить бонус фермы на
    COOLANT_DURATION_H (общая логика одиночного и bulk-эндпоинтов).
    Бросает HTTPException, если лимит фермы достигнут или канистр нет."""
    cur_count = int(farm.get("coolant", 0) or 0)
    if cur_count >= COOLANT_MAX:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"В ферме уже максимум жидкости ({COOLANT_MAX} шт.)",
        )
    # Списываем одну шт. из инвентаря игрока. Ищем именно нераспределённую
    # (farmId не задан). ВАЖНО: обновляем farmId, чтобы при разборке фермы
    # деталь вернулась в инвентарь.
    taken = await db.user_hardware.find_one_and_update(
        {
            "userId": user_id,
            "category": "supplies",
            "specs.kind": "cooling",
            "$or": [{"farmId": None}, {"farmId": {"$exists": False}}],
        },
        {"$set": {"farmId": str(farm["_id"])}},
        sort=[("created_at", 1)],
    )
    if not taken:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Нет охлаждающей жидкости в инвентаре. Купите в магазине.",
        )
    now = _now()
    current_until = farm.get("coolant_until")
    base = now if (not current_until or current_until < now) else current_until
    new_until = base + timedelta(hours=COOLANT_DURATION_H)
    await db.mining_farms.update_one(
        {"_id": farm["_id"]},
        {"$set": {"coolant": cur_count + 1, "coolant_until": new_until}},
    )


@router.post("/farms/{farm_id}/coolant")
async def add_coolant(farm_id: str, current_user: dict = Depends(require_allowed("mining")), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Заправить охлаждающую жидкость в ферму (1 шт. = +12 ч −25% к температуре)."""
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    await _take_coolant(db, user_id, farm)
    farm = await db.mining_farms.find_one({"_id": farm["_id"]})
    market = await _coin_market(db)
    econ = await get_econ(db)
    city = await _city_bonus(db, user_id)
    stats = _compute(
        farm, market,
        econ.get("energy_cost", 0.12),
        econ.get("economy_mult", 1.0),
        city,
    )
    return _serialize(farm, stats)


@router.post("/farms/{farm_id}/repair")
async def repair_farm(farm_id: str, current_user: dict = Depends(require_allowed("mining")), db: AsyncIOMotorDatabase = Depends(get_db)):
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
async def manage_manager(farm_id: str, payload: ManagerBody, current_user: dict = Depends(require_allowed("mining")), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Нанять/повысить/уволить ИИ-управляющего."""
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    manager = farm.get("manager") or {"type": "player", "level": 0}

    if payload.action == "fire":
        await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"manager": {"type": "player", "level": 0}}})
        return {"ok": True, "manager": {"type": "player", "level": 0}}

    if payload.action == "settings":
        if manager.get("type") != "ai":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Сначала наймите управляющего")
        cur = dict(manager.get("settings") or {})
        for k, v in (payload.settings or {}).items():
            if k in MANAGER_SETTINGS:
                cur[k] = bool(v)
        new_manager = {**manager, "settings": cur}
        await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {"manager": new_manager}})
        return {"ok": True, "manager": new_manager}

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


# ── Миграция: мягкий сброс старых ферм под новую экономику ───────────────────


def _reset_farm_fields() -> dict:
    """Поля фермы после мягкого сброса: снятое железо, простой, без долгов."""
    return {
        "components": {"gpus": [], "fans": []},
        "status": "idle",
        "coin": None,
        "condition": 100.0,
        "overclock": 1.0,
        "electricity_owed": 0.0,
    }


async def soft_reset_farms(db: AsyncIOMotorDatabase) -> None:
    """Один раз возвращает всё железо в инвентарь и обнуляет фермы под новую экономику."""
    if await find_config_by_key(db, MIGRATION_KEY):
        return
    await db.mining_farms.update_many({}, {"$set": _reset_farm_fields()})
    await db.user_hardware.update_many({"farmId": {"$ne": None}}, {"$set": {"farmId": None}})
    await upsert_config(db, MIGRATION_KEY, "1")


# ── Миграция: разбор сиротских ферм (houseId=None) ────────────────────────────
# Фермы, созданные до привязки к домам, не видны в новой системе (слоты
# подвала). Разбираем их при старте: железо возвращается в инвентарь,
# ферма удаляется, владелец получает уведомление. Идемпотентно: сироты
# появляются только из старых данных.
async def dismantle_orphan_farms(db: AsyncIOMotorDatabase) -> None:
    """Разбор «потерянных» ферм при старте: не привязанных к дому (houseId=None)
    ИЛИ ссылающихся на несуществующий дом / дом без подвала (дом продан или
    удалён — ферма невидима в UI, но жива и держит железо). Идемпотентно:
    после разбора таких ферм больше не появляется."""
    valid_ids = [a["_id"] async for a in db.user_assets.find(
        {"type": "realestate", "basement": {"$gt": 0}}, {"_id": 1})]
    q = {"$or": [{"houseId": None}, {"houseId": {"$nin": valid_ids}}]}
    async for farm in db.mining_farms.find(q):
        try:
            await db.user_hardware.update_many(
                {"farmId": str(farm["_id"])}, {"$set": {"farmId": None}})
            await db.mining_farms.delete_one({"_id": farm["_id"]})
            await push_notification(
                db, farm["userId"], "mining",
                "Майнинг-ферма разобрана",
                f"Ферма «{farm.get('name')}» ссылалась на недоступный дом (дом "
                "удалён или у него нет подвала). Всё оборудование возвращено "
                "в инвентарь — его можно установить в ферму в подвале дома.",
            )
        except Exception:
            pass


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
        if not (farm.get("manager") or {}).get("settings", {}).get("autoRestart", True):
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
        if ai and (manager.get("settings") or {}).get("autoCoin", True):
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

        # ИБП: шанс просадки питания за тик. Резерв покрывает долю мощности —
        # выручка и доп. износ режутся пропорционально непокрытой части.
        extra_wear = 0.0
        if random.random() < BROWNOUT_CHANCE:
            coverage = stats.get("upsCoverage", 0.0)
            if coverage < 1.0:
                stats = dict(stats)
                stats["revenuePerHour"] = round(stats["revenuePerHour"] * coverage, 2)
                stats["profitPerHour"] = round(
                    stats["revenuePerHour"] - stats["electricityPerHour"] - stats["salaryPerHour"], 2)
                extra_wear = UPS_WEAR_PENALTY * (1.0 - coverage)

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
        if ai and (manager.get("settings") or {}).get("autoRepair", True):
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
        # Расход охлаждающей жидкости: бонус истёк — списываем одну шт. и
        # продлеваем бонус на следующий период. Раньше coolant_until обнулялся:
        # списанная канистра не активировала бонус, а остаток застревал —
        # условие расхода требует активный coolant_until.
        cur_coolant = int(farm.get("coolant", 0) or 0)
        coolant_until = farm.get("coolant_until")
        if cur_coolant > 0 and coolant_until and coolant_until <= now:
            set_fields["coolant"] = cur_coolant - 1
            set_fields["coolant_until"] = now + timedelta(hours=COOLANT_DURATION_H)
            farm["coolant"] = set_fields["coolant"]
            farm["coolant_until"] = set_fields["coolant_until"]

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
    _admin=Depends(require_admin("users_property")),
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
    _admin=Depends(require_admin("users_property")),
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
    _admin=Depends(require_admin("users_property")),
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
    from shop import CATALOG, CATALOG_BY_ID
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

    # Слоты GPU: ограничены материнкой; стойка поднимает потолок до 45.
    _mb8 = {"specs": {"gpuSlots": 8}}
    _farm = {"components": {"motherboard": _mb8, "gpus": [{}] * 3}}
    # Упираемся в лимит платы: 8 слотов платы, 3 установлено → свободно 5.
    assert _capacity(_farm)["gpu"] == 5
    _farm_case = {"components": {"motherboard": _mb8,
                                 "case": {"specs": {"slots": 8}}, "gpus": [{}] * 3}}
    assert _capacity(_farm_case)["gpu"] == 2                       # корпус режет до 5
    _farm_rack = {"components": {"motherboard": _mb8,
                                 "rack": {"specs": {"slots": 45}}, "gpus": [{}] * 3}}
    assert _capacity(_farm_rack)["gpu"] == 5                       # упираемся в плату, не в стойку

    # БП — multi-компонент: открытый стенд даёт 2 места, корпус больше;
    # старое одиночное поле psu совместимо со списком psus.
    assert _psu_max({}) == 2
    # Корпус капируется на CASE_MAX_GPUS=5 мест → 5//3+1 = 2 БП.
    assert _psu_max({"case": {"specs": {"slots": 8}}}) == 2
    # Стойка на 45 мест → 45//3+1 = 16 БП.
    assert _psu_max({"rack": {"specs": {"slots": 45}}}) == 16
    assert _psus({"psu": {"hwId": "x"}}) == [{"hwId": "x"}]        # legacy single
    assert _psus({"psus": [{"hwId": "a"}], "psu": {"hwId": "x"}}) == [{"hwId": "a"}]
    _pf = {"components": {"psus": [{}], "case": {"specs": {"slots": 8}}}}
    assert _capacity(_pf)["psu"] == 1                              # 2 max − 1 used

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

    # ── _compute: доход, мощность и счётчик GPU на собранной ферме ──
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
    assert _test_stats["revenuePerHour"] > 0
    assert _test_stats["gpuCount"] == 8
    assert _test_stats["hashrate"] > 0
    assert _test_stats["power"] > 0

    # ── Снятый компонент хранится как None (см. uninstall_component) — не должен ронять расчёт ──
    _none_farm = {"components": dict(_test_farm["components"], cpu=None, ram=None, ups=None,
                                     network=None, cooling=None, motherboard=None),
                  "overclock": 1.0, "condition": 100.0, "coin": "ORB"}
    _none_profile = _farm_hw_profile(_none_farm)
    assert _none_profile["cores"] == 0 and _none_profile["ram_gb"] == 0 and _none_profile["ups_backup"] == 0
    assert _compute(_none_farm, _test_market, energy_cost=0.12)["power"] > 0

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

    # ── Мягкий сброс: железо снято, простой, долги обнулены ──
    _reset = _reset_farm_fields()
    assert _reset["components"] == {"gpus": [], "fans": []}
    assert _reset["status"] == "idle" and _reset["coin"] is None
    assert _reset["condition"] == 100.0
    assert _reset["electricity_owed"] == 0.0
    # ── Ремонт пропорционален цене железа, поэтому разгон выгоден на ЛЮБОЙ ферме ──
    # (раньше ремонт стоил фикс. сумму за GPU: на малой ферме он съедал ~30% прибыли
    # и разгон уходил в минус, на многомиллионной — 0.2% и был почти бесплатным.)
    _shop_gpu = CATALOG_BY_ID["admin-gpu-1"]   # дешёвый GPU для сравнения с ASIC-фермой
    _shop_asic = next(c for c in CATALOG if c["brand"] == "ASIC")
    assert CATALOG_BY_NAME[_shop_gpu["name"]] == _shop_gpu["base_price"]

    # ── Реальные GPU из магазина: _hardware_value ищет цену по имени ──
    _rec_market = {"CHEAP": {"symbol": "CHEAP", "price": 0.85}, "EXPENSIVE": {"symbol": "EXPENSIVE", "price": 340.0}}

    def _priced(gpu, n):
        """Рабочая ферма из _test_farm, но с РЕАЛЬНЫМИ (именованными) GPU из магазина:
        _hardware_value ищет цену по имени, у безымянных заглушек она нулевая.
        Железо масштабируется под n GPU, монета выбирается как у игрока — иначе
        ферма упирается в пол эффективности или в насыщение доли сети."""
        _farm = {"components": dict(_test_farm["components"],
                                    motherboard={"specs": {"gpuSlots": n, "power": 60}},
                                    cpu={"specs": {"cores": n, "power": 40 + n * 8}},
                                    ram={"specs": {"gb": n * 32, "power": 20}},
                                    ssd={"specs": {"gb": n * 512, "power": 10}},
                                    network={"specs": {"speed": n * 2000, "power": 15}},
                                    cooling={"specs": {"cooling": 200000, "power": 40}},
                                    gpus=[{"name": gpu["name"], "specs": gpu["specs"]}] * n),
                 "overclock": 1.0, "condition": 100.0,
                 "manager": {"type": "player", "level": 0}}
        _farm["coin"] = choose_best_coin(_rec_market, _farm_hw_profile(_farm))
        return _farm
    _small, _big = _priced(_shop_gpu, 2), _priced(_shop_asic, 19)
    # Неизвестное имя (снятый с продажи товар) не роняет расчёт, а стоит 0.
    assert _hardware_value(_small) == _shop_gpu["base_price"] * 2
    assert _repair_cost(dict(_small, condition=0.0)) > 0
    assert _repair_cost(dict(_small, condition=100.0)) == 0.0
    assert _repair_cost(dict(_big, condition=0.0)) > _repair_cost(dict(_small, condition=0.0)) * 50

    def _net_after_repair(farm, oc):
        _f = dict(farm, overclock=oc)
        _s = _compute(_f, _rec_market, energy_cost=0.12)
        return _s["profitPerHour"] - _repair_cost(dict(_f, condition=0.0)) * _s["wearPerHour"] / 100.0
    for _farm, _label in ((_small, "малая ферма"), (_big, "большая ферма")):
        assert _net_after_repair(_farm, 1.5) > _net_after_repair(_farm, 1.0), \
            f"{_label}: разгон убыточен — ремонт съедает прирост"

    # ── Флагманская линейка (Voltronix): топ-ферма 19 × Quantum V300 ──
    # с разгоном 1.5× обязана давать 60k+ $/ч выручки (потолок экономики).
    _v300 = CATALOG_BY_ID["gpu-vlt-2"]
    _max_farm = {"components": dict(_test_farm["components"],
                                    motherboard={"specs": {"gpuSlots": 19, "power": 136}},
                                    cpu={"specs": {"cores": 32, "power": 301}},
                                    ram={"specs": {"gb": 512, "power": 37}},
                                    ssd={"specs": {"gb": 8192, "power": 6}},
                                    network={"specs": {"speed": 10000, "power": 20}},
                                    cooling={"specs": {"cooling": 250000, "power": 1270}},
                                    gpus=[{"name": _v300["name"], "specs": _v300["specs"]}] * 19,
                                    psus=[{"specs": {"power": 8000}}] * 12),
                 "overclock": 1.5, "condition": 100.0, "coin": "EXPENSIVE",
                 "manager": {"type": "player", "level": 0}}
    _max_stats = _compute(_max_farm, _rec_market, energy_cost=0.12)
    assert _max_stats["revenuePerHour"] >= 60000, f"топ-ферма даёт {_max_stats['revenuePerHour']}/ч"
    # Криогенная станция: температура < 40°C → температурного износа нет,
    # остаётся базовый + надбавка за разгон 1.5× (0.5 × WEAR_OVERCLOCK_FACTOR).
    assert _max_stats["temperature"] < 40
    assert _max_stats["wearPerHour"] == round(WEAR_BASE_PER_H + 0.5 * WEAR_OVERCLOCK_FACTOR, 4)

    # ── Переключатели ИИ: дефолт «всё включено» ( manager.settings может отсутствовать) ──
    _ms = ({"type": "ai", "level": 1}.get("settings") or {}).get("autoRepair", True)
    assert _ms is True

    print("mining self-check OK")


# ── Admin: инвентарь железа и полный разбор фермы ────────────────────────────


def _serialize_hw(h: dict) -> dict:
    return {
        "id": str(h["_id"]),
        "itemId": h.get("itemId"),
        "name": h.get("name"),
        "category": h.get("category"),
        "specs": h.get("specs", {}),
        "condition": round(float(h.get("condition", 100) or 0), 1),
        "purchasePrice": h.get("purchase_price"),
        "farmId": h.get("farmId"),
        "purchasedAt": h["purchased_at"].isoformat() if isinstance(h.get("purchased_at"), datetime) else None,
    }


@router.get("/admin/inventory/{user_id}")
async def admin_list_inventory(
    user_id: str,
    _admin=Depends(require_admin("users_property")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Полный инвентарь железа игрока: каждая единица и где установлена."""
    items = [_serialize_hw(h) async for h in
             db.user_hardware.find({"userId": user_id}).sort("purchased_at", -1)]
    return {"items": items}


@router.post("/admin/hardware/{hw_id}/uninstall")
async def admin_uninstall_hw(
    hw_id: str,
    _admin=Depends(require_admin("users_property")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Снять деталь с фермы в инвентарь."""
    if not ObjectId.is_valid(hw_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID детали")
    hw = await db.user_hardware.find_one({"_id": ObjectId(hw_id)})
    if not hw:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Деталь не найдена")
    if not hw.get("farmId"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Деталь не установлена на ферму")
    farm = await db.mining_farms.find_one({"_id": hw["farmId"]})
    if farm:
        await _uninstall_hw(db, farm, str(hw["_id"]))
    try:
        from ws import push_to_user
        await push_to_user(hw["userId"], {"type": "mining", "farmId": str(hw["farmId"])})
    except Exception:
        pass
    return {"ok": True}


@router.delete("/admin/hardware/{hw_id}")
async def admin_delete_hw(
    hw_id: str,
    _admin=Depends(require_admin("users_property")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Удалить единицу железа. Установленная — сначала снимается с фермы."""
    if not ObjectId.is_valid(hw_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID детали")
    hw = await db.user_hardware.find_one({"_id": ObjectId(hw_id)})
    if not hw:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Деталь не найдена")
    if hw.get("farmId"):
        farm = await db.mining_farms.find_one({"_id": hw["farmId"]})
        if farm:
            await _uninstall_hw(db, farm, str(hw["_id"]))
    await db.user_hardware.delete_one({"_id": hw["_id"]})
    try:
        from ws import push_to_user
        await push_to_user(hw["userId"], {"type": "mining"})
    except Exception:
        pass
    return {"message": f"«{hw.get('name')}» удалена"}


@router.post("/admin/farms/{farm_id}/uninstall")
async def admin_uninstall_farm(
    farm_id: str,
    _admin=Depends(require_admin("users_property")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Полный разбор фермы: всё оборудование — в инвентарь, добыча остановлена."""
    farm = await _load_any_farm(db, farm_id)
    await _uninstall_all(db, farm)
    updated = await db.mining_farms.find_one({"_id": farm["_id"]})
    result = await _serialize_with_stats(db, updated, farm["userId"])
    try:
        from ws import push_to_user
        await push_to_user(farm["userId"], {"type": "mining", "farmId": farm_id})
    except Exception:
        pass
    return result
