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


def test_solar_request_matches_captured_app_frame():
    assert _frame().hex() == CAPTURED_SOLAR


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
    ],
)
def test_invalid_input_is_rejected(bad):
    with pytest.raises(ValueError):
        _frame(**bad)
