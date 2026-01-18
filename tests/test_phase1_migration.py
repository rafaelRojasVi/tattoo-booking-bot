"""
Test Phase 1 migration - verify all new fields are added correctly.
"""

from datetime import UTC

from sqlalchemy import inspect

from app.db.models import Lead


def test_phase1_migration_fields_exist(db):
    """Test that all Phase 1 fields exist in the Lead table after migration."""
    # Use the db session's bind (engine) to inspect
    inspector = inspect(db.bind)
    columns = {col["name"]: col for col in inspector.get_columns("leads")}

    # Tour fields
    assert "requested_city" in columns
    assert "requested_country" in columns
    assert "offered_tour_city" in columns
    assert "offered_tour_dates_text" in columns
    assert "tour_offer_accepted" in columns
    assert "waitlisted" in columns

    # Estimation fields
    assert "complexity_level" in columns
    assert "estimated_category" in columns
    assert "estimated_deposit_amount" in columns
    assert "min_budget_amount" in columns
    assert "below_min_budget" in columns

    # Instagram
    assert "instagram_handle" in columns

    # Calendar fields
    assert "calendar_event_id" in columns
    assert "calendar_start_at" in columns
    assert "calendar_end_at" in columns

    # Handover fields
    assert "handover_reason" in columns
    assert "preferred_handover_channel" in columns
    assert "call_availability_notes" in columns

    # Phase 1 funnel timestamps
    assert "qualifying_started_at" in columns
    assert "qualifying_completed_at" in columns
    assert "pending_approval_at" in columns
    assert "needs_follow_up_at" in columns
    assert "needs_artist_reply_at" in columns
    assert "stale_at" in columns
    assert "abandoned_at" in columns
    assert "booking_pending_at" in columns
    assert "deposit_sent_at" in columns


def test_phase1_fields_can_be_set(db):
    """Test that Phase 1 fields can be set and retrieved."""
    lead = Lead(
        wa_from="1234567890",
        status="NEW",
        # Tour fields
        requested_city="London",
        requested_country="UK",
        offered_tour_city="Manchester",
        offered_tour_dates_text="March 15-20, 2026",
        tour_offer_accepted=True,
        waitlisted=False,
        # Estimation fields
        complexity_level=2,
        estimated_category="MEDIUM",
        estimated_deposit_amount=15000,  # £150 in pence
        min_budget_amount=40000,  # £400 in pence
        below_min_budget=False,
        # Instagram
        instagram_handle="@testuser",
        # Calendar fields
        calendar_event_id="cal_event_123",
        # Handover fields
        handover_reason="Complex coverup",
        preferred_handover_channel="CALL",
        call_availability_notes="Available Mon-Fri 10am-2pm",
    )

    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Verify tour fields
    assert lead.requested_city == "London"
    assert lead.requested_country == "UK"
    assert lead.offered_tour_city == "Manchester"
    assert lead.offered_tour_dates_text == "March 15-20, 2026"
    assert lead.tour_offer_accepted is True
    assert lead.waitlisted is False

    # Verify estimation fields
    assert lead.complexity_level == 2
    assert lead.estimated_category == "MEDIUM"
    assert lead.estimated_deposit_amount == 15000
    assert lead.min_budget_amount == 40000
    assert lead.below_min_budget is False

    # Verify Instagram
    assert lead.instagram_handle == "@testuser"

    # Verify calendar fields
    assert lead.calendar_event_id == "cal_event_123"

    # Verify handover fields
    assert lead.handover_reason == "Complex coverup"
    assert lead.preferred_handover_channel == "CALL"
    assert lead.call_availability_notes == "Available Mon-Fri 10am-2pm"


def test_phase1_timestamps_can_be_set(db):
    """Test that Phase 1 timestamp fields can be set."""
    from datetime import datetime

    now = datetime.now(UTC)

    lead = Lead(
        wa_from="1234567891",
        status="QUALIFYING",
        qualifying_started_at=now,
        qualifying_completed_at=now,
        pending_approval_at=now,
        needs_follow_up_at=now,
        needs_artist_reply_at=now,
        stale_at=now,
        abandoned_at=now,
        booking_pending_at=now,
        deposit_sent_at=now,
    )

    db.add(lead)
    db.commit()
    db.refresh(lead)

    assert lead.qualifying_started_at is not None
    assert lead.qualifying_completed_at is not None
    assert lead.pending_approval_at is not None
    assert lead.needs_follow_up_at is not None
    assert lead.needs_artist_reply_at is not None
    assert lead.stale_at is not None
    assert lead.abandoned_at is not None
    assert lead.booking_pending_at is not None
    assert lead.deposit_sent_at is not None


def test_phase1_fields_are_nullable(db):
    """Test that Phase 1 fields are nullable (can be None)."""
    lead = Lead(
        wa_from="1234567892",
        status="NEW",
        # All Phase 1 fields should be None by default
    )

    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Verify all Phase 1 fields are None
    assert lead.requested_city is None
    assert lead.complexity_level is None
    assert lead.estimated_category is None
    assert lead.instagram_handle is None
    assert lead.calendar_event_id is None
    assert lead.handover_reason is None
    assert lead.qualifying_started_at is None
    assert lead.deposit_sent_at is None
