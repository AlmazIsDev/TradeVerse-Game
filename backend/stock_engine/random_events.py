"""
Random Events Engine
=====================
Система случайных рыночных событий.

К рассчитанной цене добавляется множитель:
    Final_Price = Calculated_Price * Event_Multiplier

События выбираются взвешенно из конфига.
Поддерживает переопределение событий на уровне акции.
"""

import random
from typing import Dict, Optional, Tuple

from .config import RANDOM_EVENTS


def roll_event(
    custom_events: Optional[Dict] = None,
) -> Tuple[str, float, str]:
    """
    Бросает кубик и возвращает случайное событие.

    Args:
        custom_events: Кастомные события (из конфига акции). Если None — используются глобальные.

    Returns:
        Кортеж (event_key, multiplier, label)
    """
    events = custom_events if custom_events is not None else RANDOM_EVENTS

    # Взвешенный выбор
    event_items = list(events.items())
    weights = [e[1].get("weight", 0) for e in event_items]

    # Нормализация весов (на случай, если не суммируются в 1.0)
    total_weight = sum(weights)
    if total_weight <= 0:
        return "none", 1.0, ""

    normalized_weights = [w / total_weight for w in weights]

    chosen_key = random.choices([e[0] for e in event_items], weights=normalized_weights, k=1)[0]
    chosen_event = events[chosen_key]

    # Случайный множитель в диапазоне события
    multiplier_range = chosen_event.get("multiplier_range", (1.0, 1.0))
    low, high = multiplier_range[0], multiplier_range[1]
    multiplier = round(random.uniform(low, high), 4)

    label = chosen_event.get("label", chosen_key)

    return chosen_key, multiplier, label


def get_event_multiplier_only(custom_events: Optional[Dict] = None) -> float:
    """
    Возвращает только множитель события (для случаев, когда не нужен лейбл).

    Returns:
        Множитель (1.0 = без события)
    """
    _, multiplier, _ = roll_event(custom_events)
    return multiplier


def get_all_events_info(custom_events: Optional[Dict] = None) -> Dict[str, Dict]:
    """
    Возвращает информацию о всех возможных событиях (для админки/документации).

    Returns:
        Словарь событий с весами и диапазонами
    """
    events = custom_events if custom_events is not None else RANDOM_EVENTS
    return {
        key: {
            "weight": data.get("weight", 0),
            "multiplier_range": data.get("multiplier_range", (1.0, 1.0)),
            "label": data.get("label", key),
        }
        for key, data in events.items()
    }
