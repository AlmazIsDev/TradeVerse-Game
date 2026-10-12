"""Уровни админки (1–4) и баны игроков.

- ADMIN_FUNCTIONS — полный реестр админ-функций: (id, уровень по умолчанию,
  ключ i18n). Распределение по уровням переопределяется в
  app_config["admin_permissions"] (редактирует только админ 4 уровня).
- require_admin(func) — dependency-фабрика: роль admin + admin_level >= уровня
  функции. У админов без поля admin_level уровень считается 4 — существующие
  админы после деплоя ничего не теряют.
- PLAYER_FUNCTIONS — игровые функции, которые админ может отключить игроку
  (users.bans[func]); require_allowed(func) проверяет бан на входе эндпоинта.
- Полный бан аккаунта (bans.account) проверяется в auth.get_current_user.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status

from auth import get_current_user
from database import get_db, find_config_by_key

PERMS_CONFIG_KEY = "admin_permissions"

# ── Реестр админ-функций (id, уровень по умолчанию, i18n) ────────────────────
ADMIN_FUNCTIONS: list[tuple[str, int, str]] = [
    # L1 — наблюдение (только чтение)
    ("economy_view", 1, "adminPerms.func_economy_view"),
    ("transactions_view", 1, "adminPerms.func_transactions_view"),
    ("users_view", 1, "adminPerms.func_users_view"),
    # L2 — модерация игроков
    ("bans", 2, "adminPerms.func_bans"),
    # L3 — оперирование
    ("crypto", 3, "adminPerms.func_crypto"),
    ("stocks", 3, "adminPerms.func_stocks"),
    ("catalog_prices", 3, "adminPerms.func_catalog_prices"),
    ("shop_config", 3, "adminPerms.func_shop_config"),
    ("price_history", 3, "adminPerms.func_price_history"),
    ("users_edit", 3, "adminPerms.func_users_edit"),
    ("users_property", 3, "adminPerms.func_users_property"),
    ("users_password", 3, "adminPerms.func_users_password"),
    ("users_logout", 3, "adminPerms.func_users_logout"),
    ("central_market", 3, "adminPerms.func_central_market"),
    ("broadcast", 3, "adminPerms.func_broadcast"),
    ("economy_config", 3, "adminPerms.func_economy_config"),
    ("market_events", 3, "adminPerms.func_market_events"),
    ("synthetic", 3, "adminPerms.func_synthetic"),
    # L4 — владение (опасные/глобальные операции)
    ("users_delete", 4, "adminPerms.func_users_delete"),
    ("transactions_delete", 4, "adminPerms.func_transactions_delete"),
    ("config", 4, "adminPerms.func_config"),
    ("database", 4, "adminPerms.func_database"),
]
ADMIN_FUNCTION_IDS = {fid for fid, _, _ in ADMIN_FUNCTIONS}

# Не настраивается: редактором прав может владеть только полный админ.
FIXED_ADMIN_FUNCTIONS: dict[str, int] = {"admin_perms": 4}

VALID_LEVELS = (1, 2, 3, 4)


async def get_admin_levels(db) -> dict:
    """Уровень каждой админ-функции: дефолты реестра + overrides из конфига."""
    levels = {fid: lvl for fid, lvl, _ in ADMIN_FUNCTIONS}
    levels.update(FIXED_ADMIN_FUNCTIONS)
    doc = await find_config_by_key(db, PERMS_CONFIG_KEY)
    if doc:
        try:
            for k, v in json.loads(doc["value"]).items():
                if k in ADMIN_FUNCTION_IDS and int(v) in VALID_LEVELS:
                    levels[k] = int(v)
        except Exception:
            pass
    return levels


async def save_admin_levels(db, levels: dict) -> None:
    """Сохраняет overrides уровней (только настраиваемые функции, 1..4)."""
    clean = {
        k: int(v) for k, v in levels.items()
        if k in ADMIN_FUNCTION_IDS and int(v) in VALID_LEVELS
    }
    from database import upsert_config
    await upsert_config(db, PERMS_CONFIG_KEY, json.dumps(clean))


def admin_level_of(user: dict) -> int:
    """Уровень админа (0 для не-админов). Нет поля → 4 (legacy-админы)."""
    if user.get("role") != "admin":
        return 0
    try:
        return int(user.get("admin_level") or 4)
    except (TypeError, ValueError):
        return 4


def require_admin(func: str | None = None):
    """Dependency-фабрика: админ с уровнем, достаточным для функции func.

    require_admin() без аргумента — «любой админ» (для эндпоинтов вне реестра).
    """
    async def dep(
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db),
    ) -> dict:
        if current_user.get("role") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Доступ запрещён: требуются права администратора",
            )
        if func:
            needed = await level_for(db, func)
            if admin_level_of(current_user) < needed:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Недостаточный уровень админки (нужен {needed})",
                )
        return current_user
    return dep


async def level_for(db, func: str) -> int:
    levels = await get_admin_levels(db)
    return levels.get(func, 4)


# ── Баны игроков ─────────────────────────────────────────────────────────────

# Игровые функции, отключаемые игроку по отдельности.
PLAYER_FUNCTIONS: list[tuple[str, str]] = [
    ("transfer", "banFunc.transfer"),
    ("crypto", "banFunc.crypto"),
    ("stocks", "banFunc.stocks"),
    ("shop", "banFunc.shop"),
    ("assets", "banFunc.assets"),
    ("centralmarket", "banFunc.centralmarket"),
    ("mining", "banFunc.mining"),
    ("farm", "banFunc.farm"),
    ("company", "banFunc.company"),
    ("cityroof", "banFunc.cityroof"),
    ("media", "banFunc.media"),
]
PLAYER_FUNCTION_IDS = {fid for fid, _ in PLAYER_FUNCTIONS}


def ban_active(ban: dict | None) -> bool:
    """Активен ли бан: без срока — навсегда; с until — пока срок не истёк."""
    if not ban:
        return False
    until = ban.get("until")
    if not until:
        return True
    if isinstance(until, str):
        try:
            until = datetime.fromisoformat(until)
        except ValueError:
            return True
    if isinstance(until, datetime):
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return until > datetime.now(timezone.utc)
    return True


def user_ban_active(user: dict, func: str) -> bool:
    return ban_active((user.get("bans") or {}).get(func))


def require_allowed(func: str):
    """Dependency-фабрика: у игрока нет активного бана функции func.

    Ставится вместо Depends(get_current_user) на входе игровых эндпоинтов.
    """
    async def dep(current_user: dict = Depends(get_current_user)) -> dict:
        if user_ban_active(current_user, func):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Функция недоступна: доступ ограничен администрацией",
            )
        return current_user
    return dep
