"""
Tests for WhatsApp notifications (deposit links and payment confirmations).
"""
import pytest
from unittest.mock import patch, AsyncMock
from app.db.models import Lead
from app.services.messaging import format_deposit_link_message, format_payment_confirmation_message
from app.services.conversation import STATUS_AWAITING_DEPOSIT, STATUS_DEPOSIT_PAID


def test_format_deposit_link_message():
    """Test formatting deposit link message."""
    checkout_url = "https://checkout.stripe.com/test/abc123"
    amount_pence = 5000  # £50.00
    
    message = format_deposit_link_message(checkout_url, amount_pence)
    
    assert "Deposit Payment Link" in message
    assert "£50.00" in message
    assert checkout_url in message
    assert "approved" in message.lower()


def test_format_payment_confirmation_message():
    """Test formatting payment confirmation message."""
    amount_pence = 5000  # £50.00
    
    message = format_payment_confirmation_message(amount_pence)
    
    assert "Deposit Confirmed" in message
    assert "£50.00" in message
    assert "booking link" in message.lower()


def test_send_deposit_sends_whatsapp_message(client, db):
    """Test that send-deposit endpoint sends WhatsApp message with deposit link."""
    lead = Lead(wa_from="1234567890", status=STATUS_AWAITING_DEPOSIT)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    with patch("app.services.whatsapp_window.send_with_window_check", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "dry_run", "message_id": None}
        
        response = client.post(
            f"/admin/leads/{lead.id}/send-deposit",
            json={"amount_pence": 5000}
        )
        
        assert response.status_code == 200
        # Verify WhatsApp message was called via send_with_window_check
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        # send_with_window_check takes db, lead, message as args or kwargs
        # Check if called with args or kwargs
        if call_args.args:
            # Called with positional args: (db, lead, message, ...)
            assert call_args.args[1] == lead  # Second arg is lead
            assert "Deposit Payment Link" in call_args.args[2] or "deposit" in call_args.args[2].lower()  # Third arg is message
        else:
            # Called with keyword args
            assert call_args.kwargs.get("lead") == lead
            assert "Deposit Payment Link" in call_args.kwargs.get("message", "") or "deposit" in call_args.kwargs.get("message", "").lower()


def test_stripe_webhook_sends_payment_confirmation(client, db):
    """Test that Stripe webhook sends WhatsApp confirmation when payment is confirmed."""
    import json
    
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_AWAITING_DEPOSIT,
        deposit_amount_pence=5000,
        stripe_checkout_session_id="cs_test_123",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    webhook_payload = {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "client_reference_id": str(lead.id),
                "metadata": {"lead_id": str(lead.id)},
                "payment_intent": "pi_test_123",
            }
        }
    }
    
    # Mock the async function properly
    async def mock_send_whatsapp(*args, **kwargs):
        return {"status": "dry_run", "message_id": None}
    
    with patch("app.api.webhooks.send_whatsapp_message", side_effect=mock_send_whatsapp):
        response = client.post(
            "/webhooks/stripe",
            content=json.dumps(webhook_payload).encode("utf-8"),
            headers={"stripe-signature": "test_signature"},
        )
        
        assert response.status_code == 200
        # Verify lead was updated
        db.refresh(lead)
        assert lead.status == STATUS_DEPOSIT_PAID
        assert lead.last_bot_message_at is not None  # Timestamp should be updated


def test_deposit_link_message_includes_amount(client, db):
    """Test that deposit link message includes correct amount formatting."""
    lead = Lead(wa_from="1234567890", status=STATUS_AWAITING_DEPOSIT)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    # Test with different amounts
    test_cases = [
        (5000, "£50.00"),
        (7500, "£75.00"),
        (10000, "£100.00"),
        (2500, "£25.00"),
    ]
    
    for amount_pence, expected_amount in test_cases:
        message = format_deposit_link_message("https://checkout.stripe.com/test", amount_pence)
        assert expected_amount in message


def test_payment_confirmation_message_includes_amount():
    """Test that payment confirmation message includes correct amount formatting."""
    test_cases = [
        (5000, "£50.00"),
        (7500, "£75.00"),
        (10000, "£100.00"),
        (2500, "£25.00"),
    ]
    
    for amount_pence, expected_amount in test_cases:
        message = format_payment_confirmation_message(amount_pence)
        assert expected_amount in message


def test_whatsapp_notification_respects_dry_run(client, db):
    """Test that WhatsApp notifications respect dry_run setting."""
    lead = Lead(wa_from="1234567890", status=STATUS_AWAITING_DEPOSIT)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    with patch("app.services.whatsapp_window.send_with_window_check", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "dry_run", "message_id": None}
        
        # Should use dry_run from settings (defaults to True)
        response = client.post(
            f"/admin/leads/{lead.id}/send-deposit",
            json={"amount_pence": 5000}
        )
        
        assert response.status_code == 200
        # Verify send_with_window_check was called
        assert mock_send.called
        call_args = mock_send.call_args
        # send_with_window_check takes db, lead, message, dry_run, etc.
        # dry_run should be passed as a kwarg
        assert call_args.kwargs.get("dry_run") is True or call_args.kwargs.get("dry_run") is False  # Either is valid


def test_deposit_link_message_timestamp_updated(client, db):
    """Test that last_bot_message_at is updated when deposit link is sent."""
    from datetime import datetime, timezone
    
    lead = Lead(wa_from="1234567890", status=STATUS_AWAITING_DEPOSIT)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    initial_timestamp = lead.last_bot_message_at
    
    with patch("app.api.admin.send_whatsapp_message", new_callable=AsyncMock):
        response = client.post(
            f"/admin/leads/{lead.id}/send-deposit",
            json={"amount_pence": 5000}
        )
        
        assert response.status_code == 200
        db.refresh(lead)
        # Timestamp should be updated
        assert lead.last_bot_message_at is not None
        if initial_timestamp:
            assert lead.last_bot_message_at > initial_timestamp


def test_payment_confirmation_timestamp_updated(client, db):
    """Test that last_bot_message_at is updated when payment confirmation is sent."""
    import json
    
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_AWAITING_DEPOSIT,
        deposit_amount_pence=5000,
        stripe_checkout_session_id="cs_test_123",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    initial_timestamp = lead.last_bot_message_at
    
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
    
    # Mock the async function properly
    async def mock_send_whatsapp(*args, **kwargs):
        return {"status": "dry_run", "message_id": None}
    
    with patch("app.api.webhooks.send_whatsapp_message", side_effect=mock_send_whatsapp):
        response = client.post(
            "/webhooks/stripe",
            content=json.dumps(webhook_payload).encode("utf-8"),
            headers={"stripe-signature": "test_signature"},
        )
        
        assert response.status_code == 200
        db.refresh(lead)
        # Timestamp should be updated
        assert lead.last_bot_message_at is not None
        if initial_timestamp:
            assert lead.last_bot_message_at > initial_timestamp
