"""
Stock Price Calculator
=======================
Ядро математической модели ценообразования акций.

Формула (Вариант А — дисбаланс объёмов):
    ΔP = Price * K * ((Buy_Volume - Sell_Volume) / Total_Supply)

Итоговая цена:
    Final_Price = (Price + ΔP) * Event_Multiplier

Поддерживает переопределение total_shares и volatility_k на уровне акции.
"""

from typing import Tuple

from .config import (
    MAX_PRICE,
    MIN_PRICE,
    TOTAL_SHARES,
    VOLATILITY_K,
)


def calculate_price_change(
    current_price: float,
    buy_volume: int,
    sell_volume: int,
    total_shares: int = TOTAL_SHARES,
    volatility_k: float = VOLATILITY_K,
) -> float:
    """
    Вычисляет изменение цены на основе дисбаланса объёмов.

    Args:
        current_price: Текущая цена акции
        buy_volume: Количество акций на покупку за такт
        sell_volume: Количество акций на продажу за такт
        total_shares: Общее количество акций (из конфига акции)
        volatility_k: Коэффициент волатильности (из конфига акции)

    Returns:
        Изменение цены (может быть отрицательным)
    """
    net_volume = buy_volume - sell_volume
    delta = current_price * volatility_k * (net_volume / total_shares)
    return delta


def apply_event_multiplier(price: float, event_multiplier: float) -> float:
    """
    Применяет множитель случайного события к цене.

    Args:
        price: Цена до применения события
        event_multiplier: Множитель из RANDOM_EVENTS

    Returns:
        Цена после применения события
    """
    return price * event_multiplier


def clamp_price(price: float, min_price: float = MIN_PRICE, max_price: float = MAX_PRICE) -> float:
    """
    Ограничивает цену в допустимых пределах.

    Args:
        price: Цена для проверки
        min_price: Минимальная цена (из конфига акции)
        max_price: Максимальная цена (из конфига акции)

    Returns:
        Цена в пределах [min_price, max_price]
    """
    return max(min_price, min(max_price, price))


def compute_new_price(
    current_price: float,
    buy_volume: int,
    sell_volume: int,
    event_multiplier: float = 1.0,
    total_shares: int = TOTAL_SHARES,
    volatility_k: float = VOLATILITY_K,
    min_price: float = MIN_PRICE,
    max_price: float = MAX_PRICE,
) -> Tuple[float, float]:
    """
    Полный расчёт новой цены.

    Args:
        current_price: Текущая цена
        buy_volume: Объём покупок
        sell_volume: Объём продаж
        event_multiplier: Множитель события (1.0 = без события)
        total_shares: Общее количество акций (из конфига акции)
        volatility_k: Коэффициент волатильности (из конфига акции)
        min_price: Минимальная цена
        max_price: Максимальная цена

    Returns:
        Кортеж (новая_цена, изменение_цены)
    """
    # Шаг 1: Дисбаланс объёмов
    delta = calculate_price_change(current_price, buy_volume, sell_volume, total_shares, volatility_k)

    # Шаг 2: Применяем изменение
    new_price = current_price + delta

    # Шаг 3: Применяем событие
    new_price = apply_event_multiplier(new_price, event_multiplier)

    # Шаг 4: Клиппинг
    new_price = clamp_price(new_price, min_price, max_price)

    return round(new_price, 4), round(delta, 6)


def calculate_initial_price(capitalization: float, total_shares: int) -> float:
    """
    Вычисляет начальную цену через капитализацию.

    Args:
        capitalization: Желаемая капитализация ($)
        total_shares: Общее количество акций

    Returns:
        Начальная цена за акцию
    """
    if total_shares <= 0:
        raise ValueError("total_shares must be positive")
    price = capitalization / total_shares
    return round(clamp_price(price), 4)
