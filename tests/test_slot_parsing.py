"""
Tests for slot selection parsing.

Tests various reply formats: numbers, "option X", day+time, time-based.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.db.models import Lead, SystemEvent
from app.services.parsing.slot_parsing import (
    format_slot_selection_prompt,
    get_slot_parse_stats,
    parse_slot_selection,
    parse_slot_selection_logged,
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


def test_parse_slot_selection_pure_returns_metadata(sample_slots):
    """Pure parse_slot_selection returns (index, metadata) without side effects."""
    index, meta = parse_slot_selection("3", sample_slots)
    assert index == 3
    assert meta == {"matched_by": "number"}

    index, meta = parse_slot_selection("I have 3 questions", sample_slots)
    assert index is None
    assert meta == {"reason": "no_intent"}


def test_parse_slot_selection_direct_number(sample_slots):
    """Test parsing direct number replies: '1', '2', etc."""
    assert parse_slot_selection_logged("1", sample_slots) == 1
    assert parse_slot_selection_logged("2", sample_slots) == 2
    assert parse_slot_selection_logged("8", sample_slots) == 8
    assert parse_slot_selection_logged("5", sample_slots) == 5


def test_parse_slot_selection_option_number(sample_slots):
    """Test parsing 'option X', 'number X', 'slot X' formats."""
    assert parse_slot_selection_logged("option 1", sample_slots) == 1
    assert parse_slot_selection_logged("option 3", sample_slots) == 3
    assert parse_slot_selection_logged("number 5", sample_slots) == 5
    assert parse_slot_selection_logged("slot 2", sample_slots) == 2
    assert parse_slot_selection_logged("choice 4", sample_slots) == 4
    assert parse_slot_selection_logged("#6", sample_slots) == 6


def test_parse_slot_selection_day_time(sample_slots):
    """Test parsing day + time descriptions."""
    # Monday morning (slot 1 is Monday 10am)
    assert parse_slot_selection_logged("Monday morning", sample_slots) == 1
    assert parse_slot_selection_logged("monday morning", sample_slots) == 1
    assert parse_slot_selection_logged("Mon morning", sample_slots) == 1

    # Monday afternoon (slot 2 is Monday 2pm)
    assert parse_slot_selection_logged("Monday afternoon", sample_slots) == 2
    assert parse_slot_selection_logged("monday afternoon", sample_slots) == 2

    # Wednesday morning (slot 4 is Wednesday 10am)
    assert parse_slot_selection_logged("Wednesday morning", sample_slots) == 4
    assert parse_slot_selection_logged("wed morning", sample_slots) == 4


def test_parse_slot_selection_time_based(sample_slots):
    """Test parsing time-based selections."""
    # "the 5pm one" - should match slot 3 (Monday 4pm, closest to 5pm)
    # Actually, let's check what times we have: 10am, 2pm, 4pm
    # "the 2pm one" should match slot 2 (Monday 2pm)
    assert parse_slot_selection_logged("the 2pm one", sample_slots) == 2
    assert parse_slot_selection_logged("2pm slot", sample_slots) == 2
    assert parse_slot_selection_logged("10am", sample_slots) == 1
    assert parse_slot_selection_logged("the 10am one", sample_slots) == 1
    assert parse_slot_selection_logged("4pm", sample_slots) == 3


def test_parse_slot_selection_time_with_minutes(sample_slots):
    """Test parsing time with minutes."""
    # "2:00pm" should match slot 2 (Monday 2pm)
    assert parse_slot_selection_logged("2:00pm", sample_slots) == 2
    assert parse_slot_selection_logged("10:00am", sample_slots) == 1
    # "4:00pm" should match slot 3 (Monday 4pm = 16:00)
    # Note: Time-based matching finds closest time within 30 minutes
    result = parse_slot_selection_logged("the 4:00pm one", sample_slots)
    # Should match slot 3 (Monday 4pm = 16:00, diff = 0) or slot 6 (Wednesday 4pm = 16:00, diff = 0)
    # Both are exact matches, so either is acceptable
    assert result in [3, 6]  # Both Monday 4pm and Wednesday 4pm are exact matches


def test_parse_slot_selection_invalid_number(sample_slots):
    """Test that invalid numbers return None."""
    assert parse_slot_selection_logged("9", sample_slots) is None  # Out of range
    assert parse_slot_selection_logged("0", sample_slots) is None  # Out of range
    assert parse_slot_selection_logged("10", sample_slots) is None  # Out of range


def test_parse_slot_selection_no_match(sample_slots):
    """Test that unrecognized formats return None."""
    assert parse_slot_selection_logged("maybe", sample_slots) is None
    assert parse_slot_selection_logged("I don't know", sample_slots) is None
    assert parse_slot_selection_logged("", sample_slots) is None
    assert parse_slot_selection_logged("   ", sample_slots) is None


def test_parse_slot_selection_case_insensitive(sample_slots):
    """Test that parsing is case-insensitive."""
    assert parse_slot_selection_logged("OPTION 1", sample_slots) == 1
    assert parse_slot_selection_logged("Option 2", sample_slots) == 2
    assert parse_slot_selection_logged("MONDAY MORNING", sample_slots) == 1
    assert parse_slot_selection_logged("The 2PM One", sample_slots) == 2


def test_parse_slot_selection_with_context(sample_slots):
    """Test parsing with additional context in message."""
    assert parse_slot_selection_logged("I'd like option 3 please", sample_slots) == 3
    assert parse_slot_selection_logged("Can I have number 5?", sample_slots) == 5
    # "Tuesday afternoon" - no Tuesday slot, should return None
    # Day matching requires exact day match, so Tuesday won't match Monday slots
    assert parse_slot_selection_logged("Tuesday afternoon works for me", sample_slots) is None
    assert parse_slot_selection_logged("Monday afternoon would be great", sample_slots) == 2


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
    assert parse_slot_selection_logged("1", []) is None

    # Message with number but NOT slot intent — must return None (anti-false-positive)
    assert parse_slot_selection_logged("I have 3 questions", sample_slots) is None
    assert parse_slot_selection_logged("Call me at 5", sample_slots) is None

    # Multiple numbers → ambiguous, return None so caller sends REPAIR_SLOT / pick one
    assert parse_slot_selection_logged("option 2 or 3", sample_slots) is None


def test_parse_slot_selection_anti_false_positive_corpus(sample_slots):
    """Anti-false-positive: numbers in normal English must NOT advance."""
    # Must return None
    assert parse_slot_selection_logged("I have 3 questions", sample_slots) is None
    assert parse_slot_selection_logged("call me at 5", sample_slots) is None
    assert parse_slot_selection_logged("I'm free on 2 days", sample_slots) is None
    assert parse_slot_selection_logged("we are 4 people", sample_slots) is None
    assert parse_slot_selection_logged("I want 1 tattoo", sample_slots) is None
    assert parse_slot_selection_logged("at 5", sample_slots) is None  # ambiguous time, no am/pm


def test_parse_slot_selection_explicit_intent_accepted(sample_slots):
    """Explicit intent must be accepted."""
    assert parse_slot_selection_logged("3", sample_slots) == 3
    assert parse_slot_selection_logged("option 3", sample_slots) == 3
    assert parse_slot_selection_logged("#3", sample_slots) == 3
    assert parse_slot_selection_logged("the 2pm one", sample_slots) == 2  # time match
    assert parse_slot_selection_logged("Monday afternoon", sample_slots) == 2  # day+time


def test_parse_slot_selection_max_slots_limit(sample_slots):
    """Test that max_slots limit is respected."""
    # If we have 8 slots but max_slots=5, only 1-5 should be valid
    assert parse_slot_selection_logged("5", sample_slots, max_slots=5) == 5
    assert parse_slot_selection_logged("6", sample_slots, max_slots=5) is None
    assert parse_slot_selection_logged("8", sample_slots, max_slots=5) is None

    # max_slots=3: #6 must return None (no hardcoding 1-8)
    assert parse_slot_selection_logged("#6", sample_slots, max_slots=3) is None
    assert parse_slot_selection_logged("#3", sample_slots, max_slots=3) == 3


def test_parse_slot_selection_time_match_requires_offered_slot(sample_slots):
    """Time-based matching only accepts when it matches an offered slot."""
    # "the 2 one" — no am/pm, ambiguous → None
    assert parse_slot_selection_logged("the 2 one", sample_slots) is None

    # "2pm" — accept only if a 2pm slot exists (sample_slots has Mon 2pm = slot 2)
    assert parse_slot_selection_logged("2pm", sample_slots) == 2
    assert parse_slot_selection_logged("the 2pm one", sample_slots) == 2

    # Slots without 2pm: only 10am and 4pm → "2pm" returns None
    tz = ZoneInfo("Europe/London")
    base = datetime(2026, 1, 19, 10, 0, tzinfo=tz)
    slots_no_2pm = [
        {"start": base.replace(hour=10, minute=0), "end": base.replace(hour=13, minute=0)},
        {"start": base.replace(hour=16, minute=0), "end": base.replace(hour=19, minute=0)},
    ]
    assert parse_slot_selection_logged("2pm", slots_no_2pm) is None


def test_parse_slot_selection_24h_time_formats(sample_slots):
    """24h formats 14:00 and 14.00: accept only if matching slot exists."""
    # sample_slots has 2pm (14:00) at slot 2
    assert parse_slot_selection_logged("14:00", sample_slots) == 2
    assert parse_slot_selection_logged("14.00", sample_slots) == 2
    assert parse_slot_selection_logged("the 14:00 one", sample_slots) == 2

    # No 15:00 slot (we have 10, 14, 16) → None
    assert parse_slot_selection_logged("15:00", sample_slots) is None
    assert parse_slot_selection_logged("15.00", sample_slots) is None


def test_slot_parse_success_logs_system_event(db, sample_slots):
    """parse_success logs slot.parse_success when valid selection is made."""
    lead = Lead(wa_from="1234567890", status="BOOKING_PENDING")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = parse_slot_selection_logged("3", sample_slots, db=db, lead_id=lead.id)
    assert result == 3

    event = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.event_type == "slot.parse_success",
            SystemEvent.lead_id == lead.id,
        )
        .order_by(SystemEvent.id.desc())
        .first()
    )
    assert event is not None
    assert event.payload["chosen_index"] == 3
    assert event.payload["matched_by"] == "number"


def test_slot_parse_reject_ambiguous_logs_system_event(db, sample_slots):
    """parse_reject_ambiguous logs when 'I have 3 questions' (no intent) is rejected."""
    lead = Lead(wa_from="1234567890", status="BOOKING_PENDING")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = parse_slot_selection_logged("I have 3 questions", sample_slots, db=db, lead_id=lead.id)
    assert result is None

    event = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.event_type == "slot.parse_reject_ambiguous",
            SystemEvent.lead_id == lead.id,
        )
        .order_by(SystemEvent.id.desc())
        .first()
    )
    assert event is not None
    assert event.payload["reason"] == "no_intent"


def test_get_slot_parse_stats_with_seeded_events(db, sample_slots):
    """get_slot_parse_stats returns counts by matched_by and reject reason."""
    lead = Lead(wa_from="1234567890", status="BOOKING_PENDING")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Seed events via parse_slot_selection_logged
    parse_slot_selection_logged("3", sample_slots, db=db, lead_id=lead.id)  # number
    parse_slot_selection_logged("#2", sample_slots, db=db, lead_id=lead.id)  # hash
    parse_slot_selection_logged("option 1", sample_slots, db=db, lead_id=lead.id)  # option
    parse_slot_selection_logged(
        "I have 3 questions", sample_slots, db=db, lead_id=lead.id
    )  # no_intent
    parse_slot_selection_logged(
        "option 2 or 3", sample_slots, db=db, lead_id=lead.id
    )  # multiple_numbers

    stats = get_slot_parse_stats(db, last_days=7)

    assert stats["total_success"] == 3
    assert stats["total_reject"] == 2
    assert stats["success"]["number"] == 1
    assert stats["success"]["hash"] == 1
    assert stats["success"]["option"] == 1
    assert stats["reject"]["no_intent"] == 1
    assert stats["reject"]["multiple_numbers"] == 1
