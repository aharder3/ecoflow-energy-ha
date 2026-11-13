"""Validated request -> frame for the Stream scheduled-charge service.

Core library module: no Home Assistant imports. The Home Assistant service in
``schedule_service.py`` only parses its call data and hands it to this module.
"""

from __future__ import annotations

from .stream_schedule import (
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

OPERATIONS = {"change": OPERATION_CHANGE, "create": OPERATION_CREATE}


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
    )
    return build_schedule_frame(
        task,
        sequence=sequence,
        device_serial=header_serial,
        timestamp=timestamp,
    )
