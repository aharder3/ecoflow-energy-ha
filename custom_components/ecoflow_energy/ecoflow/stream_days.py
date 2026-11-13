"""Weekday lists as a user types them: "MO-FR", "MO;DI;DO", "MO-MI;SA".

Core library module: no Home Assistant imports.

Days are written with the German two-letter codes (MO, DI, MI, DO, FR, SA, SO);
the English three-letter codes (MON to SUN) are accepted too. Elements are
separated by ";" or ",", and an element is a day or a range such as MO-FR.
A range may run over the end of the week (SA-MO is Sat, Sun, Mon).
"""

from __future__ import annotations

import re

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_CODES = ("MO", "DI", "MI", "DO", "FR", "SA", "SO")
_ALIASES = {
    "MO": 0,
    "MON": 0,
    "DI": 1,
    "TUE": 1,
    "MI": 2,
    "WED": 2,
    "DO": 3,
    "THU": 3,
    "FR": 4,
    "FRI": 4,
    "SA": 5,
    "SAT": 5,
    "SO": 6,
    "SUN": 6,
}

# What Home Assistant checks before the value reaches the entity. It only fixes
# the shape; whether a code is a real day is decided by ``parse_days``.
TEXT_PATTERN = (
    r"^\s*[A-Za-z]{2,3}(\s*-\s*[A-Za-z]{2,3})?"
    r"(\s*[;,]\s*[A-Za-z]{2,3}(\s*-\s*[A-Za-z]{2,3})?)*\s*$"
)


def parse_days(text: str) -> list[str] | None:
    """Return the weekday names in ``text`` (Monday first), or None if invalid."""
    parts = [part.strip() for part in re.split(r"[;,]", text.strip().upper())]
    parts = [part for part in parts if part]
    if not parts:
        return None
    indexes: set[int] = set()
    for part in parts:
        bounds = [bound.strip() for bound in part.split("-")]
        if len(bounds) == 1:
            first = last = _ALIASES.get(bounds[0])
        elif len(bounds) == 2:
            first = _ALIASES.get(bounds[0])
            last = _ALIASES.get(bounds[1])
        else:
            return None
        if first is None or last is None:
            return None
        index = first
        while True:
            indexes.add(index)
            if index == last:
                break
            index = (index + 1) % 7
    return [DAY_NAMES[index] for index in sorted(indexes)]


def format_days(days: list[str]) -> str:
    """Return the shortest text for weekday names: runs of three or more become ranges."""
    indexes = sorted({DAY_NAMES.index(day) for day in days if day in DAY_NAMES})
    runs: list[list[int]] = []
    for index in indexes:
        if runs and index == runs[-1][1] + 1:
            runs[-1][1] = index
        else:
            runs.append([index, index])
    parts: list[str] = []
    for first, last in runs:
        if last - first >= 2:
            parts.append(f"{_CODES[first]}-{_CODES[last]}")
        else:
            parts.extend(_CODES[index] for index in range(first, last + 1))
    return ";".join(parts)
