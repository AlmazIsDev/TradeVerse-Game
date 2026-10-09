"""Производство: источники → фуры → склады/пекарня → склад.

Цепочка поставок:
  * источник (шахта/лесопилка) добывает ресурс в СВОЁ хранилище
    (ёмкость = meta.capacity × уровень, уровень качается апгрейдом актива);
  * поле добывает урожай фермерской механикой (farm.py), фуры возят урожай
    с поля на склад или в пекарню;
  * фуры (авто category=truck) назначаются на источник: до 5 на выход; у
    пекарни два потока — вход (пшеница) и выход (хлеб), до 5 фур в каждом;
  * склад принимает ресурсы, меню управления показывает все ресурсы и
    позволяет продать их в деньги;
  * пекарня (factory, meta.produces='bread'): 2 кг пшеницы → 1 кг хлеба.

Модель данных:
  user_assets.prod = {
      workers: int,            # 0..50
      food: float,             # кг хлеба (еда работников) на источнике
      storage: {res_id: qty},  # запас ресурса в хранилище источника/пекарни
      storageLevel: int,       # 1..10
      destinationId: str|None, # куда возим (склад или пекарня)
      inputId: str|None,       # откуда пекарне возят пшеницу
      trucks: {input: [assetId], output: [assetId]},
      ticked_at: datetime,     # последний производственный тик
  }
  user_assets.storage = {res_id: qty}   # склад: запас ресурсов (кг)
  car.hauling = {until, cargo, toId, fromId}  # активный рейс фуры

Деньги — только через ledger. Цены ресурсов — RESOURCES_BY_ID base_price ×
economy_mult.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field, field_validator

from admin_perms import get_current_user, require_allowed
from database import get_db
from ledger import INCOME, EXPENSE, CAT_SOURCE, CAT_FACTORY, CAT_WAREHOUSE, adjust_balance, record_transaction
from resources import RESOURCES_BY_ID
from econ import get_econ
from timeutil import now_utc

router = APIRouter(prefix="/api/production", tags=["production"])


def _cfg() -> dict:
    from game_config import PRODUCTION_CONFIG
    return PRODUCTION_CONFIG


def _now() -> datetime:
    return now_utc()


def _aware(dt) -> Optional[datetime]:
    if not isinstance(dt, datetime):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# ── Типы производственных юнитов ──────────────────────────────────────────────


def _is_bakery(asset: dict) -> bool:
    """Пекарня — завод с meta.produces='bread' (см. assets._ADMIN_MARKET_FACTORIES)."""
    return asset.get("type") == "factory" and (asset.get("meta") or {}).get("produces") == "bread"


def _is_source(asset: dict) -> bool:
    return asset.get("type") == "source"


def _is_warehouse(asset: dict) -> bool:
    return asset.get("type") == "warehouse"


def _resource_ok(res: str) -> bool:
    return str(res or "") in RESOURCES_BY_ID


def _prod_state(asset: dict) -> dict:
    """Состояние prod актива с дефолтами (копия, БД не мутирует)."""
    p = dict(asset.get("prod") or {})
    p.setdefault("workers", 0)
    p.setdefault("food", 0.0)
    p.setdefault("storage", {})
    p.setdefault("storageLevel", 1)
    p.setdefault("destinationId", None)
    p.setdefault("inputId", None)
    t = p.get("trucks") or {}
    p["trucks"] = {
        "input": [str(x) for x in (t.get("input") or [])][: _cfg()["max_trucks"]],
        "output": [str(x) for x in (t.get("output") or [])][: _cfg()["max_trucks"]],
    }
    return p


# ── Ёмкости и эффективность ───────────────────────────────────────────────────


def _storage_cap(asset: dict) -> float:
    """Ёмкость хранилища юнита (кг) = meta.capacity × уровень (1..10).

    У поля capacity не используется: урожай копится в складе поля (farm.py),
    который качается той же prod.storageLevel (см. farm.py _storage_cap)."""
    meta = asset.get("meta") or {}
    cap = float(meta.get("capacity") or 0)
    if cap <= 0:
        return 0.0
    level = max(1, int((asset.get("prod") or {}).get("storageLevel", 1)))
    return cap * level


def _warehouse_cap(asset: dict) -> float:
    meta = asset.get("meta") or {}
    return float(meta.get("storageCap") or 0)


def _workers_factor(workers: int, asset: dict) -> float:
    """Эффективность штата: 0 работников → производство стоит; далее линейно
    от штатного состава (meta.employees) до потолка ×2."""
    if workers <= 0:
        return 0.0
    base = int(asset.get("employees") or asset.get("meta", {}).get("employees") or 1)
    return min(float(_cfg()["workers_factor_cap"]), workers / max(1, base))


def _food_factor(food: float, need: float) -> float:
    """Еда: полная порция → ×1.0, иначе голодный ×0.6."""
    if need <= 0:
        return _cfg()["fed_factor"]
    return _cfg()["fed_factor"] if food >= need else _cfg()["hungry_factor"]


def _efficiency(asset: dict, prod: dict, elapsed_h: float) -> tuple[float, float]:
    """(эффективность, потреблённая еда) за elapsed_h часов."""
    wf = _workers_factor(int(prod.get("workers", 0)), asset)
    need = int(prod.get("workers", 0)) * float(_cfg()["food_per_worker_per_h"]) * elapsed_h
    ff = _food_factor(float(prod.get("food", 0.0)), need)
    return wf * ff, need


# ── Сериализация ──────────────────────────────────────────────────────────────


def _serialize_unit(asset: dict, prod: dict) -> dict:
    """Юнит производства (источник/пекарня) для /overview."""
    is_bakery = _is_bakery(asset)
    meta = asset.get("meta") or {}
    out = {
        "id": str(asset["_id"]),
        "slug": asset.get("slug"),
        "type": asset.get("type"),
        "category": asset.get("category"),
        "name": asset.get("name"),
        "level": asset.get("level", 1),
        "storageLevel": int(prod.get("storageLevel", 1)),
        "workers": int(prod.get("workers", 0)),
        "employees": int(asset.get("employees") or meta.get("employees") or 0),
        "maxWorkers": int(_cfg()["max_workers"]),
        "food": round(float(prod.get("food", 0.0)), 2),
        "foodDemandPerH": round(int(prod.get("workers", 0)) * float(_cfg()["food_per_worker_per_h"]), 2),
        "storage": {k: round(float(v), 2) for k, v in (prod.get("storage") or {}).items()},
        "storageCap": _storage_cap(asset),
        "storageUpgradeCost": _storage_upgrade_cost(asset),
        "destinationId": prod.get("destinationId"),
        "inputId": prod.get("inputId"),
        "trucks": prod.get("trucks"),
        "outputPerHour": int(meta.get("outputPerHour") or 0),
        "isBakery": is_bakery,
    }
    if is_bakery:
        out["consumesPerHour"] = int(meta.get("consumesPerHour") or 0)
        out["inputResource"] = meta.get("input")
        out["outputResource"] = meta.get("produces")
    else:
        out["resource"] = meta.get("resource")
    return out


def _serialize_warehouse(asset: dict) -> dict:
    storage = asset.get("storage") or {}
    cap = _warehouse_cap(asset)
    used = sum(float(v) for v in storage.values())
    return {
        "id": str(asset["_id"]),
        "name": asset.get("name"),
        "slug": asset.get("slug"),
        "storage": {k: round(float(v), 2) for k, v in storage.items()},
        "cap": cap,
        "used": round(used, 2),
        "free": round(max(0.0, cap - used), 2),
    }


def _serialize_truck(asset: dict) -> dict:
    hauling = asset.get("hauling")
    until = _aware((hauling or {}).get("until"))
    return {
        "id": str(asset["_id"]),
        "name": asset.get("name"),
        "slug": asset.get("slug"),
        "cargoKg": int((asset.get("meta") or {}).get("cargoKg") or 0),
        "hauling": {
            "until": until.isoformat() if until else None,
            "cargo": (hauling or {}).get("cargo") or {},
            "toId": (hauling or {}).get("toId"),
            "fromId": (hauling or {}).get("fromId"),
        },
    }


# ── Цены и суммы ──────────────────────────────────────────────────────────────


def _resource_price(res: str, econ: dict) -> float:
    """Цена продажи 1 ед. ресурса (base_price × economy_mult)."""
    rec = RESOURCES_BY_ID.get(str(res or ""))
    if not rec:
        return 0.0
    return round(float(rec["base_price"]) * float(econ.get("economy_mult", 1.0)), 2)


def _food_unit_price(econ: dict) -> float:
    """Цена закупки 1 кг хлеба для работников (base_price × economy_mult)."""
    return _resource_price("bread", econ)


def _storage_upgrade_cost(asset: dict) -> float:
    """Цена следующего уровня хранилища = base_price × 10% × новый уровень."""
    level = max(1, int((asset.get("prod") or {}).get("storageLevel", 1)))
    pct = float(_cfg()["storage_cost_pct"])
    return round(float(asset.get("price", 0)) * pct * (level + 1), 2)


# ── Хранилище: списание/зачисление с потолком ─────────────────────────────────


def _store_add(store: dict, cap: float, res: str, qty: float) -> float:
    """Зачисляет qty ресурса в store, не превышая cap (суммарно). Возвращает
    фактически принятое количество. Мутирует store."""
    if cap <= 0 or qty <= 0:
        return 0.0
    used = sum(float(v) for v in store.values())
    free = max(0.0, cap - used)
    take = min(qty, free)
    if take > 0:
        store[res] = round(float(store.get(res, 0.0)) + take, 2)
    return take


def _store_take(store: dict, res: str, qty: float) -> float:
    """Списывает до qty ресурса из store. Возвращает фактически списанное."""
    have = float(store.get(res, 0.0))
    take = min(qty, have)
    if take > 0:
        store[res] = round(have - take, 2)
        if store[res] <= 0.001:
            store.pop(res, None)
    return take


# ── Тик производства ──────────────────────────────────────────────────────────


async def _tick_arrivals(db, now: datetime) -> None:
    """Прибытие фур: разгрузка в склад-получатель (с потолком вместимости).
    Груз, не поместившийся, остаётся на фуре до следующего прибытия."""
    async for truck in db.user_assets.find({"type": "car", "category": "truck", "hauling": {"$ne": None}}):
        h = truck.get("hauling") or {}
        until = _aware(h.get("until"))
        if not until or until > now:
            continue
        cargo = h.get("cargo") or {}
        dest_id = h.get("toId")
        dest = None
        if dest_id and ObjectId.is_valid(dest_id):
            dest = await db.user_assets.find_one(
                {"_id": ObjectId(dest_id), "userId": truck["userId"]},
                {"prod.storage": 1, "storage": 1, "meta.capacity": 1, "meta.storageCap": 1},
            )
        if not dest:
            # Получатель продан/передан — груз остаётся на фуре (сгорит при
            # следующей погрузке), рейс завершается.
            await db.user_assets.update_one({"_id": truck["_id"]}, {"$set": {"hauling": None}})
            continue
        if _is_warehouse(dest):
            cap = _warehouse_cap(dest)
            store = dict(dest.get("storage") or {})
        else:
            cap = _storage_cap(dest)
            store = dict((dest.get("prod") or {}).get("storage") or {})
        left = dict(cargo)
        for res, qty in list(left.items()):
            took = _store_add(store, cap, res, float(qty))
            left[res] = round(float(qty) - took, 2)
            if left[res] <= 0.001:
                del left[res]
        if _is_warehouse(dest):
            await db.user_assets.update_one({"_id": dest["_id"]}, {"$set": {"storage": store}})
        else:
            await db.user_assets.update_one({"_id": dest["_id"]}, {"$set": {"prod.storage": store}})
        # Груз, не поместившийся в получатель, остаётся на фуре до следующего
        # прибытия: hauling сохраняется с until=now (разгрузится следующим тиком).
        await db.user_assets.update_one(
            {"_id": truck["_id"]},
            {"$set": {"hauling": ({"until": now, "cargo": left, "toId": dest_id, "fromId": h.get("fromId")}
                                  if left else None)}},
        )


def _load_cargo(store: dict, cap_kg: float) -> dict:
    """Погрузка: берёт из store ресурсы под грузоподъёмность cap_kg (кг).
    Сначала самые большие стаки. Мутирует store, возвращает груз {res: qty}."""
    cargo: dict = {}
    room = float(cap_kg)
    for res, qty in sorted(store.items(), key=lambda kv: -float(kv[1])):
        if room <= 0:
            break
        take = min(room, float(qty))
        if take > 0:
            cargo[res] = round(take, 2)
            store[res] = round(float(qty) - take, 2)
            if store[res] <= 0.001:
                del store[res]
            room -= take
    return cargo


async def _truck_cargo_kg(db, truck: dict) -> float:
    """Грузоподъёмность фуры с учётом прицепленного прицепа (assets.py /hitch).
    Прицеп хранится на документе прицепа (hitchedTo -> _id фуры)."""
    base = float((truck.get("meta") or {}).get("cargoKg") or 0)
    tr = await db.user_assets.find_one(
        {"hitchedTo": truck["_id"], "userId": truck["userId"], "category": "trailer"},
        {"meta.cargoKg": 1},
    )
    return base + float(((tr or {}).get("meta") or {}).get("cargoKg") or 0)


def _trip(truck_id: str, unit_id: str, dest_id: str, cargo: dict, now: datetime) -> dict:
    return {"until": now + timedelta(minutes=float(_cfg()["trip_minutes"])),
            "cargo": cargo, "toId": dest_id, "fromId": unit_id}


async def _depart_output(db, unit: dict, p: dict, truck: dict, dest_id: str, now: datetime) -> None:
    """Отправить одну фуру с выхода юнита: погрузка → hauling."""
    truck_id = truck["id"]
    cargo_kg = await _truck_cargo_kg(db, truck)
    if unit.get("category") == "field":
        fdoc = await db.user_fields.find_one({"assetId": str(unit["_id"])})
        if not fdoc:
            return
        store = dict(fdoc.get("storage") or {})
        cargo = _load_cargo(store, cargo_kg)
        if cargo:
            await db.user_fields.update_one({"_id": fdoc["_id"]}, {"$set": {"storage": store}})
    else:
        fresh = await db.user_assets.find_one({"_id": unit["_id"]}, {"prod.storage": 1})
        store = dict(((fresh or {}).get("prod") or {}).get("storage") or {})
        cargo = _load_cargo(store, cargo_kg)
        if cargo:
            await db.user_assets.update_one(
                {"_id": unit["_id"]},
                {"$set": {f"prod.storage.{r}": q for r, q in store.items()}},
            )
    if cargo:
        await db.user_assets.update_one(
            {"_id": ObjectId(truck_id)},
            {"$set": {"hauling": _trip(truck_id, str(unit["_id"]), dest_id, cargo, now)}},
        )


async def _depart_input(db, unit: dict, truck: dict, input_id: str, now: datetime) -> None:
    """Отправить одну фуру за пшеницей для пекарни (с поля или со склада)."""
    truck_id = truck["id"]
    src = await db.user_assets.find_one({"_id": ObjectId(input_id), "userId": unit["userId"]})
    fdoc = None
    if src and _is_warehouse(src):
        store = dict(src.get("storage") or {})
    elif src:  # поле: пшеница лежит в складе поля
        fdoc = await db.user_fields.find_one({"assetId": input_id})
        if not fdoc:
            return
        store = dict(fdoc.get("storage") or {})
    else:
        return
    cargo = _load_cargo(store, await _truck_cargo_kg(db, truck))
    # Пекарне нужна только пшеница: прочий груз возвращаем в источник.
    wheat = cargo.pop("wheat", 0.0)
    for res, qty in cargo.items():
        store[res] = round(float(store.get(res, 0.0)) + qty, 2)
    if wheat <= 0:
        return
    if fdoc:
        await db.user_fields.update_one({"_id": fdoc["_id"]}, {"$set": {"storage": store}})
    else:
        await db.user_assets.update_one({"_id": src["_id"]}, {"$set": {"storage": store}})
    await db.user_assets.update_one(
        {"_id": ObjectId(truck_id)},
        {"$set": {"hauling": _trip(truck_id, input_id, str(unit["_id"]), {"wheat": wheat}, now)}},
    )


async def _tick_departures(db, now: datetime) -> None:
    """Разослать свободные фуры: выход юнита (до 5 фур) и вход пекарни (до 5)."""
    units = [a async for a in db.user_assets.find({"$or": [
        {"type": "source"},
        {"type": "factory", "meta.produces": "bread"},
    ]})]
    for unit in units:
        p = _prod_state(unit)
        is_bakery = _is_bakery(unit)
        dest_id = p.get("destinationId")
        input_id = p.get("inputId") if is_bakery else None
        if not dest_id and not input_id:
            continue
        # Собираем нужные фуры лениво, по одному запросу на юнит.
        wanted = list(p["trucks"].get("output", [])) + list(p["trucks"].get("input", []))
        wanted = [x for x in wanted if ObjectId.is_valid(x)]
        if not wanted:
            continue
        docs = await db.user_assets.find(
            {"_id": {"$in": [ObjectId(x) for x in wanted]}, "type": "car"}
        ).to_list(len(wanted))
        trucks = {str(t["_id"]): {**t, "id": str(t["_id"])} for t in docs}
        for truck_id in p["trucks"].get("output", []):
            truck = trucks.get(str(truck_id))
            if truck and not truck.get("hauling") and dest_id:
                await _depart_output(db, unit, p, truck, dest_id, now)
        for truck_id in p["trucks"].get("input", []):
            truck = trucks.get(str(truck_id))
            if truck and not truck.get("hauling") and input_id:
                await _depart_input(db, unit, truck, input_id, now)


def _apply_production(asset: dict, prod: dict, elapsed_h: float) -> float:
    """Начисляет выпуск за elapsed_h часов прямо в prod["storage"] (мутирует).
    Возвращает потреблённую еду (кг хлеба). Шахта/лесопилка: meta.outputPerHour
    × эффективность, ограничено местом. Пекарня: пшеница → хлеб (2:1),
    ограничена запасом пшеницы и свободным местом."""
    meta = asset.get("meta") or {}
    storage = prod["storage"]
    cap = _storage_cap(asset)
    eff, food_used = _efficiency(asset, prod, elapsed_h)
    if eff <= 0:
        return 0.0
    if _is_bakery(asset):
        free = max(0.0, cap - sum(float(v) for v in storage.values()))
        bread = min(int(meta.get("outputPerHour") or 0) * eff * elapsed_h, free)
        wheat = min(bread * 2.0, float(storage.get("wheat", 0.0)))
        bread = wheat / 2.0
        if bread > 0:
            storage["wheat"] = round(float(storage.get("wheat", 0.0)) - wheat, 2)
            storage["bread"] = round(float(storage.get("bread", 0.0)) + bread, 2)
    else:
        res = str(meta.get("resource") or "")
        if not _resource_ok(res):
            return food_used
        free = max(0.0, cap - sum(float(v) for v in storage.values()))
        qty = min(int(meta.get("outputPerHour") or 0) * eff * elapsed_h, free)
        if qty > 0:
            storage[res] = round(float(storage.get(res, 0.0)) + qty, 2)
    return food_used


async def tick(db: AsyncIOMotorDatabase) -> None:
    """Производственный тик (вызывается Scheduler'ом): выпуск, еда, фуры.

    Еда списывается всегда, когда есть работники (независимо от выпуска:
    хранилище может быть полно, а люди продолжают есть)."""
    cfg = _cfg()
    now = _now()
    await _tick_arrivals(db, now)
    await _tick_departures(db, now)
    units = [a async for a in db.user_assets.find({"$or": [
        {"type": "source"},
        {"type": "factory", "meta.produces": "bread"},
    ]})]
    for unit in units:
        p = _prod_state(unit)
        workers = int(p.get("workers", 0))
        prev = _aware(p.get("ticked_at"))
        if workers <= 0 and not p.get("storage"):
            await db.user_assets.update_one(
                {"_id": unit["_id"]}, {"$set": {"prod.ticked_at": now}})
            continue
        elapsed_h = min(cfg["max_tick_hours"],
                        ((now - prev).total_seconds() / 3600.0) if prev else 0.0)
        if elapsed_h <= 0:
            # Первый тик после инициализации: только фиксируем точку отсчёта.
            await db.user_assets.update_one(
                {"_id": unit["_id"]}, {"$set": {"prod.ticked_at": now}})
            continue
        food_used = _apply_production(unit, p, elapsed_h)
        food_used = min(food_used, float(p.get("food", 0.0)))
        setops = {"prod.storage": p["storage"], "prod.ticked_at": now,
                  "prod.food": round(float(p.get("food", 0.0)) - food_used, 2)}
        await db.user_assets.update_one({"_id": unit["_id"]}, {"$set": setops})


# ── Загрузка/валидация юнитов ─────────────────────────────────────────────────


async def _load_unit(db, user_id: str, unit_id: str) -> dict:
    if not ObjectId.is_valid(unit_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID")
    unit = await db.user_assets.find_one({"_id": ObjectId(unit_id), "userId": user_id})
    if not unit:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")
    if not (_is_source(unit) or _is_bakery(unit) or _is_warehouse(unit)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Управление производством доступно для источников, пекарни и складов")
    return unit


# ── Эндпоинты ─────────────────────────────────────────────────────────────────


@router.get("/overview")
async def overview(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Всё производство игрока одним запросом: юниты, склады, фуры, поля."""
    user_id = str(current_user["_id"])
    econ = await get_econ(db)
    units = [a async for a in db.user_assets.find({"$or": [
        {"userId": user_id, "type": "source"},
        {"userId": user_id, "type": "factory", "meta.produces": "bread"},
    ]})]
    warehouses = [a async for a in db.user_assets.find(
        {"userId": user_id, "type": "warehouse"})]
    trucks = [a async for a in db.user_assets.find(
        {"userId": user_id, "type": "car", "category": "truck"})]
    fields = []
    async for a in db.user_assets.find({"userId": user_id, "type": "source", "category": "field"}):
        fdoc = await db.user_fields.find_one({"assetId": str(a["_id"])})
        level = max(1, int((a.get("prod") or {}).get("storageLevel", 1)))
        from game_config import FARM_CONFIG
        cap = float(FARM_CONFIG["storage_slots_per_resource"]) * level
        fields.append({
            "id": str(a["_id"]), "name": a.get("name"),
            "storage": {k: round(float(v), 2) for k, v in ((fdoc or {}).get("storage") or {}).items()},
            "storageCap": cap,
        })
    prices = {rid: _resource_price(rid, econ) for rid in RESOURCES_BY_ID}
    prices = {rid: _resource_price(rid, econ) for rid in RESOURCES_BY_ID}
    return {
        "units": [_serialize_unit(u, _prod_state(u)) for u in units],
        "warehouses": [_serialize_warehouse(w) for w in warehouses],
        "trucks": [_serialize_truck(t) for t in trucks],
        "fields": fields,
        "prices": prices,
        "tripMinutes": _cfg()["trip_minutes"],
    }


class ConfigBody(BaseModel):
    destinationId: Optional[str] = None
    inputId: Optional[str] = None


class TrucksBody(BaseModel):
    slot: str
    truckIds: list[str] = Field(default_factory=list)

    @field_validator("slot")
    @classmethod
    def slot_ok(cls, v):
        if v not in ("input", "output"):
            raise ValueError("Слот должен быть input или output")
        return v


class WorkersBody(BaseModel):
    workers: int

    @field_validator("workers")
    @classmethod
    def workers_ok(cls, v):
        if v < 0 or v > _cfg()["max_workers"]:
            raise ValueError(f"Работников: 0..{_cfg()['max_workers']}")
        return int(v)


class FoodBody(BaseModel):
    qty: float

    @field_validator("qty")
    @classmethod
    def qty_ok(cls, v):
        if v < 1 or v > 100000:
            raise ValueError("Количество еды: 1..100000 кг")
        return float(v)


class SellBody(BaseModel):
    resource: str
    qty: float

    @field_validator("resource")
    @classmethod
    def res_ok(cls, v):
        if str(v or "") not in RESOURCES_BY_ID:
            raise ValueError("Неизвестный ресурс")
        return str(v)

    @field_validator("qty")
    @classmethod
    def qty_ok(cls, v):
        if v <= 0:
            raise ValueError("Количество должно быть положительным")
        return float(v)


@router.post("/{unit_id}/config")
async def set_config(
    unit_id: str,
    payload: ConfigBody,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Назначить получателя (destinationId: склад/пекарня) или поставщика
    пшеницы для пекарни (inputId: поле/склад)."""
    user_id = str(current_user["_id"])
    unit = await _load_unit(db, user_id, unit_id)
    is_bakery = _is_bakery(unit)
    setops: dict = {}
    if payload.destinationId is not None:
        if payload.destinationId == "":
            setops["prod.destinationId"] = None
        else:
            target = await db.user_assets.find_one(
                {"_id": ObjectId(payload.destinationId), "userId": user_id})
            if not target:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Получатель не найден")
            ok = _is_warehouse(target) or (is_bakery and False) or (not is_bakery and _is_bakery(target))
            if not ok:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    "Получателем может быть склад (или пекарня — для пшеницы с поля)")
            setops["prod.destinationId"] = str(target["_id"])
    if payload.inputId is not None:
        if not is_bakery:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Поставщик пшеницы настраивается только у пекарни")
        if payload.inputId == "":
            setops["prod.inputId"] = None
        else:
            target = await db.user_assets.find_one(
                {"_id": ObjectId(payload.inputId), "userId": user_id})
            if not target:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Поставщик не найден")
            if not (_is_warehouse(target) or target.get("type") == "source"):
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    "Пшеницу возят с поля или со склада")
            setops["prod.inputId"] = str(target["_id"])
    if not setops:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нечего менять")
    await db.user_assets.update_one({"_id": unit["_id"]}, {"$set": setops})
    return {"ok": True}


@router.post("/{unit_id}/trucks")
async def set_trucks(
    unit_id: str,
    payload: TrucksBody,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Заменить состав назначенных фур потока (до 5). Фура может работать
    только на одном юните — проверяем, что она не назначена в другой prod."""
    user_id = str(current_user["_id"])
    unit = await _load_unit(db, user_id, unit_id)
    ids: list[str] = []
    for x in payload.truckIds[: _cfg()["max_trucks"]]:
        if ObjectId.is_valid(x):
            ids.append(str(ObjectId(x)))
    ids = list(dict.fromkeys(ids))
    # Все выбранные должны быть фурами владельца.
    conflict = await db.user_assets.count_documents({
        "_id": {"$in": [ObjectId(x) for x in ids]},
        "userId": user_id, "type": "car", "category": "truck",
    })
    if conflict != len(ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Среди выбранных есть не-фуры")
    others = [a async for a in db.user_assets.find({
        "userId": user_id,
        "_id": {"$ne": unit["_id"]},
        "$or": [{"prod.trucks.output": {"$in": ids}}, {"prod.trucks.input": {"$in": ids}}],
    }, {"prod.trucks": 1})]
    if others:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Фура уже назначена на другой объект — снимите её там")
    slot = "prod.trucks." + payload.slot
    await db.user_assets.update_one({"_id": unit["_id"]}, {"$set": {slot: ids}})
    return {"ok": True, "trucks": {payload.slot: ids}}


@router.post("/{unit_id}/workers")
async def set_workers(
    unit_id: str,
    payload: WorkersBody,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Нанять/уволить работников (0..50). Эффективность = workers/штат (×2 max)."""
    user_id = str(current_user["_id"])
    unit = await _load_unit(db, user_id, unit_id)
    if _is_warehouse(unit):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "У склада нет работников")
    await db.user_assets.update_one(
        {"_id": unit["_id"]}, {"$set": {"prod.workers": payload.workers}})
    return {"ok": True, "workers": payload.workers}


@router.post("/{unit_id}/food")
async def buy_food(
    unit_id: str,
    payload: FoodBody,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Заказать хлеб для работников: деньги → prod.food (кг)."""
    user_id = str(current_user["_id"])
    unit = await _load_unit(db, user_id, unit_id)
    if _is_warehouse(unit):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Еда заказывается для источников и пекарни")
    econ = await get_econ(db)
    unit_price = _food_unit_price(econ)
    total = round(unit_price * payload.qty, 2)
    new_balance = await adjust_balance(db, user_id, -total)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
    await db.user_assets.update_one(
        {"_id": unit["_id"]},
        {"$inc": {"prod.food": payload.qty}},
    )
    await record_transaction(
        db, user_id, EXPENSE, total, CAT_SOURCE,
        f"Хлеб для работников: {unit.get('name')} ×{payload.qty} кг",
        balance_after=new_balance, meta={"unitId": unit_id, "kg": payload.qty},
    )
    return {"ok": True, "qty": payload.qty, "unitPrice": unit_price, "total": total, "balance": new_balance}


@router.post("/{unit_id}/storage-upgrade")
async def upgrade_storage(
    unit_id: str,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Прокачка хранилища юнита (до 10 уровня): ёмкость = capacity × уровень."""
    user_id = str(current_user["_id"])
    unit = await _load_unit(db, user_id, unit_id)
    if _is_warehouse(unit):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Склад не качается — вместимость задаётся площадью")
    p = _prod_state(unit)
    level = int(p.get("storageLevel", 1))
    if level >= _cfg()["storage_max_level"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Максимальный уровень хранилища — {_cfg()['storage_max_level']}")
    cost = _storage_upgrade_cost(unit)
    new_balance = await adjust_balance(db, user_id, -cost)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
    await db.user_assets.update_one(
        {"_id": unit["_id"]}, {"$set": {"prod.storageLevel": level + 1}})
    cat = CAT_FACTORY if _is_bakery(unit) else CAT_SOURCE
    await record_transaction(
        db, user_id, EXPENSE, cost, cat,
        f"Хранилище ур.{level + 1}: {unit.get('name')}",
        balance_after=new_balance, meta={"unitId": unit_id, "level": level + 1},
    )
    return {"ok": True, "level": level + 1, "cost": cost, "balance": new_balance}


@router.post("/{unit_id}/sell")
async def sell_resource(
    unit_id: str,
    payload: SellBody,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Продать ресурс с хранилища юнита или склада. Цена = base_price × economy_mult."""
    user_id = str(current_user["_id"])
    unit = await _load_unit(db, user_id, unit_id)
    if _is_warehouse(unit):
        store = dict(unit.get("storage") or {})
        key, cat = "storage", CAT_WAREHOUSE
    else:
        p = _prod_state(unit)
        store = dict(p.get("storage") or {})
        key, cat = "prod.storage", (CAT_FACTORY if _is_bakery(unit) else CAT_SOURCE)
    took = _store_take(store, payload.resource, float(payload.qty))
    if took <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет этого ресурса на складе")
    econ = await get_econ(db)
    unit_price = _resource_price(payload.resource, econ)
    total = round(unit_price * took, 2)
    new_balance = await adjust_balance(db, user_id, total)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ошибка изменения баланса")
    await db.user_assets.update_one({"_id": unit["_id"]}, {"$set": {key: store}})
    await record_transaction(
        db, user_id, INCOME, total, cat,
        f"Продажа ресурса: {RESOURCES_BY_ID[payload.resource]['name']} × {took:g}",
        balance_after=new_balance,
        meta={"unitId": unit_id, "resource": payload.resource, "qty": took, "unitPrice": unit_price},
    )
    return {"ok": True, "qty": took, "unitPrice": unit_price, "total": total, "balance": new_balance}


@router.post("/{unit_id}/haul-now")
async def haul_now(
    unit_id: str,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Отправить все свободные назначенные фуры прямо сейчас, не дожидаясь тика."""
    user_id = str(current_user["_id"])
    unit = await _load_unit(db, user_id, unit_id)
    if _is_warehouse(unit):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Со склада фуры отправляются из панели склада")
    now = _now()
    p = _prod_state(unit)
    is_bakery = _is_bakery(unit)
    sent = 0
    wanted = list(p["trucks"].get("output", [])) + (list(p["trucks"].get("input", [])) if is_bakery else [])
    wanted = [x for x in wanted if ObjectId.is_valid(x)]
    docs = await db.user_assets.find(
        {"_id": {"$in": [ObjectId(x) for x in wanted] or [ObjectId("0" * 24)]}, "type": "car"}
    ).to_list(len(wanted) or 1)
    trucks = {str(t["_id"]): {**t, "id": str(t["_id"])} for t in docs}
    dest_id = p.get("destinationId")
    for truck_id in p["trucks"].get("output", []):
        truck = trucks.get(str(truck_id))
        if truck and not truck.get("hauling") and dest_id:
            await _depart_output(db, unit, p, truck, dest_id, now)
            sent += 1
    input_id = p.get("inputId") if is_bakery else None
    for truck_id in p["trucks"].get("input", []):
        truck = trucks.get(str(truck_id))
        if truck and not truck.get("hauling") and input_id:
            await _depart_input(db, unit, truck, input_id, now)
            sent += 1
    return {"ok": True, "sent": sent}


# ── Self-check ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Ёмкость хранилища растёт по уровню, потолок 10.
    unit = {"type": "source", "category": "mine", "price": 3500000,
            "employees": 8, "meta": {"resource": "metal", "outputPerHour": 600, "capacity": 50000}}
    p = _prod_state(unit)
    assert p["storageLevel"] == 1 and p["workers"] == 0 and p["food"] == 0.0
    assert _storage_cap(unit) == 50000.0
    p["storageLevel"] = 10
    assert _storage_cap({**unit, "prod": p}) == 500000.0

    # Эффективность: без работников производство стоит; штат (8) → ×1; потолок ×2.
    assert _workers_factor(0, unit) == 0.0
    assert abs(_workers_factor(8, unit) - 1.0) < 1e-9
    assert abs(_workers_factor(50, unit) - 2.0) < 1e-9
    assert _food_factor(100.0, 2.0) == _cfg()["fed_factor"]
    assert _food_factor(0.0, 2.0) == _cfg()[" hungry"] if False else _food_factor(0.0, 2.0) == _cfg()["hungry_factor"]

    # Выпуск ограничен ёмкостью и эффективностью.
    p2 = _prod_state(unit)
    p2["workers"] = 8
    p2["food"] = 100.0
    used = _apply_production(unit, p2, 1.0)
    assert p2["storage"]["metal"] == 600.0, p2["storage"]
    assert used == 8 * 0.5  # 8 работников × 0.5 кг/ч

    # Пекарня: 240 кг пшеницы → 120 кг хлеба, потребление ограничено запасом.
    bakery = {"type": "factory", "price": 1200000, "employees": 20,
              "meta": {"produces": "bread", "input": "wheat", "outputPerHour": 120, "consumesPerHour": 240, "capacity": 30000}}
    pb = _prod_state(bakery)
    pb["workers"] = 20
    pb["food"] = 50.0
    pb["storage"] = {"wheat": 1000.0}
    _apply_production(bakery, pb, 1.0)
    assert pb["storage"]["bread"] == 120.0, pb["storage"]
    assert pb["storage"]["wheat"] == 760.0, pb["storage"]

    # Погрузка: сначала большие стаки, в пределах грузоподъёмности.
    store = {"wood": 300.0, "metal": 1000.0}
    cargo = _load_cargo(store, 500.0)
    assert cargo == {"metal": 500.0}, cargo
    assert store == {"metal": 500.0, "wood": 300.0}

    # Цены: хлеб 30 × economy_mult=1.
    econ = {"economy_mult": 1.0}
    assert _resource_price("bread", econ) == 30.0
    assert _food_unit_price(econ) == 30.0
    assert _resource_price("nope", econ) == 0.0

    print("production self-check OK")


# ── Миграция купленной инфраструктуры под новые каталоги ─────────────────────
# Активы, купленные до переработки (источники ×100, склады ×3), несут старые
# price/meta — синхронизируем их с каталогом один раз (config-ключ), иначе
# цена продажи/апгрейда и ёмкости остаются старыми.


async def migrate_owned_infra(db) -> None:
    import assets as assets_module
    from database import find_config_by_key, upsert_config
    key = "production_rework_v1"
    if await find_config_by_key(db, key):
        return
    n = 0
    q = {"slug": {"$in": [f"admin-wh-{i}" for i in range(1, 17)] + [
        "admin-src-mine-1", "admin-src-field-1", "admin-src-sawmill-1"]}}
    async for a in db.user_assets.find(q, {"slug": 1}):
        cat = assets_module._find_catalog(a["slug"])
        if not cat:
            continue
        res = await db.user_assets.update_one(
            {"_id": a["_id"]},
            {"$set": {"price": float(cat["price"]), "meta": cat["meta"]}})
        n += res.modified_count
    await upsert_config(db, key, "1")
    print(f"production: migrated {n} owned infra assets")
