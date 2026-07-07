"""
Demand Aggregator
=================
Агрегация спроса по группам игроков (розница, институционалы, киты).

Для производительности 50 млн игроков не рассчитываются по отдельности.
Вместо этого используется вероятностная модель:
- Цена упала на 5% → вероятность покупки у розницы растёт (ловят дно)
- Цена выросла на 10% → вероятность продажи у китов растёт (фиксация прибыли)

Поддерживает переопределение весов групп и порогов на уровне акции.
"""

import random
from typing import Dict, Tuple

from .config import (
    MAX_BUY_PROBABILITY,
    MAX_SELL_PROBABILITY,
    PLAYER_GROUPS,
    PRICE_DROP_THRESHOLD,
    PRICE_RISE_THRESHOLD,
)


def _clamp_probability(p: float, max_val: float) -> float:
    """Ограничивает вероятность в пределах [0, max_val]."""
    return max(0.0, min(max_val, p))


def _adjust_probability_for_price_change(
    base_prob: float,
    sensitivity: float,
    price_change_percent: float,
    trigger_threshold: float,
) -> float:
    """
    Корректирует вероятность на основе изменения цены.

    Если цена изменилась за порог — добавляем sensitivity * |изменение|.
    """
    if price_change_percent <= trigger_threshold:
        magnitude = abs(price_change_percent - trigger_threshold)
        return base_prob + sensitivity * magnitude
    return base_prob


def compute_group_volumes(
    price_change_percent: float,
    total_active_players: int = 50_000_000,
    player_groups: Dict = None,
    price_drop_threshold: float = PRICE_DROP_THRESHOLD,
    price_rise_threshold: float = PRICE_RISE_THRESHOLD,
    max_buy_probability: float = MAX_BUY_PROBABILITY,
    max_sell_probability: float = MAX_SELL_PROBABILITY,
) -> Dict[str, Dict[str, int]]:
    """
    Вычисляет объёмы покупок/продаж для каждой группы.

    Args:
        price_change_percent: Текущее изменение цены в процентах (например, -0.05)
        total_active_players: Общее количество активных игроков
        player_groups: Кастомные настройки групп (из конфига акции)
        price_drop_threshold: Порог падения для активации "ловли дно"
        price_rise_threshold: Порог роста для фиксации прибыли
        max_buy_probability: Максимальная вероятность покупки
        max_sell_probability: Максимальная вероятность продажи

    Returns:
        Словарь {группа: {"buy": int, "sell": int, ...}}
    """
    if player_groups is None:
        player_groups = PLAYER_GROUPS

    result = {}

    for group_name, group_config in player_groups.items():
        weight = group_config.get("weight", 0.1)

        # Количество игроков в группе
        group_players = int(total_active_players * weight)

        # ── Вероятность покупки ──
        buy_prob = group_config.get("base_buy_probability", 0.01)

        # Если цена упала — розница ловит дно
        if price_change_percent <= price_drop_threshold:
            buy_prob = _adjust_probability_for_price_change(
                buy_prob,
                group_config.get("buy_sensitivity", 0.03),
                price_change_percent,
                price_drop_threshold,
            )

        # Если цена выросла — снижаем желание покупать
        if price_change_percent >= price_rise_threshold:
            reduction = group_config.get("buy_sensitivity", 0.03) * (price_change_percent - price_rise_threshold)
            buy_prob = max(0.0, buy_prob - reduction)

        buy_prob = _clamp_probability(buy_prob, max_buy_probability)

        # ── Вероятность продажи ──
        sell_prob = group_config.get("base_sell_probability", 0.005)

        # Если цена выросла — фиксируем прибыль
        if price_change_percent >= price_rise_threshold:
            sell_prob = _adjust_probability_for_price_change(
                sell_prob,
                group_config.get("sell_sensitivity", 0.05),
                price_change_percent,
                price_rise_threshold,
            )

        # Если цена упала — паника, продают
        if price_change_percent <= price_drop_threshold:
            panic_sell = group_config.get("sell_sensitivity", 0.05) * abs(price_change_percent)
            sell_prob = max(sell_prob, panic_sell)

        sell_prob = _clamp_probability(sell_prob, max_sell_probability)

        # ── Объёмы ──
        # Случайное количество игроков, которые участвуют в такте
        active_in_group = max(1, int(group_players * random.uniform(0.001, 0.01)))

        buy_volume = int(active_in_group * buy_prob * random.uniform(1, 100))
        sell_volume = int(active_in_group * sell_prob * random.uniform(1, 100))

        result[group_name] = {
            "buy": buy_volume,
            "sell": sell_volume,
            "active_players": active_in_group,
            "buy_probability": round(buy_prob, 6),
            "sell_probability": round(sell_prob, 6),
        }

    return result


def aggregate_demand(
    price_change_percent: float,
    total_active_players: int = 50_000_000,
    player_groups: Dict = None,
    price_drop_threshold: float = PRICE_DROP_THRESHOLD,
    price_rise_threshold: float = PRICE_RISE_THRESHOLD,
    max_buy_probability: float = MAX_BUY_PROBABILITY,
    max_sell_probability: float = MAX_SELL_PROBABILITY,
) -> Tuple[int, int, Dict]:
    """
    Агрегирует спрос от всех групп в суммарные Buy_Volume и Sell_Volume.

    Args:
        price_change_percent: Текущее изменение цены
        total_active_players: Общее количество игроков
        player_groups: Кастомные настройки групп
        price_drop_threshold: Порог падения
        price_rise_threshold: Порог роста
        max_buy_probability: Макс. вероятность покупки
        max_sell_probability: Макс. вероятность продажи

    Returns:
        Кортеж (total_buy_volume, total_sell_volume, details_by_group)
    """
    groups = compute_group_volumes(
        price_change_percent,
        total_active_players,
        player_groups,
        price_drop_threshold,
        price_rise_threshold,
        max_buy_probability,
        max_sell_probability,
    )

    total_buy = sum(g["buy"] for g in groups.values())
    total_sell = sum(g["sell"] for g in groups.values())

    return total_buy, total_sell, groups
