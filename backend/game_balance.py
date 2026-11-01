"""Игровой баланс в MongoDB: дефолты из game_config, переопределения в app_config.

Переопределения лежат одним документом (ключ BALANCE_KEY); при чтении
глубоко мержатся поверх DEFAULTS. Кеш процесса сбрасывается при записи.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from admin_audit import changed_fields, record_admin_action
from admin_perms import require_admin
from database import find_config_by_key, get_db, upsert_config
from game_config import (
    RENTAL_CONFIG,
    ITSTUDIO_CONFIG,
    FARM_CONFIG,
    PRODUCTION_CONFIG,
    RECIPES,
    COMPONENT_BASE_PRICE,
    COMPONENT_COST,
)

BALANCE_KEY = "game_balance_config"

DEFAULTS: dict[str, Any] = {
    "rental": RENTAL_CONFIG,
    "itstudio": ITSTUDIO_CONFIG,
    "farm": FARM_CONFIG,
    "production": PRODUCTION_CONFIG,
    "recipes": RECIPES,
    "component_base_price": COMPONENT_BASE_PRICE,
    "component_cost": COMPONENT_COST,
}

_cache: dict[str, Any] | None = None


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            out[k] = _deep_merge(base[k], v) if k in base else v
        return out
    return override


def _validate_shape(value: Any, default: Any, path: str = "") -> None:
    """Переопределение обязано повторять структуру дефолта: новые ключи и смена типа запрещены."""
    if isinstance(default, dict):
        if not isinstance(value, dict):
            raise ValueError(f"{path or 'root'}: ожидается объект")
        for k, v in value.items():
            if k not in default:
                raise ValueError(f"{path}.{k}: неизвестный ключ")
            _validate_shape(v, default[k], f"{path}.{k}" if path else k)
        return
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(f"{path}: ожидается bool")
        return
    if isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path}: ожидается число")
        return
    if isinstance(default, str):
        if not isinstance(value, str):
            raise ValueError(f"{path}: ожидается строка")
        return
    if isinstance(default, list):
        if not isinstance(value, list):
            raise ValueError(f"{path}: ожидается список")
        return
    raise ValueError(f"{path}: неподдерживаемый тип")


async def _load_overrides(db: AsyncIOMotorDatabase) -> dict:
    doc = await find_config_by_key(db, BALANCE_KEY)
    if not doc:
        return {}
    try:
        data = json.loads(doc["value"])
    except (ValueError, TypeError, KeyError):
        return {}
    return data if isinstance(data, dict) else {}


async def get_balance(db: AsyncIOMotorDatabase) -> dict:
    """Текущий баланс (дефолты + переопределения), кешируется в процессе."""
    global _cache
    if _cache is None:
        overrides = await _load_overrides(db)
        _cache = _deep_merge(copy.deepcopy(DEFAULTS), overrides)
    return copy.deepcopy(_cache)


async def set_balance(db: AsyncIOMotorDatabase, patch: dict) -> dict:
    """Сохраняет переопределения: patch мержится поверх текущих overrides."""
    global _cache
    for section, value in patch.items():
        if section not in DEFAULTS:
            raise ValueError(f"{section}: неизвестный раздел баланса")
        _validate_shape(value, DEFAULTS[section], section)
    overrides = _deep_merge(await _load_overrides(db), patch)
    await upsert_config(db, BALANCE_KEY, json.dumps(overrides, ensure_ascii=False))
    _cache = None
    return await get_balance(db)


async def warm_cache(db: AsyncIOMotorDatabase) -> None:
    """Прогрев при старте: синхронные потребители читают кеш через current()."""
    await get_balance(db)


def current(section: str) -> Any:
    """Синхронное чтение раздела баланса; до прогрева отдаёт дефолты."""
    source = _cache if _cache is not None else DEFAULTS
    return source[section]


class _LiveSection(Mapping):
    """Прокси раздела: каждое обращение читает текущий кеш (модульные константы без перезапуска)."""

    __slots__ = ("_name",)

    def __init__(self, name: str):
        self._name = name

    def __getitem__(self, key):
        return current(self._name)[key]

    def __iter__(self):
        return iter(current(self._name))

    def __len__(self):
        return len(current(self._name))


def live(section: str) -> Mapping:
    if section not in DEFAULTS:
        raise KeyError(section)
    return _LiveSection(section)


def invalidate_cache() -> None:
    global _cache
    _cache = None


router = APIRouter(prefix="/api/admin/game-balance", tags=["game-balance-admin"])


class GameBalancePatch(BaseModel):
    patch: dict[str, Any]


@router.get("")
async def get_game_balance(_admin=Depends(require_admin("economy_view")), db: AsyncIOMotorDatabase = Depends(get_db)):
    return await get_balance(db)


@router.patch("")
async def patch_game_balance(
    payload: GameBalancePatch,
    admin=Depends(require_admin("economy_config")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    before = await get_balance(db)
    try:
        after = await set_balance(db, payload.patch)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    await record_admin_action(
        db, "game_balance.update", admin,
        changes=changed_fields(
            {k: before.get(k) for k in payload.patch},
            {k: after.get(k) for k in payload.patch},
        ),
    )
    return after
