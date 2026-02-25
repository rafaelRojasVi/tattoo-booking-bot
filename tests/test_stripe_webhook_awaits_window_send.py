"""
Test that Stripe webhook handler properly awaits send_with_window_check.

This ensures async functions are properly awaited rather than using asyncio.run().
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks

from app.api.webhooks import stripe_webhook
from tests.helpers.stripe_webhook import build_stripe_webhook_request


@pytest.fixture
def mock_stripe_event():
    """Create a mock Stripe checkout.session.completed event."""
    return {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "client_reference_id": "1",
                "metadata": {"lead_id": "1"},
                "payment_intent": "pi_test_123",
            }
        },
    }


@pytest.fixture
def mock_lead(db):
    """Create a mock lead in the database."""
    from app.db.models import Lead

    lead = Lead(
        id=1,
        wa_from="1234567890",
        status="AWAITING_DEPOSIT",
        deposit_amount_pence=5000,
        stripe_checkout_session_id="cs_test_123",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


async def test_stripe_webhook_awaits_send_with_window_check(db, mock_stripe_event, mock_lead):
    """Test that Stripe webhook handler awaits send_with_window_check."""
    # Mock signature verification to always succeed
    with patch("app.services.integrations.stripe_service.verify_webhook_signature") as mock_verify:
        mock_verify.return_value = mock_stripe_event

        # Mock send_with_window_check as AsyncMock (it's imported inside the function)
        with patch(
            "app.services.messaging.whatsapp_window.send_with_window_check", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = {
                "status": "sent",
                "message_id": "msg_123",
            }

            # Mock notify_artist as well (it's also awaited, imported inside function)
            with patch(
                "app.services.integrations.artist_notifications.notify_artist",
                new_callable=AsyncMock,
            ) as mock_notify:
                mock_notify.return_value = {"status": "sent"}

                # Build webhook request using helper
                request = build_stripe_webhook_request(mock_stripe_event)

                # Create BackgroundTasks instance
                background_tasks = BackgroundTasks()

                # Call webhook handler directly (async)
                result = await stripe_webhook(request, background_tasks=background_tasks, db=db)

                # Assert webhook succeeded
                assert result["received"] is True
                assert result["type"] == "checkout.session.completed"

                # CRITICAL: Assert that send_with_window_check was awaited
                # (not called with asyncio.run)
                # Use assert_awaited_once() or check await_count >= 1
                assert mock_send.await_count >= 1, (
                    "send_with_window_check was not awaited. "
                    "This indicates asyncio.run() or threadpool hack was reintroduced."
                )

                # Verify it was called with correct arguments
                call_args = mock_send.await_args
                assert call_args is not None
                # Check that db and lead were passed
                assert "db" in call_args.kwargs or len(call_args.args) > 0
                assert "lead" in call_args.kwargs or len(call_args.args) > 1


async def test_stripe_webhook_awaits_notify_artist(db, mock_stripe_event, mock_lead):
    """Test that Stripe webhook handler awaits notify_artist."""
    # Mock signature verification
    with patch("app.services.integrations.stripe_service.verify_webhook_signature") as mock_verify:
        mock_verify.return_value = mock_stripe_event

        # Mock send_with_window_check
        with patch(
            "app.services.messaging.whatsapp_window.send_with_window_check", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = {"status": "sent"}

            # Mock notify_artist as AsyncMock
            with patch(
                "app.services.integrations.artist_notifications.notify_artist",
                new_callable=AsyncMock,
            ) as mock_notify:
                mock_notify.return_value = {"status": "sent"}

                request = build_stripe_webhook_request(mock_stripe_event)

                background_tasks = BackgroundTasks()

                result = await stripe_webhook(request, background_tasks=background_tasks, db=db)

                assert result["received"] is True

                # Assert notify_artist was awaited (not called with asyncio.run)
                assert mock_notify.await_count >= 1, (
                    "notify_artist was not awaited. "
                    "This indicates asyncio.run() or threadpool hack was reintroduced."
                )
