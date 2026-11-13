"""Round-trip tests for the Stream scheduled-charge encoder.

The fixtures are frames the vendor app sent to a Stream Ultra and a Stream AC
Pro, taken from a diagnostics download. Serials were already masked there
(16 x "X"). A passing test proves the layout of these frames, nothing more:
the meaning of several fields (see the module docstring) is not established.
"""

from __future__ import annotations

import pytest

from custom_components.ecoflow_energy.ecoflow.stream_schedule import (
    ScheduleDevice,
    build_schedule_frame,
    build_schedule_task,
    pack_window,
    unpack_window,
)

SERIAL = "XXXXXXXXXXXXXXXX"

CAPTURED = [
    pytest.param(
        dict(
            operation=3, plan_id=2, start="13:30", end="16:30",
            grid=False, flag4=None, flag5=0, kind=4,
            field9=1037662, field12=0, devices=[('XXXXXXXXXXXXXXXX', 95, 1050), ('XXXXXXXXXXXXXXXX', 95, 1050)],
        ),
        7,
        1794576258,
        "0a89010a5330829fdcd7069a254a0a48100318022800400448deaa3f5204aa86f81e5a321a170a1058585858585858585858585858585858105f189a081a170a1058585858585858585858585858585858105f189a0860001020180220012801380340fe014811505358017007800103880101ba0103696f73ca011058585858585858585858585858585858",
        id="plan2-op3-seq7",
    ),
    pytest.param(
        dict(
            operation=1, plan_id=2, start="14:30", end="17:30",
            grid=False, flag4=1, flag5=0, kind=4,
            field9=1037677, field12=0, devices=[('XXXXXXXXXXXXXXXX', 95, 1050), ('XXXXXXXXXXXXXXXX', 95, 1050)],
        ),
        8,
        1794576271,
        "0a8b010a55308f9fdcd7069a254c0a4a1001180220012800400448edaa3f5204e686e8205a321a170a1058585858585858585858585858585858105f189a081a170a1058585858585858585858585858585858105f189a0860001020180220012801380340fe014811505558017008800103880101ba0103696f73ca011058585858585858585858585858585858",
        id="plan2-op1-seq8",
    ),
    pytest.param(
        dict(
            operation=3, plan_id=3, start="11:00", end="14:00",
            grid=True, flag4=None, flag5=0, kind=0,
            field9=1037677, field12=0, devices=[('XXXXXXXXXXXXXXXX', 95, 1050)],
        ),
        10,
        1794576307,
        "0a720a3c30b39fdcd7069a25330a31100318032800400048edaa3f52049485a01a5a1b08011a170a1058585858585858585858585858585858105f189a0860001020180220012801380340fe014811503c5801700a800103880101ba0103696f73ca011058585858585858585858585858585858",
        id="plan3-op3-seq10",
    ),
    pytest.param(
        dict(
            operation=3, plan_id=4, start="20:00", end="15:00",
            grid=False, flag4=1, flag5=0, kind=4,
            field9=1037677, field12=0, devices=[('XXXXXXXXXXXXXXXX', 95, 1050), ('XXXXXXXXXXXXXXXX', 95, 1050)],
        ),
        11,
        1794576310,
        "0a8b010a5530b69fdcd7069a254c0a4a1003180420012800400448edaa3f5204b089901c5a321a170a1058585858585858585858585858585858105f189a081a170a1058585858585858585858585858585858105f189a0860001020180220012801380340fe01481150555801700b800103880101ba0103696f73ca011058585858585858585858585858585858",
        id="plan4-op3-seq11",
    ),
    pytest.param(
        dict(
            operation=2, plan_id=2, start="14:30", end="17:30",
            grid=False, flag4=None, flag5=0, kind=4,
            field9=1037677, field12=0, devices=[('XXXXXXXXXXXXXXXX', 95, 1050), ('XXXXXXXXXXXXXXXX', 95, 1050)],
        ),
        13,
        1794576488,
        "0a89010a5330e8a0dcd7069a254a0a48100218022800400448edaa3f5204e686e8205a321a170a1058585858585858585858585858585858105f189a081a170a1058585858585858585858585858585858105f189a0860001020180220012801380340fe01481150535801700d800103880101ba0103696f73ca011058585858585858585858585858585858",
        id="plan2-op2-seq13",
    ),
    pytest.param(
        dict(
            operation=2, plan_id=2, start="14:30", end="19:00",
            grid=False, flag4=None, flag5=0, kind=4,
            field9=1037677, field12=0, devices=[('XXXXXXXXXXXXXXXX', 95, 1050), ('XXXXXXXXXXXXXXXX', 95, 1050)],
        ),
        14,
        1794576507,
        "0a89010a5330fba0dcd7069a254a0a48100218022800400448edaa3f5204e686d0235a321a170a1058585858585858585858585858585858105f189a081a170a1058585858585858585858585858585858105f189a0860001020180220012801380340fe01481150535801700e800103880101ba0103696f73ca011058585858585858585858585858585858",
        id="plan2-op2-seq14",
    ),
    pytest.param(
        dict(
            operation=2, plan_id=2, start="14:30", end="19:00",
            grid=False, flag4=1, flag5=0, kind=4,
            field9=1037677, field12=0, devices=[('XXXXXXXXXXXXXXXX', 95, 1050), ('XXXXXXXXXXXXXXXX', 95, 1050)],
        ),
        15,
        1794576521,
        "0a8b010a553089a1dcd7069a254c0a4a1002180220012800400448edaa3f5204e686d0235a321a170a1058585858585858585858585858585858105f189a081a170a1058585858585858585858585858585858105f189a0860001020180220012801380340fe01481150555801700f800103880101ba0103696f73ca011058585858585858585858585858585858",
        id="plan2-op2-seq15",
    ),
]


@pytest.mark.parametrize(("params", "sequence", "timestamp", "expected_hex"), CAPTURED)
def test_captured_frame_is_reproduced_byte_for_byte(
    params, sequence, timestamp, expected_hex
):
    devices = [ScheduleDevice(sn, soc, power) for sn, soc, power in params["devices"]]
    task = build_schedule_task(**{**params, "devices": devices})
    frame = build_schedule_frame(
        task, sequence=sequence, device_serial=SERIAL, timestamp=timestamp
    )
    assert frame.hex() == expected_hex


@pytest.mark.parametrize(
    ("start", "end", "value"),
    [
        ("11:00", "14:00", 55050900),
        ("20:00", "15:00", 58983600),
        ("13:30", "16:30", 64881450),
        ("14:30", "19:00", 74711910),
    ],
)
def test_window_roundtrip(start, end, value):
    assert pack_window(start, end) == value
    assert unpack_window(value) == (start, end)


@pytest.mark.parametrize("bad", ["14:15", "09:45", "10:07"])
def test_window_rejects_off_slot_minutes(bad):
    with pytest.raises(ValueError):
        pack_window(bad, "18:00")


def test_unpack_rejects_value_not_multiple_of_slot():
    with pytest.raises(ValueError):
        unpack_window(55050901)
