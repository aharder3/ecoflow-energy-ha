"""Tests for the Stream operating-mode frame.

The fixtures are the frames the vendor app sent when switching the mode on a
Stream Ultra and a Stream AC Pro; serials were already masked in the
diagnostics download (16 x "X").
"""

from __future__ import annotations

import pytest

from custom_components.ecoflow_energy.ecoflow.stream_mode import MODES, build_mode_frame

SERIAL = "XXXXXXXXXXXXXXXX"

CAPTURED = [
    pytest.param("self_powered", 26, 1794578477,
        "0a410a0b30adb0dcd706d2060208011020180220012801380340fe014811500b5801701a800103880101ba0103696f73ca011058585858585858585858585858585858",
        id="self_powered"),
    pytest.param("custom", 6, 1794576246,
        "0a410a0b30f69edcd706d2060210011020180220012801380340fe014811500b58017006800103880101ba0103696f73ca011058585858585858585858585858585858",
        id="custom"),
    pytest.param("ai", 32, 1794579377,
        "0a410a0b30b1b7dcd706d2060220011020180220012801380340fe014811500b58017020800103880101ba0103696f73ca011058585858585858585858585858585858",
        id="ai"),
]


@pytest.mark.parametrize(("mode", "sequence", "timestamp", "expected_hex"), CAPTURED)
def test_captured_mode_frame_is_reproduced_byte_for_byte(
    mode, sequence, timestamp, expected_hex
):
    frame = build_mode_frame(
        mode, device_serial=SERIAL, sequence=sequence, timestamp=timestamp
    )
    assert frame.hex() == expected_hex


def test_modes_map_to_the_observed_values():
    assert MODES == {"self_powered": 1, "custom": 2, "ai": 4}


@pytest.mark.parametrize("bad", ["", "eco", "SELF_POWERED", "3"])
def test_unknown_mode_is_rejected(bad):
    with pytest.raises(ValueError):
        build_mode_frame(bad, device_serial=SERIAL, sequence=1, timestamp=1)
