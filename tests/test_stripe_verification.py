"""
Tests for Stripe webhook checkout_session_id verification.
"""

import json

from app.db.models import Lead
from app.services.conversation import STATUS_AWAITING_DEPOSIT


def test_stripe_webhook_checkout_session_id_match(client, db):
    """Test that webhook verifies checkout_session_id matches."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_AWAITING_DEPOSIT,
        deposit_amount_pence=5000,
        stripe_checkout_session_id="cs_test_expected_123",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Webhook with matching checkout_session_id
    webhook_payload = {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_expected_123",  # Matches lead's stored session ID
                "client_reference_id": str(lead.id),
                "metadata": {"lead_id": str(lead.id)},
                "payment_intent": "pi_test_123",
            }
        },
    }

    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )

    assert response.status_code == 200
    db.refresh(lead)
    # Phase 1: Stripe webhook transitions to BOOKING_PENDING after DEPOSIT_PAID
    assert lead.status == "BOOKING_PENDING"


def test_stripe_webhook_checkout_session_id_mismatch(client, db):
    """Test that webhook rejects mismatched checkout_session_id."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_AWAITING_DEPOSIT,
        deposit_amount_pence=5000,
        stripe_checkout_session_id="cs_test_expected_123",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Webhook with different checkout_session_id
    webhook_payload = {
        "id": "evt_test_456",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_wrong_456",  # Doesn't match lead's stored session ID
                "client_reference_id": str(lead.id),
                "metadata": {"lead_id": str(lead.id)},
                "payment_intent": "pi_test_123",
            }
        },
    }

    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )

    assert response.status_code == 400
    assert "mismatch" in response.json()["error"].lower()

    # Lead status should not have changed
    db.refresh(lead)
    assert lead.status == STATUS_AWAITING_DEPOSIT
    assert lead.stripe_payment_status is None


def test_stripe_webhook_no_stored_session_id_allows_first_payment(client, db):
    """Test that webhook allows payment if lead has no stored checkout_session_id."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_AWAITING_DEPOSIT,
        deposit_amount_pence=5000,
        stripe_checkout_session_id=None,  # No stored session ID
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Webhook with checkout_session_id (first payment)
    webhook_payload = {
        "id": "evt_test_789",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_new_789",
                "client_reference_id": str(lead.id),
                "metadata": {"lead_id": str(lead.id)},
                "payment_intent": "pi_test_123",
            }
        },
    }

    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )

    assert response.status_code == 200
    db.refresh(lead)
    # Phase 1: Stripe webhook transitions to BOOKING_PENDING after DEPOSIT_PAID
    assert lead.status == "BOOKING_PENDING"
    assert lead.stripe_checkout_session_id == "cs_test_new_789"
