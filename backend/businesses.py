"""Операционное управление бизнесами игроков.

Актив остаётся главным объектом владения, а этот модуль хранит управляемые
состояния предприятия в нём же. Благодаря этому данные автоматически
переживают перезапуск MongoDB-клиента и видны администратору вместе с активом.
"""
from __future__ import annotations

import secrets
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator
from pymongo import ReturnDocument

from assets import (
    TYPE_BUSINESS, TYPE_CAR, _current_value, _income_per_hour, _upkeep_per_hour,
    _serialize, effective_catalog, effective_catalog_item,
)
from auth import get_current_user
from database import get_db
from ledger import CAT_BUSINESS, EXPENSE, INCOME, adjust_balance, record_transaction
from timeutil import now_utc

router = APIRouter(prefix="/api/businesses", tags=["business-management"])
_now = now_utc
MAX_TAXI_ACCRUAL_HOURS = 24
FUEL_PRICE = 4.5


class EmployeeCreate(BaseModel):
    name: str
    role: str = "worker"
    salary: float

    @field_validator("name")
    @classmethod
    def name_ok(cls, value):
        value = (value or "").strip()
        if len(value) < 2:
            raise ValueError("Имя сотрудника слишком короткое")
        return value[:40]

    @field_validator("salary")
    @classmethod
    def salary_ok(cls, value):
        if value <= 0 or value > 1_000_000:
            raise ValueError("Некорректная зарплата")
        return round(float(value), 2)


class EmployeeSalary(BaseModel):
    salary: float

    @field_validator("salary")
    @classmethod
    def salary_ok(cls, value):
        if value <= 0 or value > 1_000_000:
            raise ValueError("Некорректная зарплата")
        return round(float(value), 2)


class FleetBuy(BaseModel):
    slug: str


class FleetAttach(BaseModel):
    assetId: str


class FleetAssignment(BaseModel):
    vehicleId: str
    employeeId: str


class FleetVehicleAction(BaseModel):
    vehicleId: str
    amount: Optional[float] = None


async def _owned_business(db, user_id: str, asset_id: str) -> dict:
    if not ObjectId.is_valid(asset_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID бизнеса")
    asset = await db.user_assets.find_one({
        "_id": ObjectId(asset_id), "userId": user_id, "type": TYPE_BUSINESS,
    })
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Бизнес не найден")
    return asset


def _staff(asset: dict) -> list[dict]:
    return asset.get("staff") if isinstance(asset.get("staff"), list) else []


async def _property_effects(db, user_id: str) -> dict:
    totals: dict = {}
    async for asset in db.user_assets.find({
        "userId": user_id, "type": {"$in": ["realestate", TYPE_BUSINESS]},
        "companyId": None,
    }, {"meta": 1}):
        for key, value in (asset.get("meta", {}).get("effect", {}) or {}).items():
            totals[key] = totals.get(key, 0) + float(value or 0)
    return totals


async def _taxi_capacity(db, business: dict) -> int:
    effects = await _property_effects(db, business["userId"])
    return (
        int(business.get("meta", {}).get("effect", {}).get("taxiBaseSlots", 3))
        + (int(business.get("level", 1)) - 1) * 2
        + int(effects.get("taxiSlots", 0))
    )


def _vehicle_view(vehicle: dict, employees: list[dict]) -> dict:
    meta = vehicle.get("meta", {})
    driver = next((x for x in employees if x.get("id") == vehicle.get("driverId")), None)
    return {
        "id": str(vehicle["_id"]),
        "name": vehicle.get("name"),
        "slug": vehicle.get("slug"),
        "value": _current_value(vehicle),
        "condition": round(float(vehicle.get("condition", 100)), 1),
        "fuel": round(float(vehicle.get("fuel", 100)), 1),
        "driver": {"id": driver.get("id"), "name": driver.get("name")} if driver else None,
        "incomePerHour": meta.get("taxiIncomePerHour", 0),
        "fuelPerHour": meta.get("fuelPerHour", 0),
        "totalEarnings": round(float(vehicle.get("taxiEarnings", 0)), 2),
        "operatingHours": round(float(vehicle.get("taxiHours", 0)), 1),
        "lastCollected": vehicle.get("lastTaxiCollected").isoformat()
        if hasattr(vehicle.get("lastTaxiCollected"), "isoformat") else None,
    }


def _taxi_period(vehicle: dict, driver: Optional[dict], elapsed_hours: float,
                 fuel_discount: float = 0.0) -> dict:
    """Чистая формула периода для тестирования и серверного расчёта."""
    meta = vehicle.get("meta", {})
    condition_factor = max(0.25, float(vehicle.get("condition", 100)) / 100)
    fuel_per_hour = max(0.01, float(meta.get("fuelPerHour", 0)))
    available_fuel = max(0, float(vehicle.get("fuel", 100)))
    hours = min(elapsed_hours, available_fuel / fuel_per_hour) if driver else 0
    fuel_used = min(available_fuel, fuel_per_hour * hours)
    gross = float(meta.get("taxiIncomePerHour", 0)) * hours * condition_factor
    fuel_cost = fuel_used * FUEL_PRICE * (1 - min(0.5, fuel_discount))
    driver_cost = float(driver.get("salary", 0)) * hours if driver else 0
    repair_reserve = gross * 0.08
    return {
        "hours": hours,
        "fuelUsed": fuel_used,
        "gross": gross,
        "fuelCost": fuel_cost,
        "driverCost": driver_cost,
        "net": round(max(0, gross - fuel_cost - driver_cost - repair_reserve), 2),
        "condition": max(20, float(vehicle.get("condition", 100)) - hours * 0.18),
    }


async def _settle_taxi(db, business: dict) -> dict:
    """Начисляет доход каждой машине ровно один раз за расчётный период."""
    employees = _staff(business)
    total = 0.0
    effects = await _property_effects(db, business["userId"])
    fuel_discount = min(0.5, effects.get("taxiFuelDiscountPct", 0))
    async for vehicle in db.user_assets.find({
        "userId": business["userId"], "businessId": str(business["_id"]), "type": TYPE_CAR,
    }):
        last = vehicle.get("lastTaxiCollected") or vehicle.get("purchased_at") or _now()
        if last.tzinfo is None:
            last = last.replace(tzinfo=_now().tzinfo)
        elapsed_hours = min(MAX_TAXI_ACCRUAL_HOURS, max(0, (_now() - last).total_seconds() / 3600))
        driver = next((x for x in employees if x.get("id") == vehicle.get("driverId")), None)
        available_fuel = max(0, float(vehicle.get("fuel", 100)))
        period = _taxi_period(vehicle, driver, elapsed_hours, fuel_discount)
        hours = period["hours"]
        net = period["net"]
        settled_at = _now()
        matched = await db.user_assets.update_one(
            {"_id": vehicle["_id"], "lastTaxiCollected": vehicle.get("lastTaxiCollected")},
            {
                "$set": {
                    "lastTaxiCollected": settled_at,
                    "fuel": round(max(0, available_fuel - period["fuelUsed"]), 2),
                    "condition": round(period["condition"], 2),
                },
                "$inc": {"taxiEarnings": net, "taxiHours": hours},
            },
        )
        if matched.modified_count == 0:
            continue
        total += net
        if net or hours:
            await db.business_operations.insert_one({
                "businessId": str(business["_id"]), "userId": business["userId"],
                "type": "taxi_trip", "amount": net, "vehicleId": str(vehicle["_id"]),
                "gross": round(period["gross"], 2), "fuelCost": round(period["fuelCost"], 2),
                "driverCost": round(period["driverCost"], 2), "hours": round(hours, 2),
                "createdAt": settled_at,
            })
    if total:
        await db.user_assets.update_one(
            {"_id": business["_id"]},
            {"$inc": {"businessBalance": round(total, 2), "lifetimeProfit": round(total, 2)}},
        )
    updated = await db.user_assets.find_one({"_id": business["_id"]})
    return updated or business


async def _dashboard(db, business: dict) -> dict:
    if business.get("slug") == "taxi_fleet":
        business = await _settle_taxi(db, business)
    staff = _staff(business)
    vehicles = [x async for x in db.user_assets.find({
        "userId": business["userId"], "businessId": str(business["_id"]), "type": TYPE_CAR,
    })]
    effects = await _property_effects(db, business["userId"])
    car_discount = min(0.5, effects.get("carPurchaseDiscountPct", 0))
    vehicle_catalog = []
    if business.get("slug") == "taxi_fleet":
        vehicle_catalog = [{
            "slug": x["slug"], "name": x["name"],
            "price": round(float(x["price"]) * (1 - car_discount), 2),
            "incomePerHour": x.get("meta", {}).get("taxiIncomePerHour", 0),
            "fuelPerHour": x.get("meta", {}).get("fuelPerHour", 0),
        } for x in await effective_catalog(db) if x.get("type") == TYPE_CAR]
    return {
        "business": _serialize(business),
        "balance": round(float(business.get("businessBalance", 0)), 2),
        "lifetimeProfit": round(float(business.get("lifetimeProfit", 0)), 2),
        "employees": [{
            "id": x.get("id"), "name": x.get("name"), "role": x.get("role"),
            "salary": x.get("salary", 0), "hiredAt": x.get("hired_at").isoformat()
            if hasattr(x.get("hired_at"), "isoformat") else None,
        } for x in staff],
        "employeeCapacity": int(business.get("employees", 0)) + int((business.get("level", 1) - 1) * 3)
                            + int(effects.get("employeeSlots", 0)),
        "vehicleCapacity": await _taxi_capacity(db, business) if business.get("slug") == "taxi_fleet" else 0,
        "vehicleCatalog": vehicle_catalog,
        "vehicles": [_vehicle_view(x, staff) for x in vehicles],
        "stats": {
            "incomePerHour": _income_per_hour(business),
            "upkeepPerHour": _upkeep_per_hour(business),
            "profitPerHour": round(_income_per_hour(business) - _upkeep_per_hour(business), 2),
            "level": business.get("level", 1),
            "mechanic": business.get("meta", {}).get("mechanic"),
            "metric": business.get("meta", {}).get("metric"),
        },
    }


@router.get("/{asset_id}/dashboard")
async def business_dashboard(asset_id: str, current_user=Depends(get_current_user),
                             db: AsyncIOMotorDatabase = Depends(get_db)):
    return await _dashboard(db, await _owned_business(db, str(current_user["_id"]), asset_id))


@router.post("/{asset_id}/employees")
async def hire_employee(asset_id: str, payload: EmployeeCreate, current_user=Depends(get_current_user),
                        db: AsyncIOMotorDatabase = Depends(get_db)):
    business = await _owned_business(db, str(current_user["_id"]), asset_id)
    staff = _staff(business)
    effects = await _property_effects(db, str(current_user["_id"]))
    capacity = int(business.get("employees", 0)) + (int(business.get("level", 1)) - 1) * 3 \
               + int(effects.get("employeeSlots", 0))
    if len(staff) >= capacity:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Достигнут лимит сотрудников")
    employee = {"id": secrets.token_hex(8), "name": payload.name, "role": payload.role,
                "salary": payload.salary, "hired_at": _now()}
    await db.user_assets.update_one({"_id": business["_id"]}, {"$push": {"staff": employee}})
    await db.business_operations.insert_one({
        "businessId": asset_id, "userId": str(current_user["_id"]),
        "type": "hire", "employeeId": employee["id"], "createdAt": _now(),
    })
    return await _dashboard(db, await _owned_business(db, str(current_user["_id"]), asset_id))


@router.delete("/{asset_id}/employees/{employee_id}")
async def fire_employee(asset_id: str, employee_id: str, current_user=Depends(get_current_user),
                        db: AsyncIOMotorDatabase = Depends(get_db)):
    business = await _owned_business(db, str(current_user["_id"]), asset_id)
    if not any(x.get("id") == employee_id for x in _staff(business)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    await db.user_assets.update_one({"_id": business["_id"]}, {"$pull": {"staff": {"id": employee_id}}})
    await db.user_assets.update_many({"businessId": asset_id, "driverId": employee_id},
                                     {"$unset": {"driverId": ""}})
    return await _dashboard(db, await _owned_business(db, str(current_user["_id"]), asset_id))


@router.patch("/{asset_id}/employees/{employee_id}")
async def update_employee_salary(asset_id: str, employee_id: str, payload: EmployeeSalary,
                                 current_user=Depends(get_current_user),
                                 db: AsyncIOMotorDatabase = Depends(get_db)):
    business = await _owned_business(db, str(current_user["_id"]), asset_id)
    staff = _staff(business)
    if not any(x.get("id") == employee_id for x in staff):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    await db.user_assets.update_one(
        {"_id": business["_id"], "staff.id": employee_id},
        {"$set": {"staff.$.salary": payload.salary}},
    )
    return await _dashboard(db, await _owned_business(db, str(current_user["_id"]), asset_id))


@router.post("/{asset_id}/withdraw")
async def withdraw_business_balance(asset_id: str, current_user=Depends(get_current_user),
                                    db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    business = await _owned_business(db, user_id, asset_id)
    business = await _settle_taxi(db, business) if business.get("slug") == "taxi_fleet" else business
    claimed = await db.user_assets.find_one_and_update(
        {"_id": business["_id"], "businessBalance": {"$gt": 0}},
        {"$set": {"businessBalance": 0}},
        return_document=ReturnDocument.BEFORE,
    )
    amount = round(float((claimed or {}).get("businessBalance", 0)), 2)
    if amount <= 0:
        return {"withdrawn": 0, "balance": current_user.get("balance", 0)}
    new_balance = await adjust_balance(db, user_id, amount)
    await record_transaction(db, user_id, INCOME, amount, CAT_BUSINESS,
                             f"Вывод прибыли: {business.get('name')}",
                             balance_after=new_balance, meta={"assetId": asset_id})
    return {"withdrawn": amount, "balance": new_balance}


@router.post("/{asset_id}/fleet/buy", status_code=status.HTTP_201_CREATED)
async def buy_fleet_vehicle(asset_id: str, payload: FleetBuy, current_user=Depends(get_current_user),
                            db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    business = await _owned_business(db, user_id, asset_id)
    if business.get("slug") != "taxi_fleet":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Автопарк доступен только таксопарку")
    car = await effective_catalog_item(db, payload.slug)
    if not car or car.get("type") != TYPE_CAR:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Автомобиль не найден")
    count = await db.user_assets.count_documents({"businessId": asset_id, "type": TYPE_CAR})
    capacity = await _taxi_capacity(db, business)
    if count >= capacity:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет свободных мест в автопарке")
    effects = await _property_effects(db, user_id)
    price = round(float(car["price"]) * (1 - min(0.5, effects.get("carPurchaseDiscountPct", 0))), 2)
    new_balance = await adjust_balance(db, user_id, -price)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
    doc = {
        "userId": user_id, "businessId": asset_id, "slug": car["slug"], "type": TYPE_CAR,
        "name": car["name"], "rarity": car.get("rarity"), "price": price,
        "income_per_hour": 0, "upkeep_per_hour": 0, "level": 1, "meta": car.get("meta", {}),
        "condition": 100, "fuel": 100, "driverId": None, "lastTaxiCollected": _now(),
        "rental": None, "companyId": None, "purchased_at": _now(),
    }
    result = await db.user_assets.insert_one(doc)
    doc["_id"] = result.inserted_id
    await record_transaction(db, user_id, EXPENSE, price, CAT_BUSINESS,
                             f"Автомобиль в таксопарк: {car['name']}",
                             balance_after=new_balance, meta={"businessId": asset_id, "slug": car["slug"]})
    return {"vehicle": _vehicle_view(doc, _staff(business)), "balance": new_balance}


@router.post("/{asset_id}/fleet/attach")
async def attach_fleet_vehicle(asset_id: str, payload: FleetAttach, current_user=Depends(get_current_user),
                               db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    business = await _owned_business(db, user_id, asset_id)
    if business.get("slug") != "taxi_fleet" or not ObjectId.is_valid(payload.assetId):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный автомобиль")
    vehicle = await db.user_assets.find_one({"_id": ObjectId(payload.assetId), "userId": user_id,
                                             "type": TYPE_CAR, "businessId": None})
    if not vehicle:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Личный автомобиль не найден")
    count = await db.user_assets.count_documents({"businessId": asset_id, "type": TYPE_CAR})
    if count >= await _taxi_capacity(db, business):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет свободных мест в автопарке")
    await db.user_assets.update_one({"_id": vehicle["_id"]},
                                    {"$set": {"businessId": asset_id, "lastTaxiCollected": _now(),
                                              "condition": vehicle.get("condition", 100), "fuel": 100}})
    return await _dashboard(db, await _owned_business(db, user_id, asset_id))


@router.post("/{asset_id}/fleet/assign")
async def assign_fleet_vehicle(asset_id: str, payload: FleetAssignment, current_user=Depends(get_current_user),
                               db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    business = await _owned_business(db, user_id, asset_id)
    if not any(x.get("id") == payload.employeeId and x.get("role") in ("driver", "worker")
               for x in _staff(business)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Сотрудник не может водить автомобиль")
    if not ObjectId.is_valid(payload.vehicleId):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный автомобиль")
    await db.user_assets.update_many(
        {"businessId": asset_id, "driverId": payload.employeeId},
        {"$unset": {"driverId": ""}},
    )
    result = await db.user_assets.update_one({"_id": ObjectId(payload.vehicleId), "businessId": asset_id,
                                              "type": TYPE_CAR}, {"$set": {"driverId": payload.employeeId}})
    if not result.modified_count:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Автомобиль не найден")
    return await _dashboard(db, await _owned_business(db, user_id, asset_id))


@router.post("/{asset_id}/fleet/repair")
async def repair_fleet_vehicle(asset_id: str, payload: FleetVehicleAction, current_user=Depends(get_current_user),
                               db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    business = await _owned_business(db, user_id, asset_id)
    if not ObjectId.is_valid(payload.vehicleId):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный автомобиль")
    vehicle = await db.user_assets.find_one({"_id": ObjectId(payload.vehicleId), "businessId": asset_id})
    if not vehicle:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Автомобиль не найден")
    points = max(1, min(100, float(payload.amount or 100 - vehicle.get("condition", 100))))
    effects = await _property_effects(db, user_id)
    discount = min(0.5, effects.get("carRepairDiscountPct", 0) + effects.get("carServiceDiscountPct", 0))
    cost = round(float(vehicle.get("price", 0)) * 0.003 * points * (1 - discount), 2)
    new_balance = await adjust_balance(db, user_id, -cost)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
    await db.user_assets.update_one({"_id": vehicle["_id"]},
                                    {"$set": {"condition": min(100, vehicle.get("condition", 100) + points)}})
    await record_transaction(db, user_id, EXPENSE, cost, CAT_BUSINESS, "Ремонт автомобиля",
                             balance_after=new_balance, meta={"businessId": asset_id, "vehicleId": payload.vehicleId})
    return {"balance": new_balance, **await _dashboard(db, await _owned_business(db, user_id, asset_id))}


@router.post("/{asset_id}/fleet/refuel")
async def refuel_fleet_vehicle(asset_id: str, payload: FleetVehicleAction, current_user=Depends(get_current_user),
                               db: AsyncIOMotorDatabase = Depends(get_db)):
    user_id = str(current_user["_id"])
    business = await _owned_business(db, user_id, asset_id)
    if not ObjectId.is_valid(payload.vehicleId):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный автомобиль")
    vehicle = await db.user_assets.find_one({"_id": ObjectId(payload.vehicleId), "businessId": asset_id})
    if not vehicle:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Автомобиль не найден")
    liters = max(1, min(100, float(payload.amount or 100 - vehicle.get("fuel", 100))))
    effects = await _property_effects(db, user_id)
    cost = round(liters * FUEL_PRICE * (1 - min(0.5, effects.get("taxiFuelDiscountPct", 0))), 2)
    new_balance = await adjust_balance(db, user_id, -cost)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
    await db.user_assets.update_one({"_id": vehicle["_id"]},
                                    {"$set": {"fuel": min(100, vehicle.get("fuel", 100) + liters)}})
    return {"balance": new_balance, **await _dashboard(db, await _owned_business(db, user_id, asset_id))}


@router.get("/{asset_id}/history")
async def business_history(asset_id: str, current_user=Depends(get_current_user),
                           db: AsyncIOMotorDatabase = Depends(get_db)):
    business = await _owned_business(db, str(current_user["_id"]), asset_id)
    rows = [x async for x in db.business_operations.find({"businessId": str(business["_id"])}).sort("createdAt", -1).limit(100)]
    for row in rows:
        row["id"] = str(row.pop("_id"))
        if hasattr(row.get("createdAt"), "isoformat"):
            row["createdAt"] = row["createdAt"].isoformat()
    return rows
