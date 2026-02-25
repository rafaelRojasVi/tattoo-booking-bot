"""
Tests for state machine service.
"""

import pytest

from app.db.models import Lead, SystemEvent
from app.services.conversation import (
    STATUS_AWAITING_DEPOSIT,
    STATUS_BOOKED,
    STATUS_DEPOSIT_PAID,
    STATUS_NEEDS_ARTIST_REPLY,
    STATUS_NEW,
    STATUS_PENDING_APPROVAL,
    STATUS_QUALIFYING,
    STATUS_REJECTED,
)
from app.services.conversation.state_machine import (
    advance_step_if_at,
    get_allowed_transitions,
    is_transition_allowed,
    transition,
)


def test_is_transition_allowed_valid():
    """Test valid transitions."""
    assert is_transition_allowed(STATUS_NEW, STATUS_QUALIFYING) is True
    assert is_transition_allowed(STATUS_QUALIFYING, STATUS_PENDING_APPROVAL) is True
    assert is_transition_allowed(STATUS_PENDING_APPROVAL, STATUS_AWAITING_DEPOSIT) is True
    assert is_transition_allowed(STATUS_AWAITING_DEPOSIT, STATUS_DEPOSIT_PAID) is True
    # DEPOSIT_PAID goes to BOOKING_PENDING, not directly to BOOKED
    from app.services.conversation import STATUS_BOOKING_PENDING

    assert is_transition_allowed(STATUS_DEPOSIT_PAID, STATUS_BOOKING_PENDING) is True
    assert is_transition_allowed(STATUS_BOOKING_PENDING, STATUS_BOOKED) is True


def test_is_transition_allowed_invalid():
    """Test invalid transitions."""
    assert is_transition_allowed(STATUS_NEW, STATUS_BOOKED) is False
    assert is_transition_allowed(STATUS_BOOKED, STATUS_QUALIFYING) is False  # Terminal state
    assert is_transition_allowed(STATUS_REJECTED, STATUS_QUALIFYING) is False  # Terminal state
    assert is_transition_allowed(STATUS_PENDING_APPROVAL, STATUS_BOOKED) is False


def test_get_allowed_transitions():
    """Test getting allowed transitions."""
    transitions = get_allowed_transitions(STATUS_NEW)
    assert STATUS_QUALIFYING in transitions

    transitions = get_allowed_transitions(STATUS_QUALIFYING)
    assert STATUS_PENDING_APPROVAL in transitions
    assert STATUS_NEEDS_ARTIST_REPLY in transitions

    transitions = get_allowed_transitions(STATUS_BOOKED)
    assert len(transitions) == 0  # Terminal state


def test_transition_valid(db):
    """Test valid status transition."""
    lead = Lead(wa_from="1234567890", status=STATUS_NEW)
    db.add(lead)
    db.commit()

    success = transition(db, lead, STATUS_QUALIFYING)

    assert success is True
    db.refresh(lead)
    assert lead.status == STATUS_QUALIFYING
    assert lead.qualifying_started_at is not None


def test_transition_invalid_raises_error(db):
    """Test that invalid transition raises ValueError."""
    lead = Lead(wa_from="1234567890", status=STATUS_NEW)
    db.add(lead)
    db.commit()

    with pytest.raises(ValueError, match="Invalid status transition"):
        transition(db, lead, STATUS_BOOKED)


def test_transition_updates_timestamps(db):
    """Test that transition updates appropriate timestamps."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()

    transition(db, lead, STATUS_AWAITING_DEPOSIT, update_timestamp=True)

    db.refresh(lead)
    assert lead.status == STATUS_AWAITING_DEPOSIT
    assert lead.deposit_sent_at is not None


def test_transition_with_reason(db):
    """Test transition with handover reason."""
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING)
    db.add(lead)
    db.commit()

    transition(
        db,
        lead,
        STATUS_NEEDS_ARTIST_REPLY,
        reason="Parse failure: dimensions",
        update_timestamp=True,
    )

    db.refresh(lead)
    assert lead.status == STATUS_NEEDS_ARTIST_REPLY
    assert lead.handover_reason == "Parse failure: dimensions"
    assert lead.needs_artist_reply_at is not None


def test_transition_terminal_state(db):
    """Test that terminal states don't allow transitions."""
    lead = Lead(wa_from="1234567890", status=STATUS_BOOKED)
    db.add(lead)
    db.commit()

    transitions = get_allowed_transitions(STATUS_BOOKED)
    assert len(transitions) == 0

    # Should raise error if trying to transition from terminal state
    with pytest.raises(ValueError):
        transition(db, lead, STATUS_QUALIFYING)


def test_transition_needs_artist_reply_can_resume(db):
    """Test that NEEDS_ARTIST_REPLY can transition back to QUALIFYING."""
    lead = Lead(wa_from="1234567890", status=STATUS_NEEDS_ARTIST_REPLY)
    db.add(lead)
    db.commit()

    success = transition(db, lead, STATUS_QUALIFYING)

    assert success is True
    db.refresh(lead)
    assert lead.status == STATUS_QUALIFYING


def test_transition_without_timestamp_update(db):
    """Test transition without updating timestamp."""
    lead = Lead(wa_from="1234567890", status=STATUS_NEW)
    db.add(lead)
    db.commit()

    transition(db, lead, STATUS_QUALIFYING, update_timestamp=False)

    db.refresh(lead)
    assert lead.status == STATUS_QUALIFYING
    # Timestamp should not be updated
    assert lead.qualifying_started_at is None


def test_transition_handover_reason_only_for_needs_artist_reply(db):
    """Test that handover reason is only stored for NEEDS_ARTIST_REPLY."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()

    transition(
        db,
        lead,
        STATUS_AWAITING_DEPOSIT,
        reason="Test reason",
        update_timestamp=True,
    )

    db.refresh(lead)
    assert lead.status == STATUS_AWAITING_DEPOSIT
    # Reason should not be stored (only for NEEDS_ARTIST_REPLY)
    assert lead.handover_reason is None


def test_advance_step_if_at_warns_on_pending_changes(db):
    """advance_step_if_at logs SystemEvent when session has pending changes before UPDATE."""
    lead = Lead(wa_from="7999111222", status=STATUS_QUALIFYING, current_step=2)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Simulate pending changes (dirty) - caller forgot to flush/commit before advance
    lead.status = STATUS_PENDING_APPROVAL  # makes db.dirty non-empty

    success, updated = advance_step_if_at(db, lead.id, 2)

    assert success is True
    assert updated is not None
    assert updated.current_step == 3

    # Assert the pending-changes warning was logged
    event = (
        db.query(SystemEvent)
        .filter(SystemEvent.event_type == "advance_step.pending_changes")
        .filter(SystemEvent.lead_id == lead.id)
        .first()
    )
    assert event is not None
    assert event.level == "WARN"
    assert event.payload.get("dirty_count", 0) >= 1
