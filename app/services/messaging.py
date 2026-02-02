"""
WhatsApp messaging service with dry-run mode for development.
"""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_whatsapp_message(
    to: str,
    message: str,
    dry_run: bool = True,
) -> dict:
    """
    Send a WhatsApp message.

    Args:
        to: WhatsApp phone number (with country code, no +)
        message: Message text to send
        dry_run: If True, only log the message (don't actually send)

    Returns:
        dict with status and message_id (or None in dry-run)
    """
    # Policy guard: Check for missing credentials
    if not dry_run:
        if not settings.whatsapp_access_token or settings.whatsapp_access_token in [
            "",
            "test_token",
        ]:
            logger.error("WhatsApp access token missing - cannot send message")
            raise ValueError("WhatsApp access token not configured. Cannot send message.")

        if not settings.whatsapp_phone_number_id or settings.whatsapp_phone_number_id in [
            "",
            "test_id",
        ]:
            logger.error("WhatsApp phone number ID missing - cannot send message")
            raise ValueError("WhatsApp phone number ID not configured. Cannot send message.")

    # Force dry-run in tests or if credentials are placeholders/missing
    import os

    if (
        os.environ.get("PYTEST_CURRENT_TEST")
        or not settings.whatsapp_access_token
        or settings.whatsapp_access_token in ["test_token", ""]
    ):
        dry_run = True

    if dry_run:
        logger.info(f"[DRY-RUN] Would send WhatsApp message to {to}: {message}")
        return {
            "status": "dry_run",
            "message_id": None,
            "to": to,
            "message": message,
        }

    try:
        from app.services.http_client import create_httpx_client

        url = f"https://graph.facebook.com/v18.0/{settings.whatsapp_phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {settings.whatsapp_access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": message},
        }

        async with create_httpx_client() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()

            return {
                "status": "sent",
                "message_id": result.get("messages", [{}])[0].get("id"),
                "to": to,
            }
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
        # Log system event (if db session available - async context may not have it)
        # Note: This is called from async context, so we can't easily access db here
        # The calling code should log the event if it has db access
        raise


def format_summary_message(answers: dict) -> str:
    """
    Format a structured summary of the consultation (legacy compatibility).

    For Phase 1, use app.services.summary.format_summary_message() with
    extract_phase1_summary_context() instead.

    Args:
        answers: Dict mapping question_key to answer_text

    Returns:
        Formatted summary string
    """
    from app.services.summary import format_summary_message_legacy

    return format_summary_message_legacy(answers)


def format_deposit_link_message(
    checkout_url: str,
    amount_pence: int,
    lead_id: int | None = None,
) -> str:
    """
    Format message for sending deposit payment link.

    Args:
        checkout_url: Stripe checkout URL
        amount_pence: Deposit amount in pence
        lead_id: Lead ID for deterministic variant selection

    Returns:
        Formatted message string
    """
    from app.services.message_composer import render_message

    amount_gbp = amount_pence / 100
    return render_message(
        "deposit_link",
        lead_id=lead_id,
        checkout_url=checkout_url,
        amount_gbp=amount_gbp,
    )


def format_payment_confirmation_message(
    amount_pence: int,
    lead_id: int | None = None,
) -> str:
    """
    Format message confirming deposit payment.

    Args:
        amount_pence: Deposit amount in pence
        lead_id: Lead ID for deterministic variant selection

    Returns:
        Formatted message string
    """
    from app.services.message_composer import render_message

    amount_gbp = amount_pence / 100
    return render_message(
        "payment_confirmation",
        lead_id=lead_id,
        amount_gbp=amount_gbp,
    )
