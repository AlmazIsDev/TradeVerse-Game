"""Магазин оборудования (видеокарты, процессоры, корпуса, расходники и др.).

Цены НЕ хранятся статически и НЕ бывают null — они вычисляются из экономики:
    base = admin_price (если задан в /api/admin/shop-prices) иначе item.base_price
    price = base × множитель_категории × economy_mult
    итоговая = price × (1 - скидка зданий «Крыши города»)

Покупка всегда пересчитывает цену на сервере, поэтому изменение цен в
админ-панели не ломает покупку. Купленное железо попадает в инвентарь
пользователя (user_hardware) — основа для майнинг-ферм.

Каталог состоит из двух слоёв:
  1) Базовый — gpu/cpu/psu/cooling/ram/ssd/case/fan/ups/network/asic
     + motherboard (мат. платы), теперь в общем каталоге.
     Идентификаторы (gpu-cc-0-0, psu-500, mb-2, …) обратно совместимы с
     существующими user_hardware и mining-движком.
  2) Админские серии — admin-gpu-N (1..90), admin-cpu-N (1..90),
     admin-case-N (1..20, до 5 GPU), admin-ram-N (1..20),
     admin-cooling-N (1..20), admin-psu-N (1..20),
     admin-mb-N (1..20, до 5 GPU), admin-ssd-N (1..20)
     + admin-supply-cooling-fluid, admin-supply-gpu-chip.
     Контракт имён: точно совпадают с frontend/src/utils/shopCatalog.js,
     поэтому покупка и инвентарь согласованы между фронтом и бэкендом.
"""
from __future__ import annotations

from typing import Optional

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from admin_perms import get_current_user, require_admin, require_allowed
from database import get_db, find_config_by_key, upsert_config
from ledger import INCOME, EXPENSE, CAT_SHOP, adjust_balance, record_transaction
from econ import get_econ
from assets import _admin_prices as _assets_admin_prices  # единая реализация

router = APIRouter(prefix="/api/shop", tags=["shop"])
admin_router = APIRouter(prefix="/api/admin/shop", tags=["shop-admin"])
# Legacy hyphenated URL alias.
alias_admin_router = APIRouter(prefix="/api/admin/shop-prices", tags=["shop-admin-alias"])

SHOP_CONFIG_KEY = "shop_config"
SHOP_PRICES_KEY = "shop_prices"   # админские цены {id: price|null}
MAX_BUY_QTY = 1000
RESALE_RATIO = 0.65
MAX_CASE_SLOTS = 5    # Лимит слотов корпуса; для больших сборок — стойки (rack)
MAX_MB_SLOTS = 60     # Жёсткий лимит слотов мат. платы (люксовая стойка 60 GPU)

# Палитра «по мощности»: холодный (слабое) → горячий (топовое).
TIER_COLORS = ["#60a5fa", "#22d3ee", "#34d399", "#facc15", "#fb923c", "#ef4444"]
DEFAULT_SHOP_CONFIG = {
    "gpu": 1.0, "cpu": 1.0, "motherboard": 1.0, "ram": 1.0, "ssd": 1.0,
    "psu": 1.0, "case": 1.0, "cooling": 1.0, "fan": 1.0,
    "ups": 1.0, "network": 1.0, "supplies": 1.0,
}
PRICE_PER_HASH = 6.0
ASIC_PRICE_RATIO = 0.45     # цена ASIC за хеш относительно GPU (см. каталог ниже)

CATEGORY_ROLE = {
    "gpu": {"role": "gpu", "required": True, "multi": True},
    "cpu": {"role": "cpu", "required": True},
    "motherboard": {"role": "motherboard", "required": True},
    "ram": {"role": "ram", "required": True},
    "ssd": {"role": "ssd", "required": True},
    "psu": {"role": "psu", "required": True, "multi": True},
    "cooling": {"role": "cooling", "required": True},
    "case": {"role": "case", "required": False},
    "rack": {"role": "rack", "required": False},
    "fan": {"role": "fan", "required": False, "multi": True},
    "ups": {"role": "ups", "required": False},
    "network": {"role": "network", "required": False},
    "supplies": {"role": "supplies", "required": False, "multi": True},
}


# ── helpers ──────────────────────────────────────────────────────────────────


def _tier_color(rank: int) -> str:
    return TIER_COLORS[max(0, min(rank, len(TIER_COLORS) - 1))]


def _gpu_power(h: int) -> int:
    return int(120 + h * 0.05)


def _cpu_power(mult: float) -> int:
    return int(round(45 + (mult or 1) * 25))


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Базовый каталог (обратная совместимость) ─────────────────────────────────


def _build_base_catalog() -> list[dict]:
    items: list[dict] = []

    # ASIC pricing reflects network-share saturation.
    for i, (name, hashrate, power) in enumerate([
        ("AntCore S1 Pro", 12000, 3000),
        ("AntCore S2 Titan", 26000, 3400),
        ("Vulcan HydroMiner", 55000, 5300),
    ]):
        items.append({
            "id": f"gpu-asic-{i}", "category": "gpu", "name": name, "brand": "ASIC",
            "color": _tier_color(5),
            "specs": {"hashrate": hashrate, "power": power},
            "base_price": round(hashrate * PRICE_PER_HASH * ASIC_PRICE_RATIO, 2),
        })

    # Voltronix extends the maximum farm hashrate; discounted per-hash pricing
    # accounts for network-share saturation.
    for i, (name, hashrate, price_per_hash) in enumerate([
        ("Voltronix Pulse V100", 40000, 5.25),
        ("Voltronix Storm V200", 55000, 5.0),
        ("Voltronix Quantum V300", 80000, 4.7),
    ]):
        items.append({
            "id": f"gpu-vlt-{i}", "category": "gpu", "name": name, "brand": "Voltronix",
            "color": _tier_color(5),
            "specs": {"hashrate": hashrate, "power": _gpu_power(hashrate)},
            "base_price": round(hashrate * price_per_hash, 2),
        })

    # Lux uses one proportional price-per-spec for each category; no brand markup.
    # Network-share saturation keeps the performance gain modest.
    _lux = [
        ("gpu", "Voltronix Zenith V900", {"hashrate": 150000, "power": 7620}, 150000 * 60.0),
        ("cpu", "Quantum Core Q64X", {"cores": 64, "power": 557}, round(64 * 7000 * 2.10, 2)),
        ("motherboard", "Apex Board X60", {"gpuSlots": 60, "power": 136}, 60 * 12000.0),
        ("ram", "ByteForge Singularity 4096GB", {"gb": 4096, "power": 261}, 4096 * 900.0),
        ("ssd", "SolidByte Infinity 65536GB", {"gb": 65536, "power": 6}, 65536 * 40.0),
        ("cooling", "Криогенный контур «Гелиос»", {"cooling": 600000, "power": 3002}, 600000 * 12.0),
        ("psu", "AmpereX Galaxy 25000W", {"power": 25000}, 25000 * 9.0),
        ("ups", "ИБП Terra 1 MVA", {"backup": 1000000, "power": 510}, 1000000 * 11.0),
        ("rack", "Гиперстойка 300U", {"slots": 300}, 300 * 12000.0),
    ]
    for cat, name, specs, price in _lux:
        items.append({
            "id": f"lux-{cat}", "category": cat, "name": name,
            "brand": "Lux", "color": _tier_color(5),
            "specs": specs, "base_price": price,
        })

    for w in (500, 750, 1000, 1600, 2200, 3000, 4200, 6000):
        items.append({
            "id": f"psu-{w}", "category": "psu",
            "name": (f"Промышленный БП {w}W" if w >= 4200 else f"БП {w}W"),
            "color": _tier_color(w // 1000),
            "specs": {"power": w}, "base_price": round(w * 0.9, 2),
        })

    # Cooling capacity covers industrial ASIC/farm heat loads.
    coolers = [
        ("Воздушное", 400), ("Башенное", 800), ("Жидкостное", 1600),
        ("Иммерсионное", 4000), ("Иммерсионная ванна Pro", 9000),
        ("Промышленный чиллер", 25000), ("Чиллерная станция", 60000),
        ("Градирня", 120000), ("Криогенная станция", 250000),
    ]
    for i, (name, cap) in enumerate(coolers):
        items.append({
            "id": f"cooling-{i}", "category": "cooling",
            "name": f"{name} охлаждение",
            "color": _tier_color(i),
            "specs": {"cooling": cap, "power": 20 + cap // 200},
            "base_price": round(cap * 1.2, 2),
        })

    # Базовые материнские платы под стойки (6..45 GPU); слоты 1..5 покрывает
    # админ-серия и корпуса. 45 = базовый потолок; 60 GPU — только люксовая
    # Apex Board X60 (mining.RACK_MAX_GPUS).
    for i, slots in enumerate((6, 8, 12, 19, 24, 45)):
        items.append({
            "id": f"mb-{slots}", "category": "motherboard",
            "name": f"Мат. плата ({slots} GPU)",
            "color": _tier_color(min(5, i)),
            "specs": {"gpuSlots": slots, "power": 60 + slots * 4},
            "base_price": round(slots * 1200, 2),
        })

    for i, gb in enumerate((8, 16, 32, 64, 128)):
        items.append({
            "id": f"ram-{gb}", "category": "ram", "name": f"ОЗУ {gb} ГБ",
            "color": _tier_color(i),
            "specs": {"gb": gb, "power": 5},
            "base_price": round(gb * 90, 2),
        })

    for i, gb in enumerate((256, 512, 1024, 2048, 4096)):
        items.append({
            "id": f"ssd-{gb}", "category": "ssd", "name": f"SSD {gb} ГБ",
            "color": _tier_color(i),
            "specs": {"gb": gb, "power": 6},
            "base_price": round(gb * 3, 2),
        })

    # Корпуса — до 5 GPU; для больших сборок есть серверные стойки (rack).
    for i, (name, slots) in enumerate([
        ("Мини-корпус", 1), ("Компактный корпус", 2), ("Миди-башня", 3),
        ("Башенный корпус", 4), ("Full Tower", 5),
    ]):
        items.append({
            "id": f"case-{i}", "category": "case", "name": name,
            "color": _tier_color(i),
            "specs": {"slots": slots},
            "base_price": round(slots * 800, 2),
        })

    # Racks support larger farms and their proportional PSU load.
    for i, (name, slots) in enumerate([
        ("Серверная стойка 12U", 8),
        ("Серверная стойка 24U", 12),
        ("Серверная стойка 42U", 20),
        ("Промышленная стойка XL", 30),
        ("Стойка дата-центра", 45),
    ]):
        items.append({
            "id": f"rack-{i}", "category": "rack", "name": name,
            "color": _tier_color(min(5, i + 1)),
            "specs": {"slots": slots},
            "base_price": round(slots * 1200, 2),
        })

    fans = [("Комплект 120мм", 200, 15), ("Комплект 140мм", 320, 22),
            ("Промышленные вентиляторы", 700, 40)]
    for i, (name, cap, watts) in enumerate(fans):
        items.append({
            "id": f"fan-{i}", "category": "fan", "name": name,
            "color": _tier_color(i),
            "specs": {"cooling": cap, "power": watts},
            "base_price": round(cap * 1.5, 2),
        })

    # Industrial UPS models cover high-power racks.
    for i, w in enumerate((1000, 2000, 3500, 6000, 20000, 50000, 100000, 200000)):
        items.append({
            "id": f"ups-{w}", "category": "ups",
            "name": (f"Промышленный ИБП {w // 1000} kVA" if w >= 20000 else f"ИБП {w}VA"),
            "color": _tier_color(i),
            "specs": {"backup": w, "power": 10 + w // 2000}, "base_price": round(w * 1.1, 2),
        })

    for i, (name, mbps) in enumerate([("Роутер 1 Гбит", 1000), ("Коммутатор 10 Гбит", 10000)]):
        items.append({
            "id": f"net-{i}", "category": "network", "name": name,
            "color": _tier_color(i),
            "specs": {"speed": mbps, "power": 20},
            "base_price": round(mbps * 0.6, 2),
        })

    # Глобальный масштаб цен ×10 (инфляция). Люкс задан сразу в финальных
    # ценах (характеристика × K×10) — повторно не масштабируем.
    for it in items:
        if not it["id"].startswith("lux-"):
            it["base_price"] = round(it["base_price"] * 10, 2)
    return items


# ── Админский каталог ────────────────────────────────────────────────────────
# Names mirror frontend/src/utils/shopCatalog.js.

# Three brands share seven hashrate steps; equal hashrate means equal price.
_GPU_STEPS = [180, 400, 900, 2000, 4500, 10000, 25000]
_GPU_ROWS = []
for _code, _brand, _lines in [
    ("cc", "CrystalCore", ["Quartz", "Topaz", "Sapphire", "Diamond"]),
    ("py", "Pyronix", ["Spark", "Flare", "Blaze", "Inferno"]),
    ("ax", "Archivex", ["Vault", "Legacy", "Archive", "Genesis"]),
]:
    for _i, _h in enumerate(_GPU_STEPS):
        _GPU_ROWS.append((_code, _brand, _lines[min(3, _i // 2)], _h))

_GPU_SUFFIX = {
    "cc": {"Quartz": ("Q", 320), "Topaz": ("T", 520), "Sapphire": ("S", 720), "Diamond": ("D", 920)},
    "py": {"Spark": ("SP", 320), "Flare": ("FL", 520), "Blaze": ("BZ", 720), "Inferno": ("IF", 920)},
    "ax": {"Vault": ("V", 320), "Legacy": ("L", 520), "Archive": ("A", 720), "Genesis": ("G", 920)},
}


def _gpu_suffix(code: str, line: str, idx_in_line: int) -> str:
    """Суффикс модели (напр. Q320). idx_in_line — 0..5 внутри линейки (6 моделей)."""
    prefix, base = _GPU_SUFFIX[code][line]
    return f"{prefix}{base + idx_in_line * 20}"


# (brand_code, brand, line, max_gpus, multiplier)
# 3 бренда × 8 ступеней ядер. Множитель зависит только от ступени — цены
# равных по ядрам моделей совпадают, лестница строго монотонна.
_CPU_STEPS = [(2, 1.00), (4, 1.05), (6, 1.10), (8, 1.15),
              (12, 1.25), (16, 1.35), (24, 1.55), (32, 1.75)]
_CPU_ROWS = []
for _code, _brand, _lines in [
    ("cc", "CrystalChip", ["Stone", "Crystal", "Diamond"]),
    ("py", "PyroCore", ["Ember", "Blaze", "Inferno"]),
    ("ax", "ArchiveCore", ["Legacy", "Archive", "Genesis"]),
]:
    for _i, (_cores, _mult) in enumerate(_CPU_STEPS):
        _CPU_ROWS.append((_code, _brand, _lines[min(2, _i // 3)], _cores, _mult))

_CPU_SUFFIX = {
    "cc": {"Stone": ("S", 210), "Crystal": ("C", 310), "Diamond": ("D", 410)},
    "py": {"Ember": ("E", 210), "Blaze": ("B", 310), "Inferno": ("I", 410)},
    "ax": {"Legacy": ("L", 210), "Archive": ("A", 310), "Genesis": ("G", 410)},
}


def _cpu_suffix(code: str, line: str, idx_in_line: int) -> str:
    prefix, base = _CPU_SUFFIX[code][line]
    return f"{prefix}{base + idx_in_line * 10}"


# Корпуса (ТОЛЬКО до 5 GPU) — ровно 20 видов. Имена согласованы с
# frontend/src/utils/shopCatalog.js (CASE_PRODUCTS), поэтому фронт и бэкенд
# выдают одинаковые названия.
# (brand_code, brand, line, max_gpus)
_CASE_ROWS = [
    # TitanFrame — 7 моделей
    ("tf", "TitanFrame", "Mini", 1),     ("tf", "TitanFrame", "Mini", 1),
    ("tf", "TitanFrame", "Mini", 2),     ("tf", "TitanFrame", "Air", 2),
    ("tf", "TitanFrame", "Air", 3),      ("tf", "TitanFrame", "Air", 3),
    ("tf", "TitanFrame", "Pro", 5),
    # NovaCase — 7 моделей
    ("nc", "NovaCase", "Nano", 1),       ("nc", "NovaCase", "Nano", 1),
    ("nc", "NovaCase", "Nano", 2),       ("nc", "NovaCase", "Flow", 2),
    ("nc", "NovaCase", "Flow", 3),       ("nc", "NovaCase", "Flow", 4),
    ("nc", "NovaCase", "Prime", 5),
    # IronNest — 6 моделей
    ("in", "IronNest", "Base", 1),       ("in", "IronNest", "Base", 2),
    ("in", "IronNest", "Forge", 3),      ("in", "IronNest", "Forge", 4),
    ("in", "IronNest", "Forge", 5),      ("in", "IronNest", "Forge", 5),
]

_CASE_SUFFIX = {
    "tf": {"Mini": ("M", 100), "Air": ("A", 200), "Pro": ("P", 300)},
    "nc": {"Nano": ("N", 100), "Flow": ("F", 200), "Prime": ("P", 300)},
    "in": {"Base": ("B", 100), "Forge": ("F", 200), "Forge": ("F", 200)},
}


def _case_suffix(code: str, line: str, idx_in_line: int) -> str:
    # Уникальная нумерация внутри (code,line). Базы в _CASE_SUFFIX разнесены
    # так, чтобы 20 корпусов не давали коллизий имён между брендами.
    _case_bases = {
        ("tf", "Mini"): 100, ("tf", "Air"): 200, ("tf", "Pro"): 300,
        ("nc", "Nano"): 100, ("nc", "Flow"): 200, ("nc", "Prime"): 300,
        ("in", "Base"): 100, ("in", "Forge"): 200,
    }
    prefix_map = {"tf": "M", "nc": "N", "in": "B"}
    base = _case_bases[(code, line)]
    return f"{prefix_map[code]}{base + idx_in_line * 10}"


def _gpu_color_for_hashrate(h: int) -> str:
    if h < 600:    return TIER_COLORS[0]
    if h < 2000:   return TIER_COLORS[1]
    if h < 6000:   return TIER_COLORS[2]
    if h < 12000:  return TIER_COLORS[3]
    if h < 20000:  return TIER_COLORS[4]
    return TIER_COLORS[5]


# ── Дополнительные серии (20 видов каждой категории) ──────────────────────────
# Согласовано с frontend/src/utils/shopCatalog.js: имена и id совпадают,
# редактор цен (PriceEditorTab) опирается на эти id.

# (brand, line, gb, price_per_gb, color_rank)
_RAM_ROWS: list[tuple[str, str, int, float, int]] = [
    ("MemTek", "Basic", 4, 70, 0),
    ("MemTek", "Basic", 8, 75, 0),
    ("MemTek", "Plus", 16, 80, 1),
    ("MemTek", "Plus", 32, 85, 1),
    ("MemTek", "Pro", 64, 90, 2),
    ("MemTek", "Pro", 128, 95, 2),
    ("MemTek", "Ultra", 256, 100, 3),
    ("HyperCore", "Bronze", 8, 85, 0),
    ("HyperCore", "Silver", 16, 95, 1),
    ("HyperCore", "Gold", 32, 105, 2),
    ("HyperCore", "Platinum", 64, 115, 3),
    ("HyperCore", "Diamond", 128, 125, 4),
    ("HyperCore", "Quantum", 256, 135, 5),
    ("ByteForge", "Eco", 16, 65, 0),
    ("ByteForge", "Standard", 32, 72, 1),
    ("ByteForge", "Boost", 64, 80, 2),
    ("ByteForge", "Xtreme", 128, 92, 3),
    ("ByteForge", "Overdrive", 256, 110, 4),
    ("ByteForge", "Apex", 512, 130, 5),
    ("ByteForge", "Mythic", 1024, 150, 5),
]

# (brand, line, cooling_w, power_w, color_rank)
_COOLING_ROWS: list[tuple[str, str, int, int, int]] = [
    ("FrostAir", "Mini", 250, 15, 0),
    ("FrostAir", "Lite", 400, 18, 0),
    ("FrostAir", "Pro", 700, 25, 1),
    ("FrostAir", "Tower", 1000, 35, 2),
    ("FrostAir", "Mega", 1500, 45, 3),
    ("ChillCore", "Aero", 400, 20, 0),
    ("ChillCore", "Flow", 800, 30, 1),
    ("ChillCore", "Vortex", 1400, 40, 2),
    ("ChillCore", "Cyclone", 2200, 60, 3),
    ("ChillCore", "Titan", 3500, 85, 4),
    ("LiquidNet", "Droplet", 1200, 50, 2),
    ("LiquidNet", "Stream", 2200, 70, 3),
    ("LiquidNet", "River", 4000, 110, 4),
    ("LiquidNet", "Ocean", 6000, 160, 5),
    ("LiquidNet", "Abyss", 9000, 240, 5),
    ("ArcticFox", "Breeze", 500, 20, 1),
    ("ArcticFox", "Gale", 1100, 40, 2),
    ("ArcticFox", "Storm", 2500, 70, 3),
    ("ArcticFox", "Blizzard", 5000, 120, 4),
    ("ArcticFox", "Eternal", 8000, 180, 5),
]

# (brand, line, watts, price_per_w, color_rank)
_PSU_ROWS: list[tuple[str, str, int, float, int]] = [
    ("VoltCore", "Eco", 500, 0.7, 0),
    ("VoltCore", "Lite", 650, 0.75, 0),
    ("VoltCore", "Bronze", 750, 0.8, 1),
    ("VoltCore", "Silver", 850, 0.85, 1),
    ("VoltCore", "Gold", 1000, 0.9, 2),
    ("VoltCore", "Platinum", 1200, 1.0, 2),
    ("VoltCore", "Titanium", 1500, 1.1, 3),
    ("PowerMax", "Basic", 800, 0.7, 0),
    ("PowerMax", "Standard", 1000, 0.8, 1),
    ("PowerMax", "Pro", 1200, 0.9, 2),
    ("PowerMax", "Elite", 1600, 1.0, 3),
    ("PowerMax", "Ultimate", 2000, 1.1, 4),
    ("AmpereX", "Core", 1500, 0.9, 2),
    ("AmpereX", "Boost", 2000, 1.0, 3),
    ("AmpereX", "Surge", 2500, 1.1, 4),
    ("AmpereX", "Overload", 3000, 1.2, 5),
    ("AmpereX", "Fusion", 4000, 1.3, 5),
    ("AmpereX", "Reactor", 5000, 1.4, 5),
    ("AmpereX", "Singularity", 6500, 1.5, 5),
    ("AmpereX", "BigBang", 8000, 1.6, 5),
]

# (brand, line, gpu_slots, power, color_rank, price_per_slot)
_MB_ROWS: list[tuple[str, str, int, int, int, float]] = [
    ("BoardTek", "Lite", 1, 50, 0, 800),
    ("BoardTek", "Lite", 2, 55, 0, 850),
    ("BoardTek", "Plus", 2, 60, 1, 950),
    ("BoardTek", "Plus", 3, 65, 1, 1000),
    ("BoardTek", "Pro", 3, 70, 2, 1100),
    ("BoardTek", "Pro", 4, 75, 2, 1200),
    ("BoardTek", "Ultra", 4, 80, 3, 1300),
    ("BoardTek", "Ultra", 5, 85, 3, 1400),
    ("BoardTek", "Xtreme", 5, 95, 4, 1600),
    ("BoardTek", "Xtreme", 5, 100, 4, 1700, " Pro"),
    ("ChipMaster", "Bronze", 1, 55, 0, 900),
    ("ChipMaster", "Silver", 2, 65, 1, 1000),
    ("ChipMaster", "Gold", 3, 75, 2, 1150),
    ("ChipMaster", "Platinum", 4, 85, 3, 1350),
    ("ChipMaster", "Diamond", 5, 95, 4, 1550),
    ("ChipMaster", "Quantum", 5, 110, 5, 1800),
    ("NovaChip", "Eco", 2, 60, 1, 950),
    ("NovaChip", "Boost", 3, 70, 2, 1100),
    ("NovaChip", "Prime", 4, 80, 3, 1300),
    ("NovaChip", "Apex", 5, 95, 4, 1600),
]

# (brand, line, gb, color_rank, price_per_gb)
_SSD_ROWS: list[tuple[str, str, int, int, float]] = [
    ("DriveTek", "Lite", 128, 0, 3.0),
    ("DriveTek", "Lite", 256, 0, 3.2),
    ("DriveTek", "Plus", 512, 1, 3.4),
    ("DriveTek", "Plus", 1024, 1, 3.6),
    ("DriveTek", "Pro", 2048, 2, 3.8),
    ("DriveTek", "Pro", 4096, 2, 4.0),
    ("DriveTek", "Ultra", 8192, 3, 4.2),
    ("FlashCore", "Bronze", 256, 0, 3.5),
    ("FlashCore", "Silver", 512, 1, 3.7),
    ("FlashCore", "Gold", 1024, 2, 3.9),
    ("FlashCore", "Platinum", 2048, 3, 4.1),
    ("FlashCore", "Diamond", 4096, 4, 4.3),
    ("FlashCore", "Quantum", 8192, 5, 4.5),
    ("SolidByte", "Eco", 256, 0, 2.8),
    ("SolidByte", "Standard", 512, 1, 3.0),
    ("SolidByte", "Boost", 1024, 2, 3.2),
    ("SolidByte", "Xtreme", 2048, 3, 3.4),
    ("SolidByte", "Overdrive", 4096, 4, 3.6),
    ("SolidByte", "Apex", 8192, 5, 3.8),
    ("SolidByte", "Mythic", 16384, 5, 4.0),
]


def _build_admin_catalog() -> list[dict]:
    """Полные серии для магазина: GPU (90), CPU (90), и по 20 видов корпусов,
    ОЗУ, кулеров, БП, мат. плат и ССД + supplies (2 вида).

    id формируются ровно так, как ожидает frontend (adminCatalog.js):
      admin-gpu-<N>, admin-cpu-<N>, admin-case-<N>, admin-ram-<N>,
      admin-cooling-<N>, admin-psu-<N>, admin-mb-<N>, admin-ssd-<N>,
      admin-supply-<kind>.
    Имена согласованы с frontend/src/utils/shopCatalog.js.
    """
    items: list[dict] = []

    # ── GPU: 90 шт. (3 бренда × 4 линейки × 6 моделей) ──
    idx_in_line: dict[tuple[str, str], int] = {}
    for code, brand, line, hashrate in _GPU_ROWS:
        key = (code, line)
        i = idx_in_line.get(key, 0)
        idx_in_line[key] = i + 1
        pid = len(items) + 1
        suffix = _gpu_suffix(code, line, i)
        power = _gpu_power(hashrate)
        items.append({
            "id": f"admin-gpu-{pid}",
            "category": "gpu",
            "name": f"{brand} {line} {suffix}",
            "brand": brand, "line": line,
            "color": _gpu_color_for_hashrate(hashrate),
            "specs": {"hashrate": hashrate, "power": power},
            "base_price": round(hashrate * PRICE_PER_HASH, 2),
        })

    # ── CPU: 90 шт. (pid 1..90 в серии) ──
    idx_in_line = {}
    cpu_pid = 0
    for code, brand, line, max_gpus, mult in _CPU_ROWS:
        key = (code, line)
        i = idx_in_line.get(key, 0)
        idx_in_line[key] = i + 1
        cpu_pid += 1
        suffix = _cpu_suffix(code, line, i)
        items.append({
            "id": f"admin-cpu-{cpu_pid}",
            "category": "cpu",
            "name": f"{brand} {line} {suffix}",
            "brand": brand, "line": line,
            "color": _tier_color(min(5, max_gpus // 6)),
            "specs": {"cores": max_gpus, "power": _cpu_power(mult), "multiplier": mult},
            "base_price": round(max_gpus * 700 * mult, 2),
        })

    # ── Case: 20 шт. (ТОЛЬКО до 5 GPU) ──
    idx_in_line = {}
    case_pid = 0
    for code, brand, line, max_gpus in _CASE_ROWS:
        key = (code, line)
        i = idx_in_line.get(key, 0)
        idx_in_line[key] = i + 1
        case_pid += 1
        # Жёсткий лимит: корпус вмещает максимум MAX_CASE_SLOTS (5) GPU.
        max_gpus = min(max_gpus, MAX_CASE_SLOTS)
        suffix = _case_suffix(code, line, i)
        items.append({
            "id": f"admin-case-{case_pid}",
            "category": "case",
            "name": f"{brand} {line} {suffix}",
            "brand": brand, "line": line,
            "color": _tier_color(min(5, max_gpus - 1)),
            "specs": {"slots": max_gpus},
            "base_price": round(max_gpus * 800, 2),
        })

    # ── RAM: 20 видов ──
    for i, (brand, line, gb, pp_gb, color_rank) in enumerate(_RAM_ROWS, start=1):
        items.append({
            "id": f"admin-ram-{i}",
            "category": "ram",
            "name": f"{brand} {line} {gb}GB",
            "brand": brand, "line": line,
            "color": _tier_color(color_rank),
            "specs": {"gb": gb, "power": 5 + gb // 16},
            "base_price": round(gb * pp_gb, 2),
        })

    # ── Cooling: 20 видов ──
    for i, (brand, line, cool, power, color_rank) in enumerate(_COOLING_ROWS, start=1):
        items.append({
            "id": f"admin-cooling-{i}",
            "category": "cooling",
            "name": f"{brand} {line}",
            "brand": brand, "line": line,
            "color": _tier_color(color_rank),
            "specs": {"cooling": cool, "power": power},
            "base_price": round(cool * 1.2, 2),
        })

    # ── PSU: 20 видов ──
    for i, (brand, line, watts, pp_w, color_rank) in enumerate(_PSU_ROWS, start=1):
        items.append({
            "id": f"admin-psu-{i}",
            "category": "psu",
            "name": f"{brand} {line} {watts}W",
            "brand": brand, "line": line,
            "color": _tier_color(color_rank),
            "specs": {"power": watts},
            "base_price": round(watts * pp_w, 2),
        })

    # ── Motherboard: 20 видов (ТОЛЬКО до 5 GPU) ──
    # Необязательный 7-й элемент — суффикс имени; у двух BoardTek Xtreme
    # одинаковые 5 слотов, без суффикса имена совпали бы (имена каталога
    # уникальны — на них опирается mining через CATALOG_BY_NAME).
    for i, row in enumerate(_MB_ROWS, start=1):
        brand, line, slots, power, color_rank, pp_slot = row[:6]
        suffix = row[6] if len(row) > 6 else ''
        slots = min(slots, MAX_CASE_SLOTS)
        items.append({
            "id": f"admin-mb-{i}",
            "category": "motherboard",
            "name": f"{brand} {line} {slots}GPU{suffix}",
            "brand": brand, "line": line,
            "color": _tier_color(color_rank),
            "specs": {"gpuSlots": slots, "power": power},
            "base_price": round(slots * pp_slot, 2),
        })

    # ── SSD: 20 видов ──
    for i, (brand, line, gb, color_rank, pp_gb) in enumerate(_SSD_ROWS, start=1):
        items.append({
            "id": f"admin-ssd-{i}",
            "category": "ssd",
            "name": f"{brand} {line} {gb}GB",
            "brand": brand, "line": line,
            "color": _tier_color(color_rank),
            "specs": {"gb": gb, "power": 6},
            "base_price": round(gb * pp_gb, 2),
        })

    # ── Supplies: расходники. ──
    items.append({
        "id": "admin-supply-cooling-fluid",
        "category": "supplies",
        "name": "Охлаждающая жидкость",
        "kind": "cooling",
        "color": "#f97316",
        "specs": {"kind": "cooling", "power": 0},
        "base_price": 240.0,
    })
    items.append({
        "id": "admin-supply-gpu-chip",
        "category": "supplies",
        "name": "Чип для улучшения видеокарты",
        "kind": "upgrade",
        "color": "#f97316",
        "specs": {"kind": "upgrade", "power": 0},
        "base_price": 5000.0,
    })

    # Глобальный масштаб цен ×10 (см. _build_base_catalog).
    for it in items:
        it["base_price"] = round(it["base_price"] * 10, 2)
    return items


# ── Каталоги (готовые) ───────────────────────────────────────────────────────


BASE_CATALOG = _build_base_catalog()
ADMIN_CATALOG = _build_admin_catalog()
CATALOG: list[dict] = BASE_CATALOG + ADMIN_CATALOG
CATALOG_BY_ID: dict[str, dict] = {c["id"]: c for c in CATALOG}
# Установленный в ферму компонент хранит только name/specs (см. mining._install_one),
# поэтому цену железа приходится искать по имени — имена в каталоге уникальны.
CATALOG_BY_NAME: dict[str, float] = {c["name"]: c["base_price"] for c in CATALOG}
assert len(CATALOG_BY_NAME) == len(CATALOG), "имена товаров должны быть уникальны"


# ── Конфигурация и админские цены ───────────────────────────────────────────


async def _shop_config(db) -> dict:
    doc = await find_config_by_key(db, SHOP_CONFIG_KEY)
    cfg = dict(DEFAULT_SHOP_CONFIG)
    if doc:
        try:
            cfg.update(json.loads(doc["value"]))
        except Exception:
            pass
    return cfg


async def _admin_prices(db) -> dict[str, float]:
    """Админские overrides: {id: price}. None в БД = сброс к формуле.

    Реализация одна — в assets.py (там же SHOP_PRICES_KEY и _admin_price_key);
    тут раньше лежала её копия, расходившаяся при правках."""
    return await _assets_admin_prices(db)


# ── Ценообразование ──────────────────────────────────────────────────────────


async def _unit_price(
    db, item: dict, override_prices: dict[str, float] | None = None
) -> float:
    """Цена единицы товара с учётом админских overrides и экономики."""
    shop_cfg = await _shop_config(db)
    econ = await get_econ(db)
    mult = shop_cfg.get(item["category"], 1.0) * econ.get("economy_mult", 1.0)
    if override_prices is None:
        override_prices = await _admin_prices(db)
    base = float(override_prices.get(item["id"], item["base_price"]))
    return round(base * mult, 2)


# ── Скидки зданий «Крыши города» ────────────────────────────────────────────


async def _city_shop_discount(db, user_id: str) -> float:
    try:
        from cityroof import player_city_effect
        return min(0.5, await player_city_effect(db, user_id, "shop_discount"))
    except Exception:
        return 0.0


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/catalog")
async def get_catalog(
    category: str = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Каталог с живыми ценами (никаких null).

    Включает базовые позиции (gpu-cc-0-0, psu-500, mb-2, …) и админские серии
    (admin-gpu-1, admin-cpu-1, admin-case-1, admin-supply-…). Если у
    админской позиции есть override (`/api/admin/shop/prices`), используется
    он; иначе — формула по характеристикам.
    """
    shop_cfg = await _shop_config(db)
    econ = await get_econ(db)
    emult = econ.get("economy_mult", 1.0)
    override_prices = await _admin_prices(db)
    discount = await _city_shop_discount(db, str(current_user["_id"]))
    items = CATALOG if not category else [c for c in CATALOG if c["category"] == category]
    out = []
    for c in items:
        base = float(override_prices.get(c["id"], c["base_price"]))
        price = round(base * shop_cfg.get(c["category"], 1.0) * emult * (1 - discount), 2)
        specs = c.get("specs", {}) or {}
        row = {
            "id": c["id"], "category": c["category"], "name": c["name"],
            "brand": c.get("brand"), "color": c.get("color"),
            "specs": specs, "price": price,
        }
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
    current_user: dict = Depends(require_allowed("shop")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Покупка железа/расходников. Цена всегда пересчитывается сервером:
    admin-override → base_price × множитель категории × economy_mult, минус
    скидка зданий «Крыши города». Купленные экземпляры попадают в user_hardware.
    """
    item = CATALOG_BY_ID.get(payload.itemId)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Товар не найден")
    qty = max(1, min(int(payload.quantity), MAX_BUY_QTY))
    user_id = str(current_user["_id"])
    discount = await _city_shop_discount(db, user_id)
    unit = round((await _unit_price(db, item)) * (1 - discount), 2)
    total = round(unit * qty, 2)
    new_balance = await adjust_balance(db, user_id, -total)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

    docs = [{
        "userId": user_id, "itemId": item["id"], "category": item["category"],
        "name": item["name"], "specs": item.get("specs", {}) or {},
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
    return round(sum(float(p) for p in purchase_prices) * RESALE_RATIO, 2)


@router.post("/sell")
async def sell_hardware(
    payload: SellHardware,
    current_user: dict = Depends(require_allowed("shop")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Продажа лишнего железа обратно магазину с уценкой (RESALE_RATIO)."""
    qty = max(1, int(payload.quantity))
    user_id = str(current_user["_id"])
    free = await db.user_hardware.find(
        {"userId": user_id, "itemId": payload.itemId, "farmId": None}
    ).to_list(length=None)
    # Стойка — общий пул слотов: её farmId всегда None, но она может быть
    # задействована в фермах. Такие экземпляры НЕ продаём.
    from mining import in_use_rack_ids   # локально: mining импортирует shop
    in_use_racks = await in_use_rack_ids(db, user_id)
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
    cpu: Optional[float] = None
    motherboard: Optional[float] = None
    ram: Optional[float] = None
    ssd: Optional[float] = None
    case: Optional[float] = None
    psu: Optional[float] = None
    cooling: Optional[float] = None
    fan: Optional[float] = None
    supplies: Optional[float] = None


@router.get("/config")
async def shop_config(_admin=Depends(require_admin("shop_config")), db: AsyncIOMotorDatabase = Depends(get_db)):
    return await _shop_config(db)


@router.post("/config")
async def set_shop_config(
    payload: ShopConfigUpdate,
    _admin=Depends(require_admin("shop_config")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    cfg = await _shop_config(db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None and value > 0:
            cfg[key] = round(float(value), 3)
    await upsert_config(db, SHOP_CONFIG_KEY, json.dumps(cfg))
    return cfg


# ── Админские цены (PriceEditorTab) ─────────────────────────────────────────
#
# GET  /api/admin/shop/prices   — все overrides
# POST /api/admin/shop/prices   — заменить словарь (id -> price | null)
#
# Поддерживаем оба формата ключей (для совместимости с PriceEditorTab):
#  • канонические id ("admin-gpu-1", "admin-supply-cooling-fluid")
#  • числовые productId ("1", "2", …, "90") из редактора цен.
# Числовые ключи превращаем в канонические id. None трактуется как
# «сброс к формуле» и НЕ сохраняется в БД (парсер его отбрасывает).


@admin_router.get("/prices")
async def get_shop_prices(_admin=Depends(require_admin("catalog_prices")), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Все переопределения админских цен. Ключи — канонические id."""
    return {"prices": await _admin_prices(db)}


@admin_router.post("/prices")
async def set_shop_prices(
    payload: dict,
    _admin=Depends(require_admin("catalog_prices")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Сохранить админские цены. Body: {"prices": {id: price|null, ...},
    "category": "gpu"|"cpu"|"case"|"supplies"|None}.

    Числовые ключи без категории интерпретируются согласно productId из
    shopCatalog. Категория приводит числовые id к admin-<category>-<pid>.
    """
    body = payload or {}
    prices_in = body.get("prices", {})
    category = body.get("category")
    if not isinstance(prices_in, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "prices должен быть объектом")

    cat_prefix = {
        "gpu": "admin-gpu",
        "cpu": "admin-cpu",
        "case": "admin-case",
        "ram": "admin-ram",
        "cooling": "admin-cooling",
        "psu": "admin-psu",
        "motherboard": "admin-mb",
        "ssd": "admin-ssd",
        "realestate": "admin-re",
        "business": "admin-biz",
        "supplies": "admin-supply",
    }.get(category)
    cat_count = {
        "gpu": 21, "cpu": 24, "case": 20, "ram": 20, "cooling": 20,
        "psu": 20, "motherboard": 20, "ssd": 20,
        "realestate": 81, "business": 12,
    }.get(category, 90)

    # Категории, где ключ конфига — slug актива (строковые ключи проходят
    # как есть). См. _admin_price_key в assets.py и ADMIN_DEFAULT_PRICES
    # в adminCatalog.js.
    passthrough_categories = {"realestate", "business", "factory", "source", "warehouse", "cars"}

    def _normalize_key(key: str) -> Optional[str]:
        # Числовые ключи недвижимости/бизнесов (productId из редактора)
        # приводятся к admin-re-N / admin-biz-N — раньше обе группы писались
        # голым 'N' в один документ и затирали цены друг друга.
        if category in ("realestate", "business") and key.isdigit():
            pid = int(key)
            if 1 <= pid <= cat_count and cat_prefix:
                return f"{cat_prefix}-{pid}"
            return None
        if category in passthrough_categories:
            return key
        # supplies: у покупаемых позиций id вида admin-supply-<kind>
        # (admin-supply-cooling-fluid / admin-supply-gpu-chip) — числовой
        # productId редактора мапится именно в них. Ветку нужно ПЕРЕД общей:
        # иначе ключи уходят под мёртвые admin-supply-1/2, которые покупка
        # не читает.
        if category == "supplies" and key.isdigit():
            pid = int(key)
            if pid == 1:
                return "admin-supply-cooling-fluid"
            if pid == 2:
                return "admin-supply-gpu-chip"
            return None
        # gpu/cpu/case/ram/cooling/psu/motherboard/ssd — числовой
        # productId приводится к admin-<cat>-<pid>.
        if key.isdigit():
            pid = int(key)
            if cat_prefix and 1 <= pid <= cat_count:
                return f"{cat_prefix}-{pid}"
            return None
        # Строковые ключи — как есть (admin-fac-*, admin-src-*, admin-wh-*, car-*, ...),
        # плюс id базового каталога, добавленного позже (Voltronix, Lux, большие
        # материнки, ASIC) — без них редактор цен не мог бы переопределять их.
        if key.startswith(("admin-", "car-", "truck-", "trailer-",
                           "gpu-vlt-", "gpu-asic-", "lux-", "mb-")):
            return key
        return None

    norm: dict[str, Optional[float]] = {}
    for k, v in prices_in.items():
        canon = _normalize_key(str(k))
        if canon is None:
            continue
        if v is None:
            # Сброс к формуле.
            norm[canon] = None
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv <= 0:
            continue
        norm[canon] = fv

    # Мердж, а не замена: сохранение одной вкладки не должно затирать
    # переопределения цен других категорий. None = сброс к формуле → удаляем ключ.
    existing: dict = {}
    doc = await find_config_by_key(db, SHOP_PRICES_KEY)
    if doc:
        try:
            existing = json.loads(doc.get("value") or "{}")
        except Exception:
            existing = {}
    for k, v in norm.items():
        if v is None:
            existing.pop(k, None)
        else:
            existing[k] = v

    await upsert_config(db, SHOP_PRICES_KEY, json.dumps(existing))
    return {"ok": True, "count": sum(1 for v in existing.values() if v is not None)}


# ── Алиасный роутер для обратной совместимости ────────────────────────────────
# `/api/admin/shop-prices` (через дефис) — старый URL из PriceEditorTab.jsx.
# Сейчас фронт исправлен на `/api/admin/shop/prices` (через слэш), но алиас
# оставляем: если в каком-то месте фронтенда или сторонний скрипт ещё шлёт
# запрос по старому URL, он дойдёт.
# Декораторы не позволяют повесить одну функцию на два роутера, поэтому
# регистрируем те же функции ещё раз через add_api_route.
alias_admin_router.add_api_route(
    "/prices", get_shop_prices, methods=["GET"],
    dependencies=[Depends(require_admin("catalog_prices"))],
)
alias_admin_router.add_api_route(
    "/prices", set_shop_prices, methods=["POST"],
    dependencies=[Depends(require_admin("catalog_prices"))],
)


# ── Self-check ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    assert _resale_refund([100.0, 100.0]) == round(200.0 * RESALE_RATIO, 2)
    assert _resale_refund([]) == 0.0
    assert 0 < RESALE_RATIO < 1

    free_pool = [{"purchase_price": 100.0}, {"purchase_price": 100.0}]
    want = 3
    assert len(free_pool) < want

    assert all(isinstance(c["specs"].get("power", 0), (int, float)) for c in CATALOG)
    assert all("fan" != c["category"] or c["specs"].get("power", 0) > 0 for c in CATALOG)

    admin_gpu = [c for c in ADMIN_CATALOG if c["category"] == "gpu"]
    admin_cpu = [c for c in ADMIN_CATALOG if c["category"] == "cpu"]
    admin_case = [c for c in ADMIN_CATALOG if c["category"] == "case"]
    admin_ram = [c for c in ADMIN_CATALOG if c["category"] == "ram"]
    admin_cooling = [c for c in ADMIN_CATALOG if c["category"] == "cooling"]
    admin_psu = [c for c in ADMIN_CATALOG if c["category"] == "psu"]
    admin_mb = [c for c in ADMIN_CATALOG if c["category"] == "motherboard"]
    admin_ssd = [c for c in ADMIN_CATALOG if c["category"] == "ssd"]
    admin_supplies = [c for c in ADMIN_CATALOG if c["category"] == "supplies"]
    assert len(admin_gpu) == 21, f"admin gpu: {len(admin_gpu)}"
    assert len(admin_cpu) == 24, f"admin cpu: {len(admin_cpu)}"
    # CPU: равные ядра — равная цена (вне зависимости от бренда); цена строго
    # растёт по ступеням ядер.
    _by_cores = {}
    for c in admin_cpu:
        _by_cores.setdefault(c["specs"]["cores"], set()).add(c["base_price"])
        assert len(_by_cores[c["specs"]["cores"]]) == 1, "разные цены на равные ядра"
    _price_of = {k: v.pop() for k, v in _by_cores.items()}
    _steps = sorted(_price_of)
    assert all(_price_of[a] < _price_of[b] for a, b in zip(_steps, _steps[1:])),         "цены CPU не растут по ступеням"
    # GPU: равный хешрейт — равная цена; цена строго растёт по ступеням.
    _by_hash = {}
    for c in admin_gpu:
        _by_hash.setdefault(c["specs"]["hashrate"], set()).add(c["base_price"])
        assert len(_by_hash[c["specs"]["hashrate"]]) == 1, "разные цены на равный хешрейт"
    _hprice_of = {k: v.pop() for k, v in _by_hash.items()}
    _hsteps = sorted(_hprice_of)
    assert all(_hprice_of[a] < _hprice_of[b] for a, b in zip(_hsteps, _hsteps[1:])),         "цены GPU не растут по ступеням"
    assert len(admin_case) == 20, f"admin case: {len(admin_case)}"
    assert len(admin_ram) == 20, f"admin ram: {len(admin_ram)}"
    assert len(admin_cooling) == 20, f"admin cooling: {len(admin_cooling)}"
    assert len(admin_psu) == 20, f"admin psu: {len(admin_psu)}"
    assert len(admin_mb) == 20, f"admin mb: {len(admin_mb)}"
    assert len(admin_ssd) == 20, f"admin ssd: {len(admin_ssd)}"
    assert len(admin_supplies) == 2, f"admin supplies: {len(admin_supplies)}"
    # Корпуса и админские материнки — до 5 GPU; большие сборки через стойки.
    for c in admin_case + admin_mb:
        slots = c["specs"].get("slots", c["specs"].get("gpuSlots", 0))
        assert slots <= 5, f"slots > 5: {c['id']} {slots}"
    # Серверные стойки: 5 базовых (8..45 слотов) + люксовая «Гиперстойка 300U»
    # (общий пул слотов на несколько ферм, см. mining._rack_pool_check).
    racks = [c for c in CATALOG if c["category"] == "rack"]
    assert len(racks) == 6
    assert min(r["specs"]["slots"] for r in racks) == 8
    assert max(r["specs"]["slots"] for r in racks) == 300
    # Топовая базовая стойка дешевле люксовой: разница — в слотах пула.
    _base_top_rack = min(r["base_price"] for r in racks if r["specs"]["slots"] == 45)
    assert _base_top_rack < 2_000_000

    # Флагманская линейка Voltronix + криогенная станция.
    v300 = CATALOG_BY_ID["gpu-vlt-2"]
    assert v300["name"] == "Voltronix Quantum V300" and v300["specs"]["hashrate"] == 80000
    assert CATALOG_BY_NAME["Криогенная станция охлаждение"] == 250000 * 12.0

    # Премиум-линейка Lux: по позиции на каждую категорию, цена = характеристика
    # × K категории (пропорционально, без «наценки за бренд»).
    lux = [c for c in CATALOG if c["id"].startswith("lux-")]
    assert len(lux) == 9, f"lux items: {len(lux)}"
    assert next(c for c in lux if c["id"] == "lux-gpu")["base_price"] == 150000 * 60
    assert next(c for c in lux if c["id"] == "lux-psu")["base_price"] == 25000 * 9
    assert next(c for c in lux if c["id"] == "lux-rack")["base_price"] == 300 * 12000
    assert next(c for c in lux if c["id"] == "lux-gpu")["specs"]["hashrate"] == 150000
    assert next(c for c in lux if c["id"] == "lux-rack")["specs"]["slots"] == 300
    assert next(c for c in lux if c["id"] == "lux-motherboard")["specs"]["gpuSlots"] == 60
    # Базовые материнки — 6..45 GPU; 60 GPU только у люксовой Apex Board X60.
    _base_mbs = sorted(c["specs"]["gpuSlots"] for c in BASE_CATALOG
                       if c["category"] == "motherboard" and not c["id"].startswith("lux-"))
    assert _base_mbs == [6, 8, 12, 19, 24, 45], f"mb ladder: {_base_mbs}"

    ids = [c["id"] for c in CATALOG]
    assert len(ids) == len(set(ids)), "дубликаты id"

    # Контракт имён с shopCatalog.js — проверяем по одной позиции из каждой серии.
    gpu1 = CATALOG_BY_ID["admin-gpu-1"]
    assert gpu1["name"] == "CrystalCore Quartz Q320", f"got {gpu1['name']!r}"
    gpu21 = CATALOG_BY_ID["admin-gpu-21"]
    assert gpu21["name"] == "Archivex Genesis G920", f"got {gpu21['name']!r}"
    cpu1 = CATALOG_BY_ID["admin-cpu-1"]
    assert cpu1["name"] == "CrystalChip Stone S210", f"got {cpu1['name']!r}"
    cpu24 = CATALOG_BY_ID["admin-cpu-24"]
    assert cpu24["name"] == "ArchiveCore Genesis G420", f"got {cpu24['name']!r}"
    case1 = CATALOG_BY_ID["admin-case-1"]
    assert case1["specs"]["slots"] <= 5, f"case1 slots: {case1['specs']}"
    ram1 = CATALOG_BY_ID["admin-ram-1"]
    assert ram1["specs"]["gb"] > 0
    cool1 = CATALOG_BY_ID["admin-cooling-1"]
    assert cool1["specs"]["cooling"] > 0
    psu1 = CATALOG_BY_ID["admin-psu-1"]
    assert psu1["specs"]["power"] > 0
    mb1 = CATALOG_BY_ID["admin-mb-1"]
    assert mb1["specs"]["gpuSlots"] <= 5, f"mb1 slots: {mb1['specs']}"
    ssd1 = CATALOG_BY_ID["admin-ssd-1"]
    assert ssd1["specs"]["gb"] > 0

    print("shop self-check OK")


# ── Admin: выдача предметов игроку ───────────────────────────────────────────


class AdminGrantHwBody(BaseModel):
    item_id: str
    quantity: int = 1


@admin_router.get("/catalog")
async def admin_hw_catalog(_admin=Depends(require_admin("users_property"))):
    """Каталог железа для выдачи игрокам из админки."""
    return {"items": [
        {"id": c["id"], "name": c["name"], "category": c["category"],
         "price": c.get("base_price", 0)}
        for c in CATALOG
    ]}


@admin_router.post("/grant/{user_id}")
async def admin_grant_hw(
    user_id: str,
    body: AdminGrantHwBody,
    _admin=Depends(require_admin("users_property")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Выдать предмет (железо) игроку бесплатно. Без записи в ledger."""
    from bson import ObjectId as _OID
    from notifications import push_notification
    if not _OID.is_valid(user_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID пользователя")
    target = await db.users.find_one({"_id": _OID(user_id)})
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    item = CATALOG_BY_ID.get(body.item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Предмет «{body.item_id}» не найден в каталоге")
    qty = max(1, min(int(body.quantity or 1), 1000))
    now = _now()
    docs = [{
        "userId": user_id, "itemId": item["id"], "category": item["category"],
        "name": item["name"], "specs": item.get("specs", {}) or {},
        "purchase_price": item.get("base_price", 0), "condition": 100, "purchased_at": now,
    } for _ in range(qty)]
    await db.user_hardware.insert_many(docs)
    try:
        await push_notification(
            db, user_id, "system", "Предмет выдан",
            f"Администрация выдала вам «{item['name']}» ×{qty}.",
        )
    except Exception:
        pass
    return {"granted": qty, "name": item["name"]}
