"""Plan numbers of the Stream charge plans, as the user enters them.

No Home Assistant imports, so the options flow and the entities share it.
"""

from __future__ import annotations

import re

CONF_STREAM_PLAN_IDS = "stream_plan_ids"
MAX_PLAN_ID = 99


def parse_plan_ids(text: str) -> list[int] | None:
    """Return the plan numbers in ``text`` ("2, 3"), [] for empty text, None if invalid."""
    ids: list[int] = []
    for part in re.split(r"[\s,;]+", text.strip()):
        if not part:
            continue
        if not re.fullmatch(r"[0-9]+", part):
            return None
        value = int(part)
        if not 1 <= value <= MAX_PLAN_ID:
            return None
        if value not in ids:
            ids.append(value)
    return ids


def format_plan_ids(ids: list[int]) -> str:
    """Return the plan numbers as the options form shows them."""
    return ", ".join(str(value) for value in ids)
