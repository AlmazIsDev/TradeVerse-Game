"""
Bot Trader System
==================
Система автоматических ботов-трейдеров.

Логика:
- Количество ботов = количество акций / 2 (целое число)
- Каждые N секунд боты покупают/продают случайные акции
- Одна акция не может быть куплена/продана дважды за один раунд
- Количество акций для сделки зависит от текущего количества свободных акций

Формула расчёта количества:
- min_shares = max(BOT_TRADE_MIN_SHARES, free_shares * 0.001)
- max_shares = free_shares * BOT_TRADE_MAX_PERCENT
- quantity = random(min_shares, max_shares)
"""

import asyncio
import random
import logging
from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from .config import (
    BOT_TRADING_ENABLED,
    BOT_TRADING_INTERVAL,
    BOT_TRADE_MIN_SHARES,
    BOT_TRADE_MAX_PERCENT,
)
from .db import find_all_stocks, find_stock_by_symbol, update_stock_price, log_event
from .demand_aggregator import aggregate_demand
from .price_calculator import compute_new_price
from .random_events import roll_event
from .config import get_stock_config

logger = logging.getLogger(__name__)


class BotTrader:
    """Система ботов-трейдеров."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._used_symbols_this_round: set[str] = set()

    async def start(self):
        """Запускает цикл ботов."""
        if not BOT_TRADING_ENABLED:
            logger.info("[BotTrader] Система ботов отключена в конфигурации")
            return

        if self._running:
            logger.warning("[BotTrader] Уже запущен")
            return

        self._running = True
        self._task = asyncio.create_task(self._trading_loop())
        logger.info("[BotTrader] Запущен с интервалом %s сек", BOT_TRADING_INTERVAL)

    async def stop(self):
        """Останавливает цикл ботов."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[BotTrader] Остановлен")

    async def _trading_loop(self):
        """Основной цикл торговли."""
        while self._running:
            try:
                await self._execute_round()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[BotTrader] Ошибка в раунде: %s", e)

            await asyncio.sleep(BOT_TRADING_INTERVAL)

    async def _execute_round(self):
        """Выполняет один раунд торговли."""
        stocks = await find_all_stocks(self.db)
        if len(stocks) < 2:
            return

        # Количество ботов = количество акций / 2
        num_bots = max(1, len(stocks) // 2)

        # Сбрасываем использованные символы
        self._used_symbols_this_round.clear()

        # Выбираем случайные акции для ботов
        available_stocks = stocks.copy()
        random.shuffle(available_stocks)

        trades_made = 0
        for i in range(min(num_bots, len(available_stocks))):
            stock = available_stocks[i]
            symbol = stock["symbol"]

            if symbol in self._used_symbols_this_round:
                continue

            # Определяем действие (покупка/продажа)
            action = random.choice(["buy", "sell"])

            # Рассчитываем количество
            quantity = await self._calculate_trade_quantity(stock, action)
            if quantity < BOT_TRADE_MIN_SHARES:
                continue

            # Выполняем сделку
            success = await self._execute_bot_trade(symbol, action, quantity)
            if success:
                self._used_symbols_this_round.add(symbol)
                trades_made += 1

        if trades_made > 0:
            logger.info("[BotTrader] Раунд завершён: %d сделок", trades_made)

    async def _calculate_trade_quantity(self, stock: dict, action: str) -> int:
        """
        Рассчитывает количество акций для сделки бота.

        Формула:
        - min_shares = max(BOT_TRADE_MIN_SHARES, free_shares * 0.001)
        - max_shares = free_shares * BOT_TRADE_MAX_PERCENT
        - quantity = random(min_shares, max_shares)
        """
        free_shares = stock.get("free_shares", 0)
        total_shares = stock.get("total_shares", 1_000_000_000)

        if action == "buy":
            # При покупке рим свободные акции
            if free_shares <= 0:
                return 0

            min_shares = max(BOT_TRADE_MIN_SHARES, int(free_shares * 0.001))
            max_shares = max(min_shares + 1, int(free_shares * BOT_TRADE_MAX_PERCENT))

            # Ограничиваем максимумом свободных акций
            max_shares = min(max_shares, free_shares)

        else:
            # При продаже смотрим общий объём (боты "выпускают" акции обратно)
            min_shares = max(BOT_TRADE_MIN_SHARES, int(total_shares * 0.0005))
            max_shares = max(min_shares + 1, int(total_shares * BOT_TRADE_MAX_PERCENT * 0.5))

        if min_shares >= max_shares:
            return min_shares

        return random.randint(min_shares, max_shares)

    async def _execute_bot_trade(self, symbol: str, action: str, quantity: int) -> bool:
        """Выполняет сделку от имени бота."""
        try:
            stock = await find_stock_by_symbol(self.db, symbol)
            if not stock:
                return False

            current_price = stock["price"]
            total_cost = current_price * quantity

            # Создаём ордер бота
            await self.db.stock_orders.insert_one({
                "userId": "BOT",
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "price": current_price,
                "total": total_cost,
                "timestamp": datetime.now(timezone.utc),
                "status": "completed",
                "is_bot": True,
            })

            # Обновляем свободные акции
            if action == "buy":
                await self.db.stocks.update_one(
                    {"symbol": symbol},
                    {"$inc": {"free_shares": -quantity}},
                )
            else:
                await self.db.stocks.update_one(
                    {"symbol": symbol},
                    {"$inc": {"free_shares": quantity}},
                )

            # Получаем конфиг акции (с переопределениями)
            stock_config = get_stock_config(stock)

            # Рассчитываем объёмы: действие бота + фоновый спрос
            if action == "buy":
                buy_volume = quantity
                sell_volume = 0
            else:
                buy_volume = 0
                sell_volume = quantity

            # Добавляем фоновый спрос
            price_change_pct = stock.get("changePercent", 0.0) / 100.0 if stock.get("changePercent") else 0.0
            bg_buy, bg_sell, _ = aggregate_demand(
                price_change_pct,
                total_active_players=50_000_000,
                player_groups=stock_config["player_groups"],
                price_drop_threshold=stock_config["price_drop_threshold"],
                price_rise_threshold=stock_config["price_rise_threshold"],
                max_buy_probability=stock_config["max_buy_probability"],
                max_sell_probability=stock_config["max_sell_probability"],
            )

            total_buy = buy_volume + bg_buy
            total_sell = sell_volume + bg_sell

            # Случайное событие
            event_key, event_multiplier, event_label = roll_event(
                custom_events=stock_config["random_events"],
            )

            # Вычисляем новую цену
            new_price, price_delta = compute_new_price(
                current_price,
                total_buy,
                total_sell,
                event_multiplier,
                total_shares=stock_config["total_shares"],
                volatility_k=stock_config["volatility_k"],
                min_price=stock_config["min_price"],
                max_price=stock_config["max_price"],
            )

            # Рассчитываем изменение в процентах
            if current_price > 0:
                change_percent = round(((new_price - current_price) / current_price) * 100, 4)
            else:
                change_percent = 0.0

            # Обновляем цену в БД
            await update_stock_price(
                self.db,
                symbol,
                new_price,
                round(new_price - current_price, 4),
                change_percent,
                event_label if event_key != "none" else None,
            )

            # Логируем событие
            if event_key != "none":
                await log_event(
                    self.db,
                    symbol,
                    event_key,
                    event_label,
                    event_multiplier,
                    current_price,
                    new_price,
                )

            return True

        except Exception as e:
            logger.error("[BotTrader] Ошибка сделки %s %s: %s", symbol, action, e)
            return False


# Глобальный экземпляр
_bot_trader: Optional[BotTrader] = None


async def start_bot_trading(db: AsyncIOMotorDatabase):
    """Запускает систему ботов."""
    global _bot_trader
    _bot_trader = BotTrader(db)
    await _bot_trader.start()


async def stop_bot_trading():
    """Останавливает систему ботов."""
    global _bot_trader
    if _bot_trader:
        await _bot_trader.stop()
        _bot_trader = None