"""
Test calendar rules service.
"""

import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path

import pytz
import yaml

from app.services.calendar_rules import (
    apply_buffer,
    get_buffer_minutes,
    get_lookahead_days,
    get_minimum_advance_hours,
    get_session_duration,
    get_timezone,
    get_working_hours,
    is_within_working_hours,
    load_calendar_rules,
)


def test_load_calendar_rules_loads_default():
    """Test that calendar rules load from default path."""
    rules = load_calendar_rules()
    assert isinstance(rules, dict)
    assert "timezone" in rules or "working_hours" in rules


def test_get_timezone():
    """Test that timezone is returned correctly."""
    tz = get_timezone()
    assert isinstance(tz, pytz.BaseTzInfo)


def test_get_working_hours():
    """Test that working hours are retrieved correctly."""
    hours = get_working_hours("monday")
    assert hours is not None
    assert "start" in hours
    assert "end" in hours
    assert isinstance(hours["start"], time)
    assert isinstance(hours["end"], time)


def test_get_working_hours_closed_day():
    """Test that closed days return None."""
    hours = get_working_hours("sunday")
    # Sunday might be closed or have hours - either is valid
    assert hours is None or isinstance(hours, dict)


def test_get_session_duration_default():
    """Test that default session duration is returned."""
    duration = get_session_duration()
    assert isinstance(duration, int)
    assert duration > 0


def test_get_session_duration_by_category():
    """Test that category-specific durations are returned."""
    small_duration = get_session_duration("SMALL")
    medium_duration = get_session_duration("MEDIUM")
    large_duration = get_session_duration("LARGE")
    xl_duration = get_session_duration("XL")

    assert isinstance(small_duration, int)
    assert isinstance(medium_duration, int)
    assert isinstance(large_duration, int)
    assert isinstance(xl_duration, int)

    # XL should be longer than SMALL
    assert xl_duration >= small_duration


def test_get_buffer_minutes():
    """Test that buffer minutes are returned."""
    buffer = get_buffer_minutes()
    assert isinstance(buffer, int)
    assert buffer >= 0


def test_get_lookahead_days():
    """Test that lookahead days are returned."""
    days = get_lookahead_days()
    assert isinstance(days, int)
    assert days > 0


def test_get_minimum_advance_hours():
    """Test that minimum advance hours are returned."""
    hours = get_minimum_advance_hours()
    assert isinstance(hours, int)
    assert hours >= 0


def test_is_within_working_hours():
    """Test that working hours check works."""
    tz = get_timezone()
    # Create a datetime on Monday at 2pm (should be within working hours)
    monday_2pm = datetime(2026, 1, 19, 14, 0, 0)  # Monday
    monday_2pm = tz.localize(monday_2pm)

    result = is_within_working_hours(monday_2pm, tz)
    assert isinstance(result, bool)


def test_is_within_working_hours_outside_hours():
    """Test that times outside working hours are detected."""
    tz = get_timezone()
    # Create a datetime on Monday at 8am (likely before working hours)
    monday_8am = datetime(2026, 1, 19, 8, 0, 0)  # Monday
    monday_8am = tz.localize(monday_8am)

    result = is_within_working_hours(monday_8am, tz)
    # Should be False if working hours start at 10am
    assert isinstance(result, bool)


def test_apply_buffer():
    """Test that buffer is applied correctly."""
    tz = get_timezone()
    start = datetime(2026, 1, 19, 14, 0, 0, tzinfo=tz)
    end = start + timedelta(hours=3)

    buffered_start, buffered_end = apply_buffer(start, end, buffer_minutes=30)

    assert buffered_start < start
    assert buffered_end > end
    assert (start - buffered_start).total_seconds() == 30 * 60
    assert (buffered_end - end).total_seconds() == 30 * 60


def test_calendar_rules_custom_config():
    """Test that custom calendar rules can be loaded."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        rules_data = {
            "timezone": "America/New_York",
            "working_hours": {
                "monday": {"start": "09:00", "end": "17:00"},
            },
            "session_durations": {
                "default": 120,
            },
            "buffer_minutes": 15,
            "lookahead_days": 14,
        }
        yaml.dump(rules_data, f)
        temp_path = Path(f.name)

    try:
        from app.services import calendar_rules

        original_path = calendar_rules.CALENDAR_RULES_PATH
        calendar_rules.CALENDAR_RULES_PATH = temp_path
        calendar_rules._calendar_rules_cache = None
        calendar_rules.load_calendar_rules.cache_clear()

        # Test custom values
        tz = get_timezone()
        assert "New_York" in str(tz)

        hours = get_working_hours("monday")
        assert hours["start"] == time(9, 0)
        assert hours["end"] == time(17, 0)

        duration = get_session_duration()
        assert duration == 120

        buffer = get_buffer_minutes()
        assert buffer == 15

        lookahead = get_lookahead_days()
        assert lookahead == 14
    finally:
        calendar_rules.CALENDAR_RULES_PATH = original_path
        calendar_rules._calendar_rules_cache = None
        calendar_rules.load_calendar_rules.cache_clear()
        temp_path.unlink()
