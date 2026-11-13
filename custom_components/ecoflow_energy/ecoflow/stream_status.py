"""Operating mode and plan list from the Stream status frame (cmd 254/21).

Core library module: no Home Assistant imports.

Two things in that frame are reported back by the device, which is what makes
them safe to show and to control:

- Field 393 holds the operating mode in the form the mode command sends it: a
  message with one field set to 1, field 1 for self-powered, 2 for custom and 4
  for AI. After a mode command the new value shows up within a few seconds, and
  the second unit of a pair reports the same.
- Field 584 holds the plan list, one repeated entry per plan. An entry has the
  layout of the schedule command (see ``stream_schedule.py``): field 3 is the
  plan number, field 10 the packed window, field 11 the source flag and the
  per-device targets. Observed against the vendor app on a Stream Ultra and a
  Stream AC Pro: field 4 equals 1 for a plan that is switched on and is absent
  for one that is switched off, and field 5 equals 1 while the plan's window is
  running. A charge plan carries device targets; a discharge plan (the custom
  discharge of the app) has none.
"""

from __future__ import annotations

from typing import Any

from .stream_schedule import unpack_window

_FIELD_OPERATING_MODE = 393
_FIELD_PLANS = 584

OPERATING_MODES = {1: "self_powered", 2: "custom", 4: "ai"}


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    shift = 0
    value = 0
    while True:
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > 63:
            raise ValueError("oversized varint")


def _fields(payload: bytes) -> list[tuple[int, int, Any]]:
    """Return ``(field number, wire type, value)``: varints as int, blobs as bytes."""
    result: list[tuple[int, int, Any]] = []
    pos = 0
    while pos < len(payload):
        tag, pos = _read_varint(payload, pos)
        number, wire = tag >> 3, tag & 7
        if wire == 0:
            varint, pos = _read_varint(payload, pos)
            result.append((number, wire, varint))
        elif wire == 2:
            length, pos = _read_varint(payload, pos)
            result.append((number, wire, payload[pos : pos + length]))
            pos += length
        elif wire == 1:
            pos += 8
        elif wire == 5:
            pos += 4
        else:
            break
    return result


def decode_operating_mode(pdata: bytes) -> str | None:
    """Return the reported operating mode, or None when the frame has none."""
    for number, wire, value in _fields(pdata):
        if number != _FIELD_OPERATING_MODE or wire != 2:
            continue
        for inner, inner_wire, flag in _fields(value):
            if inner_wire == 0 and flag == 1 and inner in OPERATING_MODES:
                return OPERATING_MODES[inner]
    return None


def _decode_plan(task: bytes) -> dict[str, Any] | None:
    flags: dict[int, int] = {}
    window: int | None = None
    grid = False
    devices: list[dict[int, int]] = []
    for number, wire, value in _fields(task):
        if wire == 0:
            flags[number] = value
        elif wire == 2 and number == 10:
            window = _read_varint(value, 0)[0]
        elif wire == 2 and number == 11:
            for inner, inner_wire, inner_value in _fields(value):
                if inner == 1 and inner_wire == 0:
                    grid = inner_value == 1
                elif inner == 3 and inner_wire == 2:
                    devices.append(
                        {
                            key: val
                            for key, key_wire, val in _fields(inner_value)
                            if key_wire == 0
                        }
                    )
    plan_id = flags.get(3)
    if plan_id is None or window is None:
        return None
    try:
        start, end = unpack_window(window)
    except ValueError:
        return None
    first = devices[0] if devices else {}
    return {
        "id": plan_id,
        "kind": "charge" if devices else "discharge",
        "enabled": flags.get(4) == 1,
        "running": flags.get(5) == 1,
        "start": start,
        "end": end,
        "source": "grid_and_solar" if grid else "solar",
        "soc": first.get(2),
        "power": first.get(3),
    }


def decode_plans(pdata: bytes) -> list[dict[str, Any]] | None:
    """Return the reported plans, or None when the frame carries no plan list."""
    plans: list[dict[str, Any]] | None = None
    for number, wire, value in _fields(pdata):
        if number != _FIELD_PLANS or wire != 2:
            continue
        if plans is None:
            plans = []
        for inner, inner_wire, task in _fields(value):
            if inner == 1 and inner_wire == 2:
                plan = _decode_plan(task)
                if plan is not None:
                    plans.append(plan)
    return plans
