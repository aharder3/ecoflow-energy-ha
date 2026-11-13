"""Tests for the weekday text of a Stream plan ("MO-FR", "MO;DI;DO")."""

from __future__ import annotations

import re

import pytest
from ecoflow_energy.ecoflow.stream_days import TEXT_PATTERN, format_days, parse_days

WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("MO;DI;MI;DO;FR;SA;SO", WEEK),
        ("MO-SO", WEEK),
        ("MO-FR", WEEK[:5]),
        ("mo-mi; sa", ["mon", "tue", "wed", "sat"]),
        ("MO,DI", ["mon", "tue"]),
        ("Mon-Fri", WEEK[:5]),
        ("SA-MO", ["mon", "sat", "sun"]),
        ("DO", ["thu"]),
        ("DO;MO;DO", ["mon", "thu"]),
    ],
)
def test_text_is_read_as_weekdays(text, expected):
    assert parse_days(text) == expected


@pytest.mark.parametrize(
    "text", ["", "   ", ";", "XX", "MO-", "MO-XX", "MO-DI-MI", "MO;;XX", "1-5"]
)
def test_invalid_text_is_rejected(text):
    assert parse_days(text) is None


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (WEEK, "MO-SO"),
        (WEEK[:5], "MO-FR"),
        (["mon", "tue", "thu", "sat", "sun"], "MO;DI;DO;SA;SO"),
        (["mon", "tue", "thu", "fri", "sat"], "MO;DI;DO-SA"),
        (["sat", "sun"], "SA;SO"),
        (["fri"], "FR"),
        ([], ""),
    ],
)
def test_weekdays_are_written_in_the_shortest_form(days, expected):
    assert format_days(days) == expected


def test_every_selection_survives_a_round_trip():
    for mask in range(1, 128):
        days = [day for index, day in enumerate(WEEK) if mask >> index & 1]
        assert parse_days(format_days(days)) == days


@pytest.mark.parametrize("text", ["MO-FR", "MO;DI;DO", " mo - fr ; sa", "Mon,Tue"])
def test_the_home_assistant_pattern_accepts_the_shapes_the_parser_reads(text):
    assert re.match(TEXT_PATTERN, text)


@pytest.mark.parametrize("text", ["", "M", "MO-", "-FR", "MO;", "MO FR", "1;2"])
def test_the_home_assistant_pattern_refuses_other_shapes(text):
    assert not re.match(TEXT_PATTERN, text)
