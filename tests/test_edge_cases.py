"""
Edge case tests for admin actions, action tokens, and data validation.
Tests boundary conditions, special characters, null values, and error scenarios.
"""

from datetime import UTC

from app.db.models import ActionToken, Lead, LeadAnswer
from app.services.action_tokens import (
    generate_action_token,
    mark_token_used,
    validate_action_token,
)
from app.services.conversation import (
    STATUS_AWAITING_DEPOSIT,
    STATUS_DEPOSIT_PAID,
    STATUS_PENDING_APPROVAL,
    STATUS_REJECTED,
)

# ========== Data Validation Edge Cases ==========


def test_reject_with_unicode_characters(client, db):
    """Test rejection reason with Unicode/special characters."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    reason = "Budget too low 💰\nReason: €50 is not enough\nSpecial: <script>alert('xss')</script>"
    response = client.post(f"/admin/leads/{lead.id}/reject", json={"reason": reason})
    assert response.status_code == 200
    db.refresh(lead)
    assert reason in lead.admin_notes


def test_reject_with_very_long_reason(client, db):
    """Test rejection with extremely long reason text."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Very long reason (10KB)
    long_reason = "A" * 10000
    response = client.post(f"/admin/leads/{lead.id}/reject", json={"reason": long_reason})
    assert response.status_code == 200
    db.refresh(lead)
    assert long_reason in lead.admin_notes


def test_send_deposit_with_negative_amount(client, db):
    """Test that negative deposit amounts are rejected or handled."""
    lead = Lead(wa_from="1234567890", status=STATUS_AWAITING_DEPOSIT)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    response = client.post(f"/admin/leads/{lead.id}/send-deposit", json={"amount_pence": -1000})
    # Should either reject or use default (implementation dependent)
    # For now, we'll check it doesn't crash
    assert response.status_code in [200, 400]


def test_send_deposit_with_zero_amount(client, db):
    """Test deposit with zero amount."""
    lead = Lead(wa_from="1234567890", status=STATUS_AWAITING_DEPOSIT)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    response = client.post(f"/admin/leads/{lead.id}/send-deposit", json={"amount_pence": 0})
    # Should either reject or use default
    assert response.status_code in [200, 400]


def test_send_deposit_with_very_large_amount(client, db):
    """Test deposit with extremely large amount."""
    lead = Lead(wa_from="1234567890", status=STATUS_AWAITING_DEPOSIT)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Very large amount (1 million pounds)
    response = client.post(
        f"/admin/leads/{lead.id}/send-deposit",
        json={"amount_pence": 100_000_000},  # £1,000,000
    )
    # Should handle gracefully (may reject or accept)
    assert response.status_code in [200, 400]


def test_send_booking_link_with_special_characters(client, db):
    """Test booking link with special characters and Unicode."""
    lead = Lead(wa_from="1234567890", status=STATUS_DEPOSIT_PAID)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    booking_url = "https://fresha.com/book/123?ref=test&name=José&date=2026-01-20"
    response = client.post(
        f"/admin/leads/{lead.id}/send-booking-link",
        json={"booking_url": booking_url, "booking_tool": "FRESHA"},
    )
    assert response.status_code == 200
    db.refresh(lead)
    assert lead.booking_link == booking_url


def test_send_booking_link_with_very_long_url(client, db):
    """Test booking link with extremely long URL."""
    lead = Lead(wa_from="1234567890", status=STATUS_DEPOSIT_PAID)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Very long URL (close to 500 char limit)
    long_url = "https://fresha.com/book/" + "x" * 450
    response = client.post(
        f"/admin/leads/{lead.id}/send-booking-link",
        json={"booking_url": long_url, "booking_tool": "FRESHA"},
    )
    # Should either accept or reject based on field length
    assert response.status_code in [200, 400]


def test_admin_actions_with_null_lead_data(client, db):
    """Test admin actions on leads with missing/null optional fields."""
    # Create lead with minimal data (all optional fields null)
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_PENDING_APPROVAL,
        location_city=None,
        location_country=None,
        region_bucket=None,
        size_category=None,
        budget_range_text=None,
        summary_text=None,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Should still be able to approve
    response = client.post(f"/admin/leads/{lead.id}/approve")
    assert response.status_code == 200
    db.refresh(lead)
    assert lead.status == STATUS_AWAITING_DEPOSIT


def test_admin_actions_with_empty_strings(client, db):
    """Test admin actions with empty string values (vs None)."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_PENDING_APPROVAL,
        location_city="",
        location_country="",
        admin_notes="",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    response = client.post(
        f"/admin/leads/{lead.id}/reject",
        json={"reason": ""},  # Empty reason
    )
    assert response.status_code == 200
    db.refresh(lead)
    assert lead.status == STATUS_REJECTED


# ========== Action Token Edge Cases ==========


def test_token_for_deleted_lead(db):
    """Test token validation when lead is deleted after token creation."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    token = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)

    # Delete the lead
    db.delete(lead)
    db.commit()

    # Token validation should fail
    action_token, error = validate_action_token(db, token)
    assert action_token is None
    assert "not found" in error.lower()


def test_multiple_tokens_same_action(db):
    """Test generating multiple tokens for the same action (all should work until used)."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Generate multiple approve tokens
    token1 = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)
    token2 = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)
    token3 = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)

    # All should be valid
    assert validate_action_token(db, token1)[0] is not None
    assert validate_action_token(db, token2)[0] is not None
    assert validate_action_token(db, token3)[0] is not None

    # Use one
    mark_token_used(db, token1)

    # Others should still be valid
    assert validate_action_token(db, token2)[0] is not None
    assert validate_action_token(db, token3)[0] is not None


def test_token_expiry_boundary(db):
    """Test token validation exactly at expiry time."""
    from datetime import datetime, timedelta

    from sqlalchemy import select

    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    token = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)

    # Set expiry to slightly in the past (1 second ago)
    stmt = select(ActionToken).where(ActionToken.token == token)
    action_token = db.execute(stmt).scalar_one()
    action_token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    db.refresh(action_token)

    # Should be expired (now > expires_at)
    result, error = validate_action_token(db, token)
    assert result is None
    assert "expired" in error


def test_token_with_invalid_action_type(db):
    """Test token with invalid/unknown action type."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Generate token with invalid action type
    token = generate_action_token(db, lead.id, "invalid_action", STATUS_PENDING_APPROVAL)

    # Token should be valid (validation doesn't check action type)
    action_token, error = validate_action_token(db, token)
    assert action_token is not None
    # But using it should fail in the endpoint


def test_mark_token_used_twice(db):
    """Test marking the same token as used multiple times (idempotent)."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    token = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)

    # Mark as used
    result1 = mark_token_used(db, token)
    assert result1 is True

    # Mark again (should still return True, but token already used)
    result2 = mark_token_used(db, token)
    assert result2 is True  # Function succeeds, but token is already used


# ========== Status Transition Edge Cases ==========


def test_rapid_status_changes(client, db):
    """Test rapid status changes (approve then immediately reject)."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Approve
    response = client.post(f"/admin/leads/{lead.id}/approve")
    assert response.status_code == 200
    db.refresh(lead)
    assert lead.status == STATUS_AWAITING_DEPOSIT

    # Try to reject (should work - reject can be called from any status except REJECTED/BOOKED)
    response = client.post(f"/admin/leads/{lead.id}/reject", json={})
    assert response.status_code == 200
    db.refresh(lead)
    assert lead.status == STATUS_REJECTED


def test_token_after_status_change_via_admin(db, client):
    """Test token becomes invalid after status changed via admin endpoint."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Generate token for approve
    token = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)

    # Change status via admin endpoint
    response = client.post(f"/admin/leads/{lead.id}/approve")
    assert response.status_code == 200
    db.refresh(lead)
    assert lead.status == STATUS_AWAITING_DEPOSIT

    # Token should now be invalid (status mismatch)
    action_token, error = validate_action_token(db, token)
    assert action_token is None
    assert "status" in error.lower()


def test_action_after_token_generated(db, client):
    """Test admin action after token was generated (token should become invalid)."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Generate token
    token = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)

    # Use admin endpoint to approve
    response = client.post(f"/admin/leads/{lead.id}/approve")
    assert response.status_code == 200

    # Token should be invalid now (status changed)
    action_token, error = validate_action_token(db, token)
    assert action_token is None


# ========== Integration Edge Cases ==========


def test_action_token_with_lead_no_answers(db, client):
    """Test action token on lead with no answers (minimal data)."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    # No answers added

    token = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)

    # Should still work
    response = client.get(f"/a/{token}")
    assert response.status_code == 200

    response = client.post(f"/a/{token}")
    assert response.status_code == 200


def test_action_token_with_lead_all_null_fields(db, client):
    """Test action token on lead with all optional fields null."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_PENDING_APPROVAL,
        location_city=None,
        location_country=None,
        region_bucket=None,
        size_category=None,
        budget_range_text=None,
        summary_text=None,
        deposit_amount_pence=None,
        booking_link=None,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    token = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)

    # Should still work
    response = client.get(f"/a/{token}")
    assert response.status_code == 200


def test_concurrent_token_usage_attempts(db, client):
    """Test multiple concurrent attempts to use the same token."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    token = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)

    # First request - get confirm page
    response1 = client.get(f"/a/{token}")
    assert response1.status_code == 200

    # Second request - also get confirm page (should work)
    response2 = client.get(f"/a/{token}")
    assert response2.status_code == 200

    # Execute action (first POST)
    response3 = client.post(f"/a/{token}")
    assert response3.status_code == 200

    # Try to execute again (should fail - already used)
    response4 = client.post(f"/a/{token}")
    assert response4.status_code == 400


def test_sheets_logging_with_null_values(db):
    """Test Google Sheets logging with leads containing null values."""
    from app.services.sheets import log_lead_to_sheets

    lead = Lead(
        wa_from="1234567890",
        status=STATUS_PENDING_APPROVAL,
        location_city=None,
        location_country=None,
        region_bucket=None,
        size_category=None,
        budget_range_text=None,
        summary_text=None,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Should not crash with null values
    result = log_lead_to_sheets(db, lead)
    assert result is True


def test_sheets_logging_with_special_characters(db):
    """Test Google Sheets logging with special characters in lead data."""
    from app.services.sheets import log_lead_to_sheets

    lead = Lead(
        wa_from="1234567890",
        status=STATUS_PENDING_APPROVAL,
        location_city="São Paulo",
        location_country="Brasil 🇧🇷",
        admin_notes="Special: <>&\"'",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Add answer with special characters (after lead has ID)
    answer = LeadAnswer(
        lead_id=lead.id,
        question_key="tattoo_idea",
        answer_text="Dragon 🐉 with <script>alert('xss')</script>",
    )
    db.add(answer)
    db.commit()
    db.refresh(lead)

    # Should handle special characters gracefully
    result = log_lead_to_sheets(db, lead)
    assert result is True


# ========== Boundary Conditions ==========


def test_approve_lead_at_boundary_timestamp(db, client):
    """Test approval timestamp handling at boundary conditions."""
    from datetime import datetime

    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    response = client.post(f"/admin/leads/{lead.id}/approve")
    assert response.status_code == 200

    db.refresh(lead)
    assert lead.approved_at is not None
    # Timestamp should be recent (within last minute)
    now = datetime.now(UTC)
    # Handle timezone-aware/naive comparison
    approved_at = lead.approved_at
    if approved_at.tzinfo is None:
        # If naive, assume UTC
        approved_at = approved_at.replace(tzinfo=UTC)
    time_diff = (now - approved_at).total_seconds()
    assert time_diff < 60  # Less than 1 minute


def test_token_expiry_just_before_expiry(db):
    """Test token validation just before expiry (should be valid)."""
    from datetime import datetime, timedelta

    from sqlalchemy import select

    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    token = generate_action_token(db, lead.id, "approve", STATUS_PENDING_APPROVAL)

    # Set expiry to 1 second in the future
    stmt = select(ActionToken).where(ActionToken.token == token)
    action_token = db.execute(stmt).scalar_one()
    action_token.expires_at = datetime.now(UTC) + timedelta(seconds=1)
    db.commit()
    db.refresh(action_token)

    # Should still be valid
    result, error = validate_action_token(db, token)
    assert result is not None
    assert error is None


def test_send_booking_link_with_invalid_tool(client, db):
    """Test booking link with invalid booking tool value."""
    lead = Lead(wa_from="1234567890", status=STATUS_DEPOSIT_PAID)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Invalid tool (not in expected list)
    response = client.post(
        f"/admin/leads/{lead.id}/send-booking-link",
        json={"booking_url": "https://test.com", "booking_tool": "INVALID_TOOL"},
    )
    # Should either accept or reject based on validation
    # For now, we'll check it doesn't crash
    assert response.status_code in [200, 400]


def test_action_on_lead_with_max_length_fields(db, client):
    """Test actions on lead with fields at maximum length."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_PENDING_APPROVAL,
        location_city="A" * 100,  # Max length
        location_country="B" * 100,
        admin_notes="C" * 1000,  # Very long notes
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Should still work
    response = client.post(f"/admin/leads/{lead.id}/approve")
    assert response.status_code == 200
