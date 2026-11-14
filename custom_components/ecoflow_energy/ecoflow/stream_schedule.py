"""Scheduled-charge command for EcoFlow Stream (BK-series) over the app channel.

Core library module: no Home Assistant imports.

Wire format (cmd_func 254, cmd_id 17, field 595), decoded from frames the
vendor app sent to a Stream Ultra (BK11) and a Stream AC Pro (BK31)::

    595 {
      1 {                        # one schedule task
        2:  operation            # 1 = create a task, 2 = change it, 3 = delete it
        3:  plan id              # the same window kept the same id (3, 4)
        4:  flag                 # optional, 1 or absent; meaning UNKNOWN
        5:  flag                 # 0 in nearly all frames; UNKNOWN
        8:  kind                 # 4 in nearly all frames, 0 once; UNKNOWN
        9:  1037677              # constant in all but one frame; UNKNOWN
        10: packed window        # see ``pack_window``
        11 {
          1: 1                   # only present for "grid and solar"
          3 { 1: serial, 2: target SoC %, 3: power W }   # one per device
        }
        12: 0                    # 790 once, in a frame without devices
      }
    }

The operation values were read against the unit's own task list. The app sent
operation 3 for task 2 and the next report no longer listed it; it then sent
operation 1 for tasks 2 and 3 and the report listed them again. Operation 2
changes a task that exists. Earlier versions of this file called 3 "create";
it deletes. The service offers create and change only. A delete is built by
the tests alone.

Nothing here is confirmed against vendor documentation. The round-trip tests
reproduce captured frames byte for byte, which proves the layout of those
frames and nothing about values the app has not been seen to send.
"""

from __future__ import annotations

from dataclasses import dataclass

from .proto_encoding import encode_field_bytes, encode_field_varint, encode_varint

OPERATION_CREATE = 1
OPERATION_CHANGE = 2
# Removes the task. Not offered by the service.
OPERATION_DELETE = 3

SLOT_MINUTES = 30
DEFAULT_KIND = 4
DEFAULT_FIELD9 = 1037677

_CMD_FUNC = 254
_CMD_ID = 17


@dataclass(frozen=True)
class ScheduleDevice:
    """One device entry of a schedule task."""

    serial: str
    target_soc_pct: int
    power_w: int | None = None


def time_to_slot(hhmm: str) -> int:
    """Return the 30-minute slot of ``HH:MM`` (minutes must be 00 or 30)."""
    hours_s, minutes_s = hhmm.split(":")
    hours, minutes = int(hours_s), int(minutes_s)
    if not 0 <= hours <= 24 or minutes not in (0, 30):
        raise ValueError(f"time {hhmm!r} is not on a 30-minute boundary")
    return hours * 2 + minutes // 30


def slot_to_time(slot: int) -> str:
    """Return ``HH:MM`` for a 30-minute slot."""
    return f"{slot // 2:02d}:{30 * (slot % 2):02d}"


def pack_window(start: str, end: str) -> int:
    """Pack a start and end time into the wire value of field 10.

    ``((end_slot << 16) | start_slot) * 30``. A window that ends before it
    starts (20:00 to 15:00) runs past midnight, as in the app.
    """
    return ((time_to_slot(end) << 16) | time_to_slot(start)) * SLOT_MINUTES


def unpack_window(value: int) -> tuple[str, str]:
    """Return ``(start, end)`` for a wire value of field 10."""
    if value % SLOT_MINUTES:
        raise ValueError("window value is not a multiple of 30")
    slots = value // SLOT_MINUTES
    return slot_to_time(slots & 0xFFFF), slot_to_time(slots >> 16)


def build_schedule_task(
    *,
    operation: int,
    plan_id: int,
    start: str,
    end: str,
    devices: list[ScheduleDevice],
    grid: bool,
    flag4: int | None = None,
    flag5: int = 0,
    kind: int = DEFAULT_KIND,
    field9: int = DEFAULT_FIELD9,
    field12: int = 0,
) -> bytes:
    """Return the field-595 payload for one schedule task."""
    entries = b"".join(
        encode_field_bytes(
            3,
            encode_field_bytes(1, device.serial.encode())
            + encode_field_varint(2, device.target_soc_pct)
            + (encode_field_varint(3, device.power_w) if device.power_w else b""),
        )
        for device in devices
    )
    body = encode_field_varint(2, operation) + encode_field_varint(3, plan_id)
    if flag4 is not None:
        body += encode_field_varint(4, flag4)
    body += (
        encode_field_varint(5, flag5)
        + encode_field_varint(8, kind)
        + encode_field_varint(9, field9)
        + encode_field_bytes(10, encode_varint(pack_window(start, end)))
    )
    source = encode_field_varint(1, 1) if grid else b""
    body += encode_field_bytes(11, source + entries) + encode_field_varint(12, field12)
    return encode_field_bytes(595, encode_field_bytes(1, body))


def build_schedule_frame(
    task: bytes,
    *,
    sequence: int,
    device_serial: str,
    timestamp: int,
) -> bytes:
    """Wrap a field-595 payload in the header the vendor app uses."""
    pdata = encode_field_varint(6, timestamp) + task
    header = (
        encode_field_bytes(1, pdata)
        + encode_field_varint(2, 32)
        + encode_field_varint(3, 2)
        + encode_field_varint(4, 1)
        + encode_field_varint(5, 1)
        + encode_field_varint(7, 3)
        + encode_field_varint(8, _CMD_FUNC)
        + encode_field_varint(9, _CMD_ID)
        + encode_field_varint(10, len(pdata))
        + encode_field_varint(11, 1)
        + encode_field_varint(14, sequence)
        + encode_field_varint(16, 3)
        + encode_field_varint(17, 1)
        + encode_field_bytes(23, b"ios")
        + encode_field_bytes(25, device_serial.encode())
    )
    return encode_field_bytes(1, header)
