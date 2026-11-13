"""Tests for the operating mode and the plan list of the Stream status frame.

The first fixture is the payload of a status frame (cmd 254/21) from a Stream
Ultra, taken from a diagnostics download in which the serials were already
masked (16 x "X"). Only the two fields under test are kept: 393 (operating
mode) and 584 (plan list). At the time the vendor app showed plan 2 (22:00 to
06:00, grid and solar) and plan 3 (06:00 to 22:00, solar) switched on, plan 3
running, and two custom discharge plans of 790 W.

The second fixture is a later status frame of the same unit, after the repeat of
the plans had been changed in the app: plan 2 weekly on Mon, Tue, Thu, Fri, Sat,
plan 3 weekly on Mon, Tue, Thu, Sat, Sun, discharge plan 1 daily (17:00 to
20:00, off) and discharge plan 5 a plan that ran once (14:30 to 17:30, off).
"""

from __future__ import annotations

from ecoflow_energy.ecoflow.stream_status import (
    days_to_mask,
    decode_operating_mode,
    decode_plans,
    mask_to_days,
)

STATUS_PAYLOAD = bytes.fromhex(
    "ca18021001c224c6010a4a1002180220012800400448edaa3f5204a88aa00b5a3408011a170a105858585858585858585858"
    "5858585858105f189a081a170a1058585858585858585858585858585858105f189a080a481002180320012801400448edaa"
    "3f5204e882a0295a321a170a1058585858585858585858585858585858105f189a081a170a10585858585858585858585858"
    "58585858105f189a080a15100118012800400048deaa3f5204aa86f81e6096060a171002180520012801400448edaa3f5204"
    "e686e820609606"
)

# The same unit after the repeat of the plans was changed in the app.
REPEAT_PAYLOAD = bytes.fromhex(
    "ca18021001c224be010a4810021802200128004002483b5204a88aa00b5a3408011a170a1058585858585858585858585858"
    "585858105f189a081a170a1058585858585858585858585858585858105f189a080a4610021803200128004002486b5204e8"
    "82a0295a321a170a1058585858585858585858585858585858105f189a081a170a1058585858585858585858585858585858"
    "105f189a080a13100218012800400148005204fc87c0256096060a15100218052800400048edaa3f5204e686e820609606"
)


def test_operating_mode_is_read_from_field_393():
    assert decode_operating_mode(STATUS_PAYLOAD) == "custom"


def test_plan_list_is_read_in_report_order():
    plans = decode_plans(STATUS_PAYLOAD)
    assert plans is not None
    assert [(plan["id"], plan["kind"]) for plan in plans] == [
        (2, "charge"),
        (3, "charge"),
        (1, "discharge"),
        (5, "discharge"),
    ]


def test_charge_plan_values():
    plans = decode_plans(STATUS_PAYLOAD)
    assert plans is not None
    assert plans[0] == {
        "id": 2,
        "kind": "charge",
        "enabled": True,
        "running": False,
        "start": "22:00",
        "end": "06:00",
        "source": "grid_and_solar",
        "soc": 95,
        "power": 1050,
        "discharge_power": None,
        "repeat": "once",
        "days": [],
        "repeat_kind": 4,
        "repeat_value": 1037677,
    }
    assert plans[1]["source"] == "solar"
    assert plans[1]["running"] is True


def test_discharge_plans_carry_no_device_targets():
    plans = decode_plans(STATUS_PAYLOAD)
    assert plans is not None
    discharge = [plan for plan in plans if plan["kind"] == "discharge"]
    assert [plan["enabled"] for plan in discharge] == [False, True]
    assert all(plan["soc"] is None and plan["power"] is None for plan in discharge)


def test_discharge_plans_carry_their_power():
    plans = decode_plans(STATUS_PAYLOAD)
    assert plans is not None
    discharge = [plan for plan in plans if plan["kind"] == "discharge"]
    assert [plan["discharge_power"] for plan in discharge] == [790, 790]
    assert all(plan["discharge_power"] is None for plan in plans[:2])


def test_a_weekly_plan_reports_its_days():
    plans = decode_plans(REPEAT_PAYLOAD)
    assert plans is not None
    assert (plans[0]["repeat"], plans[0]["repeat_value"]) == ("weekly", 59)
    assert plans[0]["days"] == ["mon", "tue", "thu", "fri", "sat"]
    assert (plans[1]["repeat"], plans[1]["repeat_value"]) == ("weekly", 107)
    assert plans[1]["days"] == ["mon", "tue", "thu", "sat", "sun"]


def test_a_daily_plan_reports_every_day():
    plans = decode_plans(REPEAT_PAYLOAD)
    assert plans is not None
    daily = plans[2]
    assert (daily["id"], daily["kind"], daily["repeat"]) == (1, "discharge", "daily")
    assert daily["repeat_value"] == 0
    assert len(daily["days"]) == 7


def test_a_plan_that_ran_once_has_no_days():
    plans = decode_plans(REPEAT_PAYLOAD)
    assert plans is not None
    once = plans[3]
    assert (once["id"], once["repeat"], once["days"]) == (5, "once", [])
    assert once["repeat_kind"] == 0


def test_day_mask_has_monday_as_bit_zero():
    assert days_to_mask(["mon"]) == 1
    assert days_to_mask(["sun"]) == 64
    assert days_to_mask(["tue", "wed", "thu", "sat", "sun"]) == 110
    assert mask_to_days(110) == ["tue", "wed", "thu", "sat", "sun"]
    assert mask_to_days(0) == []


def test_frame_without_the_fields_reports_nothing():
    assert decode_operating_mode(b"") is None
    assert decode_plans(b"") is None
