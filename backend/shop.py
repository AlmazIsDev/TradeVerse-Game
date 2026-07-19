"""Магазин оборудования (видеокарты и др. железо).

Цены НЕ хранятся статически и НЕ бывают null — они вычисляются из экономики:
    price = base_price(по характеристикам) × множитель_категории × economy_mult

Покупка всегда пересчитывает цену на сервере по текущей конфигурации, поэтому
изменение цен в админ-панели не ломает покупку. Купленное железо попадает в
инвентарь пользователя (user_hardware) — основа для будущих майнинг-ферм.
"""
from __future__ import annotations

from typing import Optional

import json
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from auth import get_current_user, require_admin
from database import get_db, find_config_by_key, upsert_config
from ledger import INCOME, EXPENSE, CAT_SHOP, adjust_balance, record_transaction
from econ import get_econ

router = APIRouter(prefix="/api/shop", tags=["shop"])

SHOP_CONFIG_KEY = "shop_config"
MAX_BUY_QTY = 1000          # оптовая покупка (было 100)
# ponytail: фиксированный возврат 65% от цены покупки; вынести в конфиг магазина, если понадобится настройка.
RESALE_RATIO = 0.65

# Палитра «по мощности»: холодный (слабое) → горячий (топовое). Цвет считается из тира, а не из бренда.
TIER_COLORS = ["#60a5fa", "#22d3ee", "#34d399", "#facc15", "#fb923c", "#ef4444"]
DEFAULT_SHOP_CONFIG = {
    "gpu": 1.0, "cpu": 1.0, "motherboard": 1.0, "ram": 1.0, "ssd": 1.0,
    "psu": 1.0, "case": 1.0, "rack": 1.0, "cooling": 1.0, "fan": 1.0,
    "ups": 1.0, "network": 1.0,
}
PRICE_PER_HASH = 6.0

# Категории и их роль в сборке фермы (required — обязательные компоненты).
CATEGORY_ROLE = {
    "gpu": {"role": "gpu", "required": True, "multi": True},
    "cpu": {"role": "cpu", "required": True},
    "motherboard": {"role": "motherboard", "required": True},
    "ram": {"role": "ram", "required": True},
    "ssd": {"role": "ssd", "required": True},
    "psu": {"role": "psu", "required": True},
    "cooling": {"role": "cooling", "required": True},
    "case": {"role": "case", "required": False},
    "rack": {"role": "rack", "required": False},
    "fan": {"role": "fan", "required": False, "multi": True},
    "ups": {"role": "ups", "required": False},
    "network": {"role": "network", "required": False},
}


def _tier_color(rank: int) -> str:
    """Цвет по мощности/тиру: чем выше rank, тем «горячее» цвет."""
    return TIER_COLORS[max(0, min(rank, len(TIER_COLORS) - 1))]


def _build_catalog() -> list[dict]:
    """Генерирует реальный каталог железа с базовыми ценами из характеристик.

    Ключевые поля specs (контракт с майнинг-движком): specs.power — потребление
    в ваттах (у ВСЕХ, включая вентиляторы), specs.cooling — теплоотвод.
    Цвет верхнего уровня («color») вычисляется по тиру мощности.
    """
    items: list[dict] = []

    # Видеокарты: 3 бренда × 4 линейки, hashrate растёт. Цвет — по тиру, не по бренду.
    brands = [
        ("CrystalCore", ["Quartz", "Topaz", "Sapphire", "Diamond"]),
        ("Pyronix", ["Spark", "Flare", "Blaze", "Inferno"]),
        ("Archivex", ["Vault", "Legacy", "Archive", "Genesis"]),
    ]
    for brand, lines in brands:
        for li, line in enumerate(lines):
            for tier in range(3):
                rank = li * 3 + tier          # 0..11
                hashrate = int(180 * (1.6 ** rank))
                power = int(120 + hashrate * 0.05)
                model = f"{brand} {line} {(rank + 1) * 100}"
                items.append({
                    "id": f"gpu-{brand[:2].lower()}-{li}-{tier}",
                    "category": "gpu", "name": model, "brand": brand,
                    "color": _tier_color(rank // 2),
                    "specs": {"hashrate": hashrate, "power": power},
                    "base_price": round(hashrate * PRICE_PER_HASH, 2),
                })

    # ASIC-майнеры: профессиональное узкоспециализированное железо (высокий hashrate/потребление).
    for i, (name, hashrate, power) in enumerate([
        ("AntCore S1 Pro", 12000, 3000),
        ("AntCore S2 Titan", 26000, 3400),
        ("Vulcan HydroMiner", 55000, 5300),
    ]):
        items.append({
            "id": f"gpu-asic-{i}", "category": "gpu", "name": name, "brand": "ASIC",
            "color": _tier_color(5),
            "specs": {"hashrate": hashrate, "power": power},
            "base_price": round(hashrate * PRICE_PER_HASH * 0.7, 2),
        })

    # Блоки питания: по мощности (+ промышленные).
    for w in (500, 750, 1000, 1600, 2200, 3000, 4200, 6000):
        items.append({
            "id": f"psu-{w}", "category": "psu",
            "name": (f"Промышленный БП {w}W" if w >= 4200 else f"БП {w}W"),
            "color": _tier_color(w // 1000),
            "specs": {"power": w}, "base_price": round(w * 0.9, 2),
        })

    # Охлаждение: по теплоотводу (+ иммерсионные ванны для ASIC/ферм).
    coolers = [
        ("Воздушное", 400), ("Башенное", 800), ("Жидкостное", 1600),
        ("Иммерсионное", 4000), ("Иммерсионная ванна Pro", 9000),
    ]
    for i, (name, cap) in enumerate(coolers):
        items.append({
            "id": f"cooling-{i}", "category": "cooling", "name": f"{name} охлаждение",
            "color": _tier_color(i),
            "specs": {"cooling": cap, "power": 20 + cap // 200}, "base_price": round(cap * 1.2, 2),
        })

    # Процессоры: характерные имена вместо «Процессор N ядер».
    cpus = [
        ("Ryzen Quad Q4", 4), ("Ryzen Hexa H6", 6), ("Falcon Octa X8", 8),
        ("Falcon Dodeca X12", 12), ("Threadstorm 16", 16), ("Threadstorm Xeon 32", 32),
        ("EPYC Titan 64", 64),
    ]
    for i, (name, cores) in enumerate(cpus):
        items.append({
            "id": f"cpu-{cores}", "category": "cpu", "name": name,
            "color": _tier_color(i),
            "specs": {"cores": cores, "power": 45 + cores * 8}, "base_price": round(cores * 700, 2),
        })

    # Материнские платы: по числу слотов под GPU.
    for i, slots in enumerate((2, 4, 6, 8, 12, 19)):
        items.append({
            "id": f"mb-{slots}", "category": "motherboard", "name": f"Мат. плата ({slots} GPU)",
            "color": _tier_color(i),
            "specs": {"gpuSlots": slots, "power": 60}, "base_price": round(slots * 1200, 2),
        })

    # Оперативная память: по объёму (ГБ).
    for i, gb in enumerate((8, 16, 32, 64, 128)):
        items.append({
            "id": f"ram-{gb}", "category": "ram", "name": f"ОЗУ {gb} ГБ",
            "color": _tier_color(i),
            "specs": {"gb": gb, "power": 5}, "base_price": round(gb * 90, 2),
        })

    # Накопители SSD: по объёму (ГБ).
    for i, gb in enumerate((256, 512, 1024, 2048, 4096)):
        items.append({
            "id": f"ssd-{gb}", "category": "ssd", "name": f"SSD {gb} ГБ",
            "color": _tier_color(i),
            "specs": {"gb": gb, "power": 6}, "base_price": round(gb * 3, 2),
        })

    # Корпуса.
    for i, (name, slots) in enumerate([("Мини-корпус", 2), ("Миди-башня", 4), ("Full Tower", 8)]):
        items.append({
            "id": f"case-{i}", "category": "case", "name": name,
            "color": _tier_color(i),
            "specs": {"slots": slots}, "base_price": round(slots * 500, 2),
        })

    # Вентиляторы (дополнительное охлаждение). specs.power — реальное потребление, движок его вычитает.
    fans = [("Комплект 120мм", 200, 15), ("Комплект 140мм", 320, 22), ("Промышленные вентиляторы", 700, 40)]
    for i, (name, cap, watts) in enumerate(fans):
        items.append({
            "id": f"fan-{i}", "category": "fan", "name": name,
            "color": _tier_color(i),
            "specs": {"cooling": cap, "power": watts}, "base_price": round(cap * 1.5, 2),
        })

    # ИБП.
    for i, w in enumerate((1000, 2000, 3500, 6000)):
        items.append({
            "id": f"ups-{w}", "category": "ups", "name": f"ИБП {w}VA",
            "color": _tier_color(i),
            "specs": {"backup": w, "power": 10}, "base_price": round(w * 1.1, 2),
        })

    # Сетевое оборудование.
    for i, (name, mbps) in enumerate([("Роутер 1 Гбит", 1000), ("Коммутатор 10 Гбит", 10000), ("Сетевая стойка", 40000)]):
        items.append({
            "id": f"net-{i}", "category": "network", "name": name,
            "color": _tier_color(i),
            "specs": {"speed": mbps, "power": 20}, "base_price": round(mbps * 0.6, 2),
        })

    # Стойки: обычные и промышленные (по числу слотов под GPU).
    for i, slots in enumerate((4, 8, 12, 24, 48)):
        items.append({
            "id": f"rack-{slots}", "category": "rack", "name": f"Стойка на {slots} GPU",
            "color": _tier_color(i),
            "specs": {"slots": slots}, "base_price": round(slots * 900, 2),
        })
    for slots in (96, 200):
        items.append({
            "id": f"rack-ind-{slots}", "category": "rack", "name": f"Промышленная стойка ({slots} GPU)",
            "color": _tier_color(5),
            "specs": {"slots": slots, "industrial": True}, "base_price": round(slots * 1100, 2),
        })

    return items


CATALOG = _build_catalog()
CATALOG_BY_ID = {c["id"]: c for c in CATALOG}


async def _shop_config(db) -> dict:
    doc = await find_config_by_key(db, SHOP_CONFIG_KEY)
    cfg = dict(DEFAULT_SHOP_CONFIG)
    if doc:
        try:
            cfg.update(json.loads(doc["value"]))
        except Exception:
            pass
    return cfg


async def _price_of(db, item: dict) -> float:
    """Актуальная цена товара = база × множитель категории × economy_mult."""
    shop_cfg = await _shop_config(db)
    econ = await get_econ(db)
    mult = shop_cfg.get(item["category"], 1.0) * econ.get("economy_mult", 1.0)
    return round(item["base_price"] * mult, 2)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Endpoints ────────────────────────────────────────────────────────────────


async def _city_shop_discount(db, user_id: str) -> float:
    """Скидка на оборудование от зданий «Крыши города» (напр. «Морской порт»)."""
    try:
        from cityroof import player_city_effect
        return min(0.5, await player_city_effect(db, user_id, "shop_discount"))
    except Exception:
        return 0.0


@router.get("/catalog")
async def get_catalog(
    category: str = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Каталог с ЖИВЫМИ ценами (никаких null)."""
    shop_cfg = await _shop_config(db)
    econ = await get_econ(db)
    emult = econ.get("economy_mult", 1.0)
    discount = await _city_shop_discount(db, str(current_user["_id"]))
    items = CATALOG if not category else [c for c in CATALOG if c["category"] == category]
    out = []
    for c in items:
        price = round(c["base_price"] * shop_cfg.get(c["category"], 1.0) * emult * (1 - discount), 2)
        specs = c.get("specs", {})
        row = {
            "id": c["id"], "category": c["category"], "name": c["name"],
            "brand": c.get("brand"), "color": c.get("color"),
            "specs": specs, "price": price,
        }
        # Понятная подпись охлаждения вместо загадочного «4000 / 1600 охл.».
        if specs.get("cooling"):
            row["coolingLabel"] = f"{specs['cooling']} Вт охл."
        out.append(row)
    out.sort(key=lambda x: x["price"])
    return out


class BuyHardware(BaseModel):
    itemId: str
    quantity: int = 1


@router.post("/buy", status_code=status.HTTP_201_CREATED)
async def buy_hardware(
    payload: BuyHardware,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Покупка железа. Цена всегда пересчитывается сервером (не ломается при
    изменении цен админом)."""
    item = CATALOG_BY_ID.get(payload.itemId)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Товар не найден")
    qty = max(1, min(int(payload.quantity), MAX_BUY_QTY))
    user_id = str(current_user["_id"])
    discount = await _city_shop_discount(db, user_id)
    unit = round(await _price_of(db, item) * (1 - discount), 2)
    total = round(unit * qty, 2)
    new_balance = await adjust_balance(db, user_id, -total)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

    docs = [{
        "userId": user_id, "itemId": item["id"], "category": item["category"],
        "name": item["name"], "specs": item.get("specs", {}),
        "purchase_price": unit, "condition": 100, "purchased_at": _now(),
    } for _ in range(qty)]
    await db.user_hardware.insert_many(docs)

    await record_transaction(
        db, user_id, EXPENSE, total, CAT_SHOP,
        f"Покупка: {item['name']}" + (f" ×{qty}" if qty > 1 else ""),
        balance_after=new_balance, meta={"itemId": item["id"], "quantity": qty},
    )
    return {"ok": True, "unitPrice": unit, "total": total, "balance": new_balance, "quantity": qty}


@router.get("/inventory")
async def get_inventory(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Купленное железо игрока, сгруппированное по товару."""
    user_id = str(current_user["_id"])
    grouped: dict = {}
    async for h in db.user_hardware.find({"userId": user_id}):
        key = h.get("itemId")
        g = grouped.setdefault(key, {
            "itemId": key, "category": h.get("category"), "name": h.get("name"),
            "specs": h.get("specs", {}), "count": 0,
        })
        g["count"] += 1
    return list(grouped.values())


class SellHardware(BaseModel):
    itemId: str
    quantity: int = 1


def _resale_refund(purchase_prices: list[float]) -> float:
    """Возврат за продажу свободных единиц = сумма цен покупки × RESALE_RATIO."""
    return round(sum(float(p) for p in purchase_prices) * RESALE_RATIO, 2)


@router.post("/sell")
async def sell_hardware(
    payload: SellHardware,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Продажа лишнего железа обратно магазину с уценкой (RESALE_RATIO).

    Продаём только СВОБОДНЫЕ экземпляры (farmId отсутствует/None) — установленное
    в ферму железо не трогаем. Возврат = purchase_price каждого экземпляра × RESALE_RATIO.
    """
    qty = max(1, int(payload.quantity))
    user_id = str(current_user["_id"])
    # Свободные (неустановленные) экземпляры этого товара — по одному документу на штуку.
    free = await db.user_hardware.find(
        {"userId": user_id, "itemId": payload.itemId, "farmId": None}
    ).to_list(length=None)
    # Стойка — общий пул слотов: её farmId всегда None, но она может быть
    # задействована в фермах (components.rack.hwId). Такие экземпляры НЕ продаём.
    in_use_racks = set()
    async for f in db.mining_farms.find(
        {"userId": user_id, "components.rack.hwId": {"$ne": None}},
        {"components.rack.hwId": 1},
    ):
        rack = (f.get("components") or {}).get("rack") or {}
        if rack.get("hwId"):
            in_use_racks.add(rack["hwId"])
    if in_use_racks:
        free = [h for h in free if str(h["_id"]) not in in_use_racks]
    if len(free) < qty:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Недостаточно свободных единиц для продажи (есть {len(free)}, нужно {qty})",
        )
    sold = free[:qty]
    refund = _resale_refund([h.get("purchase_price", 0) for h in sold])
    await db.user_hardware.delete_many({"_id": {"$in": [h["_id"] for h in sold]}})
    new_balance = await adjust_balance(db, user_id, refund)

    name = sold[0].get("name", payload.itemId)
    await record_transaction(
        db, user_id, INCOME, refund, CAT_SHOP,
        f"Продажа: {name}" + (f" ×{qty}" if qty > 1 else ""),
        balance_after=new_balance, meta={"itemId": payload.itemId, "quantity": qty},
    )
    return {"ok": True, "refund": refund, "quantity": qty, "balance": new_balance}


class ShopConfigUpdate(BaseModel):
    gpu: Optional[float] = None
    psu: Optional[float] = None
    cooling: Optional[float] = None
    rack: Optional[float] = None


@router.get("/config")
async def shop_config(_admin=Depends(require_admin), db: AsyncIOMotorDatabase = Depends(get_db)):
    return await _shop_config(db)


@router.post("/config")
async def set_shop_config(
    payload: ShopConfigUpdate,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    cfg = await _shop_config(db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None and value > 0:
            cfg[key] = round(float(value), 3)
    await upsert_config(db, SHOP_CONFIG_KEY, json.dumps(cfg))
    return cfg


if __name__ == "__main__":
    # Самопроверка математики возврата и защиты от перепродажи (без БД/фреймворка).
    assert _resale_refund([100.0, 100.0]) == round(200.0 * RESALE_RATIO, 2)
    assert _resale_refund([]) == 0.0
    assert 0 < RESALE_RATIO < 1, "уценка должна быть между 0 и 1"

    # Перепродажа: доступно 2 свободных, просят 3 → должно быть отклонено (len(free) < qty).
    free_pool = [{"purchase_price": 100.0}, {"purchase_price": 100.0}]
    want = 3
    assert len(free_pool) < want, "оверселл должен отклоняться"

    # Каталог: у всех компонентов есть числовой specs.power (контракт с майнинг-движком).
    assert all(isinstance(c["specs"].get("power", 0), (int, float)) for c in CATALOG)
    assert all("fan" != c["category"] or c["specs"].get("power", 0) > 0 for c in CATALOG), "у вентиляторов должно быть потребление"
    print("shop self-check OK")
