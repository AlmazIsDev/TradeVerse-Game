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
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator

from auth import get_current_user, require_admin
from database import get_db
from ledger import INCOME, EXPENSE, CAT_MINING, adjust_balance, record_transaction
from econ import get_econ
from shop import CATEGORY_ROLE
from notifications import push_notification

router = APIRouter(prefix="/api/mining", tags=["mining"])

# Обязательные компоненты для запуска добычи.
REQUIRED_ROLES = ["motherboard", "cpu", "psu", "ram", "ssd", "cooling"]  # + хотя бы 1 gpu

# Ёмкость по вентиляторам, когда корпус не установлен (открытый стенд).
FAN_BASE_CAP = 6

# Лимит подвалов и корпусов:
#   - майнинг разрешён ТОЛЬКО в подвалах домов (basement > 0);
#   - в одном подвале можно установить столько корпусов, сколько его ёмкость;
#   - в каждом корпусе — до 5 GPU (см. shop.MAX_CASE_SLOTS).
MAX_CASES_PER_BASEMENT_SLOT = 1   # один корпус = один слот подвала
CASE_MAX_GPUS = 5                # жёсткий лимит слотов корпуса

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


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if isinstance(dt, datetime) and dt.tzinfo is None else dt


# ── Расчёт показателей фермы ─────────────────────────────────────────────────


def _coin_profitability(coin: Optional[dict]) -> float:
    if not coin or coin.get("price", 0) <= 0:
        return 0.0
    price = float(coin["price"])
    momentum = 1 + max(-0.5, min(0.5, coin.get("change24h", 0.0) / 100.0))
    return math.sqrt(price) * momentum * (1 - FEE)


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


def choose_best_coin(market: dict) -> Optional[str]:
    """ИИ-выбор самой прибыльной монеты: курс × момент − комиссия."""
    best, best_p = None, -1.0
    for sym, c in market.items():
        p = _coin_profitability(c)
        if p > best_p:
            best, best_p = sym, p
    return best


def _compute(farm: dict, market: dict, energy_cost: float, economy_mult: float = 1.0,
             city: Optional[dict] = None) -> dict:
    # city — бонусы зданий «Крыши города»: yield (+% к добыче), energy (−% к счёту за свет).
    city = city or {}
    yield_bonus = float(city.get("yield", 0.0))
    energy_discount = min(0.5, float(city.get("energy", 0.0)))
    comp = farm.get("components", {})
    gpus = comp.get("gpus", [])
    fans = comp.get("fans", [])
    overclock = farm.get("overclock", 1.0)
    condition = farm.get("condition", 100.0)
    cond_factor = 0.5 + 0.5 * (condition / 100.0)

    base_hash = sum(g.get("specs", {}).get("hashrate", 0) for g in gpus)
    hashrate = round(base_hash * overclock * cond_factor, 1)
    gpu_power = sum(g.get("specs", {}).get("power", 0) for g in gpus) * overclock
    cpu_power = comp.get("cpu", {}).get("specs", {}).get("power", 0)
    mb_power = comp.get("motherboard", {}).get("specs", {}).get("power", 0)
    total_power = round(gpu_power + cpu_power + mb_power + BASE_POWER_W, 1)

    cooling_cap = comp.get("cooling", {}).get("specs", {}).get("cooling", 0) + sum(f.get("specs", {}).get("cooling", 0) for f in fans)
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

    coin_sym = farm.get("coin")
    coin = market.get(coin_sym) if coin_sym else None
    prof = _coin_profitability(coin)
    revenue_per_h = round(hashrate * HASH_YIELD * prof * economy_mult * (1 + yield_bonus), 2)

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

    profit_per_h = round(revenue_per_h - electricity_per_h - salary_per_h, 2)
    return {
        "hashrate": hashrate, "power": total_power, "temperature": temperature,
        "coolingCapacity": cooling_cap, "condition": round(condition, 1),
        "revenuePerHour": revenue_per_h, "electricityPerHour": electricity_per_h,
        "salaryPerHour": salary_per_h, "profitPerHour": profit_per_h,
        "wearPerHour": wear_per_h, "gpuCount": len(gpus),
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


def _repair_cost(farm: dict) -> float:
    gpus = len(farm.get("components", {}).get("gpus", []))
    missing = max(0.0, 100.0 - farm.get("condition", 100.0))
    return round(missing * (100 + 30 * gpus), 2)


def _ai_should_repair(ai: bool, ai_level: int, condition: float,
                      revenue: float, electricity: float, salary: float, repair_cost: float) -> bool:
    """Решение ИИ-управляющего о ремонте: чинит, когда износ ниже порога уровня
    И когда добыча за тик покрывает ремонт (не загоняя игрока в минус)."""
    if not ai:
        return False
    threshold = min(80.0, MANAGER_REPAIR_BASE + ai_level * MANAGER_REPAIR_PER_LEVEL)
    if condition >= threshold:
        return False
    return revenue - electricity - salary - repair_cost >= 0


def _serialize(farm: dict, stats: dict) -> dict:
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
        "components": {
            "motherboard": comp.get("motherboard"),
            "cpu": comp.get("cpu"), "psu": comp.get("psu"),
            "ram": comp.get("ram"), "ssd": comp.get("ssd"),
            "cooling": comp.get("cooling"), "case": comp.get("case"),
            "ups": comp.get("ups"),
            "network": comp.get("network"),
            "gpus": comp.get("gpus", []), "fans": comp.get("fans", []),
        },
        "repairCost": _repair_cost(farm),
        "capacity": _capacity(farm),
        "stats": stats,
    }


def _missing_required(farm: dict) -> list[str]:
    comp = farm.get("components", {})
    missing = [r for r in REQUIRED_ROLES if not comp.get(r)]
    if not comp.get("gpus"):
        missing.append("gpu")
    return missing


def _enclosure_slots(comp: dict) -> Optional[int]:
    """Число посадочных мест корпуса (None = корпус не установлен —
    открытый стенд без жёсткого ограничения). Стойки rack удалены из игры."""
    node = comp.get("case")
    if node:
        slots = node.get("specs", {}).get("slots")
        if slots:
            return min(int(slots), CASE_MAX_GPUS)  # жёсткий лимит 5 GPU
    return None


def _capacity(farm: dict) -> dict:
    """Максимум и остаток слотов для multi-компонентов (GPU, вентиляторы).

    Корпус задаёт общий лимит посадочных мест (не более 5 GPU); для GPU он
    ещё и ограничен числом слотов материнской платы (тоже ≤ 5). Вентиляторы
    без корпуса ограничены открытым стендом (FAN_BASE_CAP)."""
    comp = farm.get("components", {})
    enclosure = _enclosure_slots(comp)
    mb_slots = min(int((comp.get("motherboard") or {}).get("specs", {}).get("gpuSlots", 0) or 0), CASE_MAX_GPUS)

    gpu_max = mb_slots if mb_slots else 0
    if enclosure is not None:
        gpu_max = min(gpu_max, enclosure) if gpu_max else enclosure
    fan_max = enclosure if enclosure is not None else FAN_BASE_CAP

    gpu_used = len(comp.get("gpus", []))
    fan_used = len(comp.get("fans", []))
    return {
        "gpu": max(0, gpu_max - gpu_used),
        "fan": max(0, fan_max - fan_used),
        "gpuMax": gpu_max, "fanMax": fan_max,
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
    missing = _missing_required(farm)
    if missing:
        # Ферма не собрана — не считаем показатели.
        item = _serialize(farm, {})
        item["missing"] = missing
        return item
    market = await _coin_market(db)
    econ = await get_econ(db)
    city = await _city_bonus(db, user_id)
    stats = _compute(farm, market, econ.get("energy_cost", 0.12), econ.get("economy_mult", 1.0), city)
    item = _serialize(farm, stats)
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


@router.get("/market")
async def mining_market(_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Монеты для выбора добычи + рекомендация ИИ (самая прибыльная)."""
    market = await _coin_market(db)
    coins = sorted(market.values(), key=lambda c: _coin_profitability(c), reverse=True)
    return {"coins": coins, "best": choose_best_coin(market)}


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
            "slots": slots,
        })
    return out


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
        item = _serialize(farm, stats)
        item["missing"] = missing
        out.append(item)
    return out


@router.post("/farms", status_code=status.HTTP_201_CREATED)
async def create_farm(payload: CreateFarm, current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
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


@router.post("/farms/{farm_id}/install")
async def install_component(farm_id: str, payload: InstallBody, current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Установить в ферму свободное оборудование выбранной категории."""
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
    meta = CATEGORY_ROLE.get(payload.category)
    if not meta:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестная категория")
    role = meta["role"]
    multi = meta.get("multi", False)

    # Игрок может выбрать КОНКРЕТНУЮ деталь (hwId) — иначе берётся любая свободная.
    if payload.hwId:
        if not ObjectId.is_valid(payload.hwId):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID детали")
        hw = await db.user_hardware.find_one({
            "_id": ObjectId(payload.hwId), "userId": user_id,
            "category": payload.category, "farmId": None,
        })
        if not hw:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Деталь недоступна (не найдена или уже установлена)")
    else:
        hw = await db.user_hardware.find_one({"userId": user_id, "category": payload.category, "farmId": None})
        if not hw:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет свободного оборудования — купите в магазине")

    comp = farm.get("components", {})
    if multi:
        role_key = "gpus" if role == "gpu" else "fans"
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
        else:  # fan
            if cap["fan"] <= 0:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет свободных мест для вентиляторов (установите корпус/стойку большего размера)")
        entry = {"hwId": str(hw["_id"]), "name": hw["name"], "specs": hw.get("specs", {}), "category": payload.category}
        await db.mining_farms.update_one({"_id": farm["_id"]}, {"$push": {f"components.{role_key}": entry}})
    else:
        # Корпус - единый вариант размещения (стоек rack больше нет).
        # Дополнительно проверяем лимит подвалов: у игрока может быть не
        # больше корпусов, чем суммарная ёмкость подвалов его домов.
        if role == "case":
            # Ферма привязана к слоту подвала дома (см. create_farm), лимит
            # на количество корпусов теперь автоматически = количеству basement.
            # Дополнительная защита: ферма должна иметь houseId.
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
            if mb_slots > CASE_MAX_GPUS:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Материнская плата рассчитана на {mb_slots} GPU - это больше лимита корпуса ({CASE_MAX_GPUS})",
                )
            enclosure_slots = _enclosure_slots(comp)
            if enclosure_slots is not None and mb_slots > enclosure_slots:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Нельзя установить материнскую плату на {mb_slots} GPU: в корпусе только {enclosure_slots} слотов",
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
        # Освобождаем ранее установленный компонент этой роли.
        old = comp.get(role)
        if old and old.get("hwId"):
            await db.user_hardware.update_one({"_id": ObjectId(old["hwId"])}, {"$set": {"farmId": None}})
        entry = {"hwId": str(hw["_id"]), "name": hw["name"], "specs": hw.get("specs", {}), "category": payload.category}
        await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {f"components.{role}": entry}})

    await db.user_hardware.update_one({"_id": hw["_id"]}, {"$set": {"farmId": str(farm["_id"])}})
    updated = await db.mining_farms.find_one({"_id": farm["_id"]})
    return await _serialize_with_stats(db, updated, user_id)


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
    for role in ["motherboard", "cpu", "psu", "ram", "ssd", "cooling", "case", "ups", "network"]:
        if comp.get(role) and comp[role].get("hwId") == hw_id:
            await db.mining_farms.update_one({"_id": farm["_id"]}, {"$set": {f"components.{role}": None}})
            changed = True
    for role_key in ["gpus", "fans"]:
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
    psu_w = farm.get("components", {}).get("psu", {}).get("specs", {}).get("power", 0)
    if psu_w < stats["power"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Недостаточная мощность БП ({psu_w}W < {stats['power']}W)")

    coin = farm.get("coin")
    manager = farm.get("manager") or {}
    if not coin:
        if manager.get("type") == "ai":
            coin = choose_best_coin(market)
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


@router.post("/farms/{farm_id}/coolant")
async def add_coolant(farm_id: str, current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Заправить охлаждающую жидкость в ферму.

    Списывает 1 ёмкость из инвентаря игрока (user_hardware category='supplies',
    specs.kind='cooling'). В ферме максимум COOLANT_MAX шт. Каждая добавленная
    шт. продлевает активный бонус на COOLANT_DURATION_H (12 ч) от now (если
    бонус ещё активен — от coolant_until). Пока coolant_until не наступил,
    температура рассчитывается со скидкой 25%.
    """
    user_id = str(current_user["_id"])
    farm = await _load_farm(db, user_id, farm_id)
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
    new_count = cur_count + 1
    await db.mining_farms.update_one(
        {"_id": farm["_id"]},
        {"$set": {"coolant": new_count, "coolant_until": new_until}},
    )
    farm["coolant"] = new_count
    farm["coolant_until"] = new_until
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

    async for farm in db.mining_farms.find({"status": "mining"}):
        last = _aware(farm.get("last_tick"))
        elapsed_h = min(MAX_ACCRUAL_H, (now - last).total_seconds() / 3600.0) if isinstance(last, datetime) else 0.0
        if elapsed_h < MINING_MIN_ELAPSED_H:
            continue

        user_id = farm["userId"]
        manager = farm.get("manager") or {"type": "player", "level": 0}
        ai = manager.get("type") == "ai"
        ai_level = manager.get("level", 0) if ai else 0

        # ИИ автоматически выбирает самую прибыльную монету.
        if ai:
            best = choose_best_coin(market)
            if best and best != farm.get("coin"):
                farm["coin"] = best

        city = await _city_bonus(db, user_id)
        stats = _compute(farm, market, ec, em, city)
        revenue = round(stats["revenuePerHour"] * elapsed_h, 2)
        electricity = round(stats["electricityPerHour"] * elapsed_h, 2)
        salary = round(stats["salaryPerHour"] * elapsed_h, 2)
        wear = stats["wearPerHour"] * elapsed_h
        new_condition = max(0.0, farm.get("condition", 100.0) - wear)

        # ИИ авто-ремонт: держит ферму в рабочем состоянии, не дожидаясь
        # критического износа (порог растёт с уровнем управляющего). Ремонт
        # применяется только если добыча покрывает его стоимость — иначе
        # управляющий не загоняет игрока в минус ради обслуживания.
        repair_cost = 0.0
        if ai:
            farm["condition"] = new_condition   # _repair_cost считает по текущему износу
            candidate_cost = _repair_cost(farm)
            if _ai_should_repair(ai, ai_level, new_condition, revenue, electricity, salary, candidate_cost):
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
        # Расход охлаждающей жидкости: если бонус истёк — списываем одну шт.
        cur_coolant = int(farm.get("coolant", 0) or 0)
        coolant_until = farm.get("coolant_until")
        if cur_coolant > 0 and coolant_until and coolant_until <= now:
            new_coolant = cur_coolant - 1
            if new_coolant > 0:
                # Продлеваем бонус: при последней шт. оставляем coolant_until=None.
                set_fields["coolant"] = new_coolant
                set_fields["coolant_until"] = None
            else:
                set_fields["coolant"] = 0
                set_fields["coolant_until"] = None
            farm["coolant"] = set_fields["coolant"]
            farm["coolant_until"] = set_fields["coolant_until"]

        # 1) Списываем денежные расходы (если ферма их не тянет — отключаем).
        if costs > 0.01:
            nb = await adjust_balance(db, user_id, -costs)
            if nb is None:
                set_fields["status"] = "off"
                set_fields["electricity_owed"] = round(farm.get("electricity_owed", 0.0) + costs, 2)
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
    assert _ai_should_repair(False, 0, 10.0, 100, 1, 0, 50) is False
    # Уровень 1 → порог ~56%; износ 40% ниже порога и добыча покрывает ремонт.
    assert _ai_should_repair(True, 1, 40.0, 100, 10, 5, 50) is True
    # Ниже порога, но добыча НЕ покрывает ремонт — не чинит (не уводит в минус).
    assert _ai_should_repair(True, 1, 40.0, 20, 10, 5, 50) is False
    # Состояние выше порога — чинить рано.
    assert _ai_should_repair(True, 5, 90.0, 1000, 1, 1, 10) is False
    # Порог растёт с уровнем: level 5 → 80%, износ 70% уже требует ремонта.
    assert _ai_should_repair(True, 5, 70.0, 1000, 1, 1, 10) is True

    # Майнинг добывает МОНЕТУ: qty = revenue_usd / price; расходы остаются в кэше.
    assert _mined_qty(100.0, 50.0) == 2.0           # 100$ по курсу 50 → 2 монеты
    assert _mined_qty(100.0, 0.0) == 0.0            # нет курса → ничего не добыто
    assert _mined_qty(0.0, 50.0) == 0.0             # нет выручки → 0 монет
    # Выручка идёт в монеты, а costs (эл-во+зарплата+ремонт) — отдельный кэш-расход.
    _rev, _price, _costs = 60.0, 30.0, 12.0
    assert _mined_qty(_rev, _price) == 2.0 and round(_costs, 2) == 12.0
    print("mining self-check OK")
