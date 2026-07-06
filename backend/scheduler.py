"""Единый планировщик фоновых задач (Scheduler).

Один asyncio-цикл вместо отдельных циклов на каждую систему. На каждом тике:
- обновление реального рынка (крипта CoinGecko, акции Finnhub/TwelveData);
- динамический рынок активов + мировые события (внутри дрейфа);
- начисление аренды;
- тик майнинг-ферм.

Запускается в lifespan приложения, корректно останавливается при завершении.
"""
import asyncio
import logging
import os

from database import get_db
import assets
import mining
import crypto
import stocks
from ws import broadcast

logger = logging.getLogger("tradeverse.scheduler")

SCHEDULER_INTERVAL_S = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "60"))

_task: asyncio.Task | None = None


async def _tick():
    db = get_db()
    # 1) Обслуживание рынков: реальные цены, симуляция-fallback, история, снимки.
    #    Вся тяжёлая работа живёт здесь — читающие эндпоинты только берут кэш из БД.
    try:
        await crypto.maintain_crypto_market(db)
    except Exception as exc:
        logger.debug("crypto market maintain skipped: %s", exc)
    try:
        await stocks.maintain_stock_market(db)
    except Exception as exc:
        logger.debug("stock market maintain skipped: %s", exc)
    # 2) Динамический рынок активов + мировые события.
    try:
        await assets.tick_market(db)
    except Exception as exc:
        logger.debug("asset market tick failed: %s", exc)
    # 3) Аренда (заселение/выплаты).
    try:
        await assets.sweep_rentals(db)
    except Exception as exc:
        logger.debug("rental sweep failed: %s", exc)
    # 4) Майнинг-фермы.
    try:
        await mining.tick_all(db)
    except Exception as exc:
        logger.debug("mining tick failed: %s", exc)


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
