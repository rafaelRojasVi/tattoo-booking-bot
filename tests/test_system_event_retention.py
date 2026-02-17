"""
Tests for SystemEvent retention cleanup.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.db.models import Lead, SystemEvent
from app.services.system_event_service import cleanup_old_events, info


def test_cleanup_old_events_deletes_older_than_cutoff(db):
    """Cleanup deletes events older than cutoff (frozen time)."""
    lead = Lead(wa_from="1234567890", status="NEW")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    info(db, event_type="test.old1", lead_id=lead.id)
    info(db, event_type="test.old2", lead_id=lead.id)
    info(db, event_type="test.recent", lead_id=lead.id)

    events = db.query(SystemEvent).order_by(SystemEvent.id).all()
    assert len(events) == 3

    from sqlalchemy import text

    # Set first two events to 100 days ago
    old_date = datetime.now(UTC) - timedelta(days=100)
    for e in events[:2]:
        db.execute(text("UPDATE system_events SET created_at = :t WHERE id = :id"), {"t": old_date, "id": e.id})
    db.commit()

    cutoff = datetime.now(UTC) - timedelta(days=90)
    deleted = cleanup_old_events(db, cutoff=cutoff)

    remaining = db.query(SystemEvent).all()
    assert len(remaining) == 1
    assert remaining[0].event_type == "test.recent"
    assert deleted == 2


def test_cleanup_old_events_retention_days(db):
    """Cleanup with retention_days parameter."""
    lead = Lead(wa_from="1234567890", status="NEW")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    info(db, event_type="test.event", lead_id=lead.id)
    events = db.query(SystemEvent).all()
    assert len(events) == 1

    from sqlalchemy import text

    # Set created_at to 100 days ago
    old_date = datetime.now(UTC) - timedelta(days=100)
    db.execute(text("UPDATE system_events SET created_at = :t"), {"t": old_date})
    db.commit()

    deleted = cleanup_old_events(db, retention_days=90)
    assert deleted == 1
    assert db.query(SystemEvent).count() == 0
