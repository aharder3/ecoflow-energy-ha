"""Validated request -> frame for the Stream scheduled-charge service.

Core library module: no Home Assistant imports. The Home Assistant service in
``schedule_service.py`` only parses its call data and hands it to this module.
"""

from __future__ import annotations

from .stream_schedule import (
    DEFAULT_FIELD9,
    DEFAULT_KIND,
    OPERATION_CHANGE,
    OPERATION_CREATE,
    ScheduleDevice,
    build_schedule_frame,
    build_schedule_task,
    time_to_slot,
)

SOURCE_SOLAR = "solar"
SOURCE_GRID_AND_SOLAR = "grid_and_solar"
SOURCES = (SOURCE_SOLAR, SOURCE_GRID_AND_SOLAR)

# Create sends operation 1 and change sends 2. The delete operation (3) is
# deliberately not offered: a service call must not be able to remove a task.
OPERATIONS = {"change": OPERATION_CHANGE, "create": OPERATION_CREATE}

# Field 8 as the vendor app sends it: 1 daily, 2 weekly (field 9 is the day
# mask), 4 once, and 0 on a plan that runs once whose window has passed.
REPEAT_KINDS = (0, 1, 2, 4)


def build_schedule_request_frame(
    *,
    header_serial: str,
    serials: list[str],
    plan_id: int,
    start: str,
    end: str,
    source: str,
    soc_pct: int,
    power_w: int,
    sequence: int,
    timestamp: int,
    operation: str = "change",
    flag4: int | None = 1,
    kind: int = DEFAULT_KIND,
    field9: int = DEFAULT_FIELD9,
) -> bytes:
    """Return the complete frame for one schedule write.

    Raises ``ValueError`` for input the app has never been seen to send, so a
    bad automation fails here instead of reaching the device.
    """
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
    if operation not in OPERATIONS:
        raise ValueError(f"operation must be one of {tuple(OPERATIONS)}")
    if not serials:
        raise ValueError("at least one device serial is required")
    if header_serial not in serials:
        raise ValueError("header_serial must be one of serials")
    if plan_id < 1:
        raise ValueError("plan_id must be 1 or higher")
    if not 1 <= soc_pct <= 100:
        raise ValueError("soc_pct must be between 1 and 100")
    if power_w < 1:
        raise ValueError("power_w must be positive")
    if kind not in REPEAT_KINDS:
        raise ValueError(f"kind must be one of {REPEAT_KINDS}, got {kind!r}")
    if kind == 2 and not 1 <= field9 <= 127:
        raise ValueError("a weekly plan needs a day mask between 1 and 127")
    if kind == 1 and field9 != 0:
        raise ValueError("a daily plan carries 0 in field 9")
    time_to_slot(start)
    time_to_slot(end)

    devices = [ScheduleDevice(serial, soc_pct, power_w) for serial in serials]
    task = build_schedule_task(
        operation=OPERATIONS[operation],
        plan_id=plan_id,
        start=start,
        end=end,
        devices=devices,
        grid=source == SOURCE_GRID_AND_SOLAR,
        flag4=flag4,
        kind=kind,
        field9=field9,
    )
    return build_schedule_frame(
        task,
        sequence=sequence,
        device_serial=header_serial,
        timestamp=timestamp,
    )
