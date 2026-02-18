"""
Slot selection parsing - handles various reply formats for slot selection.

Requires explicit intent to avoid false positives (e.g. "I have 3 questions" → slot 3).
Validates parsed numbers against effective_max (min(slot_count, max_slots)); no hardcoded 1-8.

Tier 1 (explicit intent):
- Bare number: message is just "1"-"9" (validated <= effective_max)
- Option format: "option 3", "number 5", "#3", "3)", "3."
- Day + time: "Tuesday afternoon", "Monday morning"

Tier 2 (exact time match, only when slot exists):
- "5pm", "the 5pm one", "2:00pm" — 12h with am/pm
- "14:00", "14.00" — 24h (HH:MM or HH.MM)
- "the 2 one" (no am/pm) → ambiguous, return None
- "at 5" (no am/pm) → ambiguous, return None
"""

import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


def _has_multiple_slot_numbers(message_lower: str, max_slots: int) -> bool:
    """True if message contains 2+ distinct slot numbers (1..max_slots). Used to reject '1 or 2'."""
    numbers = re.findall(r"\b([1-9])\b", message_lower)
    if not numbers:
        return False
    distinct = set(int(n) for n in numbers if 1 <= int(n) <= max_slots)
    return len(distinct) > 1


def _tier1_explicit_intent(
    message_lower: str, max_slots: int, slot_count: int
) -> tuple[int, str] | None:
    r"""
    Tier 1: Only accept when intent is explicit.
    Returns (n, match_type) or None. match_type: "number"|"hash"|"option"|"list"
    """
    stripped = message_lower.strip()
    effective_max = min(slot_count, max_slots)

    # Bare number: entire message must be just the digit (validate against effective_max)
    if re.match(r"^([1-9])$", stripped):
        n = int(stripped)
        if 1 <= n <= effective_max:
            return (n, "number")

    # Explicit option format (anywhere in message)
    option_match = re.search(
        r"(?:^|\b)(option|slot|choice|number)\s*([1-9])\b",
        message_lower,
    )
    if option_match:
        n = int(option_match.group(2))
        if 1 <= n <= effective_max:
            return (n, "option")

    # #N format (e.g. "#3", "#6") — # is non-word so \b works after the digit
    hash_match = re.search(r"#([1-9])\b", message_lower)
    if hash_match:
        n = int(hash_match.group(1))
        if 1 <= n <= effective_max:
            return (n, "hash")

    # "3)", "3.", "3:" at start
    lead_match = re.match(r"^([1-9])[\).:]", stripped)
    if lead_match:
        n = int(lead_match.group(1))
        if 1 <= n <= effective_max:
            return (n, "list")

    return None


def parse_slot_selection(
    message: str,
    slots: list[dict[str, datetime]],
    max_slots: int = 8,
) -> tuple[int | None, dict]:
    """
    Parse slot selection from user message (pure, no side effects).

    Requires explicit intent — bare numbers inside sentences (e.g. "I have 3 questions")
    return (None, metadata) to avoid false positives.

    Args:
        message: User's reply message
        slots: List of slot dicts with 'start' and 'end' datetime objects
        max_slots: Maximum number of slots (default: 8)

    Returns:
        Tuple of (index, metadata):
        - Success: (int, {"matched_by": "number"|"hash"|"option"|"list"|"time"|"daypart"})
        - Reject: (None, {"reason": "multiple_numbers"|"no_intent"|"no_time_match"|"out_of_range"})
    """
    if not message or not slots:
        return (None, {"reason": "no_message_or_slots"})

    from app.services.text_normalization import normalize_text

    message_lower = normalize_text(message).lower()
    slot_count = len(slots)
    stripped = message_lower.strip()
    effective_max = min(slot_count, max_slots)

    # Ambiguous: multiple choices → do not pick first; trigger repair
    if _has_multiple_slot_numbers(message_lower, max_slots):
        logger.debug("Slot selection ambiguous (multiple numbers), returning None")
        return (None, {"reason": "multiple_numbers"})

    # Tier 1: Explicit intent (bare number, option X, #X, 3), etc.)
    tier1 = _tier1_explicit_intent(message_lower, max_slots, slot_count)
    if tier1 is not None:
        n, match_type = tier1
        return (n, {"matched_by": match_type})

    # Tier 2a: Day + time description ("Tuesday afternoon", "Monday morning")
    day_time_match = _parse_day_time(message_lower, slots, max_slots)
    if day_time_match:
        return (day_time_match, {"matched_by": "daypart"})

    # Tier 2b: Time-based — requires am/pm or colon ("5pm", "2:00pm")
    # "at 5" (no am/pm) is ambiguous → _parse_time_based returns None
    time_match = _parse_time_based(message_lower, slots, max_slots)
    if time_match:
        return (time_match, {"matched_by": "time"})

    # Determine reject reason for observability
    if re.match(r"^([1-9])$", stripped) and int(stripped) > effective_max:
        reject_reason = "out_of_range"
    elif re.search(r"\d{1,2}\s*(am|pm)|\d{1,2}\s*[.:]\s*\d{2}", message_lower):
        reject_reason = "no_time_match"
    else:
        reject_reason = "no_intent"

    logger.debug(f"Could not parse slot selection from: {message}")
    return (None, {"reason": reject_reason})


def parse_slot_selection_logged(
    message: str,
    slots: list[dict[str, datetime]],
    max_slots: int = 8,
    *,
    db=None,
    lead_id: int | None = None,
    correlation_id: str | None = None,
) -> int | None:
    """
    Parse slot selection and log SystemEvents when db is provided.

    Calls parse_slot_selection (pure) then logs slot.parse_success or
    slot.parse_reject_ambiguous. Returns index for caller convenience.
    """
    index, metadata = parse_slot_selection(message, slots, max_slots)

    if db is not None:
        from app.services.system_event_service import info

        if index is not None:
            info(
                db,
                event_type="slot.parse_success",
                lead_id=lead_id,
                payload={"chosen_index": index, "matched_by": metadata["matched_by"]},
                correlation_id=correlation_id,
            )
        else:
            info(
                db,
                event_type="slot.parse_reject_ambiguous",
                lead_id=lead_id,
                payload={"reason": metadata["reason"]},
                correlation_id=correlation_id,
            )

    return index


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
    """Parse time-based selection (e.g., 'the 5pm one', '3pm slot', '14:00')."""
    hour_str = None
    minute_str = "0"
    period = None

    # Pattern 1: "5:30pm" or "10:00am" (12h with minutes)
    match = re.search(r"(\d{1,2})\s*:\s*(\d{2})\s*(am|pm)", message_lower)
    if match:
        hour_str, minute_str, period = match.group(1), match.group(2), match.group(3).lower()
    else:
        # Pattern 2: "5pm" or "10am" (12h, no minutes)
        match = re.search(r"(\d{1,2})\s*(am|pm)", message_lower)
        if match:
            hour_str, minute_str, period = match.group(1), "0", match.group(2).lower()
        else:
            # Pattern 3: "14:00" or "14.00" (24h) — strict: HH:MM or HH.MM, HH 0-23
            match = re.search(r"\b(0?\d|1\d|2[0-3])\s*[.:]\s*(\d{2})\b", message_lower)
            if match:
                hour_str, minute_str = match.group(1), match.group(2)
                period = None  # 24h
            else:
                return None

    try:
        hour = int(hour_str)
        minute = int(minute_str) if minute_str else 0

        # Convert to 24-hour format (12h only; 24h already is)
        if period:
            if period == "pm" and hour != 12:
                hour += 12
            elif period == "am" and hour == 12:
                hour = 0

        # Validate 24h range
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None

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


def get_slot_parse_stats(db, *, last_days: int = 7) -> dict:
    """
    Return slot parse metrics: counts by matched_by and reject reason.

    Args:
        db: Database session
        last_days: Look back this many days (default 7)

    Returns:
        Dict with "success" (matched_by counts), "reject" (reason counts), "total_success", "total_reject"
    """
    from collections import Counter
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.db.models import SystemEvent

    last_days = max(1, min(last_days, 3650))  # Clamp to avoid OverflowError
    cutoff = datetime.now(UTC) - timedelta(days=last_days)

    success_events = (
        db.execute(
            select(SystemEvent.payload).where(
                SystemEvent.event_type == "slot.parse_success",
                SystemEvent.created_at >= cutoff,
            )
        )
        .scalars()
        .all()
    )

    reject_events = (
        db.execute(
            select(SystemEvent.payload).where(
                SystemEvent.event_type == "slot.parse_reject_ambiguous",
                SystemEvent.created_at >= cutoff,
            )
        )
        .scalars()
        .all()
    )

    matched_by = dict(Counter((p or {}).get("matched_by") or "unknown" for p in success_events))
    reject_reason = dict(Counter((p or {}).get("reason") or "unknown" for p in reject_events))

    return {
        "success": matched_by,
        "reject": reject_reason,
        "total_success": sum(matched_by.values()),
        "total_reject": sum(reject_reason.values()),
    }
