"""Operating-mode command for EcoFlow Stream (BK-series) over the app channel.

Core library module: no Home Assistant imports.

The vendor app switches the operating mode with ``cmd_func 254 / cmd_id 17``
and a single field, ``106 { <mode>: 1 }``. The device acknowledges it on
``set_reply`` with field 106 and the value 1. Observed on a Stream Ultra
(BK11) and a Stream AC Pro (BK31)::

    106 { 1: 1 }   self-powered mode (Eigenstrommodus)
    106 { 2: 1 }   custom mode (Benutzerdefiniert) - scheduled plans live here
    106 { 4: 1 }   AI mode

Mode 3 has not been seen. The meaning of the trailing ``1`` is not known.
"""

from __future__ import annotations

from .proto_encoding import encode_field_bytes, encode_field_varint
from .stream_schedule import build_schedule_frame

MODE_SELF_POWERED = "self_powered"
MODE_CUSTOM = "custom"
MODE_AI = "ai"

MODES = {MODE_SELF_POWERED: 1, MODE_CUSTOM: 2, MODE_AI: 4}


def build_mode_frame(
    mode: str,
    *,
    device_serial: str,
    sequence: int,
    timestamp: int,
) -> bytes:
    """Return the complete frame that switches the operating mode."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {tuple(MODES)}, got {mode!r}")
    payload = encode_field_bytes(106, encode_field_varint(MODES[mode], 1))
    return build_schedule_frame(
        payload,
        sequence=sequence,
        device_serial=device_serial,
        timestamp=timestamp,
    )
