"""
Tests for slot selection parsing.

Tests various reply formats: numbers, "option X", day+time, time-based.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.slot_parsing import (
    format_slot_selection_prompt,
    parse_slot_selection,
)


@pytest.fixture
def sample_slots():
    """Create sample slots for testing."""
    tz = ZoneInfo("Europe/London")
    # Find a Monday - Jan 19, 2026 is a Monday (weekday 0)
    base_date = datetime(2026, 1, 19, 10, 0, tzinfo=tz)  # Monday, Jan 19, 10am

    slots = []
    # Create 8 slots: Monday 10am, Monday 2pm, Monday 4pm, Wednesday 10am, etc.
    slot_configs = [
        (0, 10, 0),  # Monday 10am (slot 1)
        (0, 14, 0),  # Monday 2pm (slot 2)
        (0, 16, 0),  # Monday 4pm (slot 3)
        (2, 10, 0),  # Wednesday 10am (slot 4) - skip Tuesday
        (2, 14, 0),  # Wednesday 2pm (slot 5)
        (2, 16, 0),  # Wednesday 4pm (slot 6)
        (4, 10, 0),  # Friday 10am (slot 7) - skip Thursday
        (4, 14, 0),  # Friday 2pm (slot 8)
    ]

    for days_offset, hour, minute in slot_configs:
        slot_start = base_date + timedelta(days=days_offset)
        slot_start = slot_start.replace(hour=hour, minute=minute)
        slot_end = slot_start + timedelta(hours=3)
        slots.append({"start": slot_start, "end": slot_end})

    return slots


def test_parse_slot_selection_direct_number(sample_slots):
    """Test parsing direct number replies: '1', '2', etc."""
    assert parse_slot_selection("1", sample_slots) == 1
    assert parse_slot_selection("2", sample_slots) == 2
    assert parse_slot_selection("8", sample_slots) == 8
    assert parse_slot_selection("5", sample_slots) == 5


def test_parse_slot_selection_option_number(sample_slots):
    """Test parsing 'option X', 'number X', 'slot X' formats."""
    assert parse_slot_selection("option 1", sample_slots) == 1
    assert parse_slot_selection("option 3", sample_slots) == 3
    assert parse_slot_selection("number 5", sample_slots) == 5
    assert parse_slot_selection("slot 2", sample_slots) == 2
    assert parse_slot_selection("choice 4", sample_slots) == 4
    assert parse_slot_selection("#6", sample_slots) == 6


def test_parse_slot_selection_day_time(sample_slots):
    """Test parsing day + time descriptions."""
    # Monday morning (slot 1 is Monday 10am)
    assert parse_slot_selection("Monday morning", sample_slots) == 1
    assert parse_slot_selection("monday morning", sample_slots) == 1
    assert parse_slot_selection("Mon morning", sample_slots) == 1

    # Monday afternoon (slot 2 is Monday 2pm)
    assert parse_slot_selection("Monday afternoon", sample_slots) == 2
    assert parse_slot_selection("monday afternoon", sample_slots) == 2

    # Wednesday morning (slot 4 is Wednesday 10am)
    assert parse_slot_selection("Wednesday morning", sample_slots) == 4
    assert parse_slot_selection("wed morning", sample_slots) == 4


def test_parse_slot_selection_time_based(sample_slots):
    """Test parsing time-based selections."""
    # "the 5pm one" - should match slot 3 (Monday 4pm, closest to 5pm)
    # Actually, let's check what times we have: 10am, 2pm, 4pm
    # "the 2pm one" should match slot 2 (Monday 2pm)
    assert parse_slot_selection("the 2pm one", sample_slots) == 2
    assert parse_slot_selection("2pm slot", sample_slots) == 2
    assert parse_slot_selection("10am", sample_slots) == 1
    assert parse_slot_selection("the 10am one", sample_slots) == 1
    assert parse_slot_selection("4pm", sample_slots) == 3


def test_parse_slot_selection_time_with_minutes(sample_slots):
    """Test parsing time with minutes."""
    # "2:00pm" should match slot 2 (Monday 2pm)
    assert parse_slot_selection("2:00pm", sample_slots) == 2
    assert parse_slot_selection("10:00am", sample_slots) == 1
    # "4:00pm" should match slot 3 (Monday 4pm = 16:00)
    # Note: Time-based matching finds closest time within 30 minutes
    result = parse_slot_selection("the 4:00pm one", sample_slots)
    # Should match slot 3 (Monday 4pm = 16:00, diff = 0) or slot 6 (Wednesday 4pm = 16:00, diff = 0)
    # Both are exact matches, so either is acceptable
    assert result in [3, 6]  # Both Monday 4pm and Wednesday 4pm are exact matches


def test_parse_slot_selection_invalid_number(sample_slots):
    """Test that invalid numbers return None."""
    assert parse_slot_selection("9", sample_slots) is None  # Out of range
    assert parse_slot_selection("0", sample_slots) is None  # Out of range
    assert parse_slot_selection("10", sample_slots) is None  # Out of range


def test_parse_slot_selection_no_match(sample_slots):
    """Test that unrecognized formats return None."""
    assert parse_slot_selection("maybe", sample_slots) is None
    assert parse_slot_selection("I don't know", sample_slots) is None
    assert parse_slot_selection("", sample_slots) is None
    assert parse_slot_selection("   ", sample_slots) is None


def test_parse_slot_selection_case_insensitive(sample_slots):
    """Test that parsing is case-insensitive."""
    assert parse_slot_selection("OPTION 1", sample_slots) == 1
    assert parse_slot_selection("Option 2", sample_slots) == 2
    assert parse_slot_selection("MONDAY MORNING", sample_slots) == 1
    assert parse_slot_selection("The 2PM One", sample_slots) == 2


def test_parse_slot_selection_with_context(sample_slots):
    """Test parsing with additional context in message."""
    assert parse_slot_selection("I'd like option 3 please", sample_slots) == 3
    assert parse_slot_selection("Can I have number 5?", sample_slots) == 5
    # "Tuesday afternoon" - no Tuesday slot, should return None
    # Day matching requires exact day match, so Tuesday won't match Monday slots
    assert parse_slot_selection("Tuesday afternoon works for me", sample_slots) is None
    assert parse_slot_selection("Monday afternoon would be great", sample_slots) == 2


def test_format_slot_selection_prompt():
    """Test fallback prompt formatting."""
    prompt = format_slot_selection_prompt(max_slots=8)
    assert "1 to 8" in prompt
    assert "number" in prompt.lower()
    assert "Tuesday afternoon" in prompt or "5pm" in prompt

    prompt_5 = format_slot_selection_prompt(max_slots=5)
    assert "1 to 5" in prompt_5


def test_parse_slot_selection_edge_cases(sample_slots):
    """Test edge cases."""
    # Empty slots
    assert parse_slot_selection("1", []) is None

    # Message with number but not slot-related
    assert parse_slot_selection("I have 3 questions", sample_slots) == 3  # Still matches number
    assert parse_slot_selection("Call me at 5", sample_slots) == 5  # Still matches number

    # Multiple numbers → ambiguous, return None so caller sends REPAIR_SLOT / pick one
    assert parse_slot_selection("option 2 or 3", sample_slots) is None


def test_parse_slot_selection_max_slots_limit(sample_slots):
    """Test that max_slots limit is respected."""
    # If we have 8 slots but max_slots=5, only 1-5 should be valid
    assert parse_slot_selection("5", sample_slots, max_slots=5) == 5
    assert parse_slot_selection("6", sample_slots, max_slots=5) is None
    assert parse_slot_selection("8", sample_slots, max_slots=5) is None
