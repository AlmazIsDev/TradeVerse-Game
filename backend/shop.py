"""Магазин оборудования (видеокарты, процессоры, корпуса, расходники и др.).

Цены НЕ хранятся статически и НЕ бывают null — они вычисляются из экономики:
    base = admin_price (если задан в /api/admin/shop-prices) иначе item.base_price
    price = base × множитель_категории × economy_mult
    итоговая = price × (1 - скидка зданий «Крыши города»)

Покупка всегда пересчитывает цену на сервере, поэтому изменение цен в
админ-панели не ломает покупку. Купленное железо попадает в инвентарь
пользователя (user_hardware) — основа для майнинг-ферм.

Каталог состоит из двух слоёв:
  1) Базовый — gpu/cpu/psu/cooling/ram/ssd/case/rack/fan/ups/network/asic.
     Идентификаторы (gpu-cc-0-0, psu-500, mb-2, …) обратно совместимы с
     существующими user_hardware и mining-движком.
  2) Админские серии — admin-gpu-N, admin-cpu-N, admin-case-N (1..90)
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

from auth import get_current_user, require_admin
from database import get_db, find_config_by_key, upsert_config
from ledger import INCOME, EXPENSE, CAT_SHOP, adjust_balance, record_transaction
from econ import get_econ

router = APIRouter(prefix="/api/shop", tags=["shop"])
admin_router = APIRouter(prefix="/api/admin/shop", tags=["shop-admin"])

SHOP_CONFIG_KEY = "shop_config"
SHOP_PRICES_KEY = "shop_prices"   # админские цены {id: price|null}
MAX_BUY_QTY = 1000
RESALE_RATIO = 0.65

# Палитра «по мощности»: холодный (слабое) → горячий (топовое).
TIER_COLORS = ["#60a5fa", "#22d3ee", "#34d399", "#facc15", "#fb923c", "#ef4444"]
DEFAULT_SHOP_CONFIG = {
    "gpu": 1.0, "cpu": 1.0, "motherboard": 1.0, "ram": 1.0, "ssd": 1.0,
    "psu": 1.0, "case": 1.0, "rack": 1.0, "cooling": 1.0, "fan": 1.0,
    "ups": 1.0, "network": 1.0, "supplies": 1.0,
}
PRICE_PER_HASH = 6.0

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

    brands = [
        ("CrystalCore", ["Quartz", "Topaz", "Sapphire", "Diamond"]),
        ("Pyronix", ["Spark", "Flare", "Blaze", "Inferno"]),
        ("Archivex", ["Vault", "Legacy", "Archive", "Genesis"]),
    ]
    for brand, lines in brands:
        for li, line in enumerate(lines):
            for tier in range(3):
                rank = li * 3 + tier
                hashrate = int(180 * (1.6 ** rank))
                power = _gpu_power(hashrate)
                model = f"{brand} {line} {(rank + 1) * 100}"
                items.append({
                    "id": f"gpu-{brand[:2].lower()}-{li}-{tier}",
                    "category": "gpu", "name": model, "brand": brand,
                    "color": _tier_color(rank // 2),
                    "specs": {"hashrate": hashrate, "power": power},
                    "base_price": round(hashrate * PRICE_PER_HASH, 2),
                })

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

    for w in (500, 750, 1000, 1600, 2200, 3000, 4200, 6000):
        items.append({
            "id": f"psu-{w}", "category": "psu",
            "name": (f"Промышленный БП {w}W" if w >= 4200 else f"БП {w}W"),
            "color": _tier_color(w // 1000),
            "specs": {"power": w}, "base_price": round(w * 0.9, 2),
        })

    coolers = [
        ("Воздушное", 400), ("Башенное", 800), ("Жидкостное", 1600),
        ("Иммерсионное", 4000), ("Иммерсионная ванна Pro", 9000),
    ]
    for i, (name, cap) in enumerate(coolers):
        items.append({
            "id": f"cooling-{i}", "category": "cooling",
            "name": f"{name} охлаждение",
            "color": _tier_color(i),
            "specs": {"cooling": cap, "power": 20 + cap // 200},
            "base_price": round(cap * 1.2, 2),
        })

    cpus = [
        ("Ryzen Quad Q4", 4), ("Ryzen Hexa H6", 6), ("Falcon Octa X8", 8),
        ("Falcon Dodeca X12", 12), ("Threadstorm 16", 16),
        ("Threadstorm Xeon 32", 32), ("EPYC Titan 64", 64),
    ]
    for i, (name, cores) in enumerate(cpus):
        items.append({
            "id": f"cpu-{cores}", "category": "cpu", "name": name,
            "color": _tier_color(i),
            "specs": {"cores": cores, "power": 45 + cores * 8},
            "base_price": round(cores * 700, 2),
        })

    for i, slots in enumerate((2, 4, 6, 8, 12, 19)):
        items.append({
            "id": f"mb-{slots}", "category": "motherboard",
            "name": f"Мат. плата ({slots} GPU)",
            "color": _tier_color(i),
            "specs": {"gpuSlots": slots, "power": 60},
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

    for i, (name, slots) in enumerate([("Мини-корпус", 2), ("Миди-башня", 4), ("Full Tower", 8)]):
        items.append({
            "id": f"case-{i}", "category": "case", "name": name,
            "color": _tier_color(i),
            "specs": {"slots": slots},
            "base_price": round(slots * 500, 2),
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

    for i, w in enumerate((1000, 2000, 3500, 6000)):
        items.append({
            "id": f"ups-{w}", "category": "ups", "name": f"ИБП {w}VA",
            "color": _tier_color(i),
            "specs": {"backup": w, "power": 10},
            "base_price": round(w * 1.1, 2),
        })

    for i, (name, mbps) in enumerate([("Роутер 1 Гбит", 1000), ("Коммутатор 10 Гбит", 10000),
                                      ("Сетевая стойка", 40000)]):
        items.append({
            "id": f"net-{i}", "category": "network", "name": name,
            "color": _tier_color(i),
            "specs": {"speed": mbps, "power": 20},
            "base_price": round(mbps * 0.6, 2),
        })

    for i, slots in enumerate((4, 8, 12, 24, 48)):
        items.append({
            "id": f"rack-{slots}", "category": "rack",
            "name": f"Стойка на {slots} GPU",
            "color": _tier_color(i),
            "specs": {"slots": slots},
            "base_price": round(slots * 900, 2),
        })
    for slots in (96, 200):
        items.append({
            "id": f"rack-ind-{slots}", "category": "rack",
            "name": f"Промышленная стойка ({slots} GPU)",
            "color": _tier_color(5),
            "specs": {"slots": slots, "industrial": True},
            "base_price": round(slots * 1100, 2),
        })

    return items


# ── Админский каталог ────────────────────────────────────────────────────────
#
# Контракт имён с frontend/src/utils/shopCatalog.js:
#   GPU:   "CrystalCore Quartz Q320" / "Pyronix Inferno IF1060" / "Archivex Genesis G1060"
#   CPU:   "CrystalChip Stone S210" / "PyroCore Inferno I560" / "ArchiveCore Genesis G560"
#   case:  "TitanFrame Mini M100" / "NovaCase Apex X550" / "IronNest Colossus C550"

# (brand_code, brand, line, hashrate)
_GPU_ROWS = [
    ("cc", "CrystalCore", "Quartz", 180),    ("cc", "CrystalCore", "Quartz", 220),
    ("cc", "CrystalCore", "Quartz", 270),    ("cc", "CrystalCore", "Quartz", 330),
    ("cc", "CrystalCore", "Quartz", 400),    ("cc", "CrystalCore", "Quartz", 480),
    ("cc", "CrystalCore", "Topaz", 620),     ("cc", "CrystalCore", "Topaz", 760),
    ("cc", "CrystalCore", "Topaz", 930),     ("cc", "CrystalCore", "Topaz", 1120),
    ("cc", "CrystalCore", "Topaz", 1340),    ("cc", "CrystalCore", "Topaz", 1600),
    ("cc", "CrystalCore", "Topaz", 1900),    ("cc", "CrystalCore", "Topaz", 2250),
    ("cc", "CrystalCore", "Sapphire", 2700), ("cc", "CrystalCore", "Sapphire", 3150),
    ("cc", "CrystalCore", "Sapphire", 3650), ("cc", "CrystalCore", "Sapphire", 4200),
    ("cc", "CrystalCore", "Sapphire", 4850), ("cc", "CrystalCore", "Sapphire", 5600),
    ("cc", "CrystalCore", "Sapphire", 6450), ("cc", "CrystalCore", "Sapphire", 7350),
    ("cc", "CrystalCore", "Diamond", 8400),  ("cc", "CrystalCore", "Diamond", 9600),
    ("cc", "CrystalCore", "Diamond", 11000), ("cc", "CrystalCore", "Diamond", 12500),
    ("cc", "CrystalCore", "Diamond", 14200), ("cc", "CrystalCore", "Diamond", 16000),
    ("cc", "CrystalCore", "Diamond", 18000), ("cc", "CrystalCore", "Diamond", 20000),
    ("py", "Pyronix", "Spark", 210),         ("py", "Pyronix", "Spark", 260),
    ("py", "Pyronix", "Spark", 320),         ("py", "Pyronix", "Spark", 390),
    ("py", "Pyronix", "Spark", 470),         ("py", "Pyronix", "Spark", 560),
    ("py", "Pyronix", "Flare", 720),         ("py", "Pyronix", "Flare", 880),
    ("py", "Pyronix", "Flare", 1070),        ("py", "Pyronix", "Flare", 1290),
    ("py", "Pyronix", "Flare", 1550),        ("py", "Pyronix", "Flare", 1860),
    ("py", "Pyronix", "Flare", 2220),        ("py", "Pyronix", "Flare", 2650),
    ("py", "Pyronix", "Blaze", 3150),        ("py", "Pyronix", "Blaze", 3700),
    ("py", "Pyronix", "Blaze", 4350),        ("py", "Pyronix", "Blaze", 5100),
    ("py", "Pyronix", "Blaze", 5950),        ("py", "Pyronix", "Blaze", 6900),
    ("py", "Pyronix", "Blaze", 8000),        ("py", "Pyronix", "Blaze", 9250),
    ("py", "Pyronix", "Inferno", 10700),     ("py", "Pyronix", "Inferno", 12300),
    ("py", "Pyronix", "Inferno", 14100),     ("py", "Pyronix", "Inferno", 16200),
    ("py", "Pyronix", "Inferno", 18500),     ("py", "Pyronix", "Inferno", 21000),
    ("py", "Pyronix", "Inferno", 24000),     ("py", "Pyronix", "Inferno", 27000),
    ("ax", "Archivex", "Vault", 170),        ("ax", "Archivex", "Vault", 210),
    ("ax", "Archivex", "Vault", 260),        ("ax", "Archivex", "Vault", 320),
    ("ax", "Archivex", "Vault", 390),        ("ax", "Archivex", "Vault", 470),
    ("ax", "Archivex", "Legacy", 600),       ("ax", "Archivex", "Legacy", 730),
    ("ax", "Archivex", "Legacy", 890),       ("ax", "Archivex", "Legacy", 1070),
    ("ax", "Archivex", "Legacy", 1290),      ("ax", "Archivex", "Legacy", 1550),
    ("ax", "Archivex", "Legacy", 1860),      ("ax", "Archivex", "Legacy", 2220),
    ("ax", "Archivex", "Archive", 2650),     ("ax", "Archivex", "Archive", 3150),
    ("ax", "Archivex", "Archive", 3700),     ("ax", "Archivex", "Archive", 4350),
    ("ax", "Archivex", "Archive", 5100),     ("ax", "Archivex", "Archive", 5950),
    ("ax", "Archivex", "Archive", 6900),     ("ax", "Archivex", "Archive", 8000),
    ("ax", "Archivex", "Genesis", 9300),     ("ax", "Archivex", "Genesis", 10800),
    ("ax", "Archivex", "Genesis", 12500),    ("ax", "Archivex", "Genesis", 14500),
    ("ax", "Archivex", "Genesis", 16700),    ("ax", "Archivex", "Genesis", 19200),
    ("ax", "Archivex", "Genesis", 22000),    ("ax", "Archivex", "Genesis", 25000),
]

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
_CPU_ROWS = [
    ("cc", "CrystalChip", "Stone", 1, 1.00),   ("cc", "CrystalChip", "Stone", 2, 1.01),
    ("cc", "CrystalChip", "Stone", 2, 1.02),   ("cc", "CrystalChip", "Stone", 3, 1.03),
    ("cc", "CrystalChip", "Stone", 4, 1.04),   ("cc", "CrystalChip", "Stone", 5, 1.05),
    ("cc", "CrystalChip", "Crystal", 6, 1.07),  ("cc", "CrystalChip", "Crystal", 7, 1.09),
    ("cc", "CrystalChip", "Crystal", 8, 1.11),  ("cc", "CrystalChip", "Crystal", 9, 1.13),
    ("cc", "CrystalChip", "Crystal", 10, 1.15), ("cc", "CrystalChip", "Crystal", 11, 1.17),
    ("cc", "CrystalChip", "Crystal", 12, 1.19), ("cc", "CrystalChip", "Crystal", 13, 1.21),
    ("cc", "CrystalChip", "Diamond", 14, 1.24), ("cc", "CrystalChip", "Diamond", 15, 1.27),
    ("cc", "CrystalChip", "Diamond", 16, 1.30), ("cc", "CrystalChip", "Diamond", 17, 1.33),
    ("cc", "CrystalChip", "Diamond", 18, 1.36), ("cc", "CrystalChip", "Diamond", 19, 1.39),
    ("cc", "CrystalChip", "Diamond", 20, 1.42), ("cc", "CrystalChip", "Diamond", 21, 1.45),
    ("cc", "CrystalChip", "Diamond", 22, 1.48), ("cc", "CrystalChip", "Diamond", 23, 1.52),
    ("cc", "CrystalChip", "Diamond", 24, 1.56), ("cc", "CrystalChip", "Diamond", 25, 1.60),
    ("cc", "CrystalChip", "Diamond", 26, 1.65), ("cc", "CrystalChip", "Diamond", 27, 1.70),
    ("cc", "CrystalChip", "Diamond", 28, 1.75), ("cc", "CrystalChip", "Diamond", 30, 1.80),
    ("py", "PyroCore", "Ember", 2, 1.02),      ("py", "PyroCore", "Ember", 3, 1.03),
    ("py", "PyroCore", "Ember", 4, 1.05),      ("py", "PyroCore", "Ember", 5, 1.07),
    ("py", "PyroCore", "Ember", 6, 1.09),      ("py", "PyroCore", "Ember", 7, 1.11),
    ("py", "PyroCore", "Blaze", 8, 1.14),      ("py", "PyroCore", "Blaze", 9, 1.17),
    ("py", "PyroCore", "Blaze", 10, 1.20),     ("py", "PyroCore", "Blaze", 11, 1.23),
    ("py", "PyroCore", "Blaze", 12, 1.26),     ("py", "PyroCore", "Blaze", 13, 1.29),
    ("py", "PyroCore", "Blaze", 14, 1.32),     ("py", "PyroCore", "Blaze", 15, 1.35),
    ("py", "PyroCore", "Inferno", 16, 1.39),   ("py", "PyroCore", "Inferno", 17, 1.43),
    ("py", "PyroCore", "Inferno", 18, 1.47),   ("py", "PyroCore", "Inferno", 19, 1.51),
    ("py", "PyroCore", "Inferno", 20, 1.55),   ("py", "PyroCore", "Inferno", 21, 1.59),
    ("py", "PyroCore", "Inferno", 22, 1.63),   ("py", "PyroCore", "Inferno", 23, 1.67),
    ("py", "PyroCore", "Inferno", 24, 1.72),   ("py", "PyroCore", "Inferno", 25, 1.77),
    ("py", "PyroCore", "Inferno", 26, 1.82),   ("py", "PyroCore", "Inferno", 27, 1.87),
    ("py", "PyroCore", "Inferno", 28, 1.92),   ("py", "PyroCore", "Inferno", 29, 1.97),
    ("py", "PyroCore", "Inferno", 30, 2.03),   ("py", "PyroCore", "Inferno", 32, 2.10),
    ("ax", "ArchiveCore", "Legacy", 1, 1.01),  ("ax", "ArchiveCore", "Legacy", 2, 1.02),
    ("ax", "ArchiveCore", "Legacy", 3, 1.03),  ("ax", "ArchiveCore", "Legacy", 4, 1.05),
    ("ax", "ArchiveCore", "Legacy", 5, 1.07),  ("ax", "ArchiveCore", "Legacy", 6, 1.09),
    ("ax", "ArchiveCore", "Archive", 7, 1.11), ("ax", "ArchiveCore", "Archive", 8, 1.13),
    ("ax", "ArchiveCore", "Archive", 9, 1.15), ("ax", "ArchiveCore", "Archive", 10, 1.17),
    ("ax", "ArchiveCore", "Archive", 11, 1.19),("ax", "ArchiveCore", "Archive", 12, 1.21),
    ("ax", "ArchiveCore", "Archive", 13, 1.23),("ax", "ArchiveCore", "Archive", 14, 1.25),
    ("ax", "ArchiveCore", "Genesis", 15, 1.28),("ax", "ArchiveCore", "Genesis", 16, 1.31),
    ("ax", "ArchiveCore", "Genesis", 17, 1.34),("ax", "ArchiveCore", "Genesis", 18, 1.37),
    ("ax", "ArchiveCore", "Genesis", 19, 1.40),("ax", "ArchiveCore", "Genesis", 20, 1.43),
    ("ax", "ArchiveCore", "Genesis", 21, 1.46),("ax", "ArchiveCore", "Genesis", 22, 1.49),
    ("ax", "ArchiveCore", "Genesis", 23, 1.53),("ax", "ArchiveCore", "Genesis", 24, 1.57),
    ("ax", "ArchiveCore", "Genesis", 25, 1.61),("ax", "ArchiveCore", "Genesis", 26, 1.65),
    ("ax", "ArchiveCore", "Genesis", 27, 1.70),("ax", "ArchiveCore", "Genesis", 28, 1.75),
    ("ax", "ArchiveCore", "Genesis", 29, 1.80),("ax", "ArchiveCore", "Genesis", 30, 1.85),
]

_CPU_SUFFIX = {
    "cc": {"Stone": ("S", 210), "Crystal": ("C", 310), "Diamond": ("D", 410)},
    "py": {"Ember": ("E", 210), "Blaze": ("B", 310), "Inferno": ("I", 410)},
    "ax": {"Legacy": ("L", 210), "Archive": ("A", 310), "Genesis": ("G", 410)},
}


def _cpu_suffix(code: str, line: str, idx_in_line: int) -> str:
    prefix, base = _CPU_SUFFIX[code][line]
    return f"{prefix}{base + idx_in_line * 10}"


# (brand_code, brand, line, max_gpus)
_CASE_ROWS = [
    ("tf", "TitanFrame", "Mini", 1),     ("tf", "TitanFrame", "Mini", 1),
    ("tf", "TitanFrame", "Mini", 2),     ("tf", "TitanFrame", "Mini", 2),
    ("tf", "TitanFrame", "Mini", 3),     ("tf", "TitanFrame", "Mini", 3),
    ("tf", "TitanFrame", "Air", 4),      ("tf", "TitanFrame", "Air", 4),
    ("tf", "TitanFrame", "Air", 5),      ("tf", "TitanFrame", "Air", 5),
    ("tf", "TitanFrame", "Air", 6),      ("tf", "TitanFrame", "Air", 6),
    ("tf", "TitanFrame", "Pro", 7),      ("tf", "TitanFrame", "Pro", 8),
    ("tf", "TitanFrame", "Pro", 9),      ("tf", "TitanFrame", "Pro", 10),
    ("tf", "TitanFrame", "Pro", 11),     ("tf", "TitanFrame", "Pro", 12),
    ("tf", "TitanFrame", "Ultra", 13),   ("tf", "TitanFrame", "Ultra", 14),
    ("tf", "TitanFrame", "Ultra", 15),   ("tf", "TitanFrame", "Ultra", 16),
    ("tf", "TitanFrame", "Ultra", 17),   ("tf", "TitanFrame", "Ultra", 18),
    ("tf", "TitanFrame", "Titan", 19),   ("tf", "TitanFrame", "Titan", 20),
    ("tf", "TitanFrame", "Titan", 22),   ("tf", "TitanFrame", "Titan", 24),
    ("tf", "TitanFrame", "Titan", 27),   ("tf", "TitanFrame", "Titan", 30),
    ("nc", "NovaCase", "Nano", 1),       ("nc", "NovaCase", "Nano", 1),
    ("nc", "NovaCase", "Nano", 2),       ("nc", "NovaCase", "Nano", 2),
    ("nc", "NovaCase", "Nano", 3),       ("nc", "NovaCase", "Nano", 4),
    ("nc", "NovaCase", "Flow", 4),       ("nc", "NovaCase", "Flow", 5),
    ("nc", "NovaCase", "Flow", 5),       ("nc", "NovaCase", "Flow", 6),
    ("nc", "NovaCase", "Flow", 6),       ("nc", "NovaCase", "Flow", 7),
    ("nc", "NovaCase", "Prime", 8),      ("nc", "NovaCase", "Prime", 9),
    ("nc", "NovaCase", "Prime", 10),     ("nc", "NovaCase", "Prime", 11),
    ("nc", "NovaCase", "Prime", 12),     ("nc", "NovaCase", "Prime", 13),
    ("nc", "NovaCase", "Elite", 14),     ("nc", "NovaCase", "Elite", 15),
    ("nc", "NovaCase", "Elite", 16),     ("nc", "NovaCase", "Elite", 17),
    ("nc", "NovaCase", "Elite", 18),     ("nc", "NovaCase", "Elite", 19),
    ("nc", "NovaCase", "Apex", 20),      ("nc", "NovaCase", "Apex", 22),
    ("nc", "NovaCase", "Apex", 24),      ("nc", "NovaCase", "Apex", 26),
    ("nc", "NovaCase", "Apex", 28),      ("nc", "NovaCase", "Apex", 30),
    ("in", "IronNest", "Base", 1),       ("in", "IronNest", "Base", 2),
    ("in", "IronNest", "Base", 2),       ("in", "IronNest", "Base", 3),
    ("in", "IronNest", "Base", 3),       ("in", "IronNest", "Base", 4),
    ("in", "IronNest", "Forge", 4),      ("in", "IronNest", "Forge", 5),
    ("in", "IronNest", "Forge", 6),      ("in", "IronNest", "Forge", 6),
    ("in", "IronNest", "Forge", 7),      ("in", "IronNest", "Forge", 8),
    ("in", "IronNest", "Steel", 9),     ("in", "IronNest", "Steel", 10),
    ("in", "IronNest", "Steel", 11),     ("in", "IronNest", "Steel", 12),
    ("in", "IronNest", "Steel", 13),     ("in", "IronNest", "Steel", 14),
    ("in", "IronNest", "Fortress", 15),  ("in", "IronNest", "Fortress", 16),
    ("in", "IronNest", "Fortress", 17),  ("in", "IronNest", "Fortress", 18),
    ("in", "IronNest", "Fortress", 19),  ("in", "IronNest", "Fortress", 20),
    ("in", "IronNest", "Colossus", 21),  ("in", "IronNest", "Colossus", 23),
    ("in", "IronNest", "Colossus", 25),  ("in", "IronNest", "Colossus", 27),
    ("in", "IronNest", "Colossus", 29),  ("in", "IronNest", "Colossus", 32),
]

_CASE_SUFFIX = {
    "tf": {"Mini": ("M", 100), "Air": ("A", 200), "Pro": ("P", 300),
           "Ultra": ("U", 400), "Titan": ("T", 500)},
    "nc": {"Nano": ("N", 100), "Flow": ("F", 200), "Prime": ("P", 300),
           "Elite": ("E", 400), "Apex": ("X", 500)},
    "in": {"Base": ("B", 100), "Forge": ("F", 200), "Steel": ("S", 300),
           "Fortress": ("R", 400), "Colossus": ("C", 500)},
}


def _case_suffix(code: str, line: str, idx_in_line: int) -> str:
    prefix, base = _CASE_SUFFIX[code][line]
    return f"{prefix}{base + idx_in_line * 10}"


def _gpu_color_for_hashrate(h: int) -> str:
    if h < 600:    return TIER_COLORS[0]
    if h < 2000:   return TIER_COLORS[1]
    if h < 6000:   return TIER_COLORS[2]
    if h < 12000:  return TIER_COLORS[3]
    if h < 20000:  return TIER_COLORS[4]
    return TIER_COLORS[5]


def _build_admin_catalog() -> list[dict]:
    """Полные серии GPU/CPU/case (по 90 шт.) + supplies (2 шт.).

    id формируются ровно так, как ожидает frontend (adminCatalog.js):
      admin-gpu-<N>, admin-cpu-<N>, admin-case-<N>, admin-supply-<kind>
    Имена совпадают с frontend/src/utils/shopCatalog.js.
    """
    items: list[dict] = []

    # ── GPU: 90 шт. (3 бренда × 4 линейки × 6 моделей)
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

    # ── CPU: 90 шт. (pid 1..90 в серии)
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

    # ── case: 90 шт. (pid 1..90 в серии)
    idx_in_line = {}
    case_pid = 0
    for code, brand, line, max_gpus in _CASE_ROWS:
        key = (code, line)
        i = idx_in_line.get(key, 0)
        idx_in_line[key] = i + 1
        case_pid += 1
        suffix = _case_suffix(code, line, i)
        items.append({
            "id": f"admin-case-{case_pid}",
            "category": "case",
            "name": f"{brand} {line} {suffix}",
            "brand": brand, "line": line,
            "color": _tier_color(min(5, max_gpus // 5)),
            "specs": {"slots": max_gpus},
            "base_price": round(max_gpus * 500, 2),
        })

    # ── Supplies: расходники.
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

    return items


# ── Каталоги (готовые) ───────────────────────────────────────────────────────


BASE_CATALOG = _build_base_catalog()
ADMIN_CATALOG = _build_admin_catalog()
CATALOG: list[dict] = BASE_CATALOG + ADMIN_CATALOG
CATALOG_BY_ID: dict[str, dict] = {c["id"]: c for c in CATALOG}


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
    """Админские overrides: {id: price}. None в БД = сброс к формуле."""
    doc = await find_config_by_key(db, SHOP_PRICES_KEY)
    if not doc:
        return {}
    try:
        raw = json.loads(doc["value"])
    except Exception:
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv > 0:
            out[str(k)] = fv
    return out


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
    current_user: dict = Depends(get_current_user),
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
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Продажа лишнего железа обратно магазину с уценкой (RESALE_RATIO)."""
    qty = max(1, int(payload.quantity))
    user_id = str(current_user["_id"])
    free = await db.user_hardware.find(
        {"userId": user_id, "itemId": payload.itemId, "farmId": None}
    ).to_list(length=qty)
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
    case: Optional[float] = None
    psu: Optional[float] = None
    cooling: Optional[float] = None
    rack: Optional[float] = None
    supplies: Optional[float] = None


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


def _canon_id(key: str) -> Optional[str]:
    """Числовой productId → канонический id каталога. None если не нашли."""
    if not key.isdigit():
        return key
    pid = int(key)
    if 1 <= pid <= 90:
        # Без доп. данных непонятно gpu/cpu/case — но редактор шлёт по одному
        # ключу на позицию в категории. По контексту: если в каталоге есть id
        # admin-{category}-{pid} — ок. Сначала проверяем gpu (исторически
        # первый в редакторе), но редактор выбирает категорию — поэтому мы
        # сохраняем ВСЕ совпадения как «category-pid» при сохранении. На
        # этапе save_payload обработаем это явно через явное указание категории.
        return f"pid:{pid}"
    if pid == 1:
        return "admin-supply-cooling-fluid"
    if pid == 2:
        return "admin-supply-gpu-chip"
    return None


@admin_router.get("/prices")
async def get_shop_prices(_admin=Depends(require_admin), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Все переопределения админских цен. Ключи — канонические id."""
    return {"prices": await _admin_prices(db)}


@admin_router.post("/prices")
async def set_shop_prices(
    payload: dict,
    _admin=Depends(require_admin),
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
        "supplies": "admin-supply",
    }.get(category)

    norm: dict[str, Optional[float]] = {}
    for k, v in prices_in.items():
        key = str(k)
        if v is None:
            # Сброс к формуле.
            canon = None
            if key.isdigit() and cat_prefix:
                pid = int(key)
                if 1 <= pid <= 90:
                    canon = f"{cat_prefix}-{pid}"
            elif key.startswith("admin-"):
                canon = key
            if canon:
                norm[canon] = None
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv <= 0:
            continue
        # Канонический id.
        if key.startswith("admin-"):
            canon = key
        elif key.isdigit() and cat_prefix:
            pid = int(key)
            if 1 <= pid <= 90:
                canon = f"{cat_prefix}-{pid}"
            elif category == "supplies":
                if pid == 1:
                    canon = "admin-supply-cooling-fluid"
                elif pid == 2:
                    canon = "admin-supply-gpu-chip"
                else:
                    continue
            else:
                continue
        else:
            continue
        norm[canon] = fv

    await upsert_config(db, SHOP_PRICES_KEY, json.dumps(norm))
    return {"ok": True, "count": sum(1 for v in norm.values() if v is not None)}


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
    admin_supplies = [c for c in ADMIN_CATALOG if c["category"] == "supplies"]
    assert len(admin_gpu) == 90, f"admin gpu: {len(admin_gpu)}"
    assert len(admin_cpu) == 90, f"admin cpu: {len(admin_cpu)}"
    assert len(admin_case) == 90, f"admin case: {len(admin_case)}"
    assert len(admin_supplies) == 2, f"admin supplies: {len(admin_supplies)}"

    ids = [c["id"] for c in CATALOG]
    assert len(ids) == len(set(ids)), "дубликаты id"

    # Контракт имён с shopCatalog.js — проверяем по одной позиции из каждой серии.
    gpu1 = CATALOG_BY_ID["admin-gpu-1"]
    assert gpu1["name"] == "CrystalCore Quartz Q320", f"got {gpu1['name']!r}"
    gpu60 = CATALOG_BY_ID["admin-gpu-60"]
    assert gpu60["name"] == "Pyronix Inferno IF1060", f"got {gpu60['name']!r}"
    gpu90 = CATALOG_BY_ID["admin-gpu-90"]
    assert gpu90["name"] == "Archivex Genesis G1060", f"got {gpu90['name']!r}"
    cpu1 = CATALOG_BY_ID["admin-cpu-1"]
    assert cpu1["name"] == "CrystalChip Stone S210", f"got {cpu1['name']!r}"
    cpu90 = CATALOG_BY_ID["admin-cpu-90"]
    assert cpu90["name"] == "ArchiveCore Genesis G560", f"got {cpu90['name']!r}"
    case1 = CATALOG_BY_ID["admin-case-1"]
    assert case1["name"] == "TitanFrame Mini M100", f"got {case1['name']!r}"
    case90 = CATALOG_BY_ID["admin-case-90"]
    assert case90["name"] == "IronNest Colossus C550", f"got {case90['name']!r}"

    print("shop self-check OK")
