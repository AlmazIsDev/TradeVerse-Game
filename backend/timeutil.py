"""Общие хелперы работы с временем (UTC-aware datetime).

Вынесены сюда, чтобы не дублировать идентичные ``_now``/``_aware`` в
нескольких модулях (см. assets.py, cityroof.py).
"""
from datetime import datetime, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_aware(dt):
    """Добавляет UTC tzinfo к naive datetime; прочие значения не трогает."""
    if isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
