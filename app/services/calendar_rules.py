"""
Calendar rules service - loads and applies calendar rules for slot suggestions.
"""

import logging
from datetime import datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import pytz
import yaml

logger = logging.getLogger(__name__)

# Default calendar rules path
CALENDAR_RULES_PATH = Path(__file__).parent.parent / "config" / "calendar_rules.yml"

# In-memory cache for calendar rules
_calendar_rules_cache: dict[str, Any] | None = None


@lru_cache(maxsize=1)
def load_calendar_rules() -> dict[str, Any]:
    """
    Load calendar rules configuration from YAML file.
    Cached for performance.

    Returns:
        Dict with calendar rules configuration
    """
    global _calendar_rules_cache

    if _calendar_rules_cache is not None:
        return _calendar_rules_cache

    try:
        if CALENDAR_RULES_PATH.exists():
            with open(CALENDAR_RULES_PATH, encoding="utf-8") as f:
                _calendar_rules_cache = yaml.safe_load(f) or {}
                logger.info(f"Loaded calendar rules from {CALENDAR_RULES_PATH}")
        else:
            logger.warning(
                f"Calendar rules file not found at {CALENDAR_RULES_PATH}, using defaults"
            )
            _calendar_rules_cache = _get_default_rules()
    except Exception as e:
        logger.error(f"Failed to load calendar rules: {e}, using defaults")
        _calendar_rules_cache = _get_default_rules()

    return _calendar_rules_cache


def _get_default_rules() -> dict[str, Any]:
    """Get default calendar rules if file not found."""
    return {
        "timezone": "Europe/London",
        "working_hours": {
            "monday": {"start": "10:00", "end": "18:00"},
            "tuesday": {"start": "10:00", "end": "18:00"},
            "wednesday": {"start": "10:00", "end": "18:00"},
            "thursday": {"start": "10:00", "end": "18:00"},
            "friday": {"start": "10:00", "end": "18:00"},
            "saturday": {"start": "10:00", "end": "16:00"},
            "sunday": {"start": None, "end": None},
        },
        "session_durations": {
            "default": 180,
            "by_category": {
                "SMALL": 120,
                "MEDIUM": 180,
                "LARGE": 240,
                "XL": 360,
            },
        },
        "buffer_minutes": 30,
        "lookahead_days": 21,
        "minimum_advance_hours": 24,
        "block_all_day_events": True,
    }


def get_timezone() -> pytz.timezone:
    """
    Get the configured timezone.

    Returns:
        pytz timezone object
    """
    rules = load_calendar_rules()
    tz_name = rules.get("timezone", "Europe/London")
    return pytz.timezone(tz_name)


def get_working_hours(weekday: str) -> dict[str, time] | None:
    """
    Get working hours for a weekday.

    Args:
        weekday: Day name (monday, tuesday, etc.)

    Returns:
        Dict with 'start' and 'end' time objects, or None if closed
    """
    rules = load_calendar_rules()
    working_hours = rules.get("working_hours", {})
    day_hours = working_hours.get(weekday.lower(), {})

    if not day_hours or day_hours.get("start") is None:
        return None

    start_str = day_hours["start"]
    end_str = day_hours["end"]

    try:
        start_time = datetime.strptime(start_str, "%H:%M").time()
        end_time = datetime.strptime(end_str, "%H:%M").time()
        return {"start": start_time, "end": end_time}
    except (ValueError, TypeError):
        return None


def get_session_duration(category: str | None = None) -> int:
    """
    Get session duration in minutes for a category.

    Args:
        category: Estimated category (SMALL, MEDIUM, LARGE, XL) or None for default

    Returns:
        Duration in minutes
    """
    rules = load_calendar_rules()
    durations = rules.get("session_durations", {})

    if category and "by_category" in durations:
        category_duration = durations["by_category"].get(category)
        if category_duration is not None:
            return cast(int, category_duration)

    return cast(int, durations.get("default", 180))


def get_buffer_minutes() -> int:
    """Get buffer time in minutes between sessions."""
    rules = load_calendar_rules()
    return cast(int, rules.get("buffer_minutes", 30))


def get_lookahead_days() -> int:
    """Get lookahead window in days for slot suggestions."""
    rules = load_calendar_rules()
    return cast(int, rules.get("lookahead_days", 21))


def get_minimum_advance_hours() -> int:
    """Get minimum advance booking time in hours."""
    rules = load_calendar_rules()
    return cast(int, rules.get("minimum_advance_hours", 24))


def should_block_all_day_events() -> bool:
    """Check if all-day events should block entire days."""
    rules = load_calendar_rules()
    return cast(bool, rules.get("block_all_day_events", True))


def is_within_working_hours(dt: datetime, tz: Any | None = None) -> bool:
    """
    Check if a datetime is within working hours.

    Args:
        dt: Datetime to check
        tz: Timezone (default: from rules)

    Returns:
        True if within working hours, False otherwise
    """
    if tz is None:
        tz = get_timezone()

    # Convert to calendar timezone
    if dt.tzinfo is None:
        dt = tz.localize(dt)
    else:
        dt = dt.astimezone(tz)

    weekday = dt.strftime("%A").lower()
    hours = get_working_hours(weekday)

    if not hours:
        return False  # Closed on this day

    dt_time = dt.time()
    return hours["start"] <= dt_time <= hours["end"]


def apply_buffer(
    start: datetime, end: datetime, buffer_minutes: int | None = None
) -> tuple[datetime, datetime]:
    """
    Apply buffer time to a slot (add buffer before start and after end).

    Args:
        start: Slot start time
        end: Slot end time
        buffer_minutes: Buffer in minutes (default: from rules)

    Returns:
        Tuple of (buffered_start, buffered_end)
    """
    if buffer_minutes is None:
        buffer_minutes = get_buffer_minutes()

    buffered_start = start - timedelta(minutes=buffer_minutes)
    buffered_end = end + timedelta(minutes=buffer_minutes)

    return buffered_start, buffered_end
