"""Tests for the operating mode and the plan list of the Stream status frame.

The fixture is the payload of a status frame (cmd 254/21) from a Stream Ultra,
taken from a diagnostics download in which the serials were already masked
(16 x "X"). Only the two fields under test are kept: 393 (operating mode) and
584 (plan list). At the time the vendor app showed plan 2 (22:00 to 06:00, grid
and solar) and plan 3 (06:00 to 22:00, solar) switched on, plan 3 running, and
two custom discharge plans of 790 W.
"""

from __future__ import annotations

from ecoflow_energy.ecoflow.stream_status import decode_operating_mode, decode_plans

STATUS_PAYLOAD = bytes.fromhex(
    "ca18021001c224c6010a4a1002180220012800400448edaa3f5204a88aa00b5a3408011a170a105858585858585858585858"
    "5858585858105f189a081a170a1058585858585858585858585858585858105f189a080a481002180320012801400448edaa"
    "3f5204e882a0295a321a170a1058585858585858585858585858585858105f189a081a170a10585858585858585858585858"
    "58585858105f189a080a15100118012800400048deaa3f5204aa86f81e6096060a171002180520012801400448edaa3f5204"
    "e686e820609606"
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
    }
    assert plans[1]["source"] == "solar"
    assert plans[1]["running"] is True


def test_discharge_plans_carry_no_device_targets():
    plans = decode_plans(STATUS_PAYLOAD)
    assert plans is not None
    discharge = [plan for plan in plans if plan["kind"] == "discharge"]
    assert [plan["enabled"] for plan in discharge] == [False, True]
    assert all(plan["soc"] is None and plan["power"] is None for plan in discharge)


def test_frame_without_the_fields_reports_nothing():
    assert decode_operating_mode(b"") is None
    assert decode_plans(b"") is None
