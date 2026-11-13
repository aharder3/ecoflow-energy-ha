"""Tests for the validated schedule request builder."""

from __future__ import annotations

import pytest

from custom_components.ecoflow_energy.ecoflow.stream_schedule_request import (
    build_schedule_request_frame,
)

SERIAL = "XXXXXXXXXXXXXXXX"

# Captured app frame: plan 2, change, 14:30-19:00, solar only, 95 % / 1050 W on
# two devices, flag 4 set (Stream Ultra + Stream AC Pro, sequence 15).
CAPTURED_SOLAR = (
    "0a8b010a553089a1dcd7069a254c0a4a1002180220012800400448edaa3f5204e686d0235a321a170a10"
    "58585858585858585858585858585858105f189a081a170a1058585858585858585858585858585858"
    "105f189a0860001020180220012801380340fe01481150555801700f800103880101ba0103696f73ca01"
    "1058585858585858585858585858585858"
)

# Frames the app sent for plan 2 (22:00-06:00, grid and solar, 95 % / 1050 W on
# two devices) while its repeat was changed. Same unit, same serials masked.
CAPTURED_ONCE = (
    "0a8d010a5730e684ddd7069a254e0a4c1002180220012800400448eeaa3f5204a88aa00b5a340801"
    "1a170a1058585858585858585858585858585858105f189a081a170a105858585858585858585858"
    "5858585858105f189a0860001020180220012801380340fe01481150575801700e800103880101ba"
    "0103696f73ca011058585858585858585858585858585858"
)
CAPTURED_WEEKLY_MON_WED_SAT = (
    "0a8b010a5530a186ddd7069a254c0a4a1002180220012800400248255204a88aa00b5a3408011a17"
    "0a1058585858585858585858585858585858105f189a081a170a1058585858585858585858585858"
    "585858105f189a0860001020180220012801380340fe014811505558017010800103880101ba0103"
    "696f73ca011058585858585858585858585858585858"
)
CAPTURED_WEEKLY_MON_TUE_THU_FRI_SAT = (
    "0a8b010a5530c187ddd7069a254c0a4a10021802200128004002483b5204a88aa00b5a3408011a17"
    "0a1058585858585858585858585858585858105f189a081a170a1058585858585858585858585858"
    "585858105f189a0860001020180220012801380340fe014811505558017014800103880101ba0103"
    "696f73ca011058585858585858585858585858585858"
)


def _frame(**overrides):
    params = dict(
        header_serial=SERIAL,
        serials=[SERIAL, SERIAL],
        plan_id=2,
        start="14:30",
        end="19:00",
        source="solar",
        soc_pct=95,
        power_w=1050,
        sequence=15,
        timestamp=1794576521,
    )
    params.update(overrides)
    return build_schedule_request_frame(**params)


def _repeat_frame(**overrides):
    params = dict(
        plan_id=2,
        start="22:00",
        end="06:00",
        source="grid_and_solar",
    )
    params.update(overrides)
    return _frame(**params)


def test_solar_request_matches_captured_app_frame():
    assert _frame().hex() == CAPTURED_SOLAR


def test_plan_that_runs_once_matches_captured_app_frame():
    frame = _repeat_frame(sequence=14, timestamp=1794589286, kind=4, field9=1037678)
    assert frame.hex() == CAPTURED_ONCE


def test_weekly_plan_matches_captured_app_frame():
    frame = _repeat_frame(sequence=16, timestamp=1794589473, kind=2, field9=37)
    assert frame.hex() == CAPTURED_WEEKLY_MON_WED_SAT


def test_weekly_plan_with_five_days_matches_captured_app_frame():
    frame = _repeat_frame(sequence=20, timestamp=1794589633, kind=2, field9=59)
    assert frame.hex() == CAPTURED_WEEKLY_MON_TUE_THU_FRI_SAT


def test_daily_plan_carries_kind_1_and_a_zero_mask():
    daily = _repeat_frame(kind=1, field9=0)
    weekly = _repeat_frame(kind=2, field9=127)
    assert bytes.fromhex("40014800") in daily  # field 8 = 1, field 9 = 0
    assert bytes.fromhex("4002487f") in weekly  # 8 = 2, 9 = 127
    assert daily != weekly


def test_grid_source_adds_exactly_the_grid_marker():
    solar = _frame()
    grid = _frame(source="grid_and_solar")
    assert grid != solar
    assert len(grid) == len(solar) + 2  # field 11.1 = 1 is two bytes


def test_create_differs_from_change_only_in_operation():
    change = _frame(operation="change")
    create = _frame(operation="create")
    assert len(change) == len(create)
    assert change != create


@pytest.mark.parametrize(
    "bad",
    [
        {"source": "grid"},
        {"operation": "delete"},
        {"serials": []},
        {"header_serial": "OTHER"},
        {"plan_id": 0},
        {"soc_pct": 0},
        {"soc_pct": 101},
        {"power_w": 0},
        {"start": "14:15"},
        {"end": "18:45"},
        {"kind": 3},
        {"kind": 2, "field9": 0},
        {"kind": 2, "field9": 128},
        {"kind": 1, "field9": 3},
    ],
)
def test_invalid_input_is_rejected(bad):
    with pytest.raises(ValueError):
        _frame(**bad)


@pytest.mark.parametrize("kind", [0, 4])
def test_a_plan_that_runs_once_is_accepted(kind):
    assert _frame(kind=kind, field9=1037677)
