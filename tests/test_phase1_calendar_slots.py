"""
Test Phase 1 calendar slot suggestions functionality.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Lead
from app.services.calendar_service import (
    format_slot_suggestions,
    get_available_slots,
    send_slot_suggestions_to_client,
)


def test_get_available_slots_returns_mock_slots():
    """Test that get_available_slots returns mock slots when calendar not enabled."""
    # Calendar not enabled by default
    slots = get_available_slots(
        duration_minutes=180,
        max_results=8,
    )

    assert len(slots) > 0
    assert len(slots) <= 8

    # Verify slot structure
    for slot in slots:
        assert "start" in slot
        assert "end" in slot
        assert isinstance(slot["start"], datetime)
        assert isinstance(slot["end"], datetime)
        assert slot["end"] > slot["start"]


def test_get_available_slots_respects_time_window():
    """Test that get_available_slots respects time_min and time_max."""
    time_min = datetime.now(UTC) + timedelta(days=1)
    time_max = time_min + timedelta(days=7)

    slots = get_available_slots(
        time_min=time_min,
        time_max=time_max,
        duration_minutes=180,
        max_results=10,
    )

    for slot in slots:
        assert slot["start"] >= time_min
        assert slot["end"] <= time_max


def test_get_available_slots_respects_duration():
    """Test that slots have the correct duration."""
    duration_minutes = 240  # 4 hours

    slots = get_available_slots(
        duration_minutes=duration_minutes,
        max_results=5,
    )

    for slot in slots:
        duration = (slot["end"] - slot["start"]).total_seconds() / 60
        assert duration == duration_minutes


def test_format_slot_suggestions_empty_list():
    """Test formatting when no slots are available."""
    message = format_slot_suggestions([])

    assert "checking my calendar" in message.lower() or "available" in message.lower()


def test_format_slot_suggestions_formats_correctly():
    """Test that slot suggestions are formatted correctly."""
    slots = [
        {
            "start": datetime(2026, 2, 15, 10, 0, tzinfo=UTC),
            "end": datetime(2026, 2, 15, 13, 0, tzinfo=UTC),
        },
        {
            "start": datetime(2026, 2, 17, 14, 0, tzinfo=UTC),
            "end": datetime(2026, 2, 17, 17, 0, tzinfo=UTC),
        },
    ]

    message = format_slot_suggestions(slots)

    assert "Available Booking Slots" in message
    assert "February 15" in message or "15" in message
    assert "10:00" in message or "10" in message
    assert len(slots) <= message.count(".")  # Each slot should have a number


def test_format_slot_suggestions_limits_to_10():
    """Test that formatting limits to 10 slots."""
    # Create 15 slots
    slots = []
    base_date = datetime.now(UTC) + timedelta(days=1)
    for i in range(15):
        slots.append(
            {
                "start": base_date + timedelta(days=i, hours=10),
                "end": base_date + timedelta(days=i, hours=13),
            }
        )

    message = format_slot_suggestions(slots)

    # Should only show 10 slots (count numbered list items)
    lines = message.split("\n")
    slot_lines = [
        line
        for line in lines
        if line.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10."))
    ]
    assert len(slot_lines) <= 10


@pytest.mark.asyncio
async def test_send_slot_suggestions_to_client(db):
    """Test sending slot suggestions to client."""
    lead = Lead(
        wa_from="1234567890",
        status="BOOKING_PENDING",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch("app.services.whatsapp_window.send_with_window_check", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        result = await send_slot_suggestions_to_client(
            db=db,
            lead=lead,
            dry_run=True,
        )

        assert result is True
        # Verify message was sent (or would be sent in dry_run)
        db.refresh(lead)
        assert lead.last_bot_message_at is not None


@pytest.mark.asyncio
async def test_send_slot_suggestions_handles_error(db):
    """Test that send_slot_suggestions handles errors gracefully."""
    lead = Lead(
        wa_from="1234567890",
        status="BOOKING_PENDING",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Force an error by making get_available_slots fail
    with patch("app.services.calendar_service.get_available_slots") as mock_slots:
        mock_slots.side_effect = Exception("Calendar API error")

        result = await send_slot_suggestions_to_client(
            db=db,
            lead=lead,
            dry_run=True,
        )

        # Should return False on error
        assert result is False


@pytest.mark.asyncio
async def test_slot_suggestions_integration_with_webhook(db):
    """Test that slot suggestions are sent after deposit is paid (integration test)."""
    from sqlalchemy import func

    lead = Lead(
        wa_from="1234567890",
        status="BOOKING_PENDING",
        deposit_paid_at=func.now(),
        deposit_amount_pence=15000,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch("app.services.whatsapp_window.send_with_window_check", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}

        # Simulate what webhook does
        result = await send_slot_suggestions_to_client(
            db=db,
            lead=lead,
            dry_run=True,
        )

        assert result is True
        assert mock_send.called
