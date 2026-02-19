"""
Tests for Outbox-lite (feature-flagged).
"""

from app.core.config import settings
from app.db.models import Lead
from app.services.outbox_service import mark_outbox_failed, mark_outbox_sent, write_outbox


def test_write_outbox_returns_none_when_disabled(db, monkeypatch):
    """When OUTBOX_ENABLED=false, write_outbox returns None."""
    monkeypatch.setattr(settings, "outbox_enabled", False)
    result = write_outbox(db, 1, "1234567890", "Hello")
    assert result is None


def test_write_outbox_creates_row_when_enabled(db, monkeypatch):
    """When OUTBOX_ENABLED=true, write_outbox creates PENDING row."""
    monkeypatch.setattr(settings, "outbox_enabled", True)

    lead = Lead(wa_from="1234567890", status="NEW")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    outbox = write_outbox(db, lead.id, lead.wa_from, "Hello")
    assert outbox is not None
    assert outbox.status == "PENDING"
    assert outbox.attempts == 0
    assert outbox.payload_json == {"to": "1234567890", "message": "Hello"}


def test_mark_outbox_sent(db, monkeypatch):
    """mark_outbox_sent sets status SENT."""
    monkeypatch.setattr(settings, "outbox_enabled", True)

    lead = Lead(wa_from="1234567890", status="NEW")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    outbox = write_outbox(db, lead.id, lead.wa_from, "Hi")
    assert outbox is not None
    assert outbox.status == "PENDING"
    mark_outbox_sent(db, outbox)
    db.refresh(outbox)
    assert outbox.status == "SENT"
    assert outbox.attempts == 1


def test_mark_outbox_failed_schedules_retry(db, monkeypatch):
    """mark_outbox_failed sets FAILED and next_retry_at."""
    monkeypatch.setattr(settings, "outbox_enabled", True)

    lead = Lead(wa_from="1234567890", status="NEW")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    outbox = write_outbox(db, lead.id, lead.wa_from, "Hi")
    assert outbox is not None
    mark_outbox_failed(db, outbox, ValueError("Send failed"))
    db.refresh(outbox)
    assert outbox.status == "FAILED"
    assert outbox.attempts == 1
    assert outbox.last_error == "Send failed"
    assert outbox.next_retry_at is not None
