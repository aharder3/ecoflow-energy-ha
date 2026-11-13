"""Discharge plan command for EcoFlow Stream (BK-series) over the app channel.

Core library module: no Home Assistant imports.

The layout is that of the charge schedule task (see ``stream_schedule.py``),
without the source and device block in field 11, and with the plan's power in
field 12. Two frames the vendor app sent for a discharge plan were reproduced
byte for byte by this encoding:

- plan 1, 17:00 to 20:00, on, daily (field 8 = 1, field 9 = 0), 790 W
- plan 1, 17:00 to 19:30, on, weekly (field 8 = 2, field 9 = 110 for Tue, Wed,
  Thu, Sat, Sun), 300 W

Field 4 is 1 for a plan that is on and absent for one that is off, as in the
status report. Field 5 carried the plan's running flag as it was reported
before the change. A plan that runs once uses field 8 = 4, or 0 once its window
has passed, and a field 9 the vendor app chooses; it is only sent back
unchanged.
"""

from __future__ import annotations

from .proto_encoding import encode_field_bytes, encode_field_varint, encode_varint
from .stream_schedule import (
    OPERATION_CHANGE,
    build_schedule_frame,
    pack_window,
    time_to_slot,
)

DISCHARGE_REPEAT_KINDS = (0, 1, 2, 4)
MAX_POWER_W = 10000


def build_discharge_request_frame(
    *,
    header_serial: str,
    plan_id: int,
    start: str,
    end: str,
    power_w: int,
    enabled: bool,
    running: bool,
    kind: int,
    field9: int,
    sequence: int,
    timestamp: int,
) -> bytes:
    """Return the complete frame that changes one discharge plan.

    Raises ``ValueError`` for input the app has never been seen to send.
    """
    if not header_serial:
        raise ValueError("a device serial is required")
    if plan_id < 1:
        raise ValueError("plan_id must be 1 or higher")
    if not 1 <= power_w <= MAX_POWER_W:
        raise ValueError(f"power_w must be between 1 and {MAX_POWER_W}")
    if kind not in DISCHARGE_REPEAT_KINDS:
        raise ValueError(
            f"kind must be one of {DISCHARGE_REPEAT_KINDS}, got {kind!r}"
        )
    if kind == 2 and not 1 <= field9 <= 127:
        raise ValueError("a weekly plan needs a day mask between 1 and 127")
    if kind == 1 and field9 != 0:
        raise ValueError("a daily plan carries 0 in field 9")
    time_to_slot(start)
    time_to_slot(end)

    body = encode_field_varint(2, OPERATION_CHANGE) + encode_field_varint(3, plan_id)
    if enabled:
        body += encode_field_varint(4, 1)
    body += (
        encode_field_varint(5, 1 if running else 0)
        + encode_field_varint(8, kind)
        + encode_field_varint(9, field9)
        + encode_field_bytes(10, encode_varint(pack_window(start, end)))
        + encode_field_varint(12, power_w)
    )
    task = encode_field_bytes(595, encode_field_bytes(1, body))
    return build_schedule_frame(
        task,
        sequence=sequence,
        device_serial=header_serial,
        timestamp=timestamp,
    )
