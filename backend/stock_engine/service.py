"""
StockEngine Service
===================
Бизнес-логика торговли акциями.

Объединяет:
- Расчёт цены (price_calculator)
- Агрегацию спроса (demand_aggregator)
- Случайные события (random_events)
- Валидацию ордеров
"""

import random
from datetime import datetime, timezone
from typing import Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorDatabase

from .config import INITIAL_PRICE, MAX_ORDER_SIZE_PERCENT, MAX_SHARES_PERCENT, MIN_ORDER_SIZE, TOTAL_SHARES, get_stock_config
from .db import (
    create_order,
    create_stock,
    find_orders_by_user,
    find_portfolio,
    find_stock_by_symbol,
    find_all_stocks,
    log_event,
    update_free_shares,
    update_stock_config,
    update_stock_price,
    upsert_portfolio_holding,
)
from .demand_aggregator import aggregate_demand
from .price_calculator import compute_new_price
from .random_events import roll_event


class StockService:
    """Сервис для операций с акциями."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    # ── Stock Management ────────────────────────────────────────────────────

    async def get_all_stocks(self) -> list[dict]:
        """Возвращает все акции."""
        return await find_all_stocks(self.db)

    async def get_stock(self, symbol: str) -> Optional[dict]:
        """Возвращает акцию по тикеру."""
        return await find_stock_by_symbol(self.db, symbol)

    async def create_new_stock(
        self,
        symbol: str,
        name: str,
        price: float = INITIAL_PRICE,
        total_shares: int = TOTAL_SHARES,
        free_shares: Optional[int] = None,
        config_overrides: Optional[dict] = None,
    ) -> dict:
        """Создаёт новую акцию."""
        stock_data = {
            "symbol": symbol.upper(),
            "name": name,
            "price": price,
            "change": 0.0,
            "changePercent": 0.0,
            "currency": "USD",
            "total_shares": total_shares,
            "free_shares": free_shares if free_shares is not None else total_shares,
            "market_cap": price * total_shares,
            "volatility_k": 0.1,
        }
        if config_overrides:
            stock_data["config_overrides"] = config_overrides
        return await create_stock(self.db, stock_data)

    async def update_stock_config(
        self,
        symbol: str,
        config_overrides: dict,
    ) -> dict:
        """
        Обновляет переопределения конфига для конкретной акции.

        Args:
            symbol: Тикер акции
            config_overrides: Словарь с переопределениями (volatility_k, total_shares, etc.)

        Returns:
            Обновлённый документ акции
        """
        from .config import validate_stock_config

        errors = validate_stock_config(config_overrides)
        if errors:
            raise ValueError(f"Ошибка валидации конфига: {'; '.join(errors)}")

        return await update_stock_config(self.db, symbol, config_overrides)

    # ── Trading ──────────────────────────────────────────────────────────────

    async def execute_trade(
        self,
        user_id: str,
        symbol: str,
        action: str,
        quantity: int,
    ) -> dict:
        """
        Выполняет покупку или продажу акций.

        Args:
            user_id: ID пользователя
            symbol: Тикер акции
            action: "buy" или "sell"
            quantity: Количество акций

        Returns:
            Результат сделки с информацией о цене
        """
        # Валидация
        if action not in ("buy", "sell"):
            raise ValueError("action должен быть 'buy' или 'sell'")

        if quantity < MIN_ORDER_SIZE:
            raise ValueError(f"Минимальный ордер: {MIN_ORDER_SIZE} акция")

        # Загружаем акцию
        stock = await find_stock_by_symbol(self.db, symbol)
        if not stock:
            raise ValueError(f"Акция '{symbol}' не найдена")

        current_price = stock["price"]
        free_shares = stock.get("free_shares", 0)

        # Проверяем лимит на размер ордера
        max_order = int(free_shares * MAX_ORDER_SIZE_PERCENT)
        if quantity > max_order:
            quantity = max_order

        # Проверяем достаточно ли свободных акций для покупки
        if action == "buy" and quantity > free_shares:
            if free_shares <= 0:
                raise ValueError("Нет свободных акций для покупки")
            quantity = free_shares

        # Проверяем ограничение на максимальное количество акций у игрока
        if action == "buy" and user_id != "BOT":
            total_shares = stock.get("total_shares", TOTAL_SHARES)
            max_shares_per_user = int(total_shares * MAX_SHARES_PERCENT)

            # Считаем текущее количество акций у пользователя
            portfolio = await find_portfolio(self.db, user_id)
            current_user_shares = 0
            if portfolio:
                for holding in portfolio.get("holdings", []):
                    if holding["symbol"] == symbol.upper():
                        current_user_shares = holding["quantity"]
                        break

            if current_user_shares + quantity > max_shares_per_user:
                allowed = max(0, max_shares_per_user - current_user_shares)
                raise ValueError(
                    f"Превышен лимит акций. Максимум: {max_shares_per_user} "
                    f"({MAX_SHARES_PERCENT*100}% от общего количества). "
                    f"У вас уже: {current_user_shares}, можно купить ещё: {allowed}"
                )

        # Рассчитываем стоимость
        total_cost = current_price * quantity

        # Проверяем баланс пользователя (для покупки)
        if action == "buy":
            user = await self.db.users.find_one({"_id": __import__("bson").ObjectId(user_id)})
            if not user:
                raise ValueError("Пользователь не найден")

            user_balance = user.get("balance", 0)
            if user_balance < total_cost:
                raise ValueError(
                    f"Недостаточно средств. Нужно: ${total_cost:.2f}, "
                    f"на счету: ${user_balance:.2f}"
                )

            # Списываем средства
            await self.db.users.update_one(
                {"_id": __import__("bson").ObjectId(user_id)},
                {"$inc": {"balance": -total_cost}},
            )
        else:
            # Продажа: проверяем наличие акций в портфеле
            portfolio = await find_portfolio(self.db, user_id)
            if portfolio:
                holdings = portfolio.get("holdings", [])
                holding = next((h for h in holdings if h["symbol"] == symbol.upper()), None)
                if not holding or holding["quantity"] < quantity:
                    available = holding["quantity"] if holding else 0
                    raise ValueError(
                        f"Недостаточно акций для продажи. "
                        f"Доступно: {available}, запрошено: {quantity}"
                    )

            # Зачисляем средства
            await self.db.users.update_one(
                {"_id": __import__("bson").ObjectId(user_id)},
                {"$inc": {"balance": total_cost}},
            )

        # Создаём ордер
        order = await create_order(self.db, {
            "userId": user_id,
            "symbol": symbol.upper(),
            "action": action,
            "quantity": quantity,
            "price": current_price,
            "total": total_cost,
        })

        # Обновляем портфель
        await upsert_portfolio_holding(
            self.db,
            user_id,
            symbol.upper(),
            stock["name"],
            quantity,
            current_price,
            is_buy=(action == "buy"),
        )

        # Обновляем свободные акции
        if action == "buy":
            await update_free_shares(self.db, symbol, quantity)
        else:
            # При продаже акции возвращаются в пул
            await update_free_shares(self.db, symbol, -quantity)

        # Получаем конфиг акции (с переопределениями)
        stock_config = get_stock_config(stock)

        # Рассчитываем новую цену на основе ордера
        # (ордер создаёт дисбаланс: покупка = +спрос, продажа = +предложение)
        if action == "buy":
            buy_volume = quantity
            sell_volume = 0
        else:
            buy_volume = 0
            sell_volume = quantity

        # Добавляем фоновый спрос от других игроков (с кастомными настройками акции)
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

        # Случайное событие (с кастомными событиями акции)
        event_key, event_multiplier, event_label = roll_event(
            custom_events=stock_config["random_events"],
        )

        # Вычисляем новую цену (с кастым volatility_k и total_shares)
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

        # Формируем ответ
        order["price_per_share"] = current_price
        order["total_cost"] = round(total_cost, 2)
        order["new_stock_price"] = new_price
        order["event_applied"] = event_label if event_key != "none" else None

        return order

    # ── Portfolio ────────────────────────────────────────────────────────────

    async def get_portfolio(self, user_id: str) -> Optional[dict]:
        """Возвращает портфель пользователя с текущей стоимостью."""
        portfolio = await find_portfolio(self.db, user_id)
        if not portfolio:
            return None

        # Обновляем текущие цены и считаем стоимость
        total_value = 0.0
        total_invested = 0.0

        for item in portfolio.get("holdings", []):
            stock = await find_stock_by_symbol(self.db, item["symbol"])
            if stock:
                current_price = stock["price"]
                item["current_price"] = current_price
                item["total_value"] = round(current_price * item["quantity"], 2)
                item["profit_loss"] = round(
                    (current_price - item["average_buy_price"]) * item["quantity"], 2
                )
                item["profit_loss_percent"] = round(
                    ((current_price - item["average_buy_price"]) / item["average_buy_price"]) * 100, 2
                ) if item["average_buy_price"] > 0 else 0.0

                total_value += item["total_value"]
                total_invested += item["average_buy_price"] * item["quantity"]
            else:
                item["current_price"] = item["average_buy_price"]
                item["total_value"] = item["average_buy_price"] * item["quantity"]
                item["profit_loss"] = 0.0
                item["profit_loss_percent"] = 0.0
                total_value += item["total_value"]
                total_invested += item["average_buy_price"] * item["quantity"]

        portfolio["total_value"] = round(total_value, 2)
        portfolio["total_invested"] = round(total_invested, 2)
        portfolio["total_profit_loss"] = round(total_value - total_invested, 2)
        portfolio["user_id"] = portfolio.get("userId", "")

        return portfolio

    # ── Order History ────────────────────────────────────────────────────────

    async def get_user_orders(self, user_id: str, limit: int = 50) -> list[dict]:
        """Возвращает историю ордеров пользователя."""
        return await find_orders_by_user(self.db, user_id, limit)

    # ── Events ───────────────────────────────────────────────────────────────

    async def get_recent_events(self, symbol: Optional[str] = None, limit: int = 20) -> list[dict]:
        """Возвращает последние рыночные события."""
        from .db import find_recent_events
        return await find_recent_events(self.db, symbol, limit)
