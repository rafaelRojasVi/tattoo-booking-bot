"""
Slot selection parsing - handles various reply formats for slot selection.

Supports:
- Number-based: "1", "option 3", "number 5"
- Day + time: "Tuesday afternoon", "Monday morning"
- Time-based: "the 5pm one", "3pm slot"
- Fallback: prompts user to reply with number 1-8
"""

import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


def _has_multiple_slot_numbers(message_lower: str, max_slots: int) -> bool:
    """True if message contains 2+ distinct slot numbers (1..max_slots). Used to reject '1 or 2'."""
    numbers = re.findall(r"\b([1-8])\b", message_lower)
    if not numbers:
        return False
    distinct = set(int(n) for n in numbers if 1 <= int(n) <= max_slots)
    return len(distinct) > 1


def parse_slot_selection(
    message: str,
    slots: list[dict[str, datetime]],
    max_slots: int = 8,
) -> int | None:
    """
    Parse slot selection from user message.

    Returns None if message contains multiple distinct slot numbers (e.g. "1 or 2")
    so caller can send REPAIR_SLOT / pick-one prompt.

    Args:
        message: User's reply message
        slots: List of slot dicts with 'start' and 'end' datetime objects
        max_slots: Maximum number of slots (default: 8)

    Returns:
        Slot index (1-based) if successfully parsed, None otherwise
    """
    if not message or not slots:
        return None

    from app.services.text_normalization import normalize_text

    message_lower = normalize_text(message).lower()

    # Ambiguous: multiple choices → do not pick first; trigger repair
    if _has_multiple_slot_numbers(message_lower, max_slots):
        logger.debug("Slot selection ambiguous (multiple numbers), returning None")
        return None

    # Method 1: Direct number match (1-8)
    # Exclude numbers that are part of time patterns (e.g., "4:00pm", "3pm")
    time_pattern = r"\d{1,2}\s*:?\s*\d{0,2}\s*(am|pm)"
    if not re.search(time_pattern, message_lower):
        number_match = re.search(r"\b([1-8])\b", message_lower)
        if number_match:
            slot_num = int(number_match.group(1))
            if 1 <= slot_num <= min(len(slots), max_slots):
                logger.debug(f"Parsed slot selection: number {slot_num}")
                return slot_num

    # Method 2: "option X", "number X", "slot X"
    option_patterns = [
        r"option\s+([1-8])",
        r"number\s+([1-8])",
        r"slot\s+([1-8])",
        r"choice\s+([1-8])",
        r"#([1-8])",
    ]
    for pattern in option_patterns:
        match = re.search(pattern, message_lower)
        if match:
            slot_num = int(match.group(1))
            if 1 <= slot_num <= min(len(slots), max_slots):
                logger.debug(f"Parsed slot selection: {pattern} -> {slot_num}")
                return slot_num

    # Method 3: Day + time description
    day_time_match = _parse_day_time(message_lower, slots, max_slots)
    if day_time_match:
        return day_time_match

    # Method 4: Time-based ("the 5pm one", "3pm slot")
    time_match = _parse_time_based(message_lower, slots, max_slots)
    if time_match:
        return time_match

    # No match found
    logger.debug(f"Could not parse slot selection from: {message}")
    return None


def _parse_day_time(
    message_lower: str,
    slots: list[dict[str, datetime]],
    max_slots: int,
) -> int | None:
    """Parse day + time description (e.g., 'Tuesday afternoon', 'Monday morning')."""
    # Day names
    days = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
        "mon": 0,
        "tue": 1,
        "wed": 2,
        "thu": 3,
        "fri": 4,
        "sat": 5,
        "sun": 6,
    }

    # Time descriptions
    time_keywords = {
        "morning": (6, 12),
        "afternoon": (12, 17),
        "evening": (17, 21),
        "night": (21, 24),
        "am": (0, 12),
        "pm": (12, 24),
    }

    # Find day in message
    day_match = None
    day_num = None
    for day_name, day_value in days.items():
        if day_name in message_lower:
            day_match = day_name
            day_num = day_value
            break

    if not day_match:
        return None

    # Find time description
    time_range = None
    for time_keyword, (start_hour, end_hour) in time_keywords.items():
        if time_keyword in message_lower:
            time_range = (start_hour, end_hour)
            break

    # Match slots by day and optionally time
    # Note: Python weekday() returns 0=Monday, 6=Sunday
    for i, slot in enumerate(slots[:max_slots], 1):
        start = slot["start"]
        slot_day = start.weekday()  # 0=Monday, 6=Sunday
        slot_hour = start.hour

        if slot_day == day_num:
            if time_range:
                # Check if slot hour is within time range
                if time_range[0] <= slot_hour < time_range[1]:
                    logger.debug(f"Matched slot {i} by day+time: {day_match} {time_range}")
                    return i
            else:
                # Just day match, return first matching slot
                logger.debug(f"Matched slot {i} by day: {day_match}")
                return i

    return None


def _parse_time_based(
    message_lower: str,
    slots: list[dict[str, datetime]],
    max_slots: int,
) -> int | None:
    """Parse time-based selection (e.g., 'the 5pm one', '3pm slot')."""
    # Extract time patterns: "5pm", "3:30pm", "10am", etc.
    # Pattern 1: "5:30pm" or "10:00am" (with minutes)
    pattern1 = r"(\d{1,2})\s*:\s*(\d{2})\s*(am|pm)"
    match = re.search(pattern1, message_lower)
    if match:
        hour_str = match.group(1)
        minute_str = match.group(2)
        period = match.group(3).lower()
    else:
        # Pattern 2: "5pm" or "10am" (no minutes)
        pattern2 = r"(\d{1,2})\s*(am|pm)"
        match = re.search(pattern2, message_lower)
        if match:
            hour_str = match.group(1)
            minute_str = "0"
            period = match.group(2).lower()
        else:
            return None

    try:
        hour = int(hour_str)
        minute = int(minute_str) if minute_str else 0

        # Convert to 24-hour format
        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0

        # Find closest matching slot
        best_match = None
        min_diff = float("inf")

        for i, slot in enumerate(slots[:max_slots], 1):
            start = slot["start"]
            slot_hour = start.hour
            slot_minute = start.minute

            # Calculate time difference (in minutes)
            diff = abs((hour * 60 + minute) - (slot_hour * 60 + slot_minute))

            # Prefer exact matches or close matches (within 30 minutes)
            if diff < min_diff and diff <= 30:
                min_diff = diff
                best_match = i

        if best_match:
            logger.debug(f"Matched slot {best_match} by time: {hour}:{minute:02d}")
            return best_match

    except ValueError:
        pass

    return None


def format_slot_selection_prompt(max_slots: int = 8) -> str:
    """
    Format fallback prompt when slot selection cannot be parsed.

    Args:
        max_slots: Maximum number of slots

    Returns:
        Prompt message string
    """
    return f"Please reply with a number from 1 to {max_slots}, or describe which slot works for you (e.g., 'Tuesday afternoon' or 'the 5pm one')."
