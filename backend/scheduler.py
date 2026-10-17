"""Единый планировщик: один общий asyncio-цикл, не по циклу на подсистему.
Тик каждые SCHEDULER_INTERVAL_S с; запуск в lifespan, корректная остановка.
Состав работ тика — по пронумерованным комментариям в _tick()."""
from __future__ import annotations

from typing import Optional

import asyncio
import logging
import os

from database import get_db
import assets
import mining
import crypto
import stocks
import cityroof
import econ
import media
from ws import broadcast, push_to_admins

logger = logging.getLogger("tradeverse.scheduler")

SCHEDULER_INTERVAL_S = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "60"))

_task: Optional[asyncio.Task] = None


async def _tick():
    db = get_db()
    # 1) Обслуживание рынков: реальные цены, симуляция-fallback, история, снимки.
    #    Вся тяжёлая работа живёт здесь — читающие эндпоинты только берут кэш из БД.
    try:
        await crypto.maintain_crypto_market(db)
    except Exception as exc:
        logger.warning("crypto market maintain skipped: %s", exc, exc_info=True)
    try:
        await stocks.maintain_stock_market(db)
    except Exception as exc:
        logger.warning("stock market maintain skipped: %s", exc, exc_info=True)
    # 2) Динамический рынок активов + мировые события.
    try:
        await assets.tick_market(db)
    except Exception as exc:
        logger.warning("asset market tick failed: %s", exc, exc_info=True)
    # 3) Аренда (заселение/выплаты).
    try:
        await assets.sweep_rentals(db)
    except Exception as exc:
        logger.warning("rental sweep failed: %s", exc, exc_info=True)
    # 4) Майнинг-фермы.
    try:
        await mining.tick_all(db)
    except Exception as exc:
        logger.warning("mining tick failed: %s", exc, exc_info=True)
    # 4b) Производство: источники/пекарня/фуры (см. production.py).
    try:
        from production import tick as production_tick
        await production_tick(db)
    except Exception as exc:
        logger.warning("production tick failed: %s", exc, exc_info=True)
    # 5) Крыша города: автосбор дохода со зданий (персональный КД у бизнеса).
    try:
        await cityroof.sweep_business_income(db)
    except Exception as exc:
        logger.warning("cityroof income sweep failed: %s", exc, exc_info=True)
    # 5b) Крыша города: завершение готовых заказов IT-студии (снижение защиты).
    try:
        await cityroof.sweep_itstudio_jobs(db)
    except Exception as exc:
        logger.warning("cityroof itstudio sweep failed: %s", exc, exc_info=True)
    # 5c) СМИ: выход «созревших» разоблачений (готовились 15 мин–2 ч).
    try:
        await media.sweep_pending_exposes(db)
    except Exception as exc:
        logger.warning("media expose sweep failed: %s", exc, exc_info=True)
    # 6) Аналитика экономики — только админам (не всем игрокам), для живого
    #    обновления вкладки EconomyAdmin без ручного релоада.
    try:
        stats = await econ.compute_analytics(db)
        await push_to_admins(db, {"type": "economy_stats", "stats": stats})
    except Exception as exc:
        logger.warning("economy stats push failed: %s", exc, exc_info=True)
    # 7) Лидерборд: тяжёлый расчёт капитала (aggregate по ledger'у на 1M+
    #    записей) делаем здесь, чтобы GET /api/leaderboard всегда читал
    #    тёплый кэш и ни один игрок не ждал 5–12 с.
    try:
        from main import refresh_leaderboard_cache
        await refresh_leaderboard_cache(db)
    except Exception as exc:
        logger.warning("leaderboard cache refresh failed: %s", exc)
    # 7b) Дрейф цен рынка активов: тяжёлый проход по user_assets/users/ledger
    #     (раз в 60 с) греем здесь, чтобы GET /api/assets/market не платил
    #     за тик внутри своего запроса — в пути запроса остаётся только
    #     дешёвый early-return по таймстемпу тика.
    try:
        from assets import _ensure_asset_market, _drift_asset_market
        await _ensure_asset_market(db)
        await _drift_asset_market(db)
    except Exception as exc:
        logger.warning("asset market drift failed: %s", exc)
    try:
        await broadcast({"type": "leaderboard_update"})
    except Exception as exc:
        logger.warning("leaderboard broadcast failed: %s", exc, exc_info=True)


async def _loop():
    logger.info("Scheduler запущен (интервал %ss)", SCHEDULER_INTERVAL_S)
    while True:
        try:
            await _tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Ошибка тика планировщика: %s", exc)
        try:
            await asyncio.sleep(SCHEDULER_INTERVAL_S)
        except asyncio.CancelledError:
            raise


def start_scheduler():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop_scheduler():
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
        _task = None
