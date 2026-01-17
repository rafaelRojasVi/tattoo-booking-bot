"""
Tests for action token system (Mode B - WhatsApp action links).
"""
import pytest
from datetime import datetime, timedelta, timezone
from app.db.models import Lead, ActionToken
from app.services.action_tokens import (
    generate_action_token,
    validate_action_token,
    mark_token_used,
    generate_action_tokens_for_lead,
    get_action_url,
)
from app.services.conversation import (
    STATUS_PENDING_APPROVAL,
    STATUS_AWAITING_DEPOSIT,
    STATUS_DEPOSIT_PAID,
    STATUS_BOOKING_LINK_SENT,
)


def test_generate_action_token(db):
    """Test generating an action token."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    token = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)
    
    assert token is not None
    assert len(token) > 0
    
    # Verify token was saved
    from sqlalchemy import select
    stmt = select(ActionToken).where(ActionToken.token == token)
    action_token = db.execute(stmt).scalar_one_or_none()
    assert action_token is not None
    assert action_token.lead_id == lead.id
    assert action_token.action_type == "approve"
    assert action_token.required_status == STATUS_PENDING_APPROVAL
    assert action_token.used is False


def test_validate_action_token_success(db):
    """Test validating a valid token."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    token = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)
    
    action_token, error = validate_action_token(db, token)
    assert action_token is not None
    assert error is None
    assert action_token.token == token


def test_validate_action_token_invalid(db):
    """Test validating an invalid token."""
    action_token, error = validate_action_token(db, "invalid-token")
    assert action_token is None
    assert error == "Invalid token"


def test_validate_action_token_already_used(db):
    """Test validating a token that's already been used."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    token = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)
    
    # Mark as used
    mark_token_used(db, token)
    
    # Try to validate again
    action_token, error = validate_action_token(db, token)
    assert action_token is None
    assert "already been used" in error


def test_validate_action_token_expired(db):
    """Test validating an expired token."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    token = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)
    
    # Manually expire the token
    from sqlalchemy import select
    stmt = select(ActionToken).where(ActionToken.token == token)
    action_token = db.execute(stmt).scalar_one()
    action_token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    db.refresh(action_token)
    
    # Try to validate
    result, error = validate_action_token(db, token)
    assert result is None
    assert "expired" in error


def test_validate_action_token_wrong_status(db):
    """Test validating a token when lead status doesn't match."""
    lead = Lead(wa_from="1234567890", status=STATUS_AWAITING_DEPOSIT)  # Wrong status
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    token = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)
    
    # Try to validate (lead is in wrong status)
    action_token, error = validate_action_token(db, token)
    assert action_token is None
    assert "status" in error.lower()


def test_mark_token_used(db):
    """Test marking a token as used."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    token = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)
    
    # Mark as used
    result = mark_token_used(db, token)
    assert result is True
    
    # Verify
    from sqlalchemy import select
    stmt = select(ActionToken).where(ActionToken.token == token)
    action_token = db.execute(stmt).scalar_one()
    assert action_token.used is True
    assert action_token.used_at is not None


def test_generate_action_tokens_for_lead_pending_approval(db):
    """Test generating tokens for a lead in PENDING_APPROVAL."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    tokens = generate_action_tokens_for_lead(db, lead.id, lead.status)
    
    assert "approve" in tokens
    assert "reject" in tokens
    assert len(tokens) == 2


def test_generate_action_tokens_for_lead_awaiting_deposit(db):
    """Test generating tokens for a lead in AWAITING_DEPOSIT."""
    lead = Lead(wa_from="1234567890", status=STATUS_AWAITING_DEPOSIT)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    tokens = generate_action_tokens_for_lead(db, lead.id, lead.status)
    
    assert "send_deposit" in tokens
    assert len(tokens) == 1


def test_generate_action_tokens_for_lead_deposit_paid(db):
    """Test generating tokens for a lead in DEPOSIT_PAID."""
    lead = Lead(wa_from="1234567890", status=STATUS_DEPOSIT_PAID)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    tokens = generate_action_tokens_for_lead(db, lead.id, lead.status)
    
    assert "send_booking_link" in tokens
    assert len(tokens) == 1


def test_generate_action_tokens_for_lead_booking_link_sent(db):
    """Test generating tokens for a lead in BOOKING_LINK_SENT."""
    lead = Lead(wa_from="1234567890", status=STATUS_BOOKING_LINK_SENT)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    tokens = generate_action_tokens_for_lead(db, lead.id, lead.status)
    
    assert "mark_booked" in tokens
    assert len(tokens) == 1


def test_get_action_url():
    """Test generating action URL."""
    token = "test-token-123"
    url = get_action_url(token)
    
    assert token in url
    assert url.startswith("http")


def test_action_token_single_use_enforcement(db, client):
    """Test that tokens can only be used once."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    token = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)
    
    # First use - should work
    response = client.get(f"/a/{token}")
    assert response.status_code == 200
    
    # Execute action
    response = client.post(f"/a/{token}")
    assert response.status_code == 200
    
    # Second use - should fail (token is already used, so status check fails)
    response = client.get(f"/a/{token}")
    assert response.status_code == 400
    # After first use, lead status changed, so error is about status mismatch or token already used
    assert "already been used" in response.text or "been used already" in response.text or "status" in response.text.lower()
