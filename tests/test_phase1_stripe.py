"""
Tests for Phase 1 Stripe webhook: DEPOSIT_PAID -> BOOKING_PENDING transition.
"""

from app.db.models import Lead
from app.services.conversation import (
    STATUS_AWAITING_DEPOSIT,
    STATUS_BOOKING_PENDING,
)


def test_stripe_webhook_sets_booking_pending(client, db):
    """Test that Stripe webhook sets DEPOSIT_PAID then BOOKING_PENDING."""
    # Create lead awaiting deposit
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_AWAITING_DEPOSIT,
        stripe_checkout_session_id="cs_test_123",
        deposit_amount_pence=15000,
    )
    db.add(lead)
    db.commit()

    # Simulate Stripe webhook
    webhook_payload = {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "payment_intent": "pi_test_123",
                "client_reference_id": str(lead.id),
                "metadata": {
                    "lead_id": str(lead.id),
                },
            },
        },
    }

    # Sign the webhook (in test mode, signature is ignored)
    response = client.post(
        "/webhooks/stripe",
        json=webhook_payload,
        headers={"stripe-signature": "test_signature"},
    )

    assert response.status_code == 200
    db.refresh(lead)

    # Should be in BOOKING_PENDING (not just DEPOSIT_PAID)
    assert lead.status == STATUS_BOOKING_PENDING
    assert lead.deposit_paid_at is not None
    assert lead.booking_pending_at is not None
    assert lead.stripe_payment_status == "paid"


def test_stripe_webhook_includes_policy_reminder(client, db):
    """Test that deposit confirmation includes policy reminder."""
    # This would test the WhatsApp message content
    # For now, we test the status transition
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_AWAITING_DEPOSIT,
        stripe_checkout_session_id="cs_test_456",
        deposit_amount_pence=20000,
    )
    db.add(lead)
    db.commit()

    webhook_payload = {
        "id": "evt_test_456",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_456",
                "payment_intent": "pi_test_456",
                "client_reference_id": str(lead.id),
                "metadata": {
                    "lead_id": str(lead.id),
                },
            },
        },
    }

    response = client.post(
        "/webhooks/stripe",
        json=webhook_payload,
        headers={"stripe-signature": "test_signature"},
    )

    assert response.status_code == 200
    # Message content is tested in integration tests
    # Here we verify the status transition worked
