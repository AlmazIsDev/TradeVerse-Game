"""Ферма: поле (сетка клеток), культуры, машины (комбайн/трактор), топливо.

Модель данных
-------------
* users.fuel — отдельная валюта (литры), покупается за деньги.
* user_fields — одна запись на (userId, assetId) для каждого купленного «поля»:
    { userId, assetId, cells:[{x,y,status,crop,planted_at,ready_at}], storage:{} }
  status ∈ {"empty","growing","ready"}. Storage: {crop_id: qty_kg}.
* user_hardware — машины фермы живут там же, что и GPU: type=vehicle, и
  поле "vehicleId" = slug из farmsCatalog.js ('combine_basic', 'tractor_basic'
  и т.п.). Пока машина занята — busy_until > now.

Баланс и баланс-механики — в game_config.FARM_CONFIG.

API (prefix=/api/farm):
  GET  /catalog        — справочник культур и машин (из RESOURCES + FARM_CONFIG)
  GET  /my             — мои поля + машина + топливо + культуры в складах
  POST /cells/buy      — докупить блок клеток на конкретном поле
  POST /plant          — посадить культуру на клетках (требует трактор)
  POST /harvest        — собрать урожай на клетках (требует комбайн)
  POST /fuel/buy       — купить топливо (литры за деньги)
  POST /sell-storage   — продать культуру со склада (запас на будущее)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from auth import get_current_user
from bson import ObjectId
from database import get_db
from pymongo import ReturnDocument
from econ import get_econ
from ledger import CAT_FARM, CAT_SHOP, EXPENSE, INCOME, adjust_balance, record_transaction
from resources import RESOURCES_BY_ID
from timeutil import now_utc

router = APIRouter(prefix="/api/farm", tags=["farm"])

# ── Константы, продублированные из game_config для быстрого доступа ───────────


def _cfg():
    from game_config import FARM_CONFIG
    return FARM_CONFIG


def _now() -> datetime:
    return now_utc()


def _as_aware_utc(value) -> datetime | None:
    """Нормализует datetime из Mongo (naive-UTC) к aware-UTC.

    Mongo отдаёт datetime без tzinfo, а now_utc() возвращает aware — прямое
    сравнение падает с TypeError. Если value None или не datetime — вернём
    None и пусть вызывающий код обработает это как «нет даты».
    """
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ── Helpers: поле / клетки / машина ──────────────────────────────────────────


async def _get_or_create_field(db, user_id: str, asset_id: str) -> dict:
    """Возвращает документ user_fields для (user_id, asset_id).

    Перед созданием проверяет, что актив «Поле» существует и принадлежит
    игроку. Клетки — плоский список; index = y*side + x.
    """
    cfg = _cfg()
    side = int(cfg["cells_per_side"])
    cell_count = side * side
    if not ObjectId.is_valid(asset_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID поля")
    # Владелец поля — только владелец актива «Поле»: без него фриминт клеток
    # невозможен, а после продажи актива на p2p-рынке работа с полем закрыта.
    asset = await db.user_assets.find_one({
        "_id": ObjectId(asset_id), "userId": user_id,
        "type": "source", "category": "field",
    })
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Поле (актив) не найдено")
    doc = await db.user_fields.find_one({"userId": user_id, "assetId": asset_id})
    if doc:
        return doc
    cells = [{"x": i % side, "y": i // side, "status": "empty", "crop": None, "planted_at": None, "ready_at": None}
             for i in range(cell_count)]
    doc = {
        "userId": user_id, "assetId": asset_id,
        "side": side, "cells": cells, "storage": {},
        "created_at": _now(),
    }
    await db.user_fields.insert_one(doc)
    return doc


async def _vehicle_for_job(db, user_id: str, kind: str) -> Optional[dict]:
    """Ищет свободную машину нужного вида (kind='combine'|'tractor').

    vehicleId = slug машины (см. farmsCatalog.js: 'combine_basic' и т.д.).
    Занятость — busy_until > now. Возвращает первый подходящий экземпляр.
    """
    now = _now()
    # Любой экземпляр user_hardware, у которого vehicleId начинается с kind.
    prefix = f"{kind}_"
    async for h in db.user_hardware.find(
        {"userId": user_id, "itemId": {"$regex": f"^{prefix}"}}
    ):
        busy_until = _as_aware_utc(h.get("busy_until"))
        if not busy_until or busy_until <= now:
            return h
    return None


def _job_duration_minutes(vehicle_id: str, kind: str, area_sqm: int) -> float:
    """Длительность работы машины на area_sqm м². Использует скорость из FARM_CONFIG."""
    cfg = _cfg()
    speed_key = f"{kind}_{vehicle_id.split('_', 1)[-1]}" if "_" in vehicle_id else f"{kind}_basic"
    speed = float(cfg["work_speed_sqm_per_min"].get(speed_key, 5.0))
    if speed <= 0:
        return 0.0
    return float(area_sqm) / speed


def _job_fuel_cost(vehicle_id: str, kind: str, area_sqm: int) -> float:
    """Расход топлива (л) для работы машины на area_sqm м²."""
    cfg = _cfg()
    speed_key = f"{kind}_{vehicle_id.split('_', 1)[-1]}" if "_" in vehicle_id else f"{kind}_basic"
    rate = float(cfg["fuel_per_sqm"].get(speed_key, 1.0))
    return float(area_sqm) * rate


def _growth_hours(crop_id: str) -> float:
    """Время роста культуры (реальных часов)."""
    cfg = _cfg()
    return float(cfg["crops"][crop_id]["growth_hours"])


def _volume_per_cell(crop_id: str) -> float:
    """Урожай с м² (кг) — для добавления в склад поля."""
    cfg = _cfg()
    return float(cfg["crops"][crop_id]["volume_per_cell"])


def _storage_cap() -> int:
    cfg = _cfg()
    return int(cfg["storage_slots_per_resource"])


def _crop_unit_price(crop_id: str, econ: dict) -> float:
    """Базовая цена за кг культуры для UI/превью продаж. Берём base_price из
    RESOURCES_BY_ID и нормализуем на кг (тут unit уже кг для всех культур)."""
    rec = RESOURCES_BY_ID.get(crop_id)
    if not rec:
        return 0.0
    return float(rec["base_price"]) * float(econ.get("economy_mult", 1.0))


# ── Pydantic schemas ─────────────────────────────────────────────────────────


class PlantRequest(BaseModel):
    assetId: str
    cropId: str
    # Клетки задаются как список индексов или как список [x,y]. Если пусто —
    # всё доступное (все 'empty') за один прогон.
    cellIndices: list[int] = Field(default_factory=list)


class HarvestRequest(BaseModel):
    assetId: str
    # Клетки, с которых собирать. Пустой список = собрать всё готовое.
    cellIndices: list[int] = Field(default_factory=list)


class BuyCellsRequest(BaseModel):
    assetId: str
    # Сколько блоков клеток купить. 1 блок = FARM_CONFIG.cells_buy.step клеток.
    blocks: int = 1


class BuyFuelRequest(BaseModel):
    liters: int = Field(ge=1, le=100000)


class SellStorageRequest(BaseModel):
    assetId: str
    cropId: str
    qty: float = Field(gt=0)


# ── Catalog endpoints ────────────────────────────────────────────────────────


@router.get("/catalog")
async def get_catalog(
    _user=Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Справочник культур и характеристик фермы (топливо, цены на клетки, потолок склада)."""
    cfg = _cfg()
    econ = await get_econ(db)
    crops = []
    for crop_id, spec in cfg["crops"].items():
        rec = RESOURCES_BY_ID.get(crop_id) or {}
        crops.append({
            "id": crop_id,
            "name": rec.get("name", crop_id),
            "description": rec.get("description", ""),
            "category": rec.get("category"),
            "unit": spec.get("unit") or rec.get("unit", "кг"),
            "growthHours": spec["growth_hours"],
            "volumePerCell": spec["volume_per_cell"],
            "basePricePerKg": round(_crop_unit_price(crop_id, econ), 2),
        })
    cells_buy = cfg["cells_buy"]
    return {
        "crops": crops,
        "cells": {
            "perSide": cfg["cells_per_side"],
            "startTotal": cfg["cells_per_side"] ** 2,
            "buyBase": cells_buy["base_cost"],
            "buyScale": cells_buy["cost_scale"],
            "buyStep": cells_buy["step"],
            "maxBlocks": cells_buy["max_blocks"],
        },
        "storage": {
            "perResource": cfg["storage_slots_per_resource"],
            "unit": cfg["storage_unit"],
        },
        "fuel": {
            "pricePerLiter": cfg["fuel_price_per_liter"],
            "bundleSize": cfg["fuel_bundle_size"],
            "max": cfg["fuel_max_per_user"],
        },
    }


# ── Get my state ─────────────────────────────────────────────────────────────


@router.get("/my")
async def get_my_farm(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Сводка фермы: поле (клетки + склад), машина, топливо, культуры."""
    user_id = str(current_user["_id"])
    cfg = _cfg()
    now = _now()

    # Автосоздание полей для купленных источников категории 'field'.
    # Покупка актива создаёт запись в user_assets; документ user_fields
    # (сетка клеток + склад) создаётся лениво здесь при первом обращении.
    owned_assets = await db.user_assets.find(
        {"userId": user_id, "type": "source", "category": "field"}
    ).to_list(length=100)
    existing = set()
    async for f in db.user_fields.find({"userId": user_id}):
        existing.add(str(f["assetId"]))
    for a in owned_assets:
        aid = str(a["_id"])
        if aid not in existing:
            await _get_or_create_field(db, user_id, aid)

    # Все поля игрока.
    fields = []
    async for f in db.user_fields.find({"userId": user_id}):
        fields.append(_serialize_field(f, cfg))

    # Машины фермы: все экземпляры user_hardware с itemId вида "combine_*" или "tractor_*".
    machines = []
    async for h in db.user_hardware.find(
        {"userId": user_id, "itemId": {"$regex": "^(combine|tractor)_"}}
    ):
        busy_until = _as_aware_utc(h.get("busy_until"))
        if busy_until and busy_until > now:
            remaining_min = round((busy_until - now).total_seconds() / 60.0, 1)
        else:
            remaining_min = 0.0
        machines.append({
            "id": str(h["_id"]), "itemId": h.get("itemId"),
            "name": h.get("name"), "busy": remaining_min > 0,
            "remainingMinutes": remaining_min,
        })

    # Топливо из users.fuel.
    user_doc = await db.users.find_one({"_id": current_user["_id"]})
    fuel = float((user_doc or {}).get("fuel", 0.0) or 0.0)

    return {"fields": fields, "machines": machines, "fuel": round(fuel, 2)}


def _serialize_field(f: dict, cfg: dict) -> dict:
    side = int(f.get("side") or cfg["cells_per_side"])
    cells = f.get("cells") or []
    ready_count = 0
    growing_count = 0
    empty_count = 0
    for c in cells:
        st = c.get("status", "empty")
        if st == "ready": ready_count += 1
        elif st == "growing": growing_count += 1
        else: empty_count += 1
    # Полные данные клеток для рендера сетки на фронте.
    cells_out = []
    for c in cells:
        ready_at = c.get("ready_at")
        planted_at = c.get("planted_at")
        cells_out.append({
            "x": c.get("x"), "y": c.get("y"),
            "status": c.get("status", "empty"),
            "crop": c.get("crop"),
            "readyAt": ready_at.isoformat() if isinstance(ready_at, datetime) else None,
            "plantedAt": planted_at.isoformat() if isinstance(planted_at, datetime) else None,
        })
    return {
        "assetId": f.get("assetId"),
        "side": side,
        "totalCells": len(cells),
        "empty": empty_count, "growing": growing_count, "ready": ready_count,
        "storage": f.get("storage") or {},
        "cells": cells_out,
    }


# ── Actions ──────────────────────────────────────────────────────────────────


@router.post("/cells/buy")
async def buy_cells(
    payload: BuyCellsRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Купить блок клеток на конкретном поле. Цена растёт экспоненциально."""
    cfg = _cfg()
    cb = cfg["cells_buy"]
    user_id = str(current_user["_id"])

    blocks = max(1, min(int(payload.blocks), int(cb["max_blocks"])))
    doc = await _get_or_create_field(db, user_id, payload.assetId)
    # Цена — сумма экспоненциальной кривой: каждый следующий блок дороже
    # предыдущего (base * scale^k), а не «цена последнего блока × количество».
    already_bought = max(0, len(doc["cells"]) - cfg["cells_per_side"] ** 2)
    step = int(cb["step"])
    total_cost = 0.0
    for i in range(blocks):
        total_cost += cb["base_cost"] * (cb["cost_scale"] ** ((already_bought + i) / step))
    total_cost = round(total_cost, 2)

    new_balance = await adjust_balance(db, user_id, -total_cost)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

    # Новые клетки добавляем за пределы текущей сетки (append в конец).
    side = int(doc["side"])
    new_cells = []
    for i in range(blocks * step):
        idx = len(doc["cells"]) + i
        # Координаты — расширяем сетку вправо от текущего края.
        col = idx % side
        row = idx // side
        new_cells.append({
            "x": col + side,  # сдвиг — новые клетки всегда справа от стартовой сетки
            "y": row, "status": "empty", "crop": None,
            "planted_at": None, "ready_at": None,
        })
    doc["cells"].extend(new_cells)
    await db.user_fields.replace_one({"_id": doc["_id"]}, doc)

    await record_transaction(
        db, user_id, EXPENSE, total_cost, CAT_SHOP,
        f"Покупка участков поля ×{blocks}",
        balance_after=new_balance,
        meta={"assetId": payload.assetId, "blocks": blocks, "cells": blocks * step},
    )
    return {
        "ok": True, "blocks": blocks, "cells": blocks * step,
        "total": total_cost, "balance": new_balance,
        "totalCells": len(doc["cells"]),
    }


@router.post("/plant")
async def plant(
    payload: PlantRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Посадить культуру на клетках. Требует свободный трактор и топливо."""
    cfg = _cfg()
    user_id = str(current_user["_id"])

    if payload.cropId not in cfg["crops"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестная культура")

    field = await _get_or_create_field(db, user_id, payload.assetId)
    if not field or len(field.get("cells", [])) == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Поле не найдено")

    cells = field["cells"]
    # Выбираем клетки: либо явные индексы, либо все пустые.
    if payload.cellIndices:
        targets = []
        for idx in payload.cellIndices:
            if idx < 0 or idx >= len(cells):
                continue
            if cells[idx].get("status") != "empty":
                continue
            targets.append(idx)
    else:
        targets = [i for i, c in enumerate(cells) if c.get("status") == "empty"]
    if not targets:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет свободных клеток для посадки")

    # Трактор.
    tractor = await _vehicle_for_job(db, user_id, "tractor")
    if not tractor:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нужен свободный трактор")

    area = len(targets)
    duration_min = _job_duration_minutes(tractor["itemId"], "tractor", area)
    fuel_cost = _job_fuel_cost(tractor["itemId"], "tractor", area)

    # Топливо.
    user_doc = await db.users.find_one({"_id": current_user["_id"]})
    current_fuel = float((user_doc or {}).get("fuel", 0.0) or 0.0)
    if current_fuel < fuel_cost:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Недостаточно топлива: нужно {fuel_cost:.1f} л, есть {current_fuel:.1f} л",
        )
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$inc": {"fuel": -fuel_cost}},
    )

    # Маркируем клетки как 'growing', ставим crop и planted_at.
    growth_hours = _growth_hours(payload.cropId)
    planted_at = _now()
    ready_at = planted_at + timedelta(hours=growth_hours)
    field["cells"] = cells
    for idx in targets:
        cells[idx]["status"] = "growing"
        cells[idx]["crop"] = payload.cropId
        cells[idx]["planted_at"] = planted_at
        cells[idx]["ready_at"] = ready_at
    await db.user_fields.replace_one({"_id": field["_id"]}, field)

    # Трактор занят до конца операции.
    busy_until = _now() + timedelta(minutes=duration_min)
    await db.user_hardware.update_one(
        {"_id": tractor["_id"]},
        {"$set": {"busy_until": busy_until, "busy_action": "plant"}},
    )

    return {
        "ok": True, "cells": len(targets), "crop": payload.cropId,
        "durationMinutes": round(duration_min, 2),
        "fuelUsed": round(fuel_cost, 2),
        "remainingMinutes": round(duration_min, 2),
    }


@router.post("/harvest")
async def harvest(
    payload: HarvestRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Собрать готовый урожай с клеток. Требует свободного комбайна и топлива."""
    cfg = _cfg()
    user_id = str(current_user["_id"])

    field = await db.user_fields.find_one({"userId": user_id, "assetId": payload.assetId})
    if not field or not field.get("cells"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Поле не найдено")

    now = _now()
    cells = field["cells"]

    # Только 'ready' клетки. Если ready_at прошёл, но status ещё 'growing' — обновляем.
    ready_indices: list[int] = []
    for idx, c in enumerate(cells):
        if c.get("status") == "growing":
            ready_at = _as_aware_utc(c.get("ready_at"))
            if ready_at and ready_at <= now:
                c["status"] = "ready"
        if c.get("status") == "ready":
            if not payload.cellIndices or idx in payload.cellIndices:
                ready_indices.append(idx)
    if not ready_indices:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет готового урожая")

    combine = await _vehicle_for_job(db, user_id, "combine")
    if not combine:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нужен свободный комбайн")

    area = len(ready_indices)
    duration_min = _job_duration_minutes(combine["itemId"], "combine", area)
    fuel_cost = _job_fuel_cost(combine["itemId"], "combine", area)

    user_doc = await db.users.find_one({"_id": current_user["_id"]})
    current_fuel = float((user_doc or {}).get("fuel", 0.0) or 0.0)
    if current_fuel < fuel_cost:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Недостаточно топлива: нужно {fuel_cost:.1f} л, есть {current_fuel:.1f} л",
        )

    # Пересчитываем склад и очищаем клетки. Группируем по культуре.
    storage = field.setdefault("storage", {})
    total_by_crop: dict[str, float] = {}
    for idx in ready_indices:
        c = cells[idx]
        crop = c.get("crop")
        if not crop or crop not in cfg["crops"]:
            c["status"] = "empty"; c["crop"] = None; c["planted_at"] = None; c["ready_at"] = None
            continue
        volume = _volume_per_cell(crop)
        cap = _storage_cap()
        current = float(storage.get(crop, 0.0) or 0.0)
        if current + volume > cap:
            # Пропуск: склад полон для этой культуры. Возвращаем клетку.
            continue
        storage[crop] = round(current + volume, 2)
        total_by_crop[crop] = total_by_crop.get(crop, 0.0) + volume
        c["status"] = "empty"; c["crop"] = None; c["planted_at"] = None; c["ready_at"] = None

    if not total_by_crop:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Склад поля полон для собираемой культуры — освободите место",
        )

    # Топливо списываем только после того, как убедились, что есть что собирать:
    # при «склад полон» endpoint раньше сжигал топливо с пустым результатом.
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$inc": {"fuel": -fuel_cost}},
    )

    field["cells"] = cells
    field["storage"] = storage
    await db.user_fields.replace_one({"_id": field["_id"]}, field)

    # Комбайн занят до конца.
    busy_until = _now() + timedelta(minutes=duration_min)
    await db.user_hardware.update_one(
        {"_id": combine["_id"]},
        {"$set": {"busy_until": busy_until, "busy_action": "harvest"}},
    )

    return {
        "ok": True,
        "cells": len(ready_indices),
        "totalByCrop": {k: round(v, 2) for k, v in total_by_crop.items()},
        "durationMinutes": round(duration_min, 2),
        "fuelUsed": round(fuel_cost, 2),
        "storage": storage,
    }


@router.post("/fuel/buy")
async def buy_fuel(
    payload: BuyFuelRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Купить топливо за деньги. Литры округляются вверх до ближайшего бандла."""
    cfg = _cfg()
    user_id = str(current_user["_id"])
    bundle = int(cfg["fuel_bundle_size"])
    liters = max(bundle, ((payload.liters + bundle - 1) // bundle) * bundle)
    liters = min(liters, int(cfg["fuel_max_per_user"]))
    price = round(liters * float(cfg["fuel_price_per_liter"]), 2)

    new_balance = await adjust_balance(db, user_id, -price)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

    cur = await db.users.find_one({"_id": current_user["_id"]})
    new_fuel = float((cur or {}).get("fuel", 0.0) or 0.0) + liters
    if new_fuel > cfg["fuel_max_per_user"]:
        new_fuel = float(cfg["fuel_max_per_user"])

    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"fuel": new_fuel}},
    )
    await record_transaction(
        db, user_id, EXPENSE, price, "fuel",
        f"Покупка топлива: {int(liters)} л",
        balance_after=new_balance, meta={"liters": liters},
    )
    return {"ok": True, "liters": liters, "total": price, "balance": new_balance, "fuel": new_fuel}


@router.post("/sell-storage")
async def sell_storage(
    payload: SellStorageRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Продать культуру со склада поля. Берём базовую цену за кг из RESOURCES.

    Атомарно: списание со склада — условный find_one_and_update ($inc при
    storage.crop >= qty), выплата после фактического списания.
    """
    user_id = str(current_user["_id"])
    if payload.cropId not in _cfg()["crops"]:
        crop_keys = ", ".join(_cfg()["crops"].keys())
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Неизвестная культура (доступно: {crop_keys})")
    field = await db.user_fields.find_one({"userId": user_id, "assetId": payload.assetId})
    if not field:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Поле не найдено")

    qty = float(payload.qty)
    if qty <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет этой культуры на складе")

    econ = await get_econ(db)
    unit_price = _crop_unit_price(payload.cropId, econ)
    total = round(qty * unit_price, 2)

    # Атомарное списание: условие «на складе не меньше qty» проверяется в БД,
    # поэтому двойной клик / гонка не продаст урожай дважды.
    updated = await db.user_fields.find_one_and_update(
        {
            "_id": field["_id"],
            "$expr": {"$gte": [{"$ifNull": [f"$storage.{payload.cropId}", 0]}, qty]},
        },
        {"$inc": {f"storage.{payload.cropId}" : -qty}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет этой культуры на складе")
    storage = updated.get("storage") or {}
    if float(storage.get(payload.cropId, 0.0) or 0.0) <= 0.001:
        await db.user_fields.update_one(
            {"_id": field["_id"]},
            {"$unset": {f"storage.{payload.cropId}": ""}},
        )
        storage.pop(payload.cropId, None)

    new_balance = await adjust_balance(db, user_id, total)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ошибка изменения баланса")

    await record_transaction(
        db, user_id, INCOME, total, "farm",
        f"Продажа культуры: {payload.cropId} × {qty}",
        balance_after=new_balance,
        meta={"crop": payload.cropId, "qty": qty, "unitPrice": unit_price},
    )
    return {"ok": True, "qty": qty, "unitPrice": unit_price, "total": total, "balance": new_balance, "storage": storage}


# ── Машины: витрина и покупка ───────────────────────────────────────────────
#
# Фермерские машины НЕ попадают в обычный каталог shop.py (там железо для майнинга).
# Они — отдельный каталог, который покупается на вкладке «Автосалон» (CarsTab) и
# попадает в user_hardware с itemId вида "combine_basic" / "tractor_pro".
#
# Расход топлива и скорость работы берём из FARM_CONFIG.fuel_per_sqm /
# work_speed_sqm_per_min по ключу "<kind>_<tier>" (см. _job_duration_minutes).

FARM_VEHICLES: list[dict] = [
    {
        "id": "combine_basic",
        "slug": "combine_basic",
        "kind": "combine",
        "tier": "basic",
        "name": "Комбайн «Собиратель»",
        "rarity": "common",
        "emoji": "🌾",
        "color": "#84cc16",
        "price": 85000,
        "specs": {
            "fuelPerSqm": 1.0,
            "speedSqmPerMin": 5.0,
            "description": "Базовый комбайн. За 1 л топлива собирает 1 м² урожая за 12 секунд.",
        },
    },
    {
        "id": "combine_pro",
        "slug": "combine_pro",
        "kind": "combine",
        "tier": "pro",
        "name": "Комбайн «Гигахэви»",
        "rarity": "rare",
        "emoji": "🌾",
        "color": "#eab308",
        "price": 220000,
        "specs": {
            "fuelPerSqm": 0.7,
            "speedSqmPerMin": 10.0,
            "description": "Премиум-комбайн. Вдвое быстрее и экономнее базового.",
        },
    },
    {
        "id": "tractor_basic",
        "slug": "tractor_basic",
        "kind": "tractor",
        "tier": "basic",
        "name": "Трактор «Сеятель»",
        "rarity": "common",
        "emoji": "🚜",
        "color": "#f59e0b",
        "price": 60000,
        "specs": {
            "fuelPerSqm": 0.5,
            "speedSqmPerMin": 4.0,
            "description": "Трактор с насадкой для засадки. Медленный, но экономит топливо.",
        },
    },
    {
        "id": "tractor_pro",
        "slug": "tractor_pro",
        "kind": "tractor",
        "tier": "pro",
        "name": "Трактор «Стройбоб»",
        "rarity": "rare",
        "emoji": "🚜",
        "color": "#ea580c",
        "price": 180000,
        "specs": {
            "fuelPerSqm": 0.35,
            "speedSqmPerMin": 8.0,
            "description": "Премиум-трактор. Дуальная насадка, вдвое быстрее базового.",
        },
    },
]

FARM_VEHICLES_BY_ID: dict[str, dict] = {v["id"]: v for v in FARM_VEHICLES}


class BuyVehicleRequest(BaseModel):
    vehicleId: str
    quantity: int = Field(default=1, ge=1, le=10)


@router.get("/vehicles")
async def get_vehicles(
    _user=Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Витрина фермерских машин (покупаются за деньги, попадают в user_hardware)."""
    econ = await get_econ(db)
    emult = float(econ.get("economy_mult", 1.0))
    owned: dict[str, int] = {}
    user_id = str(_user["_id"])
    async for h in db.user_hardware.find({"userId": user_id, "itemId": {"$in": list(FARM_VEHICLES_BY_ID.keys())}}):
        owned[h["itemId"]] = owned.get(h["itemId"], 0) + 1
    out = []
    for v in FARM_VEHICLES:
        row = dict(v)
        row["price"] = round(float(v["price"]) * emult, 2)
        row["owned"] = owned.get(v["id"], 0)
        out.append(row)
    return {"vehicles": out}


@router.post("/vehicles/buy", status_code=status.HTTP_201_CREATED)
async def buy_vehicle(
    payload: BuyVehicleRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Купить машину. Каждый экземпляр становится записью в user_hardware с itemId=slug."""
    v = FARM_VEHICLES_BY_ID.get(payload.vehicleId)
    if not v:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Машина не найдена")
    user_id = str(current_user["_id"])
    qty = max(1, min(int(payload.quantity), 10))
    econ = await get_econ(db)
    unit = round(float(v["price"]) * float(econ.get("economy_mult", 1.0)), 2)
    total = round(unit * qty, 2)

    new_balance = await adjust_balance(db, user_id, -total)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

    docs = [{
        "userId": user_id,
        "itemId": v["id"],
        "category": "vehicle",
        "name": v["name"],
        "vehicleKind": v["kind"],
        "vehicleTier": v["tier"],
        "specs": dict(v["specs"]),
        "purchase_price": unit,
        "condition": 100,
        "purchased_at": _now(),
        "busy_until": None,
        "busy_action": None,
    } for _ in range(qty)]
    await db.user_hardware.insert_many(docs)

    await record_transaction(
        db, user_id, EXPENSE, total, CAT_FARM,
        f"Покупка машины: {v['name']}" + (f" ×{qty}" if qty > 1 else ""),
        balance_after=new_balance, meta={"vehicleId": v["id"], "quantity": qty},
    )
    return {"ok": True, "unitPrice": unit, "total": total, "balance": new_balance, "quantity": qty}


# ── Self-check ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from resources import RESOURCES_BY_ID
    cfg = _cfg()
    assert set(cfg["crops"].keys()) == {"wheat", "carrot", "potato", "sunflower"}
    for cid in cfg["crops"]:
        assert cid in RESOURCES_BY_ID, cid
        assert float(cfg["crops"][cid]["growth_hours"]) > 0
        assert float(cfg["crops"][cid]["volume_per_cell"]) > 0

    assert cfg["fuel_price_per_liter"] > 0
    assert cfg["cells_per_side"] > 0
    assert cfg["cells_buy"]["base_cost"] > 0
    assert 1.0 < cfg["cells_buy"]["cost_scale"] < 2.0

    # Клетки: 50×50 = 2500.
    assert cfg["cells_per_side"] ** 2 == 2500

    # Тест формулы стоимости блока при разных bought.
    cb = cfg["cells_buy"]
    def _cost(already):
        return cb["base_cost"] * (cb["cost_scale"] ** (already / cb["step"]))
    assert abs(_cost(0) - 10000.0) < 0.001
    assert _cost(100) > 10000.0

    # Тест времени работы: 2500 м² базовым комбайном (5 м²/мин) = 500 мин.
    assert _job_duration_minutes("combine_basic", "combine", 2500) == 500.0
    # Топливо: 2500 м² × 1 л/м² = 2500 л.
    assert _job_fuel_cost("combine_basic", "combine", 2500) == 2500.0

    print("farm self-check OK")
