"""Tests for the discharge plan command of a Stream.

Both frames are the ones the vendor app sent to a Stream Ultra for its custom
discharge plan 1, taken from a diagnostics download in which the serials were
already masked (16 x "X"): first switched on and daily at 790 W, then weekly
(Tue, Wed, Thu, Sat, Sun) at 300 W with the window shortened to 19:30.
"""

from __future__ import annotations

import pytest
from ecoflow_energy.ecoflow.stream_discharge import build_discharge_request_frame

SERIAL = "XXXXXXXXXXXXXXXX"

CAPTURED_DAILY = (
    "0a560a2030c28addd7069a25170a151002180120012800400148005204fc87c025609606102018"
    "0220012801380340fe014811502058017024800103880101ba0103696f73ca0110585858585858"
    "58585858585858585858"
)
CAPTURED_WEEKLY = (
    "0a560a2030f28addd7069a25170a1510021801200128014002486e5204fc87c82460ac02102018"
    "0220012801380340fe014811502058017027800103880101ba0103696f73ca0110585858585858"
    "58585858585858585858"
)


def _frame(**overrides):
    params = dict(
        header_serial=SERIAL,
        plan_id=1,
        start="17:00",
        end="20:00",
        power_w=790,
        enabled=True,
        running=False,
        kind=1,
        field9=0,
        sequence=36,
        timestamp=1794590018,
    )
    params.update(overrides)
    return build_discharge_request_frame(**params)


def test_daily_request_matches_the_captured_app_frame():
    assert _frame().hex() == CAPTURED_DAILY


def test_weekly_request_matches_the_captured_app_frame():
    frame = _frame(
        end="19:30",
        power_w=300,
        running=True,
        kind=2,
        field9=110,
        sequence=39,
        timestamp=1794590066,
    )
    assert frame.hex() == CAPTURED_WEEKLY


def test_a_plan_that_is_off_carries_no_flag_4():
    on = _frame()
    off = _frame(enabled=False)
    assert len(off) == len(on) - 2  # field 4 = 1 is two bytes
    assert off != on


@pytest.mark.parametrize("kind", [0, 4])
def test_a_plan_that_runs_once_is_sent_back_as_reported(kind):
    assert _frame(kind=kind, field9=1037677)


@pytest.mark.parametrize(
    "bad",
    [
        {"header_serial": ""},
        {"plan_id": 0},
        {"power_w": 0},
        {"power_w": 10001},
        {"kind": 3},
        {"kind": 2, "field9": 0},
        {"kind": 2, "field9": 128},
        {"kind": 1, "field9": 5},
        {"start": "17:15"},
        {"end": "20:10"},
    ],
)
def test_invalid_input_is_rejected(bad):
    with pytest.raises(ValueError):
        _frame(**bad)
