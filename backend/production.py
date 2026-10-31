"""Производство: источники → фуры → склады/пекарня/завод; деньги — только через ledger.

Фуры до 5 на поток, рейс фиксированный (trip_minutes); пекарня 2:1 пшеница→хлеб.
Эффективность = workers/штат (×2 потолок, 0 → стоит); еда 0.5 кг/работник/час,
голодные ×0.6. Ёмкость = meta.capacity × уровень (1..10); поле — склад farm.py.
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
from ledger import INCOME, EXPENSE, CAT_SOURCE, CAT_FACTORY, CAT_WAREHOUSE, CAT_SHOP, adjust_balance, record_transaction
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


def _recipes() -> dict:
    from game_config import RECIPES
    return RECIPES


def _recipe_for(asset: dict) -> Optional[dict]:
    """Рецепт переработки завода (пекарня, завод видеокарт) или None для источника/склада."""
    if asset.get("type") != "factory":
        return None
    return _recipes().get(str((asset.get("meta") or {}).get("produces") or ""))


COMPONENT_RESOURCE = "component"


def _is_recipe_output_factory(asset: dict, produces: str) -> bool:
    return asset.get("type") == "factory" and (asset.get("meta") or {}).get("produces") == produces


def _component_unit_price(pct: float, econ: dict) -> float:
    from game_config import COMPONENT_BASE_PRICE
    return round(float(COMPONENT_BASE_PRICE) * float(econ.get("economy_mult", 1.0)) * float(pct) / 100.0, 2)


def _is_bakery(asset: dict) -> bool:
    return asset.get("type") == "factory" and (asset.get("meta") or {}).get("produces") == "bread"


def _recipe_unit_query() -> dict:
    return {"type": "factory", "meta.produces": {"$in": list(_recipes().keys())}}


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
    p.setdefault("componentPricePct", 100.0)
    t = p.get("trucks") or {}
    p["trucks"] = {
        "input": [str(x) for x in (t.get("input") or [])][: _cfg()["max_trucks"]],
        "output": [str(x) for x in (t.get("output") or [])][: _cfg()["max_trucks"]],
    }
    return p


# ── Ёмкости и эффективность ───────────────────────────────────────────────────


def _storage_cap(asset: dict) -> float:
    """Ёмкость = meta.capacity × уровень (1..10). У поля не используется: его
    склад копится в farm.py (тот же prod.storageLevel)."""
    meta = asset.get("meta") or {}
    cap = float(meta.get("capacity") or 0)
    if cap <= 0:
        return 0.0
    level = max(1, int((asset.get("prod") or {}).get("storageLevel", 1)))
    return cap * level


def _warehouse_cap(asset: dict) -> float:
    meta = asset.get("meta") or {}
    return float(meta.get("storageCap") or 0)


def _arrival_destination_projection() -> dict:
    return {
        "type": 1,
        "category": 1,
        "prod.storage": 1,
        "storage": 1,
        "meta.capacity": 1,
        "meta.storageCap": 1,
    }


def _workers_factor(workers: int, asset: dict) -> float:
    """0 работников → производство стоит; далее workers/штат до потолка ×2."""
    if workers <= 0:
        return 0.0
    base = int(asset.get("employees") or asset.get("meta", {}).get("employees") or 1)
    return min(float(_cfg()["workers_factor_cap"]), workers / max(1, base))


def _food_factor(food: float, need: float) -> float:
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
    is_gpu = _is_recipe_output_factory(asset, "gpu")
    out["isGpuPlant"] = is_gpu
    if is_gpu:
        pct = float(prod.get("componentPricePct", 100.0))
        out["componentPricePct"] = pct
        out["componentUnitPrice"] = _component_unit_price(pct, {"economy_mult": 1.0})
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
    rec = RESOURCES_BY_ID.get(str(res or ""))
    if not rec:
        return 0.0
    return round(float(rec["base_price"]) * float(econ.get("economy_mult", 1.0)), 2)


def _food_unit_price(econ: dict) -> float:
    """Закупка 1 кг хлеба для работников."""
    return _resource_price("bread", econ)


def _storage_upgrade_cost(asset: dict) -> float:
    """Следующий уровень = price × storage_cost_pct × новый уровень."""
    level = max(1, int((asset.get("prod") or {}).get("storageLevel", 1)))
    pct = float(_cfg()["storage_cost_pct"])
    return round(float(asset.get("price", 0)) * pct * (level + 1), 2)


# ── Хранилище: списание/зачисление с потолком ─────────────────────────────────


def _store_add(store: dict, cap: float, res: str, qty: float) -> float:
    """Зачисляет до cap суммарно; мутирует store, возвращает принятое."""
    if cap <= 0 or qty <= 0:
        return 0.0
    used = sum(float(v) for v in store.values())
    free = max(0.0, cap - used)
    take = min(qty, free)
    if take > 0:
        store[res] = round(float(store.get(res, 0.0)) + take, 2)
    return take


def _store_take(store: dict, res: str, qty: float) -> float:
    """Списывает до qty; возвращает фактическое."""
    have = float(store.get(res, 0.0))
    take = min(qty, have)
    if take > 0:
        store[res] = round(have - take, 2)
        if store[res] <= 0.001:
            store.pop(res, None)
    return take


# ── Тик производства ──────────────────────────────────────────────────────────


def _storage_delta_inc(prefix: str, before: dict, after: dict) -> dict:
    """$inc-дельты между снимком склада и итогом: не затирают параллельные изменения."""
    inc: dict = {}
    for res in set(before) | set(after):
        d = round(float(after.get(res, 0.0)) - float(before.get(res, 0.0)), 2)
        if d != 0:
            inc[f"{prefix}.{res}"] = d
    return inc


async def _atomic_take(db, unit_id, prefix: str, res: str, have: float, want: float) -> float:
    """Атомарно списывает min(want, have). Условие $gte в фильтре не даёт уйти в минус
    при параллельной продаже/покупке. 409 — остаток изменился между чтением и записью."""
    took = round(min(float(want), float(have)), 2)
    if took <= 0:
        return 0.0
    key = f"{prefix}.{res}"
    r = await db.user_assets.update_one({"_id": unit_id, key: {"$gte": took}}, {"$inc": {key: -took}})
    if r.modified_count != 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Склад изменился — обновите данные и повторите")
    return took


async def _atomic_spend(db, unit_id, prefix: str, res: str, need: float) -> None:
    """Атомарно списывает ровно need при условии остатка ≥ need; иначе 409."""
    key = f"{prefix}.{res}"
    r = await db.user_assets.update_one({"_id": unit_id, key: {"$gte": float(need)}},
                                        {"$inc": {key: -float(need)}})
    if r.modified_count != 1:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Недостаточно компонентов на складе или склад изменился — повторите")


async def _atomic_give(db, unit_id, prefix: str, res: str, qty: float) -> None:
    """Возврат на склад (откат списания)."""
    await db.user_assets.update_one({"_id": unit_id}, {"$inc": {f"{prefix}.{res}": float(qty)}})


async def _take_all_atomic(coll, doc_id, prefix: str, cargo: dict) -> bool:
    """Условный $inc -qty по каждому ресурсу (фильтр {ключ: {$gte: qty}}).
    Если какой-то ресурс не списался — уже списанное возвращается, результат False."""
    done: dict = {}
    for res, qty in cargo.items():
        key = f"{prefix}.{res}"
        r = await coll.update_one({"_id": doc_id, key: {"$gte": float(qty)}},
                                  {"$inc": {key: -float(qty)}})
        if r.modified_count != 1:
            if done:
                await _give_back(coll, doc_id, prefix, done)
            return False
        done[res] = float(qty)
    return True


async def _give_back(coll, doc_id, prefix: str, cargo: dict) -> None:
    """Возврат груза в склад через $inc (откат или прочий груз)."""
    if not cargo:
        return
    await coll.update_one({"_id": doc_id},
                          {"$inc": {f"{prefix}.{res}": float(qty) for res, qty in cargo.items()}})


async def _unload_capped(db, owner_id, dest: dict, cargo: dict) -> dict:
    """Разгрузка в склад-получатель. Возвращает непринятый остаток.
    Пер-ресурсный $inc принятой дельты; в фильтре $expr: сумма склада + принятое ≤ ёмкость.
    Если склад изменился параллельно (условие не выполнено) — перечитать и повторить (до 3 раз)."""
    is_wh = _is_warehouse(dest)
    prefix = "storage" if is_wh else "prod.storage"
    current = dest
    for attempt in range(3):
        if attempt:
            current = await db.user_assets.find_one(
                {"_id": dest["_id"], "userId": owner_id}, _arrival_destination_projection())
            if not current:
                return dict(cargo)
        cap = _warehouse_cap(current) if is_wh else _storage_cap(current)
        if is_wh:
            store = dict(current.get("storage") or {})
        else:
            store = dict((current.get("prod") or {}).get("storage") or {})
        accepted: dict = {}
        left = dict(cargo)
        for res, qty in list(cargo.items()):
            took = _store_add(store, cap, res, float(qty))
            if took > 0:
                accepted[res] = round(took, 2)
            left[res] = round(float(qty) - took, 2)
            if left[res] <= 0.001:
                del left[res]
        if not accepted:
            return left
        total = round(sum(accepted.values()), 2)
        cur_sum = {"$reduce": {
            "input": {"$objectToArray": {"$ifNull": [f"${prefix}", {}]}},
            "initialValue": 0,
            "in": {"$add": ["$$value", "$$this.v"]},
        }}
        inc = {f"{prefix}.{res}": v for res, v in accepted.items()}
        r = await db.user_assets.update_one(
            {"_id": dest["_id"], "$expr": {"$lte": [{"$add": [cur_sum, total]}, cap + 0.005]}},
            {"$inc": inc},
        )
        if r.modified_count == 1:
            return left
    return dict(cargo)


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
                _arrival_destination_projection(),
            )
        if not dest:
            # Получатель продан/передан — груз остаётся на фуре (сгорит при
            # следующей погрузке), рейс завершается.
            await db.user_assets.update_one({"_id": truck["_id"]}, {"$set": {"hauling": None}})
            continue
        left = await _unload_capped(db, truck["userId"], dest, cargo)
        # Непоместившийся груз остаётся на фуре: until=now → разгрузится следующим тиком.
        await db.user_assets.update_one(
            {"_id": truck["_id"]},
            {"$set": {"hauling": ({"until": now, "cargo": left, "toId": dest_id, "fromId": h.get("fromId")}
                                  if left else None)}},
        )


def _load_cargo(store: dict, cap_kg: float) -> dict:
    """Берёт до cap_kg, крупные стаки вперёд; мутирует store."""
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
    """Грузоподъёмность + прицеп: ссылка hitchedTo лежит на документе прицепа."""
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
    """Отправить одну фуру с выхода юнита: условное списание (-qty, $gte) → hauling.
    Если списание не удалось или рейс не назначился — груз возвращается, фура не едет."""
    truck_id = truck["id"]
    cargo_kg = await _truck_cargo_kg(db, truck)
    if unit.get("category") == "field":
        fdoc = await db.user_fields.find_one({"assetId": str(unit["_id"])})
        if not fdoc:
            return
        coll, doc_id, prefix = db.user_fields, fdoc["_id"], "storage"
        store = dict(fdoc.get("storage") or {})
    else:
        fresh = await db.user_assets.find_one({"_id": unit["_id"]}, {"prod.storage": 1})
        coll, doc_id, prefix = db.user_assets, unit["_id"], "prod.storage"
        store = dict(((fresh or {}).get("prod") or {}).get("storage") or {})
    cargo = _load_cargo(store, cargo_kg)
    if not cargo:
        return
    if not await _take_all_atomic(coll, doc_id, prefix, cargo):
        return
    r = await db.user_assets.update_one(
        {"_id": ObjectId(truck_id), "hauling": None},
        {"$set": {"hauling": _trip(truck_id, str(unit["_id"]), dest_id, cargo, now)}},
    )
    if r.modified_count != 1:
        await _give_back(coll, doc_id, prefix, cargo)


async def _depart_input(db, unit: dict, truck: dict, input_id: str, now: datetime) -> None:
    """Отправить одну фуру за пшеницей для пекарни (с поля или со склада).
    Списание условное ($gte); прочий груз возвращается в источник через $inc."""
    truck_id = truck["id"]
    src = await db.user_assets.find_one({"_id": ObjectId(input_id), "userId": unit["userId"]})
    if not src:
        return
    if _is_warehouse(src):
        coll, doc_id = db.user_assets, src["_id"]
        store = dict(src.get("storage") or {})
    else:  # поле: пшеница лежит в складе поля
        fdoc = await db.user_fields.find_one({"assetId": input_id})
        if not fdoc:
            return
        coll, doc_id = db.user_fields, fdoc["_id"]
        store = dict(fdoc.get("storage") or {})
    prefix = "storage"
    cargo = _load_cargo(store, await _truck_cargo_kg(db, truck))
    if not cargo:
        return
    if not await _take_all_atomic(coll, doc_id, prefix, cargo):
        return
    # Пекарне нужна только пшеница: прочий груз возвращаем в источник через $inc.
    wheat = float(cargo.pop("wheat", 0.0))
    await _give_back(coll, doc_id, prefix, cargo)
    if wheat <= 0:
        return
    r = await db.user_assets.update_one(
        {"_id": ObjectId(truck_id), "hauling": None},
        {"$set": {"hauling": _trip(truck_id, input_id, str(unit["_id"]), {"wheat": wheat}, now)}},
    )
    if r.modified_count != 1:
        await _give_back(coll, doc_id, prefix, {"wheat": wheat})


async def _tick_departures(db, now: datetime) -> None:
    """Разослать свободные фуры: выход юнита (до 5 фур) и вход пекарни (до 5)."""
    units = [a async for a in db.user_assets.find({"$or": [
        {"type": "source"},
        {"type": "factory", "meta.produces": {"$in": ["bread", "gpu"]}},
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
    """Выпуск за elapsed_h в prod["storage"] (мутирует); возвращает съеденное (кг).
    Завод по рецепту (game_config.RECIPES): выпуск = outputPerHour × эффективность,
    ограничен запасом входов и местом; источник: outputPerHour × эффективность
    (лимит — место)."""
    meta = asset.get("meta") or {}
    storage = prod["storage"]
    cap = _storage_cap(asset)
    eff, food_used = _efficiency(asset, prod, elapsed_h)
    if eff <= 0:
        return 0.0
    recipe = _recipe_for(asset)
    if recipe:
        out_kg = recipe["outputPerUnit"]
        free_units = max(0.0, cap - sum(float(v) for v in storage.values())) / out_kg
        want = int(meta.get("outputPerHour") or 0) * eff * elapsed_h
        stock_units = min(
            float(storage.get(res, 0.0)) / qty for res, qty in recipe["inputs"].items()
        )
        units = min(want, free_units, stock_units)
        if units > 0:
            for res, qty in recipe["inputs"].items():
                storage[res] = round(float(storage.get(res, 0.0)) - units * qty, 2)
                if storage[res] <= 0.001:
                    storage.pop(res, None)
            produced = recipe["output"]
            storage[produced] = round(float(storage.get(produced, 0.0)) + units * out_kg, 2)
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
    """Тик планировщика: фуры, выпуск, еда. Еда списывается всегда при работниках —
    даже когда хранилище полно и выпуска нет."""
    cfg = _cfg()
    now = _now()
    await _tick_arrivals(db, now)
    await _tick_departures(db, now)
    units = [a async for a in db.user_assets.find({"$or": [
        {"type": "source"},
        _recipe_unit_query(),
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
        before = dict(p.get("storage") or {})
        food_used = _apply_production(unit, p, elapsed_h)
        food_used = min(food_used, float(p.get("food", 0.0)))
        inc = _storage_delta_inc("prod.storage", before, p["storage"])
        inc["prod.food"] = -round(food_used, 2)
        await db.user_assets.update_one({"_id": unit["_id"]},
                                        {"$set": {"prod.ticked_at": now}, "$inc": inc})


# ── Загрузка/валидация юнитов ─────────────────────────────────────────────────


async def _load_unit(db, user_id: str, unit_id: str) -> dict:
    if not ObjectId.is_valid(unit_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID")
    unit = await db.user_assets.find_one({"_id": ObjectId(unit_id), "userId": user_id})
    if not unit:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")
    if not (_is_source(unit) or _is_bakery(unit) or _is_warehouse(unit)
            or _is_recipe_output_factory(unit, "gpu")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Управление производством доступно для источников, пекарни, заводов видеокарт и складов")
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
    """Назначить получателя (destinationId) или поставщика пшеницы пекарне (inputId)."""
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
    """Заменить состав фур потока (до 5); фура работает только на одном юните."""
    user_id = str(current_user["_id"])
    unit = await _load_unit(db, user_id, unit_id)
    ids: list[str] = []
    for x in payload.truckIds[: _cfg()["max_trucks"]]:
        if ObjectId.is_valid(x):
            ids.append(str(ObjectId(x)))
    ids = list(dict.fromkeys(ids))
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


class PricePctBody(BaseModel):
    pct: float

    @field_validator("pct")
    @classmethod
    def pct_ok(cls, v):
        if v < 50 or v > 200:
            raise ValueError("Цена: 50..200% от базовой")
        return round(float(v), 2)


@router.post("/{unit_id}/component-price")
async def set_component_price(
    unit_id: str,
    payload: PricePctBody,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Цена компонента завода в % от базовой цены econ (50..200)."""
    user_id = str(current_user["_id"])
    unit = await _load_unit(db, user_id, unit_id)
    if not _is_recipe_output_factory(unit, "gpu"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Цена компонента задаётся у завода видеокарт")
    old_pct = float((unit.get("prod") or {}).get("componentPricePct", 100.0))
    shop_published = bool(((unit.get("prod") or {}).get("shop") or {}).get("published", False))
    setops: dict = {"prod.componentPricePct": payload.pct}
    # Смена цены компонента меняет себестоимость товаров → публикация снимается.
    shop_unpublished = shop_published and payload.pct != old_pct
    if shop_unpublished:
        setops["prod.shop.published"] = False
    await db.user_assets.update_one({"_id": unit["_id"]}, {"$set": setops})
    return {"ok": True, "pct": payload.pct,
            "unitPrice": _component_unit_price(payload.pct, await get_econ(db)),
            "shopUnpublished": shop_unpublished}


class SellComponentBody(BaseModel):
    qty: int

    @field_validator("qty")
    @classmethod
    def qty_ok(cls, v):
        if v <= 0:
            raise ValueError("Количество должно быть положительным")
        return int(v)


@router.post("/{unit_id}/sell-component")
async def sell_component(
    unit_id: str,
    payload: SellComponentBody,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Продать компоненты со склада завода по цене prod.componentPricePct."""
    user_id = str(current_user["_id"])
    unit = await _load_unit(db, user_id, unit_id)
    if not _is_recipe_output_factory(unit, "gpu"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Компоненты продаются только с завода видеокарт")
    p = _prod_state(unit)
    have = float((p.get("storage") or {}).get(COMPONENT_RESOURCE, 0.0))
    took = await _atomic_take(db, unit["_id"], "prod.storage", COMPONENT_RESOURCE, have, float(payload.qty))
    if took <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет компонентов на складе")
    econ = await get_econ(db)
    unit_price = _component_unit_price(float(p.get("componentPricePct", 100.0)), econ)
    total = round(unit_price * took, 2)
    new_balance = await adjust_balance(db, user_id, total)
    if new_balance is None:
        await _atomic_give(db, unit["_id"], "prod.storage", COMPONENT_RESOURCE, took)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ошибка изменения баланса")
    await record_transaction(
        db, user_id, INCOME, total, CAT_FACTORY,
        f"Продажа компонентов × {took:g}",
        balance_after=new_balance,
        meta={"unitId": unit_id, "resource": COMPONENT_RESOURCE, "qty": took, "unitPrice": unit_price},
    )
    return {"ok": True, "qty": took, "unitPrice": unit_price, "total": total, "balance": new_balance}


class ComponentShopBuyBody(BaseModel):
    item: str
    qty: int = 1

    @field_validator("item")
    @classmethod
    def item_ok(cls, v):
        from game_config import COMPONENT_COST
        if v not in COMPONENT_COST:
            raise ValueError("Неизвестный товар магазина")
        return v

    @field_validator("qty")
    @classmethod
    def qty_ok(cls, v):
        if v <= 0 or v > 1000:
            raise ValueError("Количество: 1..1000")
        return int(v)


@router.get("/gpu-shop/catalog")
async def gpu_shop_catalog(
    current_user: dict = Depends(get_current_user),
):
    """Товары магазина «Квантум GPU» и цена каждого в компонентах."""
    from game_config import COMPONENT_COST
    return {"items": [{"id": k, "components": v} for k, v in COMPONENT_COST.items()]}


@router.post("/{unit_id}/shop-buy")
async def shop_buy_with_components(
    unit_id: str,
    payload: ComponentShopBuyBody,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Товар магазина «Квантум GPU» за компоненты: компоненты списываются со склада завода."""
    from game_config import COMPONENT_COST
    user_id = str(current_user["_id"])
    unit = await _load_unit(db, user_id, unit_id)
    if not _is_recipe_output_factory(unit, "gpu"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Компоненты берутся с завода видеокарт")
    need = COMPONENT_COST[payload.item] * payload.qty
    p = _prod_state(unit)
    have = float((p.get("storage") or {}).get(COMPONENT_RESOURCE, 0.0))
    if have < need:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Недостаточно компонентов: нужно {need}, на складе {have:g}")
    await _atomic_spend(db, unit["_id"], "prod.storage", COMPONENT_RESOURCE, float(need))
    await record_transaction(
        db, user_id, INCOME, 0.0, CAT_FACTORY,
        f"Списано компонентов {need}: {payload.item} × {payload.qty}",
        balance_after=None,
        meta={"unitId": unit_id, "item": payload.item, "qty": payload.qty, "components": need},
    )
    return {"ok": True, "item": payload.item, "qty": payload.qty, "componentsSpent": need}


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
        have_store = dict(unit.get("storage") or {})
        key, cat = "storage", CAT_WAREHOUSE
    else:
        p = _prod_state(unit)
        have_store = dict(p.get("storage") or {})
        key, cat = "prod.storage", (CAT_FACTORY if _is_bakery(unit) else CAT_SOURCE)
    have = float(have_store.get(payload.resource, 0.0))
    took = await _atomic_take(db, unit["_id"], key, payload.resource, have, float(payload.qty))
    if took <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет этого ресурса на складе")
    econ = await get_econ(db)
    unit_price = _resource_price(payload.resource, econ)
    total = round(unit_price * took, 2)
    new_balance = await adjust_balance(db, user_id, total)
    if new_balance is None:
        await _atomic_give(db, unit["_id"], key, payload.resource, took)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ошибка изменения баланса")
    await record_transaction(
        db, user_id, INCOME, total, cat,
        f"Продажа ресурса: {RESOURCES_BY_ID[payload.resource]['name']} × {took:g}",
        balance_after=new_balance,
        meta={"unitId": unit_id, "resource": payload.resource, "qty": took, "unitPrice": unit_price},
    )
    return {"ok": True, "qty": took, "unitPrice": unit_price, "total": total, "balance": new_balance}


# Магазины, принимающие компоненты со склада: GPU Market, CoreTech, Неон-Хард.
SHOP_BUYER_SLUGS = {"admin-biz-2", "admin-biz-3", "admin-biz-4"}


class WarehouseShopBody(BaseModel):
    shopId: str
    item: str
    qty: int = 1

    @field_validator("item")
    @classmethod
    def item_ok(cls, v):
        from game_config import COMPONENT_COST
        if v not in COMPONENT_COST:
            raise ValueError("Неизвестный товар магазина")
        return v

    @field_validator("qty")
    @classmethod
    def qty_ok(cls, v):
        if v <= 0 or v > 1000:
            raise ValueError("Количество: 1..1000")
        return int(v)


@router.post("/{unit_id}/warehouse-shop-buy")
async def warehouse_shop_buy(
    unit_id: str,
    payload: WarehouseShopBody,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Со склада списываются компоненты, магазин (GPU Market / CoreTech / Неон-Хард)
    оформляет товар «Квантум GPU»."""
    from game_config import COMPONENT_COST
    user_id = str(current_user["_id"])
    unit = await _load_unit(db, user_id, unit_id)
    if not _is_warehouse(unit):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Отгрузка в магазин — только со склада")
    if not ObjectId.is_valid(payload.shopId):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID магазина")
    shop = await db.user_assets.find_one(
        {"_id": ObjectId(payload.shopId), "userId": user_id, "type": "business"},
        {"slug": 1, "name": 1},
    )
    if not shop or shop.get("slug") not in SHOP_BUYER_SLUGS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Этот магазин не принимает компоненты")
    need = COMPONENT_COST[payload.item] * payload.qty
    have = float((unit.get("storage") or {}).get(COMPONENT_RESOURCE, 0.0))
    if have < need:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Недостаточно компонентов на складе: нужно {need}, есть {have:g}")
    await _atomic_spend(db, unit["_id"], "storage", COMPONENT_RESOURCE, float(need))
    await record_transaction(
        db, user_id, INCOME, 0.0, CAT_WAREHOUSE,
        f"Отгрузка компонентов {need} → {shop.get('name')}: {payload.item} × {payload.qty}",
        balance_after=None,
        meta={"unitId": unit_id, "shopId": payload.shopId, "item": payload.item,
              "qty": payload.qty, "components": need},
    )
    return {"ok": True, "item": payload.item, "qty": payload.qty, "componentsSpent": need}


# ── Магазин «Квантум GPU»: ручные цены владельца и публикация ──────────────
# Хранение: unit.prod.shop = {"items": {item_id: price_usd}, "published": bool}.
# Себестоимость товара = COMPONENT_COST[item] × цена компонента завода (componentPricePct).

GPU_SHOP_PRICE_MAX = 1_000_000_000.0


def _gpu_shop_raw(unit: dict) -> dict:
    shop = (unit.get("prod") or {}).get("shop") or {}
    items = shop.get("items") or {}
    return {"items": {k: float(v) for k, v in items.items()}, "published": bool(shop.get("published", False))}


async def _gpu_item_cost(db: AsyncIOMotorDatabase, unit: dict, item: str) -> float:
    from game_config import COMPONENT_COST
    pct = float((unit.get("prod") or {}).get("componentPricePct", 100.0))
    unit_price = _component_unit_price(pct, await get_econ(db))
    return round(COMPONENT_COST[item] * unit_price, 2)


async def _gpu_shop_view(db: AsyncIOMotorDatabase, unit: dict) -> dict:
    from game_config import COMPONENT_COST
    raw = _gpu_shop_raw(unit)
    pct = float((unit.get("prod") or {}).get("componentPricePct", 100.0))
    comp_price = _component_unit_price(pct, await get_econ(db))
    items = []
    for item_id, components in COMPONENT_COST.items():
        cost = round(components * comp_price, 2)
        price = raw["items"].get(item_id)
        items.append({
            "id": item_id,
            "components": components,
            "costPrice": cost,
            "price": price,
            "profit": round(price - cost, 2) if price is not None else None,
            "priced": price is not None,
        })
    return {
        "unitId": str(unit["_id"]),
        "published": raw["published"],
        "componentUnitPrice": comp_price,
        "items": items,
    }


class GpuShopPriceBody(BaseModel):
    item: str
    price: Optional[float] = None  # None — убрать товар из магазина

    @field_validator("item")
    @classmethod
    def item_ok(cls, v):
        from game_config import COMPONENT_COST
        if v not in COMPONENT_COST:
            raise ValueError("Неизвестный товар магазина")
        return v

    @field_validator("price")
    @classmethod
    def price_ok(cls, v):
        if v is None:
            return None
        if v <= 0 or v > GPU_SHOP_PRICE_MAX:
            raise ValueError("Цена: больше 0 и не более 1 000 000 000 $")
        return round(float(v), 2)


class GpuShopPublishBody(BaseModel):
    published: bool


@router.get("/{unit_id}/gpu-shop")
async def get_gpu_shop(
    unit_id: str,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Магазин «Квантум GPU» владельца: товары, цены, себестоимость, published."""
    user_id = str(current_user["_id"])
    unit = await _load_unit(db, user_id, unit_id)
    if not _is_recipe_output_factory(unit, "gpu"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Магазин доступен у завода видеокарт")
    return {"ok": True, **(await _gpu_shop_view(db, unit))}


@router.post("/{unit_id}/gpu-shop/price")
async def set_gpu_shop_price(
    unit_id: str,
    payload: GpuShopPriceBody,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Задать цену товара владельцем. Цена должна быть > себестоимости.
    price=null — убрать товар из магазина. Ошибки: 400 (правила), 404 (нет юнита)."""
    user_id = str(current_user["_id"])
    unit = await _load_unit(db, user_id, unit_id)
    if not _is_recipe_output_factory(unit, "gpu"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Магазин доступен у завода видеокарт")
    raw = _gpu_shop_raw(unit)
    items = dict(raw["items"])
    if payload.price is None:
        items.pop(payload.item, None)
    else:
        cost = await _gpu_item_cost(db, unit, payload.item)
        if payload.price <= cost:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Цена {payload.price:g} $ должна быть выше себестоимости {cost:g} $")
        items[payload.item] = payload.price
    await db.user_assets.update_one(
        {"_id": unit["_id"]},
        {"$set": {"prod.shop": {"items": items, "published": raw["published"]}}})
    unit["prod"] = {**(unit.get("prod") or {}), "shop": {"items": items, "published": raw["published"]}}
    return {"ok": True, **(await _gpu_shop_view(db, unit))}


@router.post("/{unit_id}/gpu-shop/publish")
async def set_gpu_shop_published(
    unit_id: str,
    payload: GpuShopPublishBody,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Опубликовать/снять с публикации магазин. Публикация требует хотя бы один товар
    и что цена каждого опубликуемого товара > себестоимости (по текущей componentPricePct).
    Снятие с публикации всегда разрешено. Ошибки: 400."""
    user_id = str(current_user["_id"])
    unit = await _load_unit(db, user_id, unit_id)
    if not _is_recipe_output_factory(unit, "gpu"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Магазин доступен у завода видеокарт")
    raw = _gpu_shop_raw(unit)
    if payload.published:
        if not raw["items"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя опубликовать пустой магазин: задайте цены товаров")
        bad = []
        for item_id, price in raw["items"].items():
            cost = await _gpu_item_cost(db, unit, item_id)
            if price <= cost:
                bad.append(f"{item_id}: цена {price:g} ≤ себестоимость {cost:g}")
        if bad:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Публикация отклонена: " + "; ".join(bad))
    new_shop = {"items": raw["items"], "published": bool(payload.published)}
    await db.user_assets.update_one({"_id": unit["_id"]}, {"$set": {"prod.shop": new_shop}})
    unit["prod"] = {**(unit.get("prod") or {}), "shop": new_shop}
    return {"ok": True, **(await _gpu_shop_view(db, unit))}


# ── Покупка игроком в опубликованном магазине «Квантум GPU» ───────────────

async def _gpu_unit_any_owner(db: AsyncIOMotorDatabase, unit_id: str) -> dict:
    """Завод видеокарт любого владельца (для покупателя). 404 — не найден."""
    if not ObjectId.is_valid(unit_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID")
    unit = await db.user_assets.find_one({"_id": ObjectId(unit_id)})
    if not unit or not _is_recipe_output_factory(unit, "gpu"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Магазин не найден")
    return unit


def _gpu_cost_with(unit: dict, item: str, econ: dict) -> float:
    """Себестоимость товара по текущей componentPricePct юнита и экономике."""
    from game_config import COMPONENT_COST
    pct = float((unit.get("prod") or {}).get("componentPricePct", 100.0))
    return round(COMPONENT_COST[item] * _component_unit_price(pct, econ), 2)


@router.get("/gpu-shops/published")
async def list_published_gpu_shops(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Опубликованные магазины «Квантум GPU» игроков. Товар с price <= себестоимости
    или без компонентов на складе помечен available=false. Остаток — число возможных
    покупок (availableQty), сырой склад владельца не отдаётся."""
    from game_config import COMPONENT_COST
    me = str(current_user["_id"])
    econ = await get_econ(db)
    shops = []
    async for unit in db.user_assets.find({
        "type": "factory", "meta.produces": "gpu", "prod.shop.published": True,
    }).limit(200):
        raw = _gpu_shop_raw(unit)
        if not raw["published"]:
            continue
        owner_id = str(unit.get("userId") or "")
        owner = None
        if ObjectId.is_valid(owner_id):
            owner = await db.users.find_one({"_id": ObjectId(owner_id)}, {"username": 1})
        store = (unit.get("prod") or {}).get("storage") or {}
        have = float(store.get(COMPONENT_RESOURCE, 0.0))
        items = []
        for item_id, price in raw["items"].items():
            if item_id not in COMPONENT_COST:
                continue
            cost = _gpu_cost_with(unit, item_id, econ)
            price_ok = price > cost
            qty_left = int(have // COMPONENT_COST[item_id]) if price_ok else 0
            items.append({
                "id": item_id,
                "price": price,
                "costPrice": cost,
                "priceOk": price_ok,
                "availableQty": qty_left,
                "available": price_ok and qty_left > 0,
            })
        shops.append({
            "unitId": str(unit["_id"]),
            "ownerId": owner_id,
            "ownerName": (owner or {}).get("username", "Игрок"),
            "isOwn": owner_id == me,
            "items": items,
        })
    return {"ok": True, "shops": shops}


@router.post("/{unit_id}/gpu-shop/buy")
async def buy_gpu_shop_item(
    unit_id: str,
    payload: ComponentShopBuyBody,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Покупка товара опубликованного магазина игроком. Тело: {item, qty}.
    Порядок: проверки → атомарное списание компонентов со склада владельца
    (условный $inc: published, та же цена, остаток ≥ нужного) → списание у покупателя
    (adjust_balance отказывает при нехватке средств; склад откатывается) → зачисление
    владельцу. Обе стороны пишутся в ledger через record_transaction.
    Ошибки: 400 (правила/средства), 404 (нет магазина), 409 (остаток/цена изменились)."""
    from game_config import COMPONENT_COST
    buyer_id = str(current_user["_id"])
    unit = await _gpu_unit_any_owner(db, unit_id)
    owner_id = str(unit.get("userId") or "")
    if owner_id == buyer_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя покупать в собственном магазине")
    if not ObjectId.is_valid(owner_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Владелец магазина недоступен")
    owner = await db.users.find_one({"_id": ObjectId(owner_id)}, {"username": 1})
    if not owner:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Владелец магазина недоступен")

    raw = _gpu_shop_raw(unit)
    if not raw["published"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Магазин не опубликован")
    price = raw["items"].get(payload.item)
    if price is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Товара нет в магазине")
    econ = await get_econ(db)
    cost = _gpu_cost_with(unit, payload.item, econ)
    if price <= cost:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Товар недоступен: цена {price:g} $ не выше себестоимости {cost:g} $")

    components = COMPONENT_COST[payload.item]
    need = components * payload.qty
    total = round(price * payload.qty, 2)
    cost_total = round(cost * payload.qty, 2)
    profit = round(total - cost_total, 2)
    comp_key = f"prod.storage.{COMPONENT_RESOURCE}"

    # 1) Атомарно списываем компоненты со склада владельца. Условие гарантирует:
    #    магазин опубликован, цена не изменилась с проверки, остатка хватает.
    #    Две параллельные покупки не могут списать один и тот же остаток дважды.
    stock_doc = await db.user_assets.find_one_and_update(
        {
            "_id": unit["_id"],
            "prod.shop.published": True,
            f"prod.shop.items.{payload.item}": price,
            comp_key: {"$gte": float(need)},
        },
        {"$inc": {comp_key: -float(need)}},
        return_document=True,
    )
    if not stock_doc:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Недостаточно товара или магазин/цена изменились — обновите список")

    async def _restore_stock() -> None:
        await db.user_assets.update_one({"_id": unit["_id"]}, {"$inc": {comp_key: float(need)}})

    # 2) Списание у покупателя: adjust_balance атомарно отказывает при нехватке средств.
    buyer_balance = await adjust_balance(db, buyer_id, -total)
    if buyer_balance is None:
        await _restore_stock()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

    # 3) Зачисление выручки владельцу (владелец проверен выше).
    owner_balance = await adjust_balance(db, owner_id, total)
    if owner_balance is None:
        # Сбой после списания: возвращаем покупателю и склад через adjust_balance/$inc.
        await adjust_balance(db, buyer_id, total)
        await _restore_stock()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ошибка зачисления владельцу")

    owner_name = owner.get("username", "Игрок")
    buyer_name = current_user.get("username", "Игрок")
    meta = {"unitId": str(unit["_id"]), "item": payload.item, "qty": payload.qty,
            "components": need, "unitPrice": price, "costPrice": cost}
    await record_transaction(
        db, buyer_id, EXPENSE, total, CAT_SHOP,
        f"Покупка «Квантум GPU»: {payload.item} × {payload.qty}",
        counterparty=owner_name,
        balance_after=buyer_balance,
        meta={**meta, "sellerId": owner_id},
    )
    await record_transaction(
        db, owner_id, INCOME, total, CAT_FACTORY,
        f"Продажа в магазине «Квантум GPU»: {payload.item} × {payload.qty}",
        counterparty=buyer_name,
        balance_after=owner_balance,
        meta={**meta, "buyerId": buyer_id, "revenue": total, "cost": cost_total, "profit": profit},
    )
    left = float(((stock_doc.get("prod") or {}).get("storage") or {}).get(COMPONENT_RESOURCE, 0.0))
    return {
        "ok": True,
        "item": payload.item,
        "qty": payload.qty,
        "amount": total,
        "ownerProfit": profit,
        "warehouseLeft": left,
        "balance": buyer_balance,
    }


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

    gpu_plant_check = {"type": "factory", "price": 250000, "employees": 24,
                       "meta": {"produces": "gpu", "outputPerHour": 4, "capacity": 20000}}
    pg = _prod_state(gpu_plant_check)
    pg["workers"] = 24
    pg["food"] = 100.0
    pg["storage"] = {"metal": 100.0, "copper": 100.0, "bronze": 100.0, "processed_wood": 100.0}
    _apply_production(gpu_plant_check, pg, 1.0)
    assert pg["storage"]["component"] == 4.0, pg["storage"]
    assert pg["storage"]["metal"] == 84.0 and pg["storage"]["copper"] == 92.0, pg["storage"]
    pg2 = _prod_state(gpu_plant_check)
    pg2["workers"] = 24
    pg2["food"] = 100.0
    pg2["storage"] = {"metal": 100.0, "copper": 100.0, "bronze": 0.0, "processed_wood": 100.0}
    _apply_production(gpu_plant_check, pg2, 1.0)
    assert "component" not in pg2["storage"], pg2["storage"]

    # Погрузка: сначала большие стаки, в пределах грузоподъёмности.
    store = {"wood": 300.0, "metal": 1000.0}
    cargo = _load_cargo(store, 500.0)
    assert cargo == {"metal": 500.0}, cargo
    assert store == {"metal": 500.0, "wood": 300.0}

    # Цены: хлеб 30 × economy_mult=1.
    econ = {"economy_mult": 1.0}
    assert _resource_price("bread", econ) == RESOURCES_BY_ID["bread"]["base_price"]
    assert _food_unit_price(econ) == RESOURCES_BY_ID["bread"]["base_price"]
    assert _resource_price("nope", econ) == 0.0

    print("production self-check OK")


# ── Миграция купленной инфраструктуры под новые каталоги ─────────────────────
# Разовая (ключ production_rework_v1): подтягивает price/meta старых купленных
# активов к каталогу — иначе цены апгрейда и ёмкости остаются устаревшими.


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
