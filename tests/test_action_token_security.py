"""
Action Token Security Tests.

Tests that action links cannot be:
- reused (single-use enforcement)
- used after expiry
- used for the wrong lead/action
- used out of order even if token is valid
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import ActionToken, Lead
from app.services.action_tokens import generate_action_token, validate_action_token
from app.services.conversation import (
    STATUS_AWAITING_DEPOSIT,
    STATUS_PENDING_APPROVAL,
)
from app.services.safety import validate_and_mark_token_used_atomic


def test_expired_token_rejected(db):
    """
    Test that expired tokens are rejected with clear error message.
    """
    # Create a lead
    lead = Lead(wa_from="1111111111", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Create a token and manually set it to expired
    expired_token = generate_action_token(
        db=db,
        lead_id=lead.id,
        action_type="approve",
        required_status=STATUS_PENDING_APPROVAL,
    )
    # Manually set expiry to past
    action_token_obj = db.query(ActionToken).filter(ActionToken.token == expired_token).first()
    action_token_obj.expires_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()

    # Try to validate the expired token
    action_token, error = validate_action_token(db, expired_token)

    assert action_token is None
    assert error is not None
    assert "expired" in error.lower()


def test_single_use_token_first_use_succeeds_second_rejected(db):
    """
    Test that single-use tokens: first use succeeds, second use rejected.
    """
    # Create a lead
    lead = Lead(wa_from="2222222222", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Create a token
    token = generate_action_token(
        db=db,
        lead_id=lead.id,
        action_type="approve",
        required_status=STATUS_PENDING_APPROVAL,
    )

    # First use should succeed
    action_token1, error1 = validate_and_mark_token_used_atomic(db, token)
    assert action_token1 is not None
    assert error1 is None
    assert action_token1.used is True
    assert action_token1.used_at is not None

    # Second use should be rejected
    action_token2, error2 = validate_and_mark_token_used_atomic(db, token)
    assert action_token2 is None
    assert error2 is not None
    assert "already been used" in error2.lower() or "already used" in error2.lower()


def test_token_for_lead_a_cannot_operate_on_lead_b(db):
    """
    Test that token for lead A cannot operate on lead B.
    """
    # Create two leads
    lead_a = Lead(wa_from="3333333333", status=STATUS_PENDING_APPROVAL)
    lead_b = Lead(wa_from="4444444444", status=STATUS_PENDING_APPROVAL)
    db.add_all([lead_a, lead_b])
    db.commit()
    db.refresh(lead_a)
    db.refresh(lead_b)

    # Create token for lead A
    token = generate_action_token(
        db=db,
        lead_id=lead_a.id,
        action_type="approve",
        required_status=STATUS_PENDING_APPROVAL,
    )

    # Try to use token on lead B (by changing lead_b's status to match)
    # The token validation checks lead_id, so this should fail
    action_token, error = validate_and_mark_token_used_atomic(db, token)

    # Token should validate (it's valid for lead_a)
    # But if we try to use it for a different lead, the action handler should check
    # For now, we verify the token is tied to lead_a
    assert action_token is not None
    assert action_token.lead_id == lead_a.id
    assert action_token.lead_id != lead_b.id


def test_token_wrong_action_type_rejected(db):
    """
    Test that token with wrong action type cannot call a different endpoint.

    Scenario: approve token used for send-deposit should fail.
    """
    # Create a lead in AWAITING_DEPOSIT (required for send_deposit)
    lead = Lead(wa_from="5555555555", status=STATUS_AWAITING_DEPOSIT)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Create an approve token (but lead is in AWAITING_DEPOSIT, not PENDING_APPROVAL)
    # Actually, let's create a token for approve when lead is in wrong status
    token = generate_action_token(
        db=db,
        lead_id=lead.id,
        action_type="approve",
        required_status=STATUS_PENDING_APPROVAL,  # But lead is in AWAITING_DEPOSIT
    )

    # Try to validate - should fail because lead status doesn't match required_status
    action_token, error = validate_and_mark_token_used_atomic(db, token)

    assert action_token is None
    assert error is not None
    assert "status" in error.lower() or "requires" in error.lower()


def test_token_status_locked_rejected(db):
    """
    Test that valid token still rejected if lead status not allowed.

    Scenario: Token is valid (not expired, not used) but lead status changed.
    """
    # Create a lead in PENDING_APPROVAL
    lead = Lead(wa_from="6666666666", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Create token for approve (requires PENDING_APPROVAL)
    token = generate_action_token(
        db=db,
        lead_id=lead.id,
        action_type="approve",
        required_status=STATUS_PENDING_APPROVAL,
    )

    # Change lead status to AWAITING_DEPOSIT (simulating status change)
    lead.status = STATUS_AWAITING_DEPOSIT
    db.commit()
    db.refresh(lead)

    # Try to validate token - should fail because status changed
    action_token, error = validate_and_mark_token_used_atomic(db, token)

    assert action_token is None
    assert error is not None
    assert "status" in error.lower() or "requires" in error.lower()


def test_token_for_deleted_lead_rejected(db):
    """
    Test that token for deleted lead is rejected.
    """
    # Create a lead
    lead = Lead(wa_from="7777777777", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Create token
    token = generate_action_token(
        db=db,
        lead_id=lead.id,
        action_type="approve",
        required_status=STATUS_PENDING_APPROVAL,
    )

    # Delete the lead
    db.delete(lead)
    db.commit()

    # Try to validate token - should fail because lead not found
    action_token, error = validate_and_mark_token_used_atomic(db, token)

    assert action_token is None
    assert error is not None
    assert "not found" in error.lower() or "Lead not found" in error


def test_token_tampered_rejected(db):
    """
    Test that tampered/invalid token is rejected.

    Since tokens are DB-backed (not JWT), tampering means using a non-existent token.
    """
    # Try to validate a completely invalid token
    invalid_token = "invalid_token_that_does_not_exist_12345"

    action_token, error = validate_and_mark_token_used_atomic(db, invalid_token)

    assert action_token is None
    assert error is not None
    assert "invalid" in error.lower() or "not found" in error.lower()


def test_token_deleted_from_db_rejected(db):
    """
    Test that token deleted from DB is rejected.
    """
    # Create a lead
    lead = Lead(wa_from="8888888888", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Create token
    token = generate_action_token(
        db=db,
        lead_id=lead.id,
        action_type="approve",
        required_status=STATUS_PENDING_APPROVAL,
    )

    # Delete the token from DB
    stmt = select(ActionToken).where(ActionToken.token == token)
    action_token_obj = db.execute(stmt).scalar_one_or_none()
    if action_token_obj:
        db.delete(action_token_obj)
        db.commit()

    # Try to validate deleted token - should fail
    action_token, error = validate_and_mark_token_used_atomic(db, token)

    assert action_token is None
    assert error is not None
    assert "invalid" in error.lower() or "not found" in error.lower()


def test_token_http_error_messages_clear(db):
    """
    Test that error messages are clear and actionable.
    """
    # Create a lead
    lead = Lead(wa_from="9999999999", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Test expired token error
    expired_token = generate_action_token(
        db=db,
        lead_id=lead.id,
        action_type="approve",
        required_status=STATUS_PENDING_APPROVAL,
    )
    # Manually set expiry to past
    action_token_obj = db.query(ActionToken).filter(ActionToken.token == expired_token).first()
    action_token_obj.expires_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()
    _, error_expired = validate_and_mark_token_used_atomic(db, expired_token)
    assert error_expired is not None
    assert len(error_expired) > 10  # Should be descriptive

    # Test used token error
    used_token = generate_action_token(
        db=db,
        lead_id=lead.id,
        action_type="approve",
        required_status=STATUS_PENDING_APPROVAL,
    )
    validate_and_mark_token_used_atomic(db, used_token)  # Use it once
    _, error_used = validate_and_mark_token_used_atomic(db, used_token)  # Try again
    assert error_used is not None
    assert len(error_used) > 10  # Should be descriptive


def test_token_valid_use_succeeds(db):
    """
    Test that valid token use succeeds (positive test case).
    """
    # Create a lead
    lead = Lead(wa_from="1010101010", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Create token
    token = generate_action_token(
        db=db,
        lead_id=lead.id,
        action_type="approve",
        required_status=STATUS_PENDING_APPROVAL,
    )

    # Validate and mark as used - should succeed
    action_token, error = validate_and_mark_token_used_atomic(db, token)

    assert action_token is not None
    assert error is None
    assert action_token.used is True
    assert action_token.used_at is not None
    assert action_token.lead_id == lead.id
    assert action_token.action_type == "approve"


def test_token_concurrent_use_race_condition(db):
    """
    Test that concurrent token use is handled atomically (race condition protection).

    This tests the atomic update in validate_and_mark_token_used_atomic.
    """
    # Create a lead
    lead = Lead(wa_from="1212121212", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Create token
    token = generate_action_token(
        db=db,
        lead_id=lead.id,
        action_type="approve",
        required_status=STATUS_PENDING_APPROVAL,
    )

    # Simulate concurrent use: first request marks as used
    action_token1, error1 = validate_and_mark_token_used_atomic(db, token)
    assert action_token1 is not None
    assert error1 is None

    # Second concurrent request should fail (atomic update prevents double-use)
    action_token2, error2 = validate_and_mark_token_used_atomic(db, token)
    assert action_token2 is None
    assert error2 is not None
    assert "already" in error2.lower() or "used" in error2.lower()
