"""
Test helpers for Stripe webhook testing.
"""

import json
from typing import Any
from unittest.mock import MagicMock

from fastapi import Request


def build_stripe_webhook_request(event_dict: dict[str, Any]) -> Request:
    """
    Build a mock FastAPI Request for Stripe webhook testing.

    Args:
        event_dict: Stripe event dictionary (with 'id', 'type', 'data', etc.)

    Returns:
        Mock Request object with proper body and headers
    """
    from unittest.mock import AsyncMock

    mock_request = MagicMock(spec=Request)

    # Encode event as JSON bytes for body
    body_bytes = json.dumps(event_dict).encode("utf-8")
    # Make body awaitable (async function)
    mock_request.body = AsyncMock(return_value=body_bytes)

    # Set headers with signature
    mock_request.headers = {"stripe-signature": "test_sig"}

    return mock_request


def create_checkout_completed_event(
    event_id: str,
    checkout_session_id: str,
    payment_intent_id: str,
    lead_id: int,
    amount_total: int = 15000,
) -> dict[str, Any]:
    """
    Create a Stripe checkout.session.completed event dictionary for testing.

    Args:
        event_id: Stripe event ID
        checkout_session_id: Checkout session ID
        payment_intent_id: Payment intent ID
        lead_id: Lead ID
        amount_total: Amount in pence

    Returns:
        Stripe event dictionary
    """
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": checkout_session_id,
                "payment_intent": payment_intent_id,
                "client_reference_id": str(lead_id),
                "amount_total": amount_total,
                "metadata": {"lead_id": str(lead_id)},
            }
        },
    }
