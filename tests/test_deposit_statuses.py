"""
Tests for deposit expiry, refunds, and cancellation statuses.
These are future features - tests verify status definitions exist.
"""

from app.db.models import Lead
from app.services.conversation import (
    STATUS_AWAITING_DEPOSIT,
    STATUS_CANCELLED,
    STATUS_DEPOSIT_EXPIRED,
    STATUS_REFUNDED,
)


def test_deposit_expired_status_exists():
    """Test that DEPOSIT_EXPIRED status constant exists."""
    assert STATUS_DEPOSIT_EXPIRED == "DEPOSIT_EXPIRED"


def test_refunded_status_exists():
    """Test that REFUNDED status constant exists."""
    assert STATUS_REFUNDED == "REFUNDED"


def test_cancelled_status_exists():
    """Test that CANCELLED status constant exists."""
    assert STATUS_CANCELLED == "CANCELLED"


def test_lead_can_have_deposit_expired_status(db):
    """Test that lead can be set to DEPOSIT_EXPIRED status."""
    lead = Lead(wa_from="1234567890", status=STATUS_AWAITING_DEPOSIT)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    lead.status = STATUS_DEPOSIT_EXPIRED
    db.commit()
    db.refresh(lead)

    assert lead.status == STATUS_DEPOSIT_EXPIRED


def test_lead_can_have_refunded_status(db):
    """Test that lead can be set to REFUNDED status."""
    lead = Lead(wa_from="1234567890", status="DEPOSIT_PAID")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    lead.status = STATUS_REFUNDED
    db.commit()
    db.refresh(lead)

    assert lead.status == STATUS_REFUNDED


def test_lead_can_have_cancelled_status(db):
    """Test that lead can be set to CANCELLED status."""
    lead = Lead(wa_from="1234567890", status="DEPOSIT_PAID")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    lead.status = STATUS_CANCELLED
    db.commit()
    db.refresh(lead)

    assert lead.status == STATUS_CANCELLED
