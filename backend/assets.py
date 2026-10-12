"""Активы: рынок недвижимости, бизнесов и автомобилей.

Игрок покупает активы с рынка (каталог), владеет ими, улучшает, собирает
пассивный доход (бизнесы/аренда) и продаёт обратно. Все денежные движения
проходят через единый реестр (ledger). Стоимость активов учитывается в
чистом капитале игрока (лидерборд).
"""
from __future__ import annotations

import json
from typing import Optional

import random
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator

from admin_perms import get_current_user, require_admin, require_allowed
from database import get_db, find_config_by_key, upsert_config
from ledger import (
    INCOME, EXPENSE, CAT_REALESTATE, CAT_BUSINESS,
    CAT_FACTORY, CAT_SOURCE, CAT_WAREHOUSE,
    adjust_balance, record_transaction,
)
from notifications import push_notification
from econ import get_econ
from timeutil import now_utc, to_aware

router = APIRouter(prefix="/api/assets", tags=["assets"])

TYPE_REALESTATE = "realestate"
TYPE_BUSINESS = "business"
TYPE_CAR = "car"
# Инфраструктурные типы: заводы (factory), источники ресурсов (source) и
# склады (warehouse). Согласованы с frontend/src/utils/adminCatalog.js
# (ADMIN_FACTORIES_CATALOG, ADMIN_SOURCES_CATALOG, ADMIN_WAREHOUSES_CATALOG)
# и с категориями витрины MarketTab. Изначально витрина магазина отдавала
# slug-и admin-fac-*/admin-src-*/admin-wh-*, а бэкенд их не знал - поэтому
# покупка отвечала 404 «Актив не найден». После добавления этих типов в
# CATALOG и ASSET_TYPES покупка корректно создаёт запись в user_assets и
# инвентаре игрока.
TYPE_FACTORY = "factory"
TYPE_SOURCE = "source"
TYPE_WAREHOUSE = "warehouse"
ASSET_TYPES = {TYPE_REALESTATE, TYPE_BUSINESS, TYPE_CAR, TYPE_FACTORY, TYPE_SOURCE, TYPE_WAREHOUSE}

# Маппер типа актива -> категория реестра (ledger). Используется в buy/sell/
# upgrade/collect, чтобы покупка завода попадала в категорию CAT_FACTORY, а не
# в CAT_REALESTATE (старое поведение тернарника). Для типов без отдельной
# категории фолбэк - CAT_REALESTATE (например, авто идут как realestate -
# раньше так и было).
_ASSET_CATEGORY = {
    TYPE_BUSINESS: CAT_BUSINESS,
    TYPE_FACTORY: CAT_FACTORY,
    TYPE_SOURCE: CAT_SOURCE,
    TYPE_WAREHOUSE: CAT_WAREHOUSE,
    TYPE_REALESTATE: CAT_REALESTATE,
    TYPE_CAR: CAT_REALESTATE,
}


def _ledger_category(asset_or_type) -> str:
    """Категория реестра по типу актива/словарю. Не зависит от регистра."""
    if isinstance(asset_or_type, dict):
        t = asset_or_type.get("type")
    else:
        t = asset_or_type
    return _ASSET_CATEGORY.get(t, CAT_REALESTATE)

SELL_RATE = 0.7          # возврат при продаже — 70% текущей стоимости
MAX_ACCRUAL_HOURS = 24   # максимум накопленного дохода за один сбор

UPGRADE_COST_PCT = 0.32  # доля базовой цены за уровень (см. _upgrade_cost)

# ── Тюнинг автомобилей ────────────────────────────────────────────────────────
# Каждая деталь повышает престиж авто; стоимость улучшения зависит от цены авто
# и текущего уровня детали. Вложения в тюнинг увеличивают стоимость авто (капитал).
TUNE_PARTS = {
    "engine": 18, "turbo": 22, "gearbox": 15, "suspension": 12,
    "brakes": 10, "tires": 9, "exhaust": 8,
}
TUNE_MAX_LEVEL = 5
TUNE_COST_FACTOR = 0.05      # доля от цены авто за уровень
TUNE_VALUE_RETAIN = 0.7      # какая часть вложений в тюнинг идёт в стоимость авто


def _tune_cost(asset: dict, level: int) -> float:
    """Стоимость следующего уровня детали (растёт с ценой авто и уровнем)."""
    return round(asset.get("price", 0) * TUNE_COST_FACTOR * (level + 1), 2)

RENT_MIN_WAIT_H = 1      # минимум ожидания арендатора
# Ожидание арендатора НЕ оплачивается, поэтому оно работает как налог на аренду:
# при разбросе 1–48ч (в среднем 24.5ч) суточная сдача приносила лишь 49% ставки,
# а часовая — 4%. Диапазон 1–6ч (в среднем 3.5ч) поднимает те же сценарии до
# 87% и 22% — сдавать становится осмысленно и на короткий срок.
RENT_MAX_WAIT_H = 6      # максимум ожидания арендатора
RENT_MAX_HOURS = 720     # максимальный срок аренды (30 суток)
RENTABLE_TYPES = {"realestate", "car", "business"}
# Среди бизнесов в аренду сдаются только те, у кого есть полезная для арендатора
# механика: IT-студия (заказы «Крыши города», cityroof.py) и Медиахолдинг
# (разоблачения в СМИ, media.py). Остальные бизнесы (шаурмечная, кофейня, завод…)
# сдавать нельзя — арендовать в них нечего, кроме голого дохода.
RENTABLE_BUSINESS_SLUGS = {"media_holding"}   # + любые itstudio_* (по префиксу slug)

# Лимиты владения на игрока (учёт по userId, включая переданные компании —
# они остаются в портфеле владельца). Проверяется при покупке и в ЦР.
TYPE_LIMITS = {TYPE_REALESTATE: 40, TYPE_BUSINESS: 20}
_LIMIT_NAMES = {TYPE_REALESTATE: "домов", TYPE_BUSINESS: "бизнесов"}


async def check_type_limit(db, user_id: str, asset_type: str) -> None:
    """Не дать игроку превысить лимит владения домами/бизнесами."""
    limit = TYPE_LIMITS.get(asset_type)
    if not limit:
        return
    cnt = await db.user_assets.count_documents({"userId": user_id, "type": asset_type})
    if cnt >= limit:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Достигнут лимит: не больше {limit} {_LIMIT_NAMES[asset_type]} на игрока",
        )



def _is_rentable(asset: dict) -> bool:
    """Можно ли выставить актив в аренду. Недвижимость и авто — всегда; бизнесы —
    только IT-студия и Медиахолдинг (см. RENTABLE_BUSINESS_SLUGS)."""
    atype = asset.get("type")
    if atype not in RENTABLE_TYPES:
        return False
    if atype == TYPE_BUSINESS:
        slug = asset.get("slug") or ""
        return slug.startswith("itstudio_") or slug in RENTABLE_BUSINESS_SLUGS
    return True

# ── Экономика аренды ─────────────────────────────────────────────────────────
# У каждого актива — своя суточная ставка аренды: она НЕ одинакова для всего
# имущества, а рассчитывается из совокупности факторов:
#   1) текущая стоимость актива (цена + уровень апгрейда + тюнинг, см. _current_value);
#   2) редкость/класс объекта (rarity) — определяет % от стоимости в сутки;
# Чем реже и роскошнее объект — тем выше именно ПРОЦЕНТ доходности (не только
# абсолютная сумма за счёт более высокой цены). Поэтому дешёвая недвижимость
# даёт скромный доход, а элитная — кратно выгоднее как в долларах, так и в %,
# и не бывает ситуации, когда дешёвый объект почти не уступает дорогому.
#
# Ориентир баланса (единый для всей экономики): суммарная доходность актива —
# 24–30% в сутки, то есть окупаемость 3.3–4.2 дня. Пассивный доход несёт 3/4
# этой цели, аренда — оставшуюся 1/4 (АКТИВНАЯ часть, её надо выставлять
# руками). Раньше пропорция была обратной, и сдаваемый актив в магазине
# выглядел втрое хуже несдаваемого той же цены — карточка показывает только
# пассивный доход. Прежние ставки 2.4–7.8%/сутки давали окупаемость 13–42 дня —
# «поставил и ушёл на месяц», из-за чего активы ощущались бесполезными.
RARITY_RENT_PCT = {
    "common": 0.060,      # 6.0%/сутки
    "uncommon": 0.0625,   # 6.2%/сутки
    "rare": 0.065,        # 6.5%/сутки
    "epic": 0.070,        # 7.0%/сутки
    "legendary": 0.075,   # 7.5%/сутки
}
# Автомобили не имеют пассивного дохода (см. _income_per_hour) — аренда для них
# единственный источник, поэтому она должна нести всю цель целиком, а не 1/4:
# без множителя авто окупались бы вчетверо дольше недвижимости той же редкости.
CAR_RENT_MULT = 4.0
# Минимальный суточный доход по редкости — подстраховка от вырожденных случаев
# (например, сильно уценённый на рынке актив), а НЕ основной драйвер экономики,
# как было раньше (плоский пол в $2000 одинаковый для всех — тот самый баг,
# из-за которого дешёвая студия зарабатывала как элитная недвижимость).
RARITY_RENT_FLOOR = {
    "common": 300.0,
    "uncommon": 850.0,
    "rare": 2500.0,
    "epic": 8500.0,
    "legendary": 22000.0,
}

# ── Материалы для бизнеса ────────────────────────────────────────────────────
# Цена за единицу = базовая × economy_mult × множитель текущего мирового
# события (см. market_events.EVENT_TYPES["materials"], настраивается через
# админ-панель — событие меняется, цена пересчитывается автоматически, без
# правки кода). Закупка временно поднимает доход бизнеса.
#
# Это ГЛАВНАЯ активная механика бизнеса: пассивный доход капает сам, а буст
# требует зайти и вложиться. Поэтому потолок высокий (+80%), а срок короткий
# (4ч) — активный игрок обгоняет пассивного примерно в 1.5 раза, но обязан
# возвращаться. Цена единицы — доля от часового дохода конкретного бизнеса
# (MATERIALS_COST_PER_INCOME_H), иначе буст премиальной IT-студии стоил бы
# столько же, сколько буст шаурмечной, то есть был бы бесплатным.
MATERIALS_BOOST_PER_UNIT = 0.02     # +2% к доходу за единицу
MATERIALS_BOOST_CAP = 0.80          # максимум +80%
MATERIALS_DURATION_H = 4            # действует 4 часа с момента закупки
# Единица материалов стоит столько же, сколько бизнес зарабатывает за этот
# процент дохода примерно за 1.6ч — полный буст окупается за ~2.5ч из 4ч срока.
MATERIALS_COST_PER_INCOME_H = 1.6

# ── Каталог рынка (сид) ──────────────────────────────────────────────────────
# income_per_hour — пассивный доход; upkeep_per_hour — расход (для бизнесов).
# rarity — определяет и рыночный дрейф цены (RARITY_FLOOR), и ставку аренды
# (RARITY_RENT_PCT/RARITY_RENT_FLOOR) — есть у всех типов, включая бизнесы.
#
# Баланс доходности: чистый пассивный доход (income − upkeep) подобран так,
# чтобы вместе с арендой актив выходил на 24–30% в сутки (окупаемость 3.3–4.2
# дня, растёт с редкостью). Пассив несёт 3/4 цели, аренда — 1/4; несдаваемые
# бизнесы (шаурмечная, кофейня, автомойка, завод) несут всю доходность в
# income_per_hour. Доход экземпляра масштабируется по уплаченной цене
# (см. buy_asset) — на пике рынка актив и стоит, и приносит больше.

CATALOG = [
    # Недвижимость: аренда как доход, налог как расход. Поле basement — ёмкость
    # подвала в корпусах, определяет цену/доходность улучшения «Майнинг»
    # Цена/доход за единицу подвала — из econ (mining_basement_cost/income).
    # чтобы более дорогой дом позволял поставить больше оборудования и быстрее
    # окупать улучшение.
    {"slug": "studio", "type": TYPE_REALESTATE, "name": "Студия", "rarity": "common",
     "price": 5000, "income_per_hour": 50, "upkeep_per_hour": 12, "rooms": 1, "basement": 2, "meta": {"tax": 12}},
    {"slug": "flat2", "type": TYPE_REALESTATE, "name": "Двухкомнатная квартира", "rarity": "common",
     "price": 14000, "income_per_hour": 140, "upkeep_per_hour": 35, "rooms": 2, "basement": 3, "meta": {"tax": 35}},
    {"slug": "townhouse", "type": TYPE_REALESTATE, "name": "Таунхаус", "rarity": "uncommon",
     "price": 45000, "income_per_hour": 469, "upkeep_per_hour": 117, "rooms": 4, "basement": 6, "meta": {"tax": 117}},
    {"slug": "villa", "type": TYPE_REALESTATE, "name": "Вилла у моря", "rarity": "rare",
     "price": 160000, "income_per_hour": 1733, "upkeep_per_hour": 433, "rooms": 6, "basement": 10, "meta": {"tax": 433}},
    {"slug": "penthouse", "type": TYPE_REALESTATE, "name": "Пентхаус", "rarity": "epic",
     "price": 480000, "income_per_hour": 5600, "upkeep_per_hour": 1400, "rooms": 8, "basement": 16, "meta": {"tax": 1400}},
    {"slug": "castle", "type": TYPE_REALESTATE, "name": "Замок", "rarity": "legendary",
     "price": 1500000, "income_per_hour": 18750, "upkeep_per_hour": 4688, "rooms": 20, "basement": 24, "meta": {"tax": 4688}},
    # Бизнесы: доход и расходы, есть сотрудники. rarity — экономический класс
    # бизнеса (отдельно от category, которая отвечает только за тематику/иконку).
    {"slug": "shawarma", "type": TYPE_BUSINESS, "name": "Шаурмечная", "category": "retail", "rarity": "common",
     "price": 8000, "income_per_hour": 119, "upkeep_per_hour": 39, "employees": 2},
    {"slug": "coffee", "type": TYPE_BUSINESS, "name": "Кофейня", "category": "retail", "rarity": "uncommon",
     "price": 25000, "income_per_hour": 389, "upkeep_per_hour": 128, "employees": 4},
    {"slug": "carwash", "type": TYPE_BUSINESS, "name": "Автомойка", "category": "service", "rarity": "rare",
     "price": 60000, "income_per_hour": 970, "upkeep_per_hour": 320, "employees": 6},
    # IT-студия — 4 тира (slug = "itstudio_" + ключ тира в game_config.ITSTUDIO_CONFIG).
    # Владение экземпляром открывает заказ атаки/защиты «Крыши города»
    # (см. cityroof.py) — материалы, шанс успеха и опыт зависят от тира.
    {"slug": "itstudio_basic", "type": TYPE_BUSINESS, "name": "IT-студия: Базовая", "category": "tech", "rarity": "epic",
     "price": 200000, "income_per_hour": 2612, "upkeep_per_hour": 862, "employees": 12},
    {"slug": "itstudio_medium", "type": TYPE_BUSINESS, "name": "IT-студия: Средняя", "category": "tech", "rarity": "epic",
     "price": 450000, "income_per_hour": 5877, "upkeep_per_hour": 1939, "employees": 20},
    {"slug": "itstudio_advanced", "type": TYPE_BUSINESS, "name": "IT-студия: Продвинутая", "category": "tech", "rarity": "legendary",
     "price": 900000, "income_per_hour": 12593, "upkeep_per_hour": 4156, "employees": 32},
    {"slug": "itstudio_premium", "type": TYPE_BUSINESS, "name": "IT-студия: Премиальная", "category": "tech", "rarity": "legendary",
     "price": 1800000, "income_per_hour": 25187, "upkeep_per_hour": 8312, "employees": 50},
    {"slug": "factory", "type": TYPE_BUSINESS, "name": "Завод", "category": "office", "rarity": "legendary",
     "price": 750000, "income_per_hour": 13993, "upkeep_per_hour": 4618, "employees": 40},
    # Медиахолдинг — открывает заказ разоблачений в СМИ (см. media.py): владелец
    # может ударить по доходам бизнесов конкурента и цене его акции.
    {"slug": "media_holding", "type": TYPE_BUSINESS, "name": "Медиахолдинг", "category": "media", "rarity": "legendary",
     "price": 1200000, "income_per_hour": 16791, "upkeep_per_hour": 5541, "employees": 45},
    # Автомобили: престиж (без дохода), учитываются в капитале, но сдаются в аренду
    {"slug": "citycar", "type": TYPE_CAR, "name": "Городской хэтчбек", "rarity": "common",
     "price": 12000, "income_per_hour": 0, "upkeep_per_hour": 0, "meta": {"prestige": 5}},
    {"slug": "sedan", "type": TYPE_CAR, "name": "Бизнес-седан", "rarity": "uncommon",
     "price": 40000, "income_per_hour": 0, "upkeep_per_hour": 0, "meta": {"prestige": 20}},
    {"slug": "sport", "type": TYPE_CAR, "name": "Спорткар", "rarity": "rare",
     "price": 150000, "income_per_hour": 0, "upkeep_per_hour": 0, "meta": {"prestige": 60}},
    {"slug": "super", "type": TYPE_CAR, "name": "Суперкар", "rarity": "epic",
     "price": 600000, "income_per_hour": 0, "upkeep_per_hour": 0, "meta": {"prestige": 200}},
]

# ── Расширенный каталог недвижимости и бизнесов (admin-re-1..81, admin-biz-1..12) ──
# Добавлено для согласования с frontend/src/utils/adminCatalog.js:
# витрина в MarketTab показывает 81 дом и 12 бизнесов. Цены, income, basement
# и employees рассчитаны по тем же формулам, что и в adminCatalog.js, чтобы
# карточки в «Рынке» и реальный покупаемый каталог совпадали.
# Цены admin-re поднимаются плавной лестницей по rarity (5 ступеней × 81 дом),
# цены admin-biz — лестницей по category (4 ступени × 3 объекта).

_ADMIN_MARKET_HOUSES = [
    {"slug": "admin-re-1", "type": TYPE_REALESTATE, "name": "Sunny Cottage", "rarity": "common", "price": 5000, "income_per_hour": 25, "upkeep_per_hour": 4, "rooms": 1, "basement": 1, "meta": {"tax": 5}},
    {"slug": "admin-re-2", "type": TYPE_REALESTATE, "name": "Green Nest", "rarity": "common", "price": 5225, "income_per_hour": 25, "upkeep_per_hour": 4, "rooms": 1, "basement": 1, "meta": {"tax": 5}},
    {"slug": "admin-re-3", "type": TYPE_REALESTATE, "name": "Little Oak", "rarity": "common", "price": 5450, "income_per_hour": 25, "upkeep_per_hour": 4, "rooms": 1, "basement": 1, "meta": {"tax": 5}},
    {"slug": "admin-re-4", "type": TYPE_REALESTATE, "name": "Rose House", "rarity": "common", "price": 5675, "income_per_hour": 25, "upkeep_per_hour": 4, "rooms": 1, "basement": 2, "meta": {"tax": 5}},
    {"slug": "admin-re-5", "type": TYPE_REALESTATE, "name": "Maple Home", "rarity": "common", "price": 5959, "income_per_hour": 25, "upkeep_per_hour": 4, "rooms": 2, "basement": 2, "meta": {"tax": 5}},
    {"slug": "admin-re-6", "type": TYPE_REALESTATE, "name": "Silver Cottage", "rarity": "common", "price": 6186, "income_per_hour": 25, "upkeep_per_hour": 4, "rooms": 2, "basement": 2, "meta": {"tax": 5}},
    {"slug": "admin-re-7", "type": TYPE_REALESTATE, "name": "Forest View", "rarity": "common", "price": 6414, "income_per_hour": 25, "upkeep_per_hour": 4, "rooms": 2, "basement": 2, "meta": {"tax": 5}},
    {"slug": "admin-re-8", "type": TYPE_REALESTATE, "name": "Pine Residence", "rarity": "common", "price": 6641, "income_per_hour": 25, "upkeep_per_hour": 4, "rooms": 2, "basement": 3, "meta": {"tax": 5}},
    {"slug": "admin-re-9", "type": TYPE_REALESTATE, "name": "Golden Nest", "rarity": "common", "price": 6868, "income_per_hour": 25, "upkeep_per_hour": 4, "rooms": 2, "basement": 3, "meta": {"tax": 5}},
    {"slug": "admin-re-10", "type": TYPE_REALESTATE, "name": "Blue Horizon", "rarity": "common", "price": 7095, "income_per_hour": 25, "upkeep_per_hour": 4, "rooms": 2, "basement": 3, "meta": {"tax": 5}},
    {"slug": "admin-re-11", "type": TYPE_REALESTATE, "name": "Stone Cottage", "rarity": "common", "price": 7322, "income_per_hour": 25, "upkeep_per_hour": 4, "rooms": 2, "basement": 3, "meta": {"tax": 5}},
    {"slug": "admin-re-12", "type": TYPE_REALESTATE, "name": "Autumn House", "rarity": "common", "price": 7550, "income_per_hour": 25, "upkeep_per_hour": 4, "rooms": 2, "basement": 4, "meta": {"tax": 5}},
    {"slug": "admin-re-13", "type": TYPE_REALESTATE, "name": "Meadow Home", "rarity": "common", "price": 7854, "income_per_hour": 26, "upkeep_per_hour": 5, "rooms": 3, "basement": 4, "meta": {"tax": 5}},
    {"slug": "admin-re-14", "type": TYPE_REALESTATE, "name": "Oak Residence", "rarity": "common", "price": 8084, "income_per_hour": 26, "upkeep_per_hour": 5, "rooms": 3, "basement": 4, "meta": {"tax": 5}},
    {"slug": "admin-re-15", "type": TYPE_REALESTATE, "name": "Cherry Cottage", "rarity": "common", "price": 8313, "income_per_hour": 26, "upkeep_per_hour": 5, "rooms": 3, "basement": 4, "meta": {"tax": 5}},
    {"slug": "admin-re-16", "type": TYPE_REALESTATE, "name": "Birch House", "rarity": "common", "price": 8542, "income_per_hour": 26, "upkeep_per_hour": 5, "rooms": 3, "basement": 4, "meta": {"tax": 5}},
    {"slug": "admin-re-17", "type": TYPE_REALESTATE, "name": "Morning Villa", "rarity": "common", "price": 8772, "income_per_hour": 26, "upkeep_per_hour": 5, "rooms": 3, "basement": 5, "meta": {"tax": 5}},
    {"slug": "admin-re-18", "type": TYPE_REALESTATE, "name": "Hill Cottage", "rarity": "common", "price": 9002, "income_per_hour": 26, "upkeep_per_hour": 5, "rooms": 3, "basement": 5, "meta": {"tax": 5}},
    {"slug": "admin-re-19", "type": TYPE_REALESTATE, "name": "River House", "rarity": "common", "price": 9231, "income_per_hour": 26, "upkeep_per_hour": 5, "rooms": 3, "basement": 5, "meta": {"tax": 5}},
    {"slug": "admin-re-20", "type": TYPE_REALESTATE, "name": "Sunset Home", "rarity": "common", "price": 9460, "income_per_hour": 26, "upkeep_per_hour": 5, "rooms": 3, "basement": 5, "meta": {"tax": 5}},
    {"slug": "admin-re-21", "type": TYPE_REALESTATE, "name": "Crystal Garden", "rarity": "uncommon", "price": 46350, "income_per_hour": 116, "upkeep_per_hour": 21, "rooms": 4, "basement": 6, "meta": {"tax": 23}},
    {"slug": "admin-re-22", "type": TYPE_REALESTATE, "name": "Lake Breeze", "rarity": "uncommon", "price": 48436, "income_per_hour": 116, "upkeep_per_hour": 21, "rooms": 4, "basement": 6, "meta": {"tax": 23}},
    {"slug": "admin-re-23", "type": TYPE_REALESTATE, "name": "Amber Villa", "rarity": "uncommon", "price": 50522, "income_per_hour": 116, "upkeep_per_hour": 21, "rooms": 4, "basement": 6, "meta": {"tax": 23}},
    {"slug": "admin-re-24", "type": TYPE_REALESTATE, "name": "Willow Manor", "rarity": "uncommon", "price": 52607, "income_per_hour": 116, "upkeep_per_hour": 21, "rooms": 4, "basement": 6, "meta": {"tax": 23}},
    {"slug": "admin-re-25", "type": TYPE_REALESTATE, "name": "Mountain Rest", "rarity": "uncommon", "price": 54693, "income_per_hour": 116, "upkeep_per_hour": 21, "rooms": 4, "basement": 7, "meta": {"tax": 23}},
    {"slug": "admin-re-26", "type": TYPE_REALESTATE, "name": "Emerald Home", "rarity": "uncommon", "price": 56779, "income_per_hour": 116, "upkeep_per_hour": 21, "rooms": 4, "basement": 7, "meta": {"tax": 23}},
    {"slug": "admin-re-27", "type": TYPE_REALESTATE, "name": "Harmony House", "rarity": "uncommon", "price": 58864, "income_per_hour": 116, "upkeep_per_hour": 21, "rooms": 4, "basement": 7, "meta": {"tax": 23}},
    {"slug": "admin-re-28", "type": TYPE_REALESTATE, "name": "Royal Cottage", "rarity": "uncommon", "price": 61542, "income_per_hour": 118, "upkeep_per_hour": 21, "rooms": 5, "basement": 7, "meta": {"tax": 24}},
    {"slug": "admin-re-29", "type": TYPE_REALESTATE, "name": "Garden Estate", "rarity": "uncommon", "price": 63648, "income_per_hour": 118, "upkeep_per_hour": 21, "rooms": 5, "basement": 8, "meta": {"tax": 24}},
    {"slug": "admin-re-30", "type": TYPE_REALESTATE, "name": "Windy Hill", "rarity": "uncommon", "price": 65754, "income_per_hour": 118, "upkeep_per_hour": 21, "rooms": 5, "basement": 8, "meta": {"tax": 24}},
    {"slug": "admin-re-31", "type": TYPE_REALESTATE, "name": "Golden Villa", "rarity": "uncommon", "price": 67860, "income_per_hour": 118, "upkeep_per_hour": 21, "rooms": 5, "basement": 8, "meta": {"tax": 24}},
    {"slug": "admin-re-32", "type": TYPE_REALESTATE, "name": "Ocean View", "rarity": "uncommon", "price": 69966, "income_per_hour": 118, "upkeep_per_hour": 21, "rooms": 5, "basement": 8, "meta": {"tax": 24}},
    {"slug": "admin-re-33", "type": TYPE_REALESTATE, "name": "Snow Peak", "rarity": "uncommon", "price": 72072, "income_per_hour": 118, "upkeep_per_hour": 21, "rooms": 5, "basement": 9, "meta": {"tax": 24}},
    {"slug": "admin-re-34", "type": TYPE_REALESTATE, "name": "Silver Lake", "rarity": "uncommon", "price": 74178, "income_per_hour": 118, "upkeep_per_hour": 21, "rooms": 5, "basement": 9, "meta": {"tax": 24}},
    {"slug": "admin-re-35", "type": TYPE_REALESTATE, "name": "Crystal Peak", "rarity": "uncommon", "price": 76284, "income_per_hour": 118, "upkeep_per_hour": 21, "rooms": 5, "basement": 9, "meta": {"tax": 24}},
    {"slug": "admin-re-36", "type": TYPE_REALESTATE, "name": "Rose Manor", "rarity": "uncommon", "price": 78390, "income_per_hour": 118, "upkeep_per_hour": 21, "rooms": 5, "basement": 10, "meta": {"tax": 24}},
    {"slug": "admin-re-37", "type": TYPE_REALESTATE, "name": "Royal Garden", "rarity": "uncommon", "price": 81270, "income_per_hour": 120, "upkeep_per_hour": 22, "rooms": 6, "basement": 10, "meta": {"tax": 24}},
    {"slug": "admin-re-38", "type": TYPE_REALESTATE, "name": "Moonlight Villa", "rarity": "uncommon", "price": 83396, "income_per_hour": 120, "upkeep_per_hour": 22, "rooms": 6, "basement": 10, "meta": {"tax": 24}},
    {"slug": "admin-re-39", "type": TYPE_REALESTATE, "name": "Green Palace", "rarity": "uncommon", "price": 85522, "income_per_hour": 120, "upkeep_per_hour": 22, "rooms": 6, "basement": 10, "meta": {"tax": 24}},
    {"slug": "admin-re-40", "type": TYPE_REALESTATE, "name": "Diamond Cottage", "rarity": "uncommon", "price": 87649, "income_per_hour": 120, "upkeep_per_hour": 22, "rooms": 6, "basement": 10, "meta": {"tax": 24}},
    {"slug": "admin-re-41", "type": TYPE_REALESTATE, "name": "Imperial Home", "rarity": "rare", "price": 168000, "income_per_hour": 458, "upkeep_per_hour": 82, "rooms": 6, "basement": 11, "meta": {"tax": 92}},
    {"slug": "admin-re-42", "type": TYPE_REALESTATE, "name": "Ruby Manor", "rarity": "rare", "price": 175560, "income_per_hour": 458, "upkeep_per_hour": 82, "rooms": 6, "basement": 11, "meta": {"tax": 92}},
    {"slug": "admin-re-43", "type": TYPE_REALESTATE, "name": "Forest Palace", "rarity": "rare", "price": 183120, "income_per_hour": 458, "upkeep_per_hour": 82, "rooms": 6, "basement": 11, "meta": {"tax": 92}},
    {"slug": "admin-re-44", "type": TYPE_REALESTATE, "name": "Sunrise Estate", "rarity": "rare", "price": 190680, "income_per_hour": 458, "upkeep_per_hour": 82, "rooms": 6, "basement": 12, "meta": {"tax": 92}},
    {"slug": "admin-re-45", "type": TYPE_REALESTATE, "name": "North Residence", "rarity": "rare", "price": 200128, "income_per_hour": 465, "upkeep_per_hour": 84, "rooms": 7, "basement": 12, "meta": {"tax": 93}},
    {"slug": "admin-re-46", "type": TYPE_REALESTATE, "name": "Sky House", "rarity": "rare", "price": 207760, "income_per_hour": 465, "upkeep_per_hour": 84, "rooms": 7, "basement": 12, "meta": {"tax": 93}},
    {"slug": "admin-re-47", "type": TYPE_REALESTATE, "name": "Aurora Villa", "rarity": "rare", "price": 215392, "income_per_hour": 465, "upkeep_per_hour": 84, "rooms": 7, "basement": 13, "meta": {"tax": 93}},
    {"slug": "admin-re-48", "type": TYPE_REALESTATE, "name": "Prestige Manor", "rarity": "rare", "price": 223024, "income_per_hour": 465, "upkeep_per_hour": 84, "rooms": 7, "basement": 13, "meta": {"tax": 93}},
    {"slug": "admin-re-49", "type": TYPE_REALESTATE, "name": "King's Home", "rarity": "rare", "price": 230656, "income_per_hour": 465, "upkeep_per_hour": 84, "rooms": 7, "basement": 13, "meta": {"tax": 93}},
    {"slug": "admin-re-50", "type": TYPE_REALESTATE, "name": "Elite Residence", "rarity": "rare", "price": 238288, "income_per_hour": 465, "upkeep_per_hour": 84, "rooms": 7, "basement": 14, "meta": {"tax": 93}},
    {"slug": "admin-re-51", "type": TYPE_REALESTATE, "name": "Majestic Villa", "rarity": "rare", "price": 248240, "income_per_hour": 473, "upkeep_per_hour": 85, "rooms": 8, "basement": 14, "meta": {"tax": 95}},
    {"slug": "admin-re-52", "type": TYPE_REALESTATE, "name": "Royal Heights", "rarity": "rare", "price": 255944, "income_per_hour": 473, "upkeep_per_hour": 85, "rooms": 8, "basement": 14, "meta": {"tax": 95}},
    {"slug": "admin-re-53", "type": TYPE_REALESTATE, "name": "Silver Crown", "rarity": "rare", "price": 263648, "income_per_hour": 473, "upkeep_per_hour": 85, "rooms": 8, "basement": 15, "meta": {"tax": 95}},
    {"slug": "admin-re-54", "type": TYPE_REALESTATE, "name": "Golden Ridge", "rarity": "rare", "price": 271352, "income_per_hour": 473, "upkeep_per_hour": 85, "rooms": 8, "basement": 15, "meta": {"tax": 95}},
    {"slug": "admin-re-55", "type": TYPE_REALESTATE, "name": "Crimson Estate", "rarity": "rare", "price": 279056, "income_per_hour": 473, "upkeep_per_hour": 85, "rooms": 8, "basement": 15, "meta": {"tax": 95}},
    {"slug": "admin-re-56", "type": TYPE_REALESTATE, "name": "Azure Palace", "rarity": "rare", "price": 286760, "income_per_hour": 473, "upkeep_per_hour": 85, "rooms": 8, "basement": 16, "meta": {"tax": 95}},
    {"slug": "admin-re-57", "type": TYPE_REALESTATE, "name": "Ivory Manor", "rarity": "rare", "price": 294464, "income_per_hour": 473, "upkeep_per_hour": 85, "rooms": 8, "basement": 16, "meta": {"tax": 95}},
    {"slug": "admin-re-58", "type": TYPE_REALESTATE, "name": "Stormwatch Villa", "rarity": "epic", "price": 518400, "income_per_hour": 1487, "upkeep_per_hour": 268, "rooms": 9, "basement": 16, "meta": {"tax": 297}},
    {"slug": "admin-re-59", "type": TYPE_REALESTATE, "name": "Dragonspire House", "rarity": "epic", "price": 541728, "income_per_hour": 1487, "upkeep_per_hour": 268, "rooms": 9, "basement": 17, "meta": {"tax": 297}},
    {"slug": "admin-re-60", "type": TYPE_REALESTATE, "name": "Obsidian Hall", "rarity": "epic", "price": 565056, "income_per_hour": 1487, "upkeep_per_hour": 268, "rooms": 9, "basement": 17, "meta": {"tax": 297}},
    {"slug": "admin-re-61", "type": TYPE_REALESTATE, "name": "Titan Crest", "rarity": "epic", "price": 588384, "income_per_hour": 1487, "upkeep_per_hour": 268, "rooms": 9, "basement": 18, "meta": {"tax": 297}},
    {"slug": "admin-re-62", "type": TYPE_REALESTATE, "name": "Eclipse Estate", "rarity": "epic", "price": 611712, "income_per_hour": 1487, "upkeep_per_hour": 268, "rooms": 9, "basement": 18, "meta": {"tax": 297}},
    {"slug": "admin-re-63", "type": TYPE_REALESTATE, "name": "Starforge Manor", "rarity": "epic", "price": 635040, "income_per_hour": 1487, "upkeep_per_hour": 268, "rooms": 9, "basement": 18, "meta": {"tax": 297}},
    {"slug": "admin-re-64", "type": TYPE_REALESTATE, "name": "Celestial Home", "rarity": "epic", "price": 664464, "income_per_hour": 1511, "upkeep_per_hour": 272, "rooms": 10, "basement": 19, "meta": {"tax": 302}},
    {"slug": "admin-re-65", "type": TYPE_REALESTATE, "name": "Nightfall Villa", "rarity": "epic", "price": 688008, "income_per_hour": 1511, "upkeep_per_hour": 272, "rooms": 10, "basement": 19, "meta": {"tax": 302}},
    {"slug": "admin-re-66", "type": TYPE_REALESTATE, "name": "Thunder Peak", "rarity": "epic", "price": 711552, "income_per_hour": 1511, "upkeep_per_hour": 272, "rooms": 10, "basement": 20, "meta": {"tax": 302}},
    {"slug": "admin-re-67", "type": TYPE_REALESTATE, "name": "Phoenix Residence", "rarity": "epic", "price": 735096, "income_per_hour": 1511, "upkeep_per_hour": 272, "rooms": 10, "basement": 20, "meta": {"tax": 302}},
    {"slug": "admin-re-68", "type": TYPE_REALESTATE, "name": "Ironwind Estate", "rarity": "epic", "price": 758640, "income_per_hour": 1511, "upkeep_per_hour": 272, "rooms": 10, "basement": 20, "meta": {"tax": 302}},
    {"slug": "admin-re-69", "type": TYPE_REALESTATE, "name": "Lunar Fortress", "rarity": "epic", "price": 782184, "income_per_hour": 1511, "upkeep_per_hour": 272, "rooms": 10, "basement": 21, "meta": {"tax": 302}},
    {"slug": "admin-re-70", "type": TYPE_REALESTATE, "name": "Solar Mansion", "rarity": "epic", "price": 805728, "income_per_hour": 1511, "upkeep_per_hour": 272, "rooms": 10, "basement": 21, "meta": {"tax": 302}},
    {"slug": "admin-re-71", "type": TYPE_REALESTATE, "name": "Astral Palace", "rarity": "legendary", "price": 1650000, "income_per_hour": 4956, "upkeep_per_hour": 892, "rooms": 11, "basement": 21, "meta": {"tax": 991}},
    {"slug": "admin-re-72", "type": TYPE_REALESTATE, "name": "Void Castle", "rarity": "legendary", "price": 1724250, "income_per_hour": 4956, "upkeep_per_hour": 892, "rooms": 11, "basement": 22, "meta": {"tax": 991}},
    {"slug": "admin-re-73", "type": TYPE_REALESTATE, "name": "Infinity House", "rarity": "legendary", "price": 1798500, "income_per_hour": 4956, "upkeep_per_hour": 892, "rooms": 11, "basement": 22, "meta": {"tax": 991}},
    {"slug": "admin-re-74", "type": TYPE_REALESTATE, "name": "Nebula Citadel", "rarity": "legendary", "price": 1872750, "income_per_hour": 4956, "upkeep_per_hour": 892, "rooms": 11, "basement": 22, "meta": {"tax": 991}},
    {"slug": "admin-re-75", "type": TYPE_REALESTATE, "name": "Quantum Villa", "rarity": "legendary", "price": 1964700, "income_per_hour": 5032, "upkeep_per_hour": 906, "rooms": 12, "basement": 23, "meta": {"tax": 1006}},
    {"slug": "admin-re-76", "type": TYPE_REALESTATE, "name": "Godfall Residence", "rarity": "legendary", "price": 2039625, "income_per_hour": 5032, "upkeep_per_hour": 906, "rooms": 12, "basement": 23, "meta": {"tax": 1006}},
    {"slug": "admin-re-77", "type": TYPE_REALESTATE, "name": "Eternal Palace", "rarity": "legendary", "price": 2114550, "income_per_hour": 5032, "upkeep_per_hour": 906, "rooms": 12, "basement": 24, "meta": {"tax": 1006}},
    {"slug": "admin-re-78", "type": TYPE_REALESTATE, "name": "Supreme Nexus", "rarity": "legendary", "price": 2189475, "income_per_hour": 5032, "upkeep_per_hour": 906, "rooms": 12, "basement": 24, "meta": {"tax": 1006}},
    {"slug": "admin-re-79", "type": TYPE_REALESTATE, "name": "Hyperion Tower Home", "rarity": "legendary", "price": 2264400, "income_per_hour": 5032, "upkeep_per_hour": 906, "rooms": 12, "basement": 24, "meta": {"tax": 1006}},
    {"slug": "admin-re-80", "type": TYPE_REALESTATE, "name": "Omega Estate", "rarity": "legendary", "price": 2339325, "income_per_hour": 5032, "upkeep_per_hour": 906, "rooms": 12, "basement": 24, "meta": {"tax": 1006}},
    {"slug": "admin-re-81", "type": TYPE_REALESTATE, "name": "Final Crown House", "rarity": "legendary", "price": 2414250, "income_per_hour": 5032, "upkeep_per_hour": 906, "rooms": 12, "basement": 24, "meta": {"tax": 1006}},
]

_ADMIN_MARKET_BUSINESSES = [
    {"slug": "admin-biz-1", "type": TYPE_BUSINESS, "name": "Pixel Store", "category": "retail", "rarity": "common", "price": 6000, "income_per_hour": 60, "upkeep_per_hour": 19, "employees": 4},
    {"slug": "admin-biz-2", "type": TYPE_BUSINESS, "name": "GPU Market", "category": "tech", "rarity": "common", "price": 50000, "income_per_hour": 400, "upkeep_per_hour": 128, "employees": 6},
    {"slug": "admin-biz-3", "type": TYPE_BUSINESS, "name": "CoreTech Shop", "category": "tech", "rarity": "common", "price": 55000, "income_per_hour": 440, "upkeep_per_hour": 141, "employees": 8},
    {"slug": "admin-biz-4", "type": TYPE_BUSINESS, "name": "Neon Hardware", "category": "tech", "rarity": "common", "price": 60000, "income_per_hour": 480, "upkeep_per_hour": 154, "employees": 10},
    {"slug": "admin-biz-5", "type": TYPE_BUSINESS, "name": "Quantum GPUs", "category": "tech", "rarity": "common", "price": 65000, "income_per_hour": 520, "upkeep_per_hour": 166, "employees": 2},
    {"slug": "admin-biz-6", "type": TYPE_BUSINESS, "name": "Street Kiosk", "category": "retail", "rarity": "common", "price": 6600, "income_per_hour": 66, "upkeep_per_hour": 21, "employees": 4},
    {"slug": "admin-biz-7", "type": TYPE_BUSINESS, "name": "Mini Market", "category": "retail", "rarity": "common", "price": 7200, "income_per_hour": 72, "upkeep_per_hour": 23, "employees": 6},
    {"slug": "admin-biz-8", "type": TYPE_BUSINESS, "name": "Urban Shop", "category": "retail", "rarity": "common", "price": 7800, "income_per_hour": 78, "upkeep_per_hour": 25, "employees": 8},
    {"slug": "admin-biz-9", "type": TYPE_BUSINESS, "name": "Fashion Store", "category": "retail", "rarity": "common", "price": 8400, "income_per_hour": 84, "upkeep_per_hour": 27, "employees": 10},
    {"slug": "admin-biz-10", "type": TYPE_BUSINESS, "name": "Tech Repair", "category": "service", "rarity": "common", "price": 18000, "income_per_hour": 150, "upkeep_per_hour": 48, "employees": 2},
    {"slug": "admin-biz-11", "type": TYPE_BUSINESS, "name": "Overclock Lab", "category": "service", "rarity": "common", "price": 19800, "income_per_hour": 165, "upkeep_per_hour": 53, "employees": 4},
    {"slug": "admin-biz-12", "type": TYPE_BUSINESS, "name": "Crypto Office", "category": "office", "rarity": "common", "price": 28000, "income_per_hour": 250, "upkeep_per_hour": 80, "employees": 6},
]

# ── Каталог инфраструктурных активов (заводы, источники, склады) ──────────────
# Соответствует frontend/src/utils/adminCatalog.js → ADMIN_FACTORIES_CATALOG /
# ADMIN_SOURCES_CATALOG / ADMIN_WAREHOUSES_CATALOG. Без этих записей бэкенд
# отвечал 404 «Актив не найден» на покупку (MarketTab отправлял slug-и
# admin-fac-*/admin-src-*/admin-wh-*, которые раньше игнорировались). Цены
# и характеристики согласованы с фронтом: при покупке клиентское значение
# цены не используется — сервер пересчитывает итог от базовой цены каталога.
_ADMIN_MARKET_FACTORIES = [
    {"slug": "admin-fac-gpu-1", "type": TYPE_FACTORY, "category": "gpu", "name": "Завод видеокарт",
     "rarity": "rare", "price": 250000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "employees": 24, "meta": {"produces": "gpu", "outputPerHour": 4}},
    # Пекарня: перерабатывает пшеницу в хлеб (физические ресурсы, не деньги).
    # Пшеницу возят фуры с поля или со склада (prod.inputId), хлеб вывозится
    # на склад (prod.destinationId). Механика в production.py.
    {"slug": "admin-fac-bakery-1", "type": TYPE_FACTORY, "category": "bakery", "name": "Пекарня",
     "rarity": "rare", "price": 1200000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "employees": 20, "meta": {"produces": "bread", "input": "wheat",
                               "outputPerHour": 120, "consumesPerHour": 240, "capacity": 30000}},
]

# Источники: цены ×100 к старым (35k→3.5M, 22k→2.2M, 48k→4.8M), добыча и
# ёмкость хранилища тоже ×100 — окупаемость сохраняется в игровом коридоре
# (~4 суток при штатном составе работников). Источник теперь копит РЕСУРС в
# своём хранилище (см. production.py), а не деньги.
_ADMIN_MARKET_SOURCES = [
    {"slug": "admin-src-mine-1", "type": TYPE_SOURCE, "category": "mine", "name": "Шахта",
     "rarity": "common", "price": 3500000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "employees": 8, "meta": {"resource": "metal", "outputPerHour": 600, "capacity": 50000}},
    {"slug": "admin-src-field-1", "type": TYPE_SOURCE, "category": "field", "name": "Поле",
     "rarity": "common", "price": 2200000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "employees": 6, "meta": {"resource": "food", "outputPerHour": 800, "capacity": 60000}},
    {"slug": "admin-src-sawmill-1", "type": TYPE_SOURCE, "category": "sawmill", "name": "Лесопилка",
     "rarity": "uncommon", "price": 4800000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "employees": 10, "meta": {"resource": "wood", "outputPerHour": 500, "capacity": 45000}},
]

# 16 складов с логарифмической шкалой площади 50..100000 м². Цена и rarity
# рассчитаны по той же формуле, что и в adminCatalog.js → _warehousePrice.
import math as _math

def _wh_price(area: int) -> int:
    # 3600 = 1200 × 3 (цены складов подняты ×3 к старым).
    return int(round(3600 * area * (1 + 0.5 * _math.log10(area / 50))))

def _wh_rarity(area: int) -> str:
    if area < 500: return "common"
    if area < 2000: return "uncommon"
    if area < 10000: return "rare"
    if area < 50000: return "epic"
    return "legendary"

_WAREHOUSE_AREAS = [50, 80, 120, 200, 300, 500, 800, 1200, 2000, 3500,
                    6000, 10000, 18000, 35000, 60000, 100000]
_ADMIN_MARKET_WAREHOUSES = [
    {"slug": f"admin-wh-{i + 1}", "type": TYPE_WAREHOUSE, "category": "warehouse",
     "name": f"Склад {area:,} м²".replace(",", " "), "rarity": _wh_rarity(area),
     "price": _wh_price(area), "income_per_hour": 0, "upkeep_per_hour": 0,
     "employees": max(2, round(area / 200)),
     # storageCap — вместимость в кг ресурса (см. production.py), масштаб ×1000
     # к старым area×20: добыча источников выросла ×100, склад должен вмещать
     # осмысленный запас между рейсами фур.
     "meta": {"areaSqm": area, "storageCap": area * 1000, "slots": 1}}
    for i, area in enumerate(_WAREHOUSE_AREAS)
]

# ── Автосалон (cars/trucks/trailers) ─────────────────────────────────────────
# Согласовано с frontend/src/utils/carsCatalog.js (CarsTab): те же слаги,
# цены и редкость. Все идут как TYPE_CAR (общая логика владения/тюнинга),
# категория (car/truck/trailer) и характеристики — в category/meta.
# При покупке клиентская цена не используется — сервер берёт цену отсюда.
_CAR_CATALOG = [
    # Легковые
    {"slug": "car-hatchback-1", "type": TYPE_CAR, "category": "car", "name": "Хэтчбек «Старт»",
     "rarity": "common", "price": 12000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "meta": {"fuelPer100km": 6.5, "cargoKg": 350, "maxSpeed": 160}},
    {"slug": "car-sedan-1", "type": TYPE_CAR, "category": "car", "name": "Седан «Комфорт»",
     "rarity": "common", "price": 22000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "meta": {"fuelPer100km": 7.2, "cargoKg": 450, "maxSpeed": 180}},
    {"slug": "car-suv-1", "type": TYPE_CAR, "category": "car", "name": "Кроссовер «Тропик»",
     "rarity": "uncommon", "price": 38000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "meta": {"fuelPer100km": 8.5, "cargoKg": 600, "maxSpeed": 190}},
    {"slug": "car-sport-1", "type": TYPE_CAR, "category": "car", "name": "Спорткар «Вихрь»",
     "rarity": "rare", "price": 95000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "meta": {"fuelPer100km": 11.0, "cargoKg": 220, "maxSpeed": 280}},
    {"slug": "car-premium-1", "type": TYPE_CAR, "category": "car", "name": "Премиум «Империал»",
     "rarity": "epic", "price": 220000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "meta": {"fuelPer100km": 9.4, "cargoKg": 500, "maxSpeed": 250}},
    # Фуры (тягачи): hookable — какие прицепы можно цеплять
    {"slug": "truck-light-1", "type": TYPE_CAR, "category": "truck", "name": "Фура «Курьер»",
     "rarity": "common", "price": 65000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "meta": {"fuelPer100km": 18.0, "cargoKg": 1500, "maxSpeed": 110,
              "hookable": ["trailer-small", "trailer-medium"]}},
    {"slug": "truck-mid-1", "type": TYPE_CAR, "category": "truck", "name": "Фура «Магистраль»",
     "rarity": "uncommon", "price": 130000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "meta": {"fuelPer100km": 26.0, "cargoKg": 3000, "maxSpeed": 100,
              "hookable": ["trailer-small", "trailer-medium", "trailer-large"]}},
    {"slug": "truck-heavy-1", "type": TYPE_CAR, "category": "truck", "name": "Фура «Тяжеловоз»",
     "rarity": "rare", "price": 240000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "meta": {"fuelPer100km": 38.0, "cargoKg": 6000, "maxSpeed": 90,
              "hookable": ["trailer-medium", "trailer-large", "trailer-jumbo"]}},
    # Прицепы
    {"slug": "trailer-small", "type": TYPE_CAR, "category": "trailer", "name": "Прицеп «Малый»",
     "rarity": "common", "price": 9000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "meta": {"fuelPer100km": 0, "cargoKg": 2000, "maxSpeed": 110}},
    {"slug": "trailer-medium", "type": TYPE_CAR, "category": "trailer", "name": "Прицеп «Средний»",
     "rarity": "uncommon", "price": 22000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "meta": {"fuelPer100km": 0, "cargoKg": 6000, "maxSpeed": 100}},
    {"slug": "trailer-large", "type": TYPE_CAR, "category": "trailer", "name": "Прицеп «Большой»",
     "rarity": "rare", "price": 55000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "meta": {"fuelPer100km": 0, "cargoKg": 15000, "maxSpeed": 90}},
    {"slug": "trailer-jumbo", "type": TYPE_CAR, "category": "trailer", "name": "Прицеп «Джамбо»",
     "rarity": "epic", "price": 130000, "income_per_hour": 0, "upkeep_per_hour": 0,
     "meta": {"fuelPer100km": 0, "cargoKg": 30000, "maxSpeed": 80}},
]

CATALOG = (CATALOG + _ADMIN_MARKET_HOUSES + _ADMIN_MARKET_BUSINESSES
           + _ADMIN_MARKET_FACTORIES + _ADMIN_MARKET_SOURCES + _ADMIN_MARKET_WAREHOUSES
           + _CAR_CATALOG)

# ── Масштабирование каталога ─────────────────────────────────────────────────
# Бизнесы ×1000 (цена, доход, расход): топовые сборки майнинга приносят десятки
# тысяч $/ч, бизнесы за $50k с доходом $400/ч стали бы копеечными.
for _c in CATALOG:
    if _c["type"] == TYPE_BUSINESS:
        _c["price"] = _c["price"] * 1000
        _c["income_per_hour"] = _c.get("income_per_hour", 0) * 1000
        _c["upkeep_per_hour"] = _c.get("upkeep_per_hour", 0) * 1000
# Дома пассивный доход не приносят: дом — это подвал для майнинга и аренда,
# деньги делаются майнингом/бизнесами. Существующие экземпляры ловятся
# guard'ом в _income_per_hour (без миграции).
for _c in CATALOG:
    if _c["type"] == TYPE_REALESTATE:
        _c["income_per_hour"] = 0
CATALOG_BY_SLUG = {c["slug"]: c for c in CATALOG}
CATALOG_BY_SLUG_CI = {c["slug"].lower(): c for c in CATALOG}
CATALOG_BY_NAME = {c["name"].strip().lower(): c for c in CATALOG}


# Индекс по `id` записи (раньше фронт отправлял slug, а в части старых
# позиций id и slug различались — это приводило к «Актив не найден» при покупке).
_CATALOG_BY_ID = {c.get("id", c["slug"]): c for c in CATALOG}


def _find_catalog(slug: str):
    """Найти позицию каталога по slug/id (с учётом регистра) или точному имени.

    Поиск ведётся по нескольким ключам, потому что витрина домов/бизнесов
    исторически шлёт то `admin-re-1` (slug), то `id` записи из
    ``adminCatalog.js``. Любой из них должен находить каталог.
    """
    s = (slug or "").strip()
    if not s:
        return None
    return (
        CATALOG_BY_SLUG.get(s)
        or CATALOG_BY_SLUG_CI.get(s.lower())
        or _CATALOG_BY_ID.get(s)
        or _CATALOG_BY_ID.get(s.lower())
        or CATALOG_BY_NAME.get(s.lower())
    )

# ── Динамическая экономика рынка ─────────────────────────────────────────────
# Цена каждого товара = базовая × множитель. Множитель двигается от спроса
# (покупки поднимают, продажи опускают), дрейфа и случайных событий.
ASSET_MARKET_TICK_S = 60
ASSET_MULT_MIN = 0.5
ASSET_MULT_MAX = 2.5
DEMAND_BUY = 0.015      # покупка поднимает множитель
DEMAND_SELL = 0.01      # продажа опускает множитель
RARITY_FLOOR = {"common": 0.0, "uncommon": 0.03, "rare": 0.07, "epic": 0.12, "legendary": 0.20}


async def _ensure_asset_market(db: AsyncIOMotorDatabase):
    for c in CATALOG:
        await db.asset_market.update_one(
            {"slug": c["slug"]},
            {"$setOnInsert": {"slug": c["slug"], "mult": 1.0, "updated_at": _now()}},
            upsert=True,
        )


async def _drift_asset_market(db: AsyncIOMotorDatabase):
    """Естественный дрейф цен к целевому уровню, определяемому реальными факторами:
    спрос (владельцы), предложение (объявления аренды), редкость, денежная масса,
    инфляция, активность игроков и мировые экономические события. Плавно, без скачков.
    """
    meta = await db.asset_market_meta.find_one({"key": "tick"})
    last = meta.get("updated_at") if meta else None
    if isinstance(last, datetime):
        la = last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last
        if (_now() - la).total_seconds() < ASSET_MARKET_TICK_S:
            return

    econ = await get_econ(db)
    inflation = float(econ.get("inflation", 0.0))

    # Спрос — число владельцев по slug.
    owners: dict = {}
    async for a in db.user_assets.find({}, {"slug": 1}):
        owners[a.get("slug")] = owners.get(a.get("slug"), 0) + 1
    # Предложение — активные объявления аренды по slug.
    listings: dict = {}
    async for a in db.user_assets.find({"rental": {"$ne": None}}, {"slug": 1}):
        listings[a.get("slug")] = listings.get(a.get("slug"), 0) + 1
    # Активность игроков за последний час.
    since = _now() - timedelta(hours=1)
    activity = await db.transactions.count_documents({"timestamp": {"$gte": since}})
    activity_factor = min(0.10, activity * 0.002)
    # Денежная масса — средние деньги игроков слегка поднимают уровень цен.
    total_cash, users = 0.0, 0
    async for u in db.users.find({}, {"balance": 1}):
        users += 1
        total_cash += float(u.get("balance", 0) or 0)
    supply_factor = max(-0.10, min(0.20, (total_cash / users / 50000.0) * 0.10)) if users else 0.0

    # Мировые события (могут стартовать/завершаться).
    try:
        from market_events import maybe_autostart, event_shifts, slug_event_shift
        await maybe_autostart(db)
        ev = await event_shifts(db)
    except Exception:
        ev = {"shifts": {}}

    for m in [x async for x in db.asset_market.find({})]:
        slug = m.get("slug")
        catalog = CATALOG_BY_SLUG.get(slug, {})
        atype = catalog.get("type", "realestate")
        rarity = catalog.get("rarity", "common")

        target = 1.0
        target += RARITY_FLOOR.get(rarity, 0.0)
        target += min(0.40, owners.get(slug, 0) * 0.02)      # спрос
        target -= min(0.30, listings.get(slug, 0) * 0.03)    # переизбыток предложения
        target += inflation + supply_factor + activity_factor
        target += slug_event_shift(ev.get("shifts", {}), slug, atype)  # событие

        cur = m.get("mult", 1.0)
        # Плавный дрейф к цели (8%) + маленький шум → без резких скачков.
        new = cur + (target - cur) * 0.08 + random.gauss(0, 0.01)
        new = max(ASSET_MULT_MIN, min(ASSET_MULT_MAX, new))
        await db.asset_market.update_one({"_id": m["_id"]}, {"$set": {"mult": round(new, 4), "updated_at": _now()}})

    await db.asset_market_meta.update_one({"key": "tick"}, {"$set": {"updated_at": _now()}}, upsert=True)


async def _mult_map(db: AsyncIOMotorDatabase) -> dict:
    return {m["slug"]: float(m.get("mult", 1.0)) async for m in db.asset_market.find({})}


async def _asset_mult(db: AsyncIOMotorDatabase, slug: str) -> float:
    m = await db.asset_market.find_one({"slug": slug})
    return float(m.get("mult", 1.0)) if m else 1.0


async def _bump_demand(db: AsyncIOMotorDatabase, slug: str, delta: float):
    m = await db.asset_market.find_one({"slug": slug})
    cur = m.get("mult", 1.0) if m else 1.0
    new = max(ASSET_MULT_MIN, min(ASSET_MULT_MAX, cur + delta))
    await db.asset_market.update_one(
        {"slug": slug},
        {"$set": {"mult": round(new, 4), "updated_at": _now()}, "$setOnInsert": {"slug": slug}},
        upsert=True,
    )


# ── Schemas ──────────────────────────────────────────────────────────────────


class BuyRequest(BaseModel):
    slug: str

    @field_validator("slug")
    @classmethod
    def slug_ok(cls, v):
        s = (v or "").strip()
        if not s:
            raise ValueError("Не указан актив")
        return s


class TuneBody(BaseModel):
    part: str

    @field_validator("part")
    @classmethod
    def part_ok(cls, v):
        if v not in TUNE_PARTS:
            raise ValueError("Неизвестная деталь тюнинга")
        return v


class RentListing(BaseModel):
    minHours: int

    @field_validator("minHours")
    @classmethod
    def hours_ok(cls, v):
        if v < 1 or v > RENT_MAX_HOURS:
            raise ValueError(f"Срок аренды: 1–{RENT_MAX_HOURS} часов")
        return int(v)


class MaterialsBuy(BaseModel):
    qty: int

    @field_validator("qty")
    @classmethod
    def qty_ok(cls, v):
        if v is None or v < 1:
            raise ValueError("Количество должно быть не меньше 1")
        if v > 500:
            raise ValueError("Слишком большое количество")
        return int(v)


class AdminAssetUpdate(BaseModel):
    """Правки актива администратором — без ограничений, действующих на игрока."""
    level: Optional[int] = None
    price: Optional[float] = None
    income_per_hour: Optional[float] = None
    upkeep_per_hour: Optional[float] = None


class AdminTransferBody(BaseModel):
    toUsername: str


class RenameBody(BaseModel):
    """Переименование имущества/транспорта игроком."""
    name: str

    @field_validator("name")
    @classmethod
    def name_ok(cls, v):
        v = (v or "").strip()
        if len(v) < 2:
            raise ValueError("Название слишком короткое")
        return v[:40]


class HitchBody(BaseModel):
    """Прицепить/отцепить прицеп: truckId обязателен для hitch."""
    truckId: Optional[str] = None


class TransferToPlayer(BaseModel):
    """Передача личного актива другому игроку по нику."""
    toUsername: str

    @field_validator("toUsername")
    @classmethod
    def name_ok(cls, v):
        v = (v or "").strip()
        if len(v) < 2:
            raise ValueError("Укажите ник игрока")
        return v[:40]


# ── Helpers ──────────────────────────────────────────────────────────────────


_now = now_utc


def _price_mult(asset: dict) -> float:
    """Во сколько раз экземпляр куплен дороже базовой цены каталога.

    Рынок гоняет цену в ×0.5…×2.5 (ASSET_MULT_MIN/MAX), и без этой привязки
    доход оставался бы базовым: купленный на пике актив окупался бы 8 дней
    вместо 3.3, а на просадке — 1.7. Доход масштабируется вместе с ценой,
    поэтому рыночный множитель решает, СКОЛЬКО вложить, а не насколько
    выгодна сделка. Активы, купленные до появления поля, считаются как ×1.0."""
    return float(asset.get("price_mult", 1.0) or 1.0)


def _current_value(asset: dict) -> float:
    """Текущая рыночная стоимость экземпляра с учётом уровня улучшений и тюнинга."""
    base = asset.get("price", 0)
    level = asset.get("level", 1)
    return round(base * (1 + 0.35 * (level - 1)) + asset.get("tuning_value", 0.0), 2)


def _materials_boost(asset: dict) -> float:
    """Активный бонус к доходу бизнеса от закупленных материалов (0, если срок истёк)."""
    m = asset.get("materials")
    if not m:
        return 0.0
    expires = m.get("expires_at")
    if not isinstance(expires, datetime):
        return 0.0
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if _now() >= expires:
        return 0.0
    return float(m.get("boostPct", 0.0))


# ── Майнинг-улучшение для домов ──────────────────────────────────────────────
# Подвал дома (поле basement, ёмкость в корпусах) используется как множитель
# майнинговой фермы. Улучшение «Майнинг» покупается 1 раз: цена и доход за
# единицу подвала берутся из econ (mining_basement_cost/income). После
# активации дом начинает приносить пассивный доход, включаемый в общую формулу
# _income_per_hour, чтобы он собирался тем же /collect и попадал в
# /collect-all без отдельной механики. Поле mining хранится на документе актива
# (bool) — повторная покупка запрещена.
# Коэффициенты майнинг-подвала и инфраструктуры берутся из econ (DEFAULT_ECON),
# поэтому показываются и списываются одними и теми же числами. В sync-контекстах
# (_serialize/_income_per_hour без econ) используются значения по умолчанию;
# расхождение возможно только сразу после смены коэффициента админом.
from econ import DEFAULT_ECON


def _mining_income_per_hour(asset: dict, econ: Optional[dict] = None) -> float:
    """Доход от майнинг-улучшения в час. 0, если улучшение не куплено или
    актив — не недвижимость / без подвала."""
    if not asset.get("mining"):
        return 0.0
    if asset.get("type") != TYPE_REALESTATE:
        return 0.0
    basement = int(asset.get("basement") or 0)
    if basement <= 0:
        return 0.0
    rate = float(econ.get("mining_basement_income")) if econ else DEFAULT_ECON["mining_basement_income"]
    return round(basement * rate, 2)


def _mining_cost(asset: dict, econ: Optional[dict] = None) -> float:
    """Цена улучшения «Майнинг» = basement × mining_basement_cost (из econ).
    Подвал 0 → улучшение недоступно (дублируется проверкой в эндпоинте покупки)."""
    basement = int(asset.get("basement") or 0)
    if basement <= 0:
        return 0.0
    cost_per = float(econ.get("mining_basement_cost")) if econ else DEFAULT_ECON["mining_basement_cost"]
    return float(basement * cost_per)


def _infra_income_per_hour(asset: dict, econ: Optional[dict] = None) -> float:
    """Почасовой доход инфраструктуры.

    Остался только у завода видеокарт (meta.produces='gpu'): продукция продаётся
    «на сторону» по фиксированной цене из econ. Источники и пекарня теперь
    производят ФИЗИЧЕСКИЕ ресурсы в собственное хранилище (см. production.py) —
    деньги приносит продажа ресурсов со склада, поэтому денежный поток
    источников отключён, чтобы не платить дважды. Склады прибыли не приносят.
    Коэффициенты берутся из econ; в sync-контексте — дефолты.
    """
    t = asset.get("type")
    meta = asset.get("meta") or {}
    if t == TYPE_FACTORY and meta.get("produces") == "gpu":
        return round(int(meta.get("outputPerHour") or 0) * float(
            econ.get("infra_gpu_price") if econ else DEFAULT_ECON["infra_gpu_price"]), 2)
    return 0.0


def _income_per_hour(asset: dict, econ: Optional[dict] = None) -> float:
    # Авто не приносят почасового пассивного дохода — только аренда (см. _is_rentable).
    # Их «уровень» не качается через upgrade, прогресс идёт через тюнинг/престиж.
    if asset.get("type") == TYPE_CAR:
        return 0.0
    # Дома тоже: пассивный доход отключён (см. масштабирование CATALOG),
    # майнинг-улучшение подвала и аренда остаются — они добавляются ниже.
    base = 0.0 if asset.get("type") == TYPE_REALESTATE else asset.get("income_per_hour", 0)
    level = asset.get("level", 1)
    value = base * (1 + 0.25 * (level - 1)) * _price_mult(asset)
    if asset.get("type") == TYPE_BUSINESS:
        value *= (1 + _materials_boost(asset))
    # Майнинг-улучшение дома: пассивный доход от оборудования в подвале,
    # складывается с базовым почасовым доходом (у большинства домов он уже 0,
    # а у арендных моделей база ненулевая — суммирование уместно).
    value += _mining_income_per_hour(asset, econ)
    # Инфраструктура (завод/источник/склад): доход от продукции/хранения.
    value += _infra_income_per_hour(asset, econ)
    return round(value, 2)


def _rent_rarity(asset: dict) -> str:
    """Редкость актива для расчёта аренды. Берётся из самого экземпляра (в него
    копируется при покупке из каталога — buy_asset), с запасным вариантом через
    каталог по slug — на случай активов, купленных до появления rarity у бизнесов."""
    rarity = asset.get("rarity")
    if rarity in RARITY_RENT_PCT:
        return rarity
    catalog_rarity = CATALOG_BY_SLUG.get(asset.get("slug"), {}).get("rarity")
    return catalog_rarity if catalog_rarity in RARITY_RENT_PCT else "common"


def _rent_daily_rate(asset: dict) -> float:
    """Суточная ставка аренды — СВОЯ для каждого объекта, а не единый коэффициент
    для всего имущества. Зависит от текущей стоимости актива (цена + апгрейды +
    тюнинг — см. _current_value) и его редкости/класса (RARITY_RENT_PCT): чем
    реже и роскошнее объект, тем выше именно % доходности, а не только сумма.
    Авто получают повышенную ставку (CAR_RENT_MULT) — у них нет пассивного дохода.
    RARITY_RENT_FLOOR — лишь подстраховка от вырожденно низких значений, а не
    основной регулятор (как было раньше с плоским полом в $2000 для всех).
    Как и пассивный доход, ставка масштабируется по уплаченной цене (_price_mult)."""
    if not _is_rentable(asset):
        return 0.0
    rarity = _rent_rarity(asset)
    pct = RARITY_RENT_PCT[rarity]
    floor = RARITY_RENT_FLOOR[rarity]
    if asset.get("type") == TYPE_CAR:
        pct *= CAR_RENT_MULT
        floor *= CAR_RENT_MULT
    return round(max(floor, _current_value(asset) * pct) * _price_mult(asset), 2)


def _rent_rate_per_hour(asset: dict) -> float:
    """Ставка аренды в час — для отображения клиенту (не используется в расчёте
    итоговой суммы, чтобы округление ставки не накапливалось на длинных сроках)."""
    return round(_rent_daily_rate(asset) / 24, 2)


def _rent_total(asset: dict, hours: int) -> float:
    """Итоговая стоимость аренды за срок — линейно от часов, единая формула для
    клиента (превью) и сервера (авторитетный пересчёт при выставлении объявления)."""
    if not _is_rentable(asset):
        return 0.0
    return round(_rent_daily_rate(asset) * hours / 24, 2)


def _upkeep_per_hour(asset: dict) -> float:
    # Масштабируется вместе с доходом (см. _price_mult), иначе купленный на пике
    # актив имел бы прежний расход при повышенном доходе — доходность в % росла бы.
    return round(asset.get("upkeep_per_hour", 0) * _price_mult(asset), 2)


def _upgrade_cost(asset: dict) -> float:
    """Улучшение стоит фиксированную долю базовой цены — НЕ растёт с уровнем.

    Прирост дохода за уровень плоский (+25% базы, см. _income_per_hour), поэтому
    цена вида base*0.4*level делала апгрейд всё хуже: L1→L2 окупался за 3.6 суток,
    а L5→L6 уже за 18 — качать актив было втрое невыгоднее, чем купить второй.
    При плоской доле окупаемость улучшения (2.9–4.0 суток) совпадает с покупкой
    нового актива (3.3–4.2), и уровень перестаёт быть ловушкой."""
    base = asset.get("price", 0)
    # Доход экземпляра масштабируется ценой покупки (_price_mult) — цена улучшения тоже,
    # иначе купленный на пике актив качался бы по базовой цене за повышенный доход.
    return round(base * UPGRADE_COST_PCT * _price_mult(asset), 2)


UPGRADE_PREVIEW_LEVELS = 10   # сколько будущих уровней показывать в модалке «Улучшения»


def _upgrade_plan(asset: dict, steps: int) -> list[dict]:
    """Предпросмотр следующих уровней: цена перехода, накопленная стоимость,
    доход и стоимость актива на каждом уровне. Формулы те же, что в
    _upgrade_cost / _income_per_hour / _current_value — считаются на сервере,
    чтобы клиент их не дублировал и не мог разойтись с фактическим списанием."""
    level = asset.get("level", 1)
    cumulative = 0.0
    plan = []
    for i in range(1, steps + 1):
        at = {**asset, "level": level + i - 1}
        cumulative += _upgrade_cost(at)
        nxt = {**asset, "level": level + i}
        plan.append({
            "level": level + i,
            "stepCost": _upgrade_cost(at),
            "totalCost": round(cumulative, 2),
            "incomePerHour": _income_per_hour(nxt),
            "profitPerHour": round(_income_per_hour(nxt) - _upkeep_per_hour(nxt), 2),
            "value": _current_value(nxt),
            "rentRatePerHour": _rent_rate_per_hour(nxt),
        })
    return plan


def _accrued(asset: dict, econ: Optional[dict] = None) -> float:
    """Чистый накопленный доход (доход − расход) с последнего сбора, cap 24ч."""
    last = asset.get("last_collected")
    if not isinstance(last, datetime):
        return 0.0
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    hours = min((_now() - last).total_seconds() / 3600.0, MAX_ACCRUAL_HOURS)
    if hours <= 0:
        return 0.0
    net = (_income_per_hour(asset, econ) - _upkeep_per_hour(asset)) * hours
    return round(max(0.0, net), 2)


# ── Аренда ───────────────────────────────────────────────────────────────────


def _rental_view(asset: dict) -> Optional[dict]:
    r = asset.get("rental")
    if not r:
        return None
    return {
        "status": r.get("status"),
        "price": r.get("price"),
        "minHours": r.get("minHours"),
        "tenantAt": r["tenant_at"].isoformat() if isinstance(r.get("tenant_at"), datetime) else None,
        "endsAt": r["ends_at"].isoformat() if isinstance(r.get("ends_at"), datetime) else None,
    }


async def _process_rental(db: AsyncIOMotorDatabase, asset: dict) -> dict:
    """Ленивая обработка аренды: заселение арендатора и выплата по окончании.

    listed → (наступило tenant_at) → rented → (наступило ends_at) → выплата владельцу.
    """
    r = asset.get("rental")
    if not r:
        return asset
    now = _now()

    # Заселение арендатора
    if r.get("status") == "listed":
        tenant_at = to_aware(r.get("tenant_at"))
        if tenant_at and now >= tenant_at:
            ends_at = tenant_at + timedelta(hours=r.get("minHours", 1))
            r["status"] = "rented"
            r["ends_at"] = ends_at
            await db.user_assets.update_one({"_id": asset["_id"]}, {"$set": {"rental": r}})
            asset["rental"] = r
            await push_notification(
                db, asset["userId"], "rental",
                "Появился арендатор", f"«{asset.get('name')}» сдан в аренду.",
                data={"assetId": str(asset["_id"])},
            )
            try:
                from ws import push_to_user
                await push_to_user(asset["userId"], {"type": "asset_update", "assetId": str(asset["_id"])})
            except Exception:
                pass

    # Завершение аренды и выплата
    if r.get("status") == "rented":
        ends_at = to_aware(r.get("ends_at"))
        if ends_at and now >= ends_at:
            payout = round(float(r.get("price", 0)), 2)
            # Админ-коэффициент аренды.
            try:
                econ = await get_econ(db)
                payout = round(payout * econ.get("rent_mult", 1.0) * econ.get("economy_mult", 1.0), 2)
                from market_events import event_shifts
                payout = round(payout * (await event_shifts(db)).get("rental", 1.0), 2)
            except Exception:
                pass
            # Бонус «Гранд-отеля» (Крыша города) — +% к доходу от аренды.
            try:
                from cityroof import player_city_effect
                bonus = await player_city_effect(db, asset["userId"], "rental_income")
                if bonus:
                    payout = round(payout * (1 + bonus), 2)
            except Exception:
                pass
            await db.user_assets.update_one({"_id": asset["_id"]}, {"$set": {"rental": None}})
            asset["rental"] = None
            try:
                from ws import push_to_user
                await push_to_user(asset["userId"], {"type": "asset_update", "assetId": str(asset["_id"])})
            except Exception:
                pass
            if payout > 0:
                company_id = asset.get("companyId")
                if company_id and ObjectId.is_valid(company_id):
                    # Актив компании — доход поступает в бюджет компании.
                    await db.companies.update_one({"_id": ObjectId(company_id)}, {"$inc": {"budget": payout}})
                    company = await db.companies.find_one({"_id": ObjectId(company_id)})
                    from ledger import CAT_COMPANY
                    await record_transaction(
                        db, asset["userId"], INCOME, payout, CAT_COMPANY,
                        f"Аренда (компания): {asset.get('name')}",
                        meta={"assetId": str(asset["_id"]), "companyId": company_id, "toBudget": True},
                    )
                    if company:
                        await push_notification(
                            db, company.get("ownerId", asset["userId"]), "rental",
                            "Аренда компании завершена",
                            f"В бюджет «{company.get('name')}» начислено ${payout:.2f} за «{asset.get('name')}».",
                            data={"assetId": str(asset["_id"]), "payout": payout, "companyId": company_id},
                        )
                else:
                    new_balance = await adjust_balance(db, asset["userId"], payout)
                    await record_transaction(
                        db, asset["userId"], INCOME, payout, CAT_REALESTATE,
                        f"Аренда: {asset.get('name')}", balance_after=new_balance,
                        meta={"assetId": str(asset["_id"])},
                    )
                    await push_notification(
                        db, asset["userId"], "rental",
                        "Аренда завершена", f"Начислено ${payout:.2f} за «{asset.get('name')}».",
                        data={"assetId": str(asset["_id"]), "payout": payout},
                    )
    return asset


# ── Активы компании (реальный источник дохода) ───────────────────────────────


async def company_income_per_hour(db: AsyncIOMotorDatabase, company_id: str,
                                  media_factor: float = 1.0) -> float:
    """Чистый доход компании в час от принадлежащих ей активов.

    ``media_factor`` — репутационный множитель СМИ владельца: применяется только
    к доходной части бизнесов (расходы/содержание и небизнес-активы не трогаем)."""
    total = 0.0
    async for a in db.user_assets.find({"companyId": company_id}):
        income = _income_per_hour(a)
        if media_factor != 1.0 and a.get("type") == TYPE_BUSINESS:
            income = round(income * media_factor, 2)
        total += (income - _upkeep_per_hour(a))
    return round(total, 2)


async def list_company_assets(db: AsyncIOMotorDatabase, company_id: str) -> list[dict]:
    return [_serialize(a) async for a in db.user_assets.find({"companyId": company_id})]


async def sweep_rentals(db: AsyncIOMotorDatabase):
    """Глобальная обработка аренды (заселение/выплаты) — вызывается Scheduler'ом."""
    async for a in db.user_assets.find({"rental": {"$ne": None}}):
        try:
            await _process_rental(db, a)
        except Exception:
            pass


async def tick_market(db: AsyncIOMotorDatabase):
    """Публичная точка для Scheduler: дрейф динамического рынка активов."""
    await _ensure_asset_market(db)
    await _drift_asset_market(db)
    try:
        from ws import broadcast
        await broadcast({"type": "market_update"})
    except Exception:
        pass


def _studio_view(asset: dict) -> Optional[dict]:
    """Прокачка/материалы IT-студии (см. cityroof.py) — None для остальных активов."""
    slug = asset.get("slug") or ""
    if not slug.startswith("itstudio_"):
        return None
    tier = slug[len("itstudio_"):]
    try:
        from cityroof import studio_progress
    except Exception:
        return None
    return studio_progress(tier, asset.get("studioXp", 0), asset.get("itstudioMaterials", {}))


def _mining_view(asset: dict) -> Optional[dict]:
    """Информация об улучшении «Майнинг» для UI. Доступно только для
    недвижимости; для остальных типов None. Включается в _serialize чтобы
    клиент мог показать кнопку покупки/статус без отдельного эндпоинта."""
    if asset.get("type") != TYPE_REALESTATE:
        return None
    basement = int(asset.get("basement") or 0)
    cost = _mining_cost(asset)   # basement × mining_basement_cost (из econ)
    return {
        "available": basement > 0,
        "purchased": bool(asset.get("mining")),
        "basement": basement,
        "cost": cost,
        "incomePerHour": _mining_income_per_hour(asset),
    }


def _serialize(asset: dict) -> dict:
    return {
        "id": str(asset["_id"]),
        "slug": asset.get("slug"),
        "type": asset.get("type"),
        "name": asset.get("name"),
        "category": asset.get("category"),
        "rarity": asset.get("rarity"),
        "rooms": asset.get("rooms"),
        "basement": asset.get("basement"),
        "employees": asset.get("employees", 0),
        "level": asset.get("level", 1),
        "price": asset.get("price", 0),
        "value": _current_value(asset),
        "incomePerHour": _income_per_hour(asset),
        "upkeepPerHour": _upkeep_per_hour(asset),
        "profitPerHour": round(_income_per_hour(asset) - _upkeep_per_hour(asset), 2),
        "upgradeCost": _upgrade_cost(asset),
        "accrued": _accrued(asset),
        "meta": asset.get("meta", {}),
        "companyId": asset.get("companyId"),
        "rental": _rental_view(asset),
        "rentRatePerHour": _rent_rate_per_hour(asset),
        "customName": bool(asset.get("custom_name")),
        "hitchedTo": str(asset["hitchedTo"]) if asset.get("hitchedTo") else None,
        "tuning": asset.get("tuning", {}),
        "tuneMaxLevel": TUNE_MAX_LEVEL,
        "materialsBoostPct": _materials_boost(asset),
        "studio": _studio_view(asset),
        "mining": _mining_view(asset),
        "purchasedAt": asset.get("purchased_at").isoformat() if isinstance(asset.get("purchased_at"), datetime) else None,
    }


# ── Админские цены (PriceEditorTab) ──────────────────────────────────────────
#
# Админ-редактор цен пишет overrides в общий конфиг "shop_prices" (см.
# shop.py:SHOP_PRICES_KEY). Магазин железа их применяет сам; рынок активов
# раньше игнорировал их и брал цену напрямую из статичного CATALOG — из-за
# этого правки в админ-панели не отражались в MarketTab / при покупке.
#
# Ключи в конфиге совпадают с slug актива (admin-re-N / admin-biz-N /
# admin-fac-... / car-...): раньше дома и бизнесы схлопывались в один
# числовой ключ 'N' и перезаписывали цены друг друга.
#
# Чтобы маппинг совпадал с frontend/src/utils/adminCatalog.js и
# frontend/src/utils/shopCatalog.js — см. ADMIN_DEFAULT_PRICES и
# REAL_ESTATE_PRODUCTS / BUSINESS_PRODUCTS.
SHOP_PRICES_KEY = "shop_prices"


def _admin_price_key(slug: str) -> str:
    """slug актива -> ключ в конфиге shop_prices.

    Ключ — сам slug: дома (admin-re-N) и бизнесы (admin-biz-N) живут в одном
    документе, и схлопывание обеих групп в голое 'N' приводило к тому, что
    цены домов и бизнесов перезаписывали друг друга.
    """
    return slug


async def _admin_prices(db) -> dict[str, float]:
    """Админские overrides: {key: price}. Бросает ValueError -> возвращаем {}."""
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


def _admin_price_for(slug: str, overrides: dict[str, float]) -> float | None:
    """Цена актива из админ-overrides (None = сброс к базовой из каталога)."""
    return overrides.get(_admin_price_key(slug))


# ── Market ───────────────────────────────────────────────────────────────────


@router.get("/market")
async def get_market(
    type: str = Query(None),
    search: str = Query(None),
    min_price: float = Query(None),
    max_price: float = Query(None),
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Каталог рынка с ДИНАМИЧЕСКИМИ ценами и admin-overrides из редактора цен."""
    await _ensure_asset_market(db)
    await _drift_asset_market(db)
    mults = await _mult_map(db)
    overrides = await _admin_prices(db)

    items = CATALOG
    if type in ASSET_TYPES:
        items = [c for c in items if c["type"] == type]
    if search:
        s = search.lower()
        items = [c for c in items if s in c["name"].lower()]

    out = []
    for c in items:
        mult = mults.get(c["slug"], 1.0)
        base = _admin_price_for(c["slug"], overrides) or float(c["price"])
        price = round(base * mult, 2)
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue
        out.append({
            "slug": c["slug"], "type": c["type"], "name": c["name"],
            "category": c.get("category"), "rarity": c.get("rarity"),
            "rooms": c.get("rooms"), "employees": c.get("employees", 0),
            "price": price,
            "basePrice": base,
            "trend": round((mult - 1) * 100, 1),   # % отклонения цены от базовой
            "incomePerHour": c.get("income_per_hour", 0),
            "upkeepPerHour": c.get("upkeep_per_hour", 0),
            "profitPerHour": round(c.get("income_per_hour", 0) - c.get("upkeep_per_hour", 0), 2),
            "meta": c.get("meta", {}),
        })
    out.sort(key=lambda x: x["price"])
    return out


# ── Заводы/Источники/Склады на лету (фолбэк для старого каталога) ────────────
# Дублируем определения, чтобы покупка работала даже если в коде на сервере
# ещё не подхвачены _ADMIN_MARKET_FACTORIES / _ADMIN_MARKET_SOURCES /
# _ADMIN_MARKET_WAREHOUSES (например, в кэшированном процессе). При наличии
# каталожной записи в CATALOG используется она (приоритет).


def _fallback_factory(slug: str) -> Optional[dict]:
    if slug == "admin-fac-gpu-1":
        return {"slug": slug, "type": TYPE_FACTORY, "category": "gpu",
                "name": "Завод видеокарт", "rarity": "rare", "price": 250000,
                "income_per_hour": 0, "upkeep_per_hour": 0, "employees": 24,
                "meta": {"produces": "gpu", "outputPerHour": 4}}
    if slug == "admin-fac-bakery-1":
        return {"slug": slug, "type": TYPE_FACTORY, "category": "bakery",
                "name": "Пекарня", "rarity": "rare", "price": 1200000,
                "income_per_hour": 0, "upkeep_per_hour": 0, "employees": 20,
                "meta": {"produces": "bread", "input": "wheat",
                         "outputPerHour": 120, "consumesPerHour": 240, "capacity": 30000}}


def _fallback_source(slug: str) -> Optional[dict]:
    SRC = {
        "admin-src-mine-1": ("Шахта", "common", 3500000, 8, "metal", 600, 50000),
        "admin-src-field-1": ("Поле", "common", 2200000, 6, "food", 800, 60000),
        "admin-src-sawmill-1": ("Лесопилка", "uncommon", 4800000, 10, "wood", 500, 45000),
    }
    info = SRC.get(slug)
    if not info:
        return None
    name, rarity, price, employees, resource, out, cap = info
    return {"slug": slug, "type": TYPE_SOURCE, "category": _src_category(slug),
            "name": name, "rarity": rarity, "price": price,
            "income_per_hour": 0, "upkeep_per_hour": 0, "employees": employees,
            "meta": {"resource": resource, "outputPerHour": out, "capacity": cap}}


def _src_category(slug: str) -> str:
    if "mine" in slug: return "mine"
    if "field" in slug: return "field"
    if "sawmill" in slug: return "sawmill"
    return "source"


def _fallback_warehouse(slug: str) -> Optional[dict]:
    # Слаги admin-wh-1..16 → площадь по WAREHOUSE_AREAS.
    if not slug.startswith("admin-wh-"):
        return None
    try:
        i = int(slug[len("admin-wh-"):]) - 1
    except ValueError:
        return None
    if i < 0 or i >= len(_WAREHOUSE_AREAS):
        return None
    area = _WAREHOUSE_AREAS[i]
    return {"slug": slug, "type": TYPE_WAREHOUSE, "category": "warehouse",
            "name": f"Склад {area:,} м²".replace(",", " "),
            "rarity": _wh_rarity(area), "price": _wh_price(area),
            "income_per_hour": 0, "upkeep_per_hour": 0,
            "employees": max(2, round(area / 200)),
            "meta": {"areaSqm": area, "storageCap": area * 1000, "slots": 1}}


def _fallback_catalog(slug: str) -> Optional[dict]:
    """Собрать каталожную запись на лету для инфраструктурных slug-ов.
    Используется, если _find_catalog вернул None (например, в кэшированном
    процессе бэкенда ещё не подхвачены _ADMIN_MARKET_FACTORIES/_SOURCES/
    _WAREHOUSES). Без этого фолбэка покупка отвечала 404 «Актив не найден»."""
    if not slug:
        return None
    if slug.startswith("admin-fac-"):
        return _fallback_factory(slug)
    if slug.startswith("admin-src-"):
        return _fallback_source(slug)
    if slug.startswith("admin-wh-"):
        return _fallback_warehouse(slug)
    return None


@router.post("/buy", status_code=status.HTTP_201_CREATED)
async def buy_asset(
    payload: BuyRequest,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Покупка актива с рынка: списывает баланс, создаёт экземпляр во владении."""
    catalog = _find_catalog(payload.slug)
    if not catalog:
        # Фолбэк: если slug относится к инфраструктуре (factory/source/
        # warehouse) и почему-то не попал в CATALOG, собираем запись на лету.
        catalog = _fallback_catalog(payload.slug)
    if not catalog:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Актив «{payload.slug}» не найден в каталоге. "
            "Если вы только что обновили игру — перезапустите бэкенд, "
            "чтобы подхватить новые позиции рынка.",
        )

    user_id = str(current_user["_id"])
    await check_type_limit(db, user_id, catalog["type"])
    # Динамическая цена покупки: admin-override (если задан в редакторе цен)
    # → базовая цена каталога. Затем применяем рыночный множитель.
    await _ensure_asset_market(db)
    mult = await _asset_mult(db, catalog["slug"])
    overrides = await _admin_prices(db)
    base_price = _admin_price_for(catalog["slug"], overrides) or float(catalog["price"])
    pay_price = round(base_price * mult, 2)

    new_balance = await adjust_balance(db, user_id, -pay_price)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

    doc = {
        "userId": user_id,
        "slug": catalog["slug"],
        "type": catalog["type"],
        "name": catalog["name"],
        "category": catalog.get("category"),
        "rarity": catalog.get("rarity"),
        "rooms": catalog.get("rooms"),
        "basement": catalog.get("basement"),   # ёмкость подвала (недвижимость) — для улучшения «Майнинг»
        "employees": catalog.get("employees", 0),
        "price": float(catalog["price"]),   # базовая цена — для расчёта стоимости/улучшений
        # Куплено дороже/дешевле базы → доход и расход экземпляра масштабируются
        # так же (см. _price_mult), иначе покупка на пике рынка была бы ловушкой.
        "price_mult": round(mult, 4),
        "income_per_hour": catalog.get("income_per_hour", 0),
        "upkeep_per_hour": catalog.get("upkeep_per_hour", 0),
        "level": 1,
        "mining": False,         # улучшение «Майнинг» ещё не куплено
        "meta": catalog.get("meta", {}),
        "companyId": None,      # None = личный актив; иначе принадлежит компании
        "rental": None,         # активное объявление/аренда (см. rental)
        "purchased_at": _now(),
        "last_collected": _now(),
    }
    result = await db.user_assets.insert_one(doc)
    doc["_id"] = result.inserted_id

    cat = _ledger_category(catalog)
    await record_transaction(
        db, user_id, EXPENSE, pay_price, cat,
        f"Покупка: {catalog['name']}", balance_after=new_balance,
        meta={"slug": catalog["slug"], "type": catalog["type"]},
    )
    # Спрос поднимает рыночную цену этого товара.
    await _bump_demand(db, catalog["slug"], DEMAND_BUY)
    return {"asset": _serialize(doc), "balance": new_balance, "paid": pay_price}


# ── Ownership ────────────────────────────────────────────────────────────────


@router.get("/mine")
async def get_my_assets(
    type: str = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Личные активы игрока (без переданных компании) + агрегаты."""
    user_id = str(current_user["_id"])
    query = {"userId": user_id, "companyId": None}
    if type in ASSET_TYPES:
        query["type"] = type
    docs = [a async for a in db.user_assets.find(query)]
    assets = []
    for a in docs:
        a = await _process_rental(db, a)   # ленивое заселение/выплата аренды
        assets.append(_serialize(a))
    assets.sort(key=lambda a: a["value"], reverse=True)
    total_value = round(sum(a["value"] for a in assets), 2)
    total_profit = round(sum(a["profitPerHour"] for a in assets), 2)
    total_accrued = round(sum(a["accrued"] for a in assets), 2)
    return {
        "assets": assets,
        "totalValue": total_value,
        "profitPerHour": total_profit,
        "accrued": total_accrued,
        "count": len(assets),
    }


async def _load_owned(db, user_id, asset_id):
    if not ObjectId.is_valid(asset_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID актива")
    asset = await db.user_assets.find_one({"_id": ObjectId(asset_id), "userId": user_id})
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Актив не найден")
    return asset


@router.post("/{asset_id}/collect")
async def collect_income(
    asset_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Собрать накопленный доход (за вычетом расходов на содержание)."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    # Актив, переданный в компанию, приносит доход в бюджет компании (отдельный
    # last_tick). Личный сбор по нему запрещён — иначе один актив платит дважды
    # (владельцу лично И в бюджет компании).
    if asset.get("companyId"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Актив принадлежит компании — доход идёт в бюджет компании")
    econ = await get_econ(db)
    city_bonus = await _city_asset_bonus(db, user_id)
    media_factor = await _media_income_factor(db, user_id)
    event_income = await _event_income_factor(db)
    amount = await _collect_asset_income(db, user_id, asset, econ, event_income, city_bonus, media_factor)
    if amount <= 0:
        return {"collected": 0.0, "balance": current_user.get("balance", 0.0)}
    new_balance = await adjust_balance(db, user_id, amount)
    cat = _ledger_category(asset)
    await record_transaction(
        db, user_id, INCOME, amount, cat,
        f"Доход: {asset['name']}", balance_after=new_balance,
        meta={"slug": asset.get("slug"), "assetId": asset_id},
    )
    return {"collected": amount, "balance": new_balance}


async def _city_asset_bonus(db, user_id: str) -> float:
    try:
        from cityroof import player_city_effect
        return await player_city_effect(db, user_id, "asset_income")
    except Exception:
        return 0.0


async def _media_income_factor(db, user_id: str) -> float:
    """Репутационный множитель СМИ для бизнесов игрока (1.0 — нет эффектов)."""
    try:
        from media import active_owner_income_factor
        return await active_owner_income_factor(db, user_id)
    except Exception:
        return 1.0


async def _event_income_factor(db) -> float:
    """Множитель пассивного дохода от активных мировых событий
    (кризис/бум/реформа — market_events.event_shifts['income']; 1.0 — нет событий)."""
    try:
        from market_events import event_shifts
        return float((await event_shifts(db)).get("income", 1.0))
    except Exception:
        return 1.0


async def _collect_asset_income(db, user_id: str, asset: dict, econ: dict,
                                event_income: float, city_bonus: float,
                                media_factor: float = 1.0) -> float:
    """Считает и применяет (обнуляет КД) доход одного актива, возвращает сумму.
    Множители (econ/событие/город/СМИ) передаются готовыми, чтобы при массовом
    сборе не пересчитывать их на каждый актив.

    ``media_factor`` — репутационный множитель СМИ (media.py): применяется только
    к бизнесам владельца (недвижимость/авто не затрагиваются разоблачением).

    Присвоение накопления атомарно: last_collected сбрасывается условным
    апдейтом по ТОМУ ЖЕ значению, что было прочитано. Если два параллельных
    запроса читают один last_collected, апдейт сработает лишь у одного —
    второй получит 0 (иначе доход дублировался бы, TOCTOU)."""
    seen = asset.get("last_collected")
    matched = await db.user_assets.update_one(
        {"_id": asset["_id"], "last_collected": seen},
        {"$set": {"last_collected": _now()}},
    )
    if matched.modified_count == 0:
        return 0.0  # накопление уже присвоено параллельным запросом
    amount = _accrued(asset, econ)
    amount = round(amount * econ.get("income_mult", 1.0) * econ.get("economy_mult", 1.0), 2)
    amount = round(amount * event_income, 2)
    if city_bonus:
        amount = round(amount * (1 + city_bonus), 2)
    if media_factor != 1.0 and asset.get("type") == TYPE_BUSINESS:
        amount = round(amount * media_factor, 2)
    return amount


@router.post("/collect-all")
async def collect_all_income(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Собрать накопленный доход со всех личных активов игрока разом."""
    user_id = str(current_user["_id"])
    econ = await get_econ(db)
    city_bonus = await _city_asset_bonus(db, user_id)
    media_factor = await _media_income_factor(db, user_id)
    event_income = await _event_income_factor(db)

    total = 0.0
    count = 0
    async for asset in db.user_assets.find({"userId": user_id, "companyId": None}):
        if asset.get("income_per_hour", 0) <= 0:
            # У заводов/источников статичный income_per_hour = 0 — они зарабатывают
            # только динамически (продукция × цена из econ). Не пропускаем их:
            # раньше «Собрать всё» молча пропускал завод и источник целиком.
            if _infra_income_per_hour(asset, econ) <= 0 and _mining_income_per_hour(asset, econ) <= 0:
                continue
        amount = await _collect_asset_income(db, user_id, asset, econ, event_income, city_bonus, media_factor)
        if amount <= 0:
            continue
        new_balance = await adjust_balance(db, user_id, amount)
        cat = _ledger_category(asset)
        await record_transaction(
            db, user_id, INCOME, amount, cat,
            f"Доход: {asset['name']}", balance_after=new_balance,
            meta={"slug": asset.get("slug"), "assetId": str(asset["_id"])},
        )
        total = round(total + amount, 2)
        count += 1

    balance = current_user.get("balance", 0.0)
    if count:
        u = await db.users.find_one({"_id": ObjectId(user_id)}, {"balance": 1})
        balance = (u or {}).get("balance", balance)
    return {"collected": round(total, 2), "count": count, "balance": balance}


class UpgradeBody(BaseModel):
    """Улучшение сразу на несколько уровней (модалка «Улучшения» со скроллером)."""
    levels: int = 1

    @field_validator("levels")
    @classmethod
    def levels_ok(cls, v):
        if v is None or v < 1:
            raise ValueError("Минимум 1 уровень")
        if v > UPGRADE_PREVIEW_LEVELS:
            raise ValueError(f"Максимум {UPGRADE_PREVIEW_LEVELS} уровней за раз")
        return int(v)


@router.get("/{asset_id}/upgrade-preview")
async def upgrade_preview(
    asset_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Что даст каждый следующий уровень — для модалки «Улучшения»."""
    asset = await _load_owned(db, str(current_user["_id"]), asset_id)
    if asset.get("type") == TYPE_CAR:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Автомобиль не улучшается по уровню — используйте тюнинг деталей")
    return {
        "current": {
            "level": asset.get("level", 1),
            "incomePerHour": _income_per_hour(asset),
            "profitPerHour": round(_income_per_hour(asset) - _upkeep_per_hour(asset), 2),
            "value": _current_value(asset),
            "rentRatePerHour": _rent_rate_per_hour(asset),
        },
        "levels": _upgrade_plan(asset, UPGRADE_PREVIEW_LEVELS),
    }


@router.post("/{asset_id}/upgrade")
async def upgrade_asset(
    asset_id: str,
    payload: UpgradeBody = UpgradeBody(),
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Улучшить актив: повышает стоимость и доход."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    # Авто не улучшаются через уровень — у них нет почасового дохода, а стоимость
    # растят тюнингом деталей (см. /tune). Поэтому уровень авто всегда 1.
    if asset.get("type") == TYPE_CAR:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Автомобиль не улучшается по уровню — используйте тюнинг деталей")
    steps = payload.levels
    seen_level = asset.get("level", 1)
    cost = _upgrade_plan(asset, steps)[-1]["totalCost"]
    new_balance = await adjust_balance(db, user_id, -cost)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
    # Уровень поднимаем условно — по тому же значению, что прочитали. Иначе два
    # параллельных запроса, прочитав level=N, оба заплатят цену перехода с N и
    # поднимут актив на 2·steps — уровни дешевле прайса (TOCTOU).
    res = await db.user_assets.update_one(
        {"_id": asset["_id"], "level": seen_level}, {"$inc": {"level": steps}},
    )
    if res.modified_count == 0:
        await adjust_balance(db, user_id, cost)
        raise HTTPException(status.HTTP_409_CONFLICT, "Уровень актива изменился — повторите")
    cat = CAT_BUSINESS if asset["type"] == TYPE_BUSINESS else CAT_REALESTATE
    await record_transaction(
        db, user_id, EXPENSE, cost, cat,
        f"Улучшение: {asset['name']} → ур.{seen_level + steps}",
        balance_after=new_balance, meta={"assetId": asset_id, "levels": steps},
    )
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    return {"asset": _serialize(updated), "balance": new_balance}


@router.post("/{asset_id}/tune")
async def tune_asset(
    asset_id: str,
    payload: TuneBody,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Тюнинг автомобиля: улучшает деталь, повышает престиж и стоимость авто."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    if asset.get("type") != TYPE_CAR:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Тюнинг доступен только для автомобилей")
    if asset.get("category") == "trailer":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Прицепы не тюнингуются")

    part = payload.part
    tuning = dict(asset.get("tuning", {}))
    level = int(tuning.get(part, 0))
    if level >= TUNE_MAX_LEVEL:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Достигнут максимальный уровень детали")

    cost = _tune_cost(asset, level)
    new_balance = await adjust_balance(db, user_id, -cost)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

    tuning[part] = level + 1
    meta = dict(asset.get("meta", {}))
    meta["prestige"] = int(meta.get("prestige", 0)) + TUNE_PARTS[part]
    tuning_value = round(asset.get("tuning_value", 0.0) + cost * TUNE_VALUE_RETAIN, 2)
    await db.user_assets.update_one(
        {"_id": asset["_id"]},
        {"$set": {"tuning": tuning, "meta": meta, "tuning_value": tuning_value}},
    )
    await record_transaction(
        db, user_id, EXPENSE, cost, CAT_REALESTATE,
        f"Тюнинг: {asset.get('name')} — {part}", balance_after=new_balance,
        meta={"assetId": asset_id, "part": part, "level": level + 1},
    )
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    return {"asset": _serialize(updated), "balance": new_balance, "cost": cost}


# ── Переименование и прицепы ─────────────────────────────────────────────────


@router.patch("/{asset_id}/rename")
async def rename_asset(
    asset_id: str,
    payload: RenameBody,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Переименовать своё имущество/транспорт. Название игрока приоритетнее
    каталожного: фронт показывает custom_name, если задан (customName в _serialize)."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    await db.user_assets.update_one(
        {"_id": asset["_id"]},
        {"$set": {"name": payload.name, "custom_name": True}},
    )
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    return {"asset": _serialize(updated)}


@router.post("/{asset_id}/hitch")
async def hitch_trailer(
    asset_id: str,
    payload: HitchBody,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Прицепить прицеп к фуре. Правила:
      - прицеп и фура принадлежат игроку (личные, не в компании);
      - у фуры в meta.hookable перечислены совместимые slug прицепов;
      - один прицеп на фуру, прицеп не может быть уже прицеплен."""
    user_id = str(current_user["_id"])
    trailer = await _load_owned(db, user_id, asset_id)
    if trailer.get("category") != "trailer":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Это не прицеп")
    if trailer.get("hitchedTo"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Прицеп уже прицеплен к другой фуре")
    truck_id = (payload.truckId or "").strip()
    if not truck_id or not ObjectId.is_valid(truck_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не указана фура")
    truck = await db.user_assets.find_one({
        "_id": ObjectId(truck_id), "userId": user_id,
        "type": TYPE_CAR, "category": "truck",
    })
    if not truck:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Фура не найдена")
    if truck.get("companyId"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Фура принадлежит компании")
    hookable = (truck.get("meta") or {}).get("hookable") or []
    if trailer.get("slug") not in hookable:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Эта фура не может тянуть прицеп «{trailer.get('name')}»",
        )
    busy = await db.user_assets.find_one({"hitchedTo": ObjectId(truck_id)})
    if busy:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "К этой фуре уже прицеплен другой прицеп")
    await db.user_assets.update_one({"_id": trailer["_id"]}, {"$set": {"hitchedTo": ObjectId(truck_id)}})
    return {"ok": True, "asset": _serialize(await db.user_assets.find_one({"_id": trailer["_id"]}))}


@router.post("/{asset_id}/unhitch")
async def unhitch_trailer(
    asset_id: str,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Отцепить прицеп от фуры."""
    user_id = str(current_user["_id"])
    trailer = await _load_owned(db, user_id, asset_id)
    if trailer.get("category") != "trailer":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Это не прицеп")
    if not trailer.get("hitchedTo"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Прицеп не прицеплен")
    await db.user_assets.update_one({"_id": trailer["_id"]}, {"$unset": {"hitchedTo": ""}})
    return {"ok": True, "asset": _serialize(await db.user_assets.find_one({"_id": trailer["_id"]}))}


@router.post("/{asset_id}/mining/buy")
async def buy_mining_upgrade(
    asset_id: str,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Купить улучшение «Майнинг» для дома. Доступно только для недвижимости
    с подвалом (basement > 0). Покупается ровно 1 раз — повторные вызовы
    запрещены. Цена всегда пересчитывается сервером от basement (формула
    econ.mining_basement_cost) — клиентское значение не используется, чтобы цену нельзя
    было подменить. После покупки дом начинает приносить пассивный доход
    (basement × mining_basement_income $/ч), собирается тем же /collect, что и обычный
    доход недвижимости."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    if asset.get("type") != TYPE_REALESTATE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Улучшение «Майнинг» доступно только для домов")
    if asset.get("mining"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Улучшение «Майнинг» уже куплено")
    basement = int(asset.get("basement") or 0)
    if basement <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "У этого дома нет подвала — майнинг недоступен")
    cost = _mining_cost(asset, await get_econ(db))
    # Атомарно занимаем слот улучшения ДО списания: условие mining != True
    # сработает только у одного из параллельных запросов, двойной оплаты нет.
    # last_collected запоминаем: при откате (не хватило денег) его надо
    # вернуть, иначе накопленный доход дома молча сотрётся.
    prev_collected = asset.get("last_collected")
    claimed = await db.user_assets.find_one_and_update(
        {"_id": asset["_id"], "mining": {"$ne": True}},
        {"$set": {"mining": True, "last_collected": _now()}},
    )
    if not claimed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Улучшение «Майнинг» уже куплено")
    new_balance = await adjust_balance(db, user_id, -cost)
    if new_balance is None:
        # Денег не хватило — снимаем заявку и восстанавливаем окно сбора.
        rollback = {"$unset": {"mining": ""}}
        if prev_collected is None:
            rollback["$unset"]["last_collected"] = ""
        else:
            rollback["$set"] = {"last_collected": prev_collected}
        await db.user_assets.update_one({"_id": asset["_id"]}, rollback)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
    await record_transaction(
        db, user_id, EXPENSE, cost, CAT_REALESTATE,
        f"Майнинг-улучшение: {asset.get('name')}", balance_after=new_balance,
        meta={"assetId": asset_id, "basement": basement},
    )
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    try:
        from ws import push_to_user
        await push_to_user(user_id, {"type": "asset_update", "assetId": asset_id})
    except Exception:
        pass
    return {"asset": _serialize(updated), "balance": new_balance, "cost": cost}


@router.post("/{asset_id}/sell")
async def sell_asset(
    asset_id: str,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Продать актив обратно (70% текущей стоимости) + невыбранный доход."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    # Стоимость продажи учитывает тот же рыночный множитель, что и покупка —
    # иначе при mult<0.7 возникает арбитраж (купил за 0.5×base, продал за
    # 0.7×base). Множитель применяется к базовой стоимости экземпляра; тюнинг
    # (tuning_value) и накопленный доход к рынку не привязаны.
    await _ensure_asset_market(db)
    mult = await _asset_mult(db, asset.get("slug"))
    base_value = round(_current_value(asset) - asset.get("tuning_value", 0.0), 2)
    market_value = round(base_value * mult + asset.get("tuning_value", 0.0), 2)
    payout = round(market_value * SELL_RATE + _accrued(asset), 2)
    # Если продали фуру — отцепляем её прицеп (иначе ссылка висела бы мёртвым грузом).
    if asset.get("category") == "truck":
        await db.user_assets.update_many({"hitchedTo": asset["_id"]}, {"$unset": {"hitchedTo": ""}})
    await db.user_assets.delete_one({"_id": asset["_id"]})
    new_balance = await adjust_balance(db, user_id, payout)
    cat = _ledger_category(asset)
    await record_transaction(
        db, user_id, INCOME, payout, cat,
        f"Продажа: {asset['name']}", balance_after=new_balance,
        meta={"slug": asset.get("slug")},
    )
    # Продажа опускает рыночную цену этого товара.
    if asset.get("slug"):
        await _bump_demand(db, asset["slug"], -DEMAND_SELL)
    return {"sold": payout, "balance": new_balance}


@router.post("/{asset_id}/transfer-to-company")
async def transfer_to_company(
    asset_id: str,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Передать актив своей компании — доход с него начнёт получать компания."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    if asset.get("companyId"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Актив уже принадлежит компании")
    company = await db.companies.find_one({"ownerId": user_id})
    if not company:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Сначала создайте компанию")
    await db.user_assets.update_one(
        {"_id": asset["_id"]},
        {"$set": {"companyId": str(company["_id"]), "rental": None, "last_collected": _now()}},
    )
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    return {"ok": True, "asset": _serialize(updated)}


@router.post("/{asset_id}/transfer-to-player")
async def transfer_to_player(
    asset_id: str,
    payload: TransferToPlayer,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Подарить личный актив другому игроку по нику. Актив уходит целиком
    (со всеми улучшениями/материалами) — доход по нему начнёт получать новый
    владелец. Нельзя передавать активы, отданные компании или сдаваемые."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    if asset.get("companyId"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Актив принадлежит компании — сначала верните его себе")
    if asset.get("category") == "truck":
        await db.user_assets.update_many({"hitchedTo": asset["_id"]}, {"$unset": {"hitchedTo": ""}})
    if asset.get("rental"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Актив сдаётся или ждёт арендатора — снимите с аренды")
    target = await db.users.find_one({"username": payload.toUsername})
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Игрок не найден")
    new_owner_id = str(target["_id"])
    if new_owner_id == user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя передать актив самому себе")
    # Копим доход у прежнего владельца обнуляется — новый владелец начинает с чистого КД.
    await db.user_assets.update_one(
        {"_id": asset["_id"]},
        {"$set": {"userId": new_owner_id, "companyId": None, "rental": None, "last_collected": _now()}},
    )
    try:
        from ws import push_to_user
        await push_to_user(user_id, {"type": "asset_update", "assetId": asset_id})
        await push_to_user(new_owner_id, {"type": "asset_update", "assetId": asset_id})
    except Exception:
        pass
    return {"ok": True, "toUsername": payload.toUsername}


@router.post("/{asset_id}/rent/list")
async def rent_list(
    asset_id: str,
    payload: RentListing,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Выставить недвижимость/авто/бизнес в аренду на произвольный срок (в часах).
    Арендатор появится через случайный диапазон часов. Цена всегда пересчитывается
    сервером от стоимости актива, его редкости и срока (см. _rent_total) —
    клиент выбирает только срок, поэтому её нельзя подделать.

    Работает и для личных активов, и для активов компании (владелец компании
    управляет ими) — в последнем случае выплата поступит в бюджет компании.
    """
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    if not _is_rentable(asset):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Сдавать можно недвижимость, авто, а из бизнесов — только IT-студию и Медиахолдинг")
    if asset.get("rental"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Объект уже сдаётся или ждёт арендатора")
    # Итоговая цена всегда пересчитывается сервером из срока — клиентской цене не доверяем.
    price = _rent_total(asset, payload.minHours)
    wait_h = random.randint(RENT_MIN_WAIT_H, RENT_MAX_WAIT_H)
    rental = {
        "status": "listed",
        "price": price,
        "minHours": payload.minHours,
        "tenant_at": _now() + timedelta(hours=wait_h),
        "ends_at": None,
        "listed_at": _now(),
    }
    await db.user_assets.update_one({"_id": asset["_id"]}, {"$set": {"rental": rental}})
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    return {"ok": True, "asset": _serialize(updated), "tenantInHours": wait_h}


@router.post("/{asset_id}/rent/cancel")
async def rent_cancel(
    asset_id: str,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Снять объявление об аренде (пока арендатор не заселился)."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    r = asset.get("rental")
    if not r or r.get("status") != "listed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Объект уже сдан или не выставлен")
    await db.user_assets.update_one({"_id": asset["_id"]}, {"$set": {"rental": None}})
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    return {"ok": True, "asset": _serialize(updated)}


# ── Материалы для бизнеса ────────────────────────────────────────────────────


async def _materials_unit_price(db: AsyncIOMotorDatabase, asset: Optional[dict] = None) -> float:
    """Цена единицы материалов для конкретного бизнеса.

    Пропорциональна часовому доходу бизнеса: единица даёт +MATERIALS_BOOST_PER_UNIT
    к доходу, поэтому и стоить должна долю от того, что этот процент приносит.
    Без актива (общий прайс до выбора бизнеса) считаем по самому дешёвому
    бизнесу каталога — это нижняя граница, которую клиент показывает как «от».
    """
    econ = await get_econ(db)
    mult = econ.get("economy_mult", 1.0)
    try:
        from market_events import event_shifts
        mult *= (await event_shifts(db)).get("materials", 1.0)
    except Exception:
        pass
    if asset is not None:
        income_h = _income_per_hour(asset) / (1 + _materials_boost(asset))
    else:
        income_h = min(c["income_per_hour"] for c in CATALOG if c["type"] == TYPE_BUSINESS)
    unit = income_h * MATERIALS_BOOST_PER_UNIT * MATERIALS_COST_PER_INCOME_H
    return round(max(1.0, unit) * mult, 2)


@router.get("/materials/price")
async def materials_price(
    assetId: str = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Текущая цена материалов за единицу. Зависит от активного мирового события
    и от самого бизнеса (цена пропорциональна его доходу) — без assetId вернём
    нижнюю границу по каталогу."""
    asset = None
    if assetId:
        asset = await _load_owned(db, str(current_user["_id"]), assetId)
    return {
        "unitPrice": await _materials_unit_price(db, asset),
        "boostPerUnit": MATERIALS_BOOST_PER_UNIT,
        "boostCap": MATERIALS_BOOST_CAP,
        "durationHours": MATERIALS_DURATION_H,
    }


@router.post("/{asset_id}/materials/buy")
async def buy_materials(
    asset_id: str,
    payload: MaterialsBuy,
    current_user: dict = Depends(require_allowed("assets")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Закупить материалы для бизнеса — временно (на MATERIALS_DURATION_H)
    поднимает его доход. Цена за единицу пересчитывается сервером от текущего
    мирового события — клиентская цена никогда не используется."""
    user_id = str(current_user["_id"])
    asset = await _load_owned(db, user_id, asset_id)
    if asset.get("type") != TYPE_BUSINESS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Материалы закупаются только для бизнеса")

    unit_price = await _materials_unit_price(db, asset)
    total = round(unit_price * payload.qty, 2)
    new_balance = await adjust_balance(db, user_id, -total)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

    boost = min(MATERIALS_BOOST_CAP, _materials_boost(asset) + MATERIALS_BOOST_PER_UNIT * payload.qty)
    materials = {"boostPct": round(boost, 4), "expires_at": _now() + timedelta(hours=MATERIALS_DURATION_H)}
    await db.user_assets.update_one({"_id": asset["_id"]}, {"$set": {"materials": materials}})

    await record_transaction(
        db, user_id, EXPENSE, total, CAT_BUSINESS,
        f"Материалы: {asset.get('name')} ×{payload.qty}", balance_after=new_balance,
        meta={"assetId": asset_id, "qty": payload.qty, "unitPrice": unit_price},
    )
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    return {"asset": _serialize(updated), "balance": new_balance, "unitPrice": unit_price, "total": total}


# ── Admin ────────────────────────────────────────────────────────────────────


async def _load_any(db: AsyncIOMotorDatabase, asset_id: str) -> dict:
    if not ObjectId.is_valid(asset_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID актива")
    asset = await db.user_assets.find_one({"_id": ObjectId(asset_id)})
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Актив не найден")
    return asset


@router.patch("/admin/{asset_id}")
async def admin_update_asset(
    asset_id: str,
    payload: AdminAssetUpdate,
    _admin=Depends(require_admin("users_property")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    asset = await _load_any(db, asset_id)
    update_fields = payload.model_dump(exclude_unset=True)
    if not update_fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нет полей для обновления")
    await db.user_assets.update_one({"_id": asset["_id"]}, {"$set": update_fields})
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    try:
        from ws import push_to_user
        await push_to_user(asset["userId"], {"type": "asset_update", "assetId": asset_id})
    except Exception:
        pass
    return {"asset": _serialize(updated)}


@router.delete("/admin/{asset_id}")
async def admin_delete_asset(
    asset_id: str,
    _admin=Depends(require_admin("users_property")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    asset = await _load_any(db, asset_id)
    await db.user_assets.delete_one({"_id": asset["_id"]})
    try:
        from ws import push_to_user
        await push_to_user(asset["userId"], {"type": "asset_update", "assetId": asset_id})
    except Exception:
        pass
    return {"message": f"Актив «{asset.get('name')}» удалён"}


@router.post("/admin/{asset_id}/transfer")
async def admin_transfer_asset(
    asset_id: str,
    payload: AdminTransferBody,
    _admin=Depends(require_admin("users_property")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    asset = await _load_any(db, asset_id)
    target = await db.users.find_one({"username": payload.toUsername})
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Игрок не найден")
    new_owner_id = str(target["_id"])
    old_owner_id = asset["userId"]
    await db.user_assets.update_one(
        {"_id": asset["_id"]},
        {"$set": {"userId": new_owner_id, "companyId": None, "rental": None}},
    )
    updated = await db.user_assets.find_one({"_id": asset["_id"]})
    try:
        from ws import push_to_user
        await push_to_user(old_owner_id, {"type": "asset_update", "assetId": asset_id})
        await push_to_user(new_owner_id, {"type": "asset_update", "assetId": asset_id})
    except Exception:
        pass
    return {"asset": _serialize(updated)}


# ── Aggregate value (для лидерборда/капитала) ────────────────────────────────


async def total_asset_value(db: AsyncIOMotorDatabase, user_id: str) -> float:
    total = 0.0
    async for a in db.user_assets.find({"userId": user_id}):
        total += _current_value(a)
    return round(total, 2)


if __name__ == "__main__":
    # Санити-чек формулы аренды: цена обязана расти линейно со сроком (в часах)
    # и совпадать с той же формулой, что используется при выставлении объявления.
    demo_asset = {"type": "realestate", "price": 40000, "rarity": "uncommon", "level": 1, "tuning_value": 0.0}
    rate = _rent_rate_per_hour(demo_asset)
    assert rate > 0
    assert abs(_rent_total(demo_asset, 1) - rate) < 0.01
    assert abs(_rent_total(demo_asset, 6) - rate * 6) < 0.05
    assert _rent_total(demo_asset, RENT_MAX_HOURS) == round(_rent_daily_rate(demo_asset) * RENT_MAX_HOURS / 24, 2)
    # 1 час не должен стоить столько же, сколько 30 суток.
    assert _rent_total(demo_asset, 1) < _rent_total(demo_asset, RENT_MAX_HOURS)

    # Ориентир баланса: вилла (rare, $160k) — аренда несёт 1/4 доходности,
    # остальное даёт пассивный доход (см. RARITY_RENT_PCT).
    villa = {"type": "realestate", "price": 160000, "rarity": "rare", "level": 1, "tuning_value": 0.0}
    assert 9000 <= _rent_daily_rate(villa) <= 12000, _rent_daily_rate(villa)

    # Суммарная доходность каждого актива каталога — 24–31%/сутки (окупаемость
    # 3.2–4.2 дня). Единый ориентир для всей экономики: активы, ферма и компании
    # должны отбиваться за сопоставимое время, иначе один класс обесценивает остальные.
    # Инфраструктура (admin-re-*/*factory/source/warehouse) проверяется отдельно:
    # источники/пекарня зарабатывают физическими ресурсами (production.py), склады
    # денег не приносят, а лестница admin-re-* исторически ниже коридора.
    for _c in CATALOG:
        if _c["slug"].startswith("admin-") or _c["type"] in (TYPE_FACTORY, TYPE_SOURCE, TYPE_WAREHOUSE):
            continue
        _inst = _c | {"level": 1, "tuning_value": 0.0}
        _daily = (_income_per_hour(_inst) - _upkeep_per_hour(_inst)) * 24 + _rent_daily_rate(_inst)
        _pct = _daily / _c["price"] * 100
        assert 23.0 <= _pct <= 31.0, f"{_c['slug']}: {_pct:.1f}%/сутки вне коридора 23–31"

    # Авто не имеют пассивного дохода, поэтому их аренда дороже недвижимости той
    # же редкости (CAR_RENT_MULT) — иначе машины были бы заведомо худшим активом.
    _car_epic = {"type": "car", "price": 600000, "rarity": "epic", "level": 1, "tuning_value": 0.0}
    _re_epic = {"type": "realestate", "price": 600000, "rarity": "epic", "level": 1, "tuning_value": 0.0}
    assert _rent_daily_rate(_car_epic) > _rent_daily_rate(_re_epic)

    # Ожидание арендатора не должно съедать короткую сдачу: при среднем ожидании
    # (RENT_MIN_WAIT_H+RENT_MAX_WAIT_H)/2 суточная аренда реализует >80% ставки.
    _avg_wait = (RENT_MIN_WAIT_H + RENT_MAX_WAIT_H) / 2
    assert 24 / (24 + _avg_wait) > 0.8, "мёртвое ожидание съедает суточную аренду"

    # Один и тот же тип актива с разной редкостью НЕ должен зарабатывать одинаково:
    # дешёвый/частый объект уступает дорогому/редкому и в % доходности, и в сумме.
    common_re = {"type": "realestate", "price": 160000, "rarity": "common", "level": 1, "tuning_value": 0.0}
    uncommon_re = {"type": "realestate", "price": 160000, "rarity": "uncommon", "level": 1, "tuning_value": 0.0}
    epic_re = {"type": "realestate", "price": 160000, "rarity": "epic", "level": 1, "tuning_value": 0.0}
    legendary_re = {"type": "realestate", "price": 160000, "rarity": "legendary", "level": 1, "tuning_value": 0.0}
    assert _rent_daily_rate(common_re) < _rent_daily_rate(uncommon_re) < _rent_daily_rate(villa) \
        < _rent_daily_rate(epic_re) < _rent_daily_rate(legendary_re)

    # Настоящий каталог: дешёвая студия НЕ должна почти совпадать по доходности
    # с элитным замком (старый баг — единый пол в $2000 для всех активов).
    studio_rate = _rent_daily_rate(CATALOG_BY_SLUG["studio"] | {"level": 1, "tuning_value": 0.0})
    castle_rate = _rent_daily_rate(CATALOG_BY_SLUG["castle"] | {"level": 1, "tuning_value": 0.0})
    assert studio_rate < 1500, studio_rate
    assert castle_rate > 100000, castle_rate
    assert castle_rate / studio_rate > 100

    # Бизнесы и авто тоже сдаются в аренду — у каждого своя ставка через rarity,
    # добавленную в каталог (не одинаковый коэффициент для всего имущества).
    # НО из бизнесов сдаются только IT-студия и Медиахолдинг (у остальных нет
    # полезной арендатору механики), поэтому у бизнеса важен slug.
    studio_biz = CATALOG_BY_SLUG["itstudio_basic"] | {"level": 1, "tuning_value": 0.0}
    media_biz = CATALOG_BY_SLUG["media_holding"] | {"level": 1, "tuning_value": 0.0}
    plain_biz = CATALOG_BY_SLUG["coffee"] | {"level": 1, "tuning_value": 0.0}
    assert _is_rentable(studio_biz) and _rent_daily_rate(studio_biz) > 0
    assert _is_rentable(media_biz) and _rent_daily_rate(media_biz) > 0
    # Обычный бизнес (кофейня) сдавать нельзя — ставка 0.
    assert not _is_rentable(plain_biz)
    assert _rent_daily_rate(plain_biz) == 0.0
    car_asset = CATALOG_BY_SLUG["super"] | {"level": 1, "tuning_value": 0.0}
    assert _is_rentable(car_asset)
    assert _rent_daily_rate(car_asset) > 0
    # Авто НЕ приносят почасового дохода — только аренда (даже если в данные
    # просочилась ненулевая ставка income_per_hour).
    assert _income_per_hour(CATALOG_BY_SLUG["super"] | {"income_per_hour": 999}) == 0.0
    # Недвижимость по-прежнему сдаётся без всяких slug-ограничений.
    assert _is_rentable({"type": "realestate", "slug": "studio"})

    non_rentable = {"type": "crypto", "price": 40000, "rarity": "rare", "level": 1}
    assert _rent_rate_per_hour(non_rentable) == 0.0
    assert not _is_rentable(non_rentable)

    # Купленный на пике рынка актив окупается за то же время, что купленный на
    # просадке: доход, расход и аренда масштабируются вместе с ценой (_price_mult).
    # Иначе покупка при ×2.5 растягивала бы окупаемость с 3.3 до 8 суток.
    _base = CATALOG_BY_SLUG["itstudio_premium"] | {"level": 1, "tuning_value": 0.0}
    def _payback_pct(mult):
        _inst = _base | {"price_mult": mult}
        _daily = (_income_per_hour(_inst) - _upkeep_per_hour(_inst)) * 24 + _rent_daily_rate(_inst)
        return _daily / (_base["price"] * mult) * 100
    for _m in (ASSET_MULT_MIN, 1.0, ASSET_MULT_MAX):
        assert abs(_payback_pct(_m) - _payback_pct(1.0)) < 0.1, (_m, _payback_pct(_m))
    # Активы, купленные до появления поля, считаются как ×1.0.
    assert _income_per_hour(_base) == _income_per_hour(_base | {"price_mult": 1.0})

    # Качать актив должно быть не хуже, чем купить ещё один: окупаемость улучшения
    # не растёт с уровнем и держится в том же коридоре, что покупка нового.
    # (Старый баг: цена улучшения base*0.4*level при плоском приросте дохода —
    # L1→L2 окупался за 3.6 суток, L5→L6 за 18.)
    def _daily(asset):
        return (_income_per_hour(asset) - _upkeep_per_hour(asset)) * 24 + _rent_daily_rate(asset)
    for _c in CATALOG:
        if _c["type"] in (TYPE_CAR, TYPE_FACTORY, TYPE_SOURCE, TYPE_WAREHOUSE):
            continue   # авто качаются тюнингом; инфраструктура — вне коридора доходности
        _lvl1 = _c | {"level": 1, "tuning_value": 0.0}
        _buy_days = _c["price"] / _daily(_lvl1)
        for _lvl in (1, 5, 10):
            _inst = _c | {"level": _lvl, "tuning_value": 0.0}
            _gain = _daily(_c | {"level": _lvl + 1, "tuning_value": 0.0}) - _daily(_inst)
            _days = _upgrade_cost(_inst) / _gain
            assert _days <= _buy_days + 0.5, f"{_c['slug']} ур.{_lvl}: апгрейд {_days:.1f}д против покупки {_buy_days:.1f}д"
    # Цена улучшения следует за ценой покупки — как и доход экземпляра.
    assert _upgrade_cost(_base | {"price_mult": 2.5}) == _upgrade_cost(_base) * 2.5

    # Предпросмотр улучшений: суммарная цена N уровней обязана совпадать с суммой
    # пошаговых цен, иначе модалка «Улучшения» покажет не то, что спишет сервер.
    biz = CATALOG_BY_SLUG["coffee"] | {"level": 1, "tuning_value": 0.0}
    plan = _upgrade_plan(biz, UPGRADE_PREVIEW_LEVELS)
    assert len(plan) == UPGRADE_PREVIEW_LEVELS
    assert plan[0]["level"] == 2 and plan[0]["stepCost"] == _upgrade_cost(biz)
    assert abs(plan[-1]["totalCost"] - sum(p["stepCost"] for p in plan)) < 0.01
    # Шаг стоит одинаково на любом уровне (см. _upgrade_cost), а доход и стоимость растут.
    assert all(plan[i]["stepCost"] == plan[i + 1]["stepCost"] for i in range(len(plan) - 1))
    assert all(plan[i]["profitPerHour"] < plan[i + 1]["profitPerHour"] for i in range(len(plan) - 1))
    assert all(plan[i]["value"] < plan[i + 1]["value"] for i in range(len(plan) - 1))
    # План от уровня N совпадает с продолжением плана от уровня 1 — цена не
    # зависит от того, купили уровни за один раз или по одному.
    at3 = _upgrade_plan(biz | {"level": 3}, 2)
    assert at3[0]["level"] == 4
    assert abs(at3[-1]["totalCost"] - (plan[3]["totalCost"] - plan[1]["totalCost"])) < 0.01

    print("assets.py rent formula: OK")
    print(f"  studio(common,$5k)   = ${studio_rate}/сутки")
    print(f"  villa(rare,$160k)    = ${_rent_daily_rate(villa)}/сутки")
    print(f"  castle(legendary,$1.5M) = ${castle_rate}/сутки")


# ── Admin: выдача активов игроку ─────────────────────────────────────────────


class AdminGrantBody(BaseModel):
    slug: str
    quantity: int = 1


@router.get("/admin/catalog")
async def admin_asset_catalog(
    _admin=Depends(require_admin("users_property")),
):
    """Каталог активов для выдачи игрокам из админки."""
    return {"items": [
        {"slug": c["slug"], "name": c["name"], "type": c["type"],
         "category": c.get("category"), "price": c["price"]}
        for c in CATALOG
    ]}


@router.post("/admin/grant/{user_id}")
async def admin_grant_asset(
    user_id: str,
    body: AdminGrantBody,
    _admin=Depends(require_admin("users_property")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Выдать актив игроку бесплатно: без списания денег, записи в ledger
    и влияния на рыночный спрос. Лимиты владения действуют."""
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID пользователя")
    target = await db.users.find_one({"_id": ObjectId(user_id)})
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    catalog = _find_catalog(body.slug) or _fallback_catalog(body.slug)
    if not catalog:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Актив «{body.slug}» не найден в каталоге")
    qty = max(1, min(int(body.quantity or 1), 20))

    granted = 0
    for _ in range(qty):
        try:
            await check_type_limit(db, user_id, catalog["type"])
        except HTTPException:
            if granted == 0:
                raise
            break  # лимит типа достигнут — выдаём сколько влезло
        doc = {
            "userId": user_id,
            "slug": catalog["slug"],
            "type": catalog["type"],
            "name": catalog["name"],
            "category": catalog.get("category"),
            "rarity": catalog.get("rarity"),
            "rooms": catalog.get("rooms"),
            "basement": catalog.get("basement"),
            "employees": catalog.get("employees", 0),
            "price": float(catalog["price"]),
            "price_mult": 1.0,
            "income_per_hour": catalog.get("income_per_hour", 0),
            "upkeep_per_hour": catalog.get("upkeep_per_hour", 0),
            "level": 1,
            "mining": False,
            "meta": catalog.get("meta", {}),
            "companyId": None,
            "rental": None,
            "purchased_at": _now(),
            "last_collected": _now(),
        }
        await db.user_assets.insert_one(doc)
        granted += 1

    if granted:
        try:
            await push_notification(
                db, user_id, "system", "Актив выдан",
                f"Администрация выдала вам «{catalog['name']}»"
                + (f" ×{granted}" if granted > 1 else "") + ".",
            )
        except Exception:
            pass
    return {"granted": granted, "name": catalog["name"]}
