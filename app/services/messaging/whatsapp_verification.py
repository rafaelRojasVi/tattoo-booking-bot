"""
WhatsApp webhook signature verification service.

Verifies incoming webhook requests from Meta using X-Hub-Signature-256 header
with HMAC-SHA256 algorithm.
"""

import hashlib
import hmac
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def verify_whatsapp_signature(payload: bytes, signature_header: str | None) -> bool:
    """
    Verify WhatsApp webhook signature using HMAC-SHA256.

    Meta sends webhook signatures in the X-Hub-Signature-256 header
    in the format: sha256=<hex_digest>

    Args:
        payload: Raw request body (bytes)
        signature_header: X-Hub-Signature-256 header value (e.g., "sha256=abc123...")

    Returns:
        True if signature is valid, False otherwise

    Raises:
        ValueError: If app secret is not configured
    """
    # If app secret is not configured, skip verification (dev mode)
    if not settings.whatsapp_app_secret:
        logger.warning(
            "WhatsApp app secret not configured - skipping signature verification. "
            "Set WHATSAPP_APP_SECRET in production."
        )
        return True  # Allow in dev mode

    # If signature header is missing, reject
    if not signature_header:
        logger.warning("Missing X-Hub-Signature-256 header in WhatsApp webhook")
        return False

    # Parse signature header (format: "sha256=<hex_digest>")
    if not signature_header.startswith("sha256="):
        logger.warning(f"Invalid signature header format: {signature_header}")
        return False

    received_signature = signature_header.split("=", 1)[1]

    # Compute HMAC-SHA256 of payload using app secret
    computed_hmac = hmac.new(
        settings.whatsapp_app_secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    # Use constant-time comparison to prevent timing attacks
    is_valid = hmac.compare_digest(received_signature, computed_hmac)

    if not is_valid:
        logger.warning(
            "Invalid WhatsApp webhook signature - request rejected. "
            "This may indicate a spoofed request or misconfigured app secret."
        )

    return is_valid
