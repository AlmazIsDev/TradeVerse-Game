"""
StockEngine Configuration
===========================
Центральная конфигурация математической модели акций TradeVerse.

Два уровня настройки:
1. Глобальные дефолты (константы ниже) — используются если акция не имеет своих переопределений
2. Переопределения на уровне акции (поля в документе MongoDB: config_overrides)

Для кастомизации конкретной акции используйте:
    await db.update_stock_config(symbol, {"volatility_k": 0.2, "total_shares": 500_000_000})
"""

from typing import Any, Dict, Optional


# ── Initial Price ──────────────────────────────────────────────────────────────

TOTAL_SHARES = 1_000_000_000  # Общее количество акций (1 млрд)
INITIAL_CAPITALIZATION = 10_000_000_000.0  # $10 млрд — желаемая капитализация
INITIAL_PRICE = INITIAL_CAPITALIZATION / TOTAL_SHARES  # $10.00

# ── Volatility (Formula Variant A) ──────────────────────────────────────────────

VOLATILITY_K = 0.1  # Коэффициент волатильности (скорость изменения цены)

# ── Demand Aggregator ──────────────────────────────────────────────────────────

# Группы игроков и их доли в общем объёме
PLAYER_GROUPS = {
    "retail": {
        "weight": 0.60,  # 60% объёма — розница
        "buy_sensitivity": 0.05,  # Чувствительность к падению цены (% для смены вероятности)
        "sell_sensitivity": 0.08,  # Чувствительность к росту цены
        "base_buy_probability": 0.02,  # Базовая вероятность покупки за такт
        "base_sell_probability": 0.01,  # Базовая вероятность продажи за такт
    },
    "institutional": {
        "weight": 0.30,  # 30% объёма — институционалы
        "buy_sensitivity": 0.03,
        "sell_sensitivity": 0.05,
        "base_buy_probability": 0.01,
        "base_sell_probability": 0.005,
    },
    "whale": {
        "weight": 0.10,  # 10% объёма — киты
        "buy_sensitivity": 0.02,
        "sell_sensitivity": 0.10,  # Киты агрессивно фиксируют прибыль
        "base_buy_probability": 0.005,
        "base_sell_probability": 0.002,
    },
}

# Пороги изменения цены для активации поведения (%)
PRICE_DROP_THRESHOLD = -0.05  # -5% → розница ловит дно
PRICE_RISE_THRESHOLD = 0.10  # +10% → киты фиксируют прибыль

# Максимальная вероятность покупки/продажи за такт (клиппинг)
MAX_BUY_PROBABILITY = 0.15
MAX_SELL_PROBABILITY = 0.10

# ── Random Events ──────────────────────────────────────────────────────────────

# Случайные события с весами (должны суммироваться в 1.0)
RANDOM_EVENTS = {
    "none": {
        "weight": 0.85,
        "multiplier_range": (1.0, 1.0),  # Без изменений
        "label": "Нет события",
    },
    "good_news": {
        "weight": 0.08,
        "multiplier_range": (1.02, 1.05),  # +2-5%
        "label": "Хорошая новость",
    },
    "scandal": {
        "weight": 0.04,
        "multiplier_range": (0.90, 0.95),  # -5-10%
        "label": "Скандал",
    },
    "market_crash": {
        "weight": 0.02,
        "multiplier_range": (0.80, 0.88),  # -12-20%
        "label": "Обвал рынка",
    },
    "moon": {
        "weight": 0.01,
        "multiplier_range": (1.10, 1.20),  # +10-20%
        "label": "🚀 На луну!",
    },
}

# ── Trading Limits ─────────────────────────────────────────────────────────────

MIN_ORDER_SIZE = 1  # Минимальный ордер (акции)
MAX_ORDER_SIZE_PERCENT = 0.01  # Макс. ордер = 1% от свободных акций
MAX_SHARES_PERCENT = 0.05  # Макс. акций у одного игрока = 5% от общего количества

# ── Price Bounds ───────────────────────────────────────────────────────────────

MIN_PRICE = 0.01  # Минимальная цена (не может упасть ниже)
MAX_PRICE = 10_000.0  # Максимальная цена (защита от overflow)

# ── Bot Trading ────────────────────────────────────────────────────────────────

BOT_TRADING_ENABLED = True  # Включена ли система ботов
BOT_TRADING_INTERVAL = 5  # Интервал между сделками ботов (секунды)
BOT_TRADE_MIN_SHARES = 10  # Мин. количество акций для сделки бота
BOT_TRADE_MAX_PERCENT = 0.005  # Макс. % от свободных акций за одну сделку бота


# ── Per-Stock Config Override ──────────────────────────────────────────────────

def get_stock_config(stock: dict) -> dict:
    """
    Возвращает итоговый конфиг для конкретной акции.

    Мержит глобальные дефолты с config_overrides из документа акции.
    Любое поле можно переопределить для конкретной акции.

    Args:
        stock: Документ акции из MongoDB

    Returns:
        Словарь с итоговыми настройками:
        - total_shares
        - volatility_k
        - player_groups (веса, чувствительности)
        - price_drop_threshold
        - price_rise_threshold
        - max_buy_probability
        - max_sell_probability
        - random_events (веса и диапазоны)
        - min_order_size
        - max_order_size_percent
        - min_price
        - max_price
    """
    overrides = stock.get("config_overrides", {})

    return {
        "total_shares": overrides.get("total_shares", TOTAL_SHARES),
        "volatility_k": overrides.get("volatility_k", VOLATILITY_K),
        "player_groups": overrides.get("player_groups", PLAYER_GROUPS),
        "price_drop_threshold": overrides.get("price_drop_threshold", PRICE_DROP_THRESHOLD),
        "price_rise_threshold": overrides.get("price_rise_threshold", PRICE_RISE_THRESHOLD),
        "max_buy_probability": overrides.get("max_buy_probability", MAX_BUY_PROBABILITY),
        "max_sell_probability": overrides.get("max_sell_probability", MAX_SELL_PROBABILITY),
        "random_events": overrides.get("random_events", RANDOM_EVENTS),
        "min_order_size": overrides.get("min_order_size", MIN_ORDER_SIZE),
        "max_order_size_percent": overrides.get("max_order_size_percent", MAX_ORDER_SIZE_PERCENT),
        "min_price": overrides.get("min_price", MIN_PRICE),
        "max_price": overrides.get("max_price", MAX_PRICE),
    }


def validate_stock_config(config: dict) -> list[str]:
    """
    Валидирует переопределения конфига акции.

    Returns:
        Список ошибок (пустой = всё ок)
    """
    errors = []

    if "volatility_k" in config:
        v = config["volatility_k"]
        if not (0.001 <= v <= 1.0):
            errors.append("volatility_k должен быть в диапазоне [0.001, 1.0]")

    if "total_shares" in config:
        v = config["total_shares"]
        if v <= 0:
            errors.append("total_shares должен быть > 0")

    if "player_groups" in config:
        groups = config["player_groups"]
        if not isinstance(groups, dict):
            errors.append("player_groups должен быть объектом")
        else:
            total_weight = sum(g.get("weight", 0) for g in groups.values())
            if not (0.99 <= total_weight <= 1.01):
                errors.append(f"Сумма весов player_groups должна быть 1.0 (сейчас: {total_weight})")
            for name, group in groups.items():
                for field in ("buy_sensitivity", "sell_sensitivity", "base_buy_probability", "base_sell_probability"):
                    if field in group and not (0 <= group[field] <= 1):
                        errors.append(f"{name}.{field} должен быть в диапазоне [0, 1]")

    if "price_drop_threshold" in config:
        v = config["price_drop_threshold"]
        if not (-0.5 <= v <= 0):
            errors.append("price_drop_threshold должен быть в диапазоне [-0.5, 0]")

    if "price_rise_threshold" in config:
        v = config["price_rise_threshold"]
        if not (0 <= v <= 1.0):
            errors.append("price_rise_threshold должен быть в диапазоне [0, 1.0]")

    if "random_events" in config:
        events = config["random_events"]
        if not isinstance(events, dict):
            errors.append("random_events должен быть объектом")
        else:
            total_weight = sum(e.get("weight", 0) for e in events.values())
            if not (0.99 <= total_weight <= 1.01):
                errors.append(f"Сумма весов random_events должна быть 1.0 (сейчас: {total_weight})")

    if "max_order_size_percent" in config:
        v = config["max_order_size_percent"]
        if not (0.001 <= v <= 0.5):
            errors.append("max_order_size_percent должен быть в диапазоне [0.001, 0.5]")

    if "min_price" in config:
        v = config["min_price"]
        if v <= 0:
            errors.append("min_price должен быть > 0")

    if "max_price" in config:
        v = config["max_price"]
        if v <= 0:
            errors.append("max_price должен быть > 0")

    return errors
