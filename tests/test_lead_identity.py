"""
Tests for lead identity and multiple enquiries handling.
"""
import pytest
from app.db.models import Lead
from app.services.leads import get_or_create_lead
from app.services.conversation import (
    STATUS_QUALIFYING,
    STATUS_PENDING_APPROVAL,
    STATUS_BOOKED,
    STATUS_REJECTED,
    STATUS_ABANDONED,
)


def test_get_or_create_lead_new_number_creates_new(db):
    """Test that new phone number creates new lead."""
    lead = get_or_create_lead(db, "1234567890")
    
    assert lead.wa_from == "1234567890"
    assert lead.status == "NEW"
    assert lead.id is not None


def test_get_or_create_lead_reuses_active_qualifying(db):
    """Test that active QUALIFYING lead is reused."""
    # Create active lead
    lead1 = Lead(wa_from="1234567890", status=STATUS_QUALIFYING)
    db.add(lead1)
    db.commit()
    db.refresh(lead1)
    
    # Get or create should return existing active lead
    lead2 = get_or_create_lead(db, "1234567890")
    
    assert lead2.id == lead1.id
    assert lead2.status == STATUS_QUALIFYING


def test_get_or_create_lead_reuses_active_pending_approval(db):
    """Test that active PENDING_APPROVAL lead is reused."""
    lead1 = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead1)
    db.commit()
    db.refresh(lead1)
    
    lead2 = get_or_create_lead(db, "1234567890")
    
    assert lead2.id == lead1.id
    assert lead2.status == STATUS_PENDING_APPROVAL


def test_get_or_create_lead_creates_new_after_booked(db):
    """Test that new lead is created after BOOKED status."""
    # Create inactive lead (BOOKED)
    lead1 = Lead(wa_from="1234567890", status=STATUS_BOOKED)
    db.add(lead1)
    db.commit()
    db.refresh(lead1)
    lead1_id = lead1.id
    
    # Get or create should create NEW lead (not reuse BOOKED)
    lead2 = get_or_create_lead(db, "1234567890")
    
    assert lead2.id != lead1_id
    assert lead2.status == "NEW"
    assert lead2.wa_from == "1234567890"


def test_get_or_create_lead_creates_new_after_rejected(db):
    """Test that new lead is created after REJECTED status."""
    lead1 = Lead(wa_from="1234567890", status=STATUS_REJECTED)
    db.add(lead1)
    db.commit()
    db.refresh(lead1)
    lead1_id = lead1.id
    
    lead2 = get_or_create_lead(db, "1234567890")
    
    assert lead2.id != lead1_id
    assert lead2.status == "NEW"


def test_get_or_create_lead_creates_new_after_abandoned(db):
    """Test that new lead is created after ABANDONED status."""
    lead1 = Lead(wa_from="1234567890", status=STATUS_ABANDONED)
    db.add(lead1)
    db.commit()
    db.refresh(lead1)
    lead1_id = lead1.id
    
    lead2 = get_or_create_lead(db, "1234567890")
    
    assert lead2.id != lead1_id
    assert lead2.status == "NEW"


def test_get_or_create_lead_reuses_active_over_inactive(db):
    """Test that active lead is reused even if inactive leads exist."""
    # Create inactive lead (old)
    lead1 = Lead(wa_from="1234567890", status=STATUS_BOOKED)
    db.add(lead1)
    db.commit()
    db.refresh(lead1)
    
    # Create active lead (newer)
    lead2 = Lead(wa_from="1234567890", status=STATUS_QUALIFYING)
    db.add(lead2)
    db.commit()
    db.refresh(lead2)
    
    # Get or create should return active lead
    lead3 = get_or_create_lead(db, "1234567890")
    
    assert lead3.id == lead2.id
    assert lead3.status == STATUS_QUALIFYING


def test_get_or_create_lead_multiple_inactive_creates_new(db):
    """Test that multiple inactive leads result in new lead creation."""
    # Create multiple inactive leads
    lead1 = Lead(wa_from="1234567890", status=STATUS_BOOKED)
    lead2 = Lead(wa_from="1234567890", status=STATUS_REJECTED)
    db.add(lead1)
    db.add(lead2)
    db.commit()
    db.refresh(lead1)
    db.refresh(lead2)
    
    # Get or create should create new lead
    lead3 = get_or_create_lead(db, "1234567890")
    
    assert lead3.id not in [lead1.id, lead2.id]
    assert lead3.status == "NEW"
