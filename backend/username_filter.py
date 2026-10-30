"""Фильтр ников: мат на русском и английском, в т.ч. транслитом и с обходами.

Ник приводится к «скелету»: нижний регистр, leet-замены (3→e, 0→o, @→a...),
удаление всего, кроме латиницы. Затем проверяются две формы: исходная и с
схлопнутыми повторами (blyaaat → blyat). Корни ищутся подстрокой.
"""
from __future__ import annotations

import re

_LEET = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
    "8": "b", "@": "a", "$": "s", "!": "i", "|": "i",
})

# Корни выбраны длинными или однозначными: короткие («hue», «manda») дают
# ложные срабатывания на обычные имена (Amanda, Miranda).
_ROOTS = (
    # русский мат транслитом
    "blya", "bliad", "bliat", "blyad", "blyat",
    "pizd", "pizz", "pidor", "pidar", "pidr", "pedik",
    "khuy", "khui", "huy", "huj", "hui",
    "ebat", "ebal", "ebla", "ebnu", "eban", "yeban", "jeba", "jebn", "yebl",
    "mudak", "mudil", "gondon", "zalup", "dolboeb", "dolbaeb", "shlyu",
    "shalav", "shluh", "gnida", "dristn", "chmo",
    # английский мат
    "fuck", "fuk", "shit", "bitch", "cunt", "nigger", "nigga", "faggot", "fagot",
    "whore", "slut", "retard", "asshole",
)


def _variants(name: str) -> tuple[str, str]:
    skeleton = re.sub(r"[^a-z]", "", name.lower().translate(_LEET))
    collapsed = re.sub(r"(.)\1+", r"\1", skeleton)
    return skeleton, collapsed


def is_profane(name: str) -> bool:
    return any(root in variant for variant in _variants(name) for root in _ROOTS)
