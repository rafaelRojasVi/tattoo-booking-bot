"""
Stripe service - handles checkout session creation and payment processing.
"""

import logging

import stripe

from app.core.config import settings

logger = logging.getLogger(__name__)

# Initialize Stripe
stripe.api_key = settings.stripe_secret_key

# Check if we're in test mode (stub API key)
STRIPE_TEST_MODE = settings.stripe_secret_key.startswith(
    "sk_test_test"
) or settings.stripe_secret_key.startswith("sk_test_")


def create_checkout_session(
    lead_id: int,
    amount_pence: int,
    success_url: str,
    cancel_url: str,
    metadata: dict | None = None,
) -> dict:
    """
    Create a Stripe Checkout session for a deposit payment.

    Args:
        lead_id: Lead ID (stored in metadata)
        amount_pence: Amount in pence (e.g., 5000 = £50.00)
        success_url: URL to redirect to after successful payment
        cancel_url: URL to redirect to if payment is cancelled
        metadata: Additional metadata to store with the session

    Returns:
        dict with checkout_session_id and checkout_url
    """
    try:
        # Build metadata (ensure deposit_rule_version and amount_pence are included)
        session_metadata = {
            "lead_id": str(lead_id),
            "type": "deposit",
            "amount_pence": str(amount_pence),  # Always include amount in metadata
        }
        if metadata:
            session_metadata.update(metadata)
        # Ensure deposit_rule_version is set (from metadata or settings)
        if "deposit_rule_version" not in session_metadata:
            session_metadata["deposit_rule_version"] = settings.deposit_rule_version

        # Calculate expiry time (24 hours from now)
        from datetime import UTC, datetime, timedelta

        expires_at = datetime.now(UTC) + timedelta(hours=24)

        # In test mode with stub key, return mock data
        if STRIPE_TEST_MODE and settings.stripe_secret_key == "sk_test_test":
            logger.info(f"[TEST MODE] Would create Stripe checkout session for lead {lead_id}")
            mock_session_id = f"cs_test_{lead_id}_{amount_pence}"
            mock_url = f"https://checkout.stripe.com/test/{mock_session_id}"
            return {
                "checkout_session_id": mock_session_id,
                "checkout_url": mock_url,
                "amount_pence": amount_pence,
                "expires_at": expires_at,
            }

        # Create checkout session (real Stripe API call)
        expires_at_timestamp = int(expires_at.timestamp())
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "gbp",
                        "product_data": {
                            "name": "Tattoo Booking Deposit",
                            "description": f"Deposit for booking request #{lead_id}",
                        },
                        "unit_amount": amount_pence,
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=session_metadata,
            # Store lead_id in client_reference_id for easy lookup
            client_reference_id=str(lead_id),
            # Set expiry to 24 hours from now
            expires_at=expires_at_timestamp,
        )

        logger.info(f"Created Stripe checkout session {checkout_session.id} for lead {lead_id}")

        return {
            "checkout_session_id": checkout_session.id,
            "checkout_url": checkout_session.url,
            "amount_pence": amount_pence,
            "expires_at": expires_at,
        }

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating checkout session for lead {lead_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating checkout session: {e}")
        raise


def verify_webhook_signature(payload: bytes, signature: str) -> dict:
    """
    Verify Stripe webhook signature.

    Args:
        payload: Raw request body (bytes)
        signature: Stripe signature from header

    Returns:
        Parsed event object if valid

    Raises:
        ValueError: If signature is invalid
    """
    # In test mode with stub secret, allow test events
    if STRIPE_TEST_MODE and settings.stripe_webhook_secret == "whsec_test":
        # For testing, accept any signature and parse payload as JSON
        import json

        try:
            event = json.loads(payload.decode("utf-8"))
            logger.info(f"[TEST MODE] Accepting test Stripe webhook event: {event.get('type')}")
            return event
        except Exception as e:
            raise ValueError(f"Invalid test webhook payload: {e}") from e

    try:
        event = stripe.Webhook.construct_event(
            payload,
            signature,
            settings.stripe_webhook_secret,
        )
        return event
    except ValueError as e:
        logger.error(f"Invalid Stripe webhook signature: {e}")
        raise
    except Exception as e:
        logger.error(f"Error verifying Stripe webhook: {e}")
        raise
