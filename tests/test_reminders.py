"""
Tests for reminder service with idempotency.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import Lead, ProcessedMessage
from app.services.conversation import (
    STATUS_BOOKING_LINK_SENT,
    STATUS_DEPOSIT_PAID,
    STATUS_QUALIFYING,
)
from app.services.reminders import (
    check_and_send_booking_reminder,
    check_and_send_qualifying_reminder,
)


def test_qualifying_reminder_not_due(db):
    """Test reminder not sent if not enough time has passed."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_QUALIFYING,
        last_client_message_at=datetime.now(UTC) - timedelta(hours=10),  # Less than 12h threshold
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = check_and_send_qualifying_reminder(db, lead, reminder_number=1, dry_run=True)

    assert result["status"] == "not_due"
    assert result["hours_passed"] < 12


def test_qualifying_reminder_sent(db):
    """Test reminder sent when enough time has passed."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_QUALIFYING,
        last_client_message_at=datetime.now(UTC) - timedelta(hours=13),  # Over 12h threshold
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = check_and_send_qualifying_reminder(db, lead, reminder_number=1, dry_run=True)

    assert result["status"] == "sent"
    assert "event_id" in result
    assert lead.reminder_qualifying_sent_at is not None

    # Verify idempotency - event recorded
    event_id = result["event_id"]
    processed = db.execute(
        select(ProcessedMessage).where(ProcessedMessage.message_id == event_id)
    ).scalar_one_or_none()
    assert processed is not None
    assert processed.event_type == "reminder.qualifying.1"


def test_qualifying_reminder_idempotent(db):
    """Test reminder is idempotent (won't send twice)."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_QUALIFYING,
        last_client_message_at=datetime.now(UTC) - timedelta(hours=13),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Send first reminder
    result1 = check_and_send_qualifying_reminder(db, lead, reminder_number=1, dry_run=True)
    assert result1["status"] == "sent"

    # Try to send again
    result2 = check_and_send_qualifying_reminder(db, lead, reminder_number=1, dry_run=True)
    assert result2["status"] in ["duplicate", "already_sent"]


def test_booking_reminder_24h_sent(db):
    """Test 24h booking reminder sent."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_BOOKING_LINK_SENT,
        booking_link="https://test.com/book",
        booking_link_sent_at=datetime.now(UTC) - timedelta(hours=25),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = check_and_send_booking_reminder(
        db, lead, hours_since_booking_link=24, reminder_type="24h", dry_run=True
    )

    assert result["status"] == "sent"
    assert lead.reminder_booking_sent_24h_at is not None

    # Verify idempotency
    event_id = result["event_id"]
    processed = db.execute(
        select(ProcessedMessage).where(ProcessedMessage.message_id == event_id)
    ).scalar_one_or_none()
    assert processed is not None
    assert processed.event_type == "reminder.booking.24h"


def test_booking_reminder_72h_sent(db):
    """Test 72h booking reminder sent."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_BOOKING_LINK_SENT,
        booking_link="https://test.com/book",
        booking_link_sent_at=datetime.now(UTC) - timedelta(hours=73),
        reminder_booking_sent_24h_at=datetime.now(UTC) - timedelta(hours=50),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = check_and_send_booking_reminder(
        db, lead, hours_since_booking_link=72, reminder_type="72h", dry_run=True
    )

    assert result["status"] == "sent"
    assert lead.reminder_booking_sent_72h_at is not None


def test_reminder_wrong_status(db):
    """Test reminder not sent for wrong status."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_DEPOSIT_PAID,  # Not QUALIFYING
        last_client_message_at=datetime.now(UTC) - timedelta(hours=25),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    result = check_and_send_qualifying_reminder(db, lead, reminder_number=1, dry_run=True)

    assert result["status"] == "skipped"
    assert "not in" in result["reason"]
