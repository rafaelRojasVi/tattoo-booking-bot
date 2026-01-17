"""
Tests for Stripe integration (checkout session creation and webhook handling).
"""
import pytest
import json
from app.db.models import Lead
from app.services.stripe_service import create_checkout_session, verify_webhook_signature
from app.services.conversation import STATUS_AWAITING_DEPOSIT, STATUS_DEPOSIT_PAID


def test_create_checkout_session_test_mode(db):
    """Test creating a checkout session in test mode (stub API key)."""
    lead = Lead(wa_from="1234567890", status=STATUS_AWAITING_DEPOSIT)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    result = create_checkout_session(
        lead_id=lead.id,
        amount_pence=5000,
        success_url="https://example.com/success",
        cancel_url="https://example.com/cancel",
    )
    
    assert "checkout_session_id" in result
    assert "checkout_url" in result
    assert result["amount_pence"] == 5000
    assert result["checkout_session_id"].startswith("cs_test_")
    assert "checkout.stripe.com" in result["checkout_url"]


def test_create_checkout_session_with_metadata(db):
    """Test creating checkout session with custom metadata."""
    lead = Lead(wa_from="1234567890", status=STATUS_AWAITING_DEPOSIT)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    result = create_checkout_session(
        lead_id=lead.id,
        amount_pence=7500,
        success_url="https://example.com/success",
        cancel_url="https://example.com/cancel",
        metadata={"custom_field": "test_value"},
    )
    
    assert result["amount_pence"] == 7500
    assert result["checkout_session_id"] is not None


def test_stripe_webhook_checkout_completed(client, db):
    """Test Stripe webhook for completed checkout session."""
    # Create lead in AWAITING_DEPOSIT
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_AWAITING_DEPOSIT,
        deposit_amount_pence=5000,
        stripe_checkout_session_id="cs_test_123",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    # Simulate Stripe webhook payload
    webhook_payload = {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "client_reference_id": str(lead.id),
                "metadata": {
                    "lead_id": str(lead.id),
                    "type": "deposit",
                },
                "payment_intent": "pi_test_123",
            }
        }
    }
    
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["received"] is True
    assert data["type"] == "checkout.session.completed"
    assert data["lead_id"] == lead.id
    
    # Verify lead was updated
    db.refresh(lead)
    assert lead.status == STATUS_DEPOSIT_PAID
    assert lead.stripe_payment_status == "paid"
    assert lead.deposit_paid_at is not None
    assert lead.stripe_payment_intent_id == "pi_test_123"


def test_stripe_webhook_duplicate_processing(client, db):
    """Test that duplicate Stripe webhooks are handled (idempotency)."""
    # Create lead already marked as paid
    from sqlalchemy import func
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_DEPOSIT_PAID,
        deposit_amount_pence=5000,
        stripe_checkout_session_id="cs_test_123",
        stripe_payment_status="paid",
        deposit_paid_at=func.now(),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    # Send same webhook again
    webhook_payload = {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "client_reference_id": str(lead.id),
                "metadata": {"lead_id": str(lead.id)},
            }
        }
    }
    
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "duplicate"  # Should be marked as duplicate


def test_stripe_webhook_missing_signature(client):
    """Test that webhook without signature is rejected."""
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps({"type": "test"}).encode("utf-8"),
    )
    
    assert response.status_code == 400
    assert "signature" in response.json()["error"].lower()


def test_stripe_webhook_unknown_event_type(client):
    """Test handling of unknown Stripe event types."""
    webhook_payload = {
        "id": "evt_test_123",
        "type": "payment_intent.succeeded",  # Not handled, but should ack
        "data": {"object": {}}
    }
    
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["received"] is True
    assert "not handled" in data["message"].lower()


def test_stripe_webhook_lead_not_found(client, db):
    """Test webhook for non-existent lead."""
    webhook_payload = {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "client_reference_id": "99999",  # Non-existent lead
                "metadata": {"lead_id": "99999"},
            }
        }
    }
    
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    
    assert response.status_code == 404
    assert "not found" in response.json()["error"].lower()


def test_stripe_webhook_missing_lead_id(client):
    """Test webhook without lead_id in metadata or client_reference_id."""
    webhook_payload = {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                # No client_reference_id or metadata.lead_id
            }
        }
    }
    
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    
    assert response.status_code == 400
    assert "lead_id" in response.json()["error"].lower()


def test_send_deposit_creates_checkout_session(client, db):
    """Test that send-deposit endpoint creates Stripe checkout session."""
    lead = Lead(wa_from="1234567890", status=STATUS_AWAITING_DEPOSIT)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    response = client.post(
        f"/admin/leads/{lead.id}/send-deposit",
        json={"amount_pence": 5000}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "checkout_url" in data
    assert "checkout_session_id" in data
    assert data["deposit_amount_pence"] == 5000
    
    # Verify checkout session ID was stored
    db.refresh(lead)
    assert lead.stripe_checkout_session_id is not None
    assert lead.stripe_checkout_session_id == data["checkout_session_id"]
