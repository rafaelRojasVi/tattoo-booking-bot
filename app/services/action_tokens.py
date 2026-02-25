"""
Action token service - generates and validates secure tokens for Mode B (WhatsApp action links).

Action token requirements:
- Single-use tokens (marked as used after confirmation)
- Expiry (default 7 days, configurable)
- Status-locked (lead must be in correct status)
- Confirm/Cancel page before execution
"""

import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.helpers import commit_and_refresh
from app.db.models import ActionToken
from app.services.leads import get_lead_or_none
from app.utils.datetime_utils import dt_replace_utc

logger = logging.getLogger(__name__)

# User-facing error messages (shared with safety.validate_and_mark_token_used_atomic)
ERR_INVALID_TOKEN = "Invalid token"
ERR_ALREADY_USED = "This action link has already been used"
ERR_EXPIRED = "This action link has expired"
ERR_LEAD_NOT_FOUND = "Lead not found"


def _err_status_mismatch(lead_status: str, required_status: str) -> str:
    """Exact user-facing message for status-locked validation."""
    return f"Cannot perform this action. Lead is in status '{lead_status}', but requires '{required_status}'"


def _validate_action_token_checks(
    db: Session, action_token: ActionToken
) -> tuple[ActionToken | None, str | None]:
    """
    Shared validation: expiry, lead exists, lead status matches.
    Caller must have already resolved token and (for read-only flow) checked 'used'.
    Returns (action_token, None) if valid, (None, error_message) otherwise.
    """
    now = datetime.now(UTC)
    expires = dt_replace_utc(action_token.expires_at)
    if expires is None or now > expires:
        return None, ERR_EXPIRED

    lead = get_lead_or_none(db, action_token.lead_id)
    if not lead:
        return None, ERR_LEAD_NOT_FOUND

    if lead.status != action_token.required_status:
        return None, _err_status_mismatch(lead.status, action_token.required_status)

    return action_token, None


def generate_action_token(
    db: Session,
    lead_id: int,
    action_type: str,
    required_status: str,
) -> str:
    """
    Generate a secure action token for a lead action.

    Args:
        db: Database session
        lead_id: Lead ID
        action_type: Type of action (approve, reject, send_deposit, send_booking_link, mark_booked)
        required_status: Status the lead must be in for this action

    Returns:
        Secure token string
    """
    # Generate secure random token (64 characters)
    token = secrets.token_urlsafe(48)  # 48 bytes = 64 URL-safe characters

    # Calculate expiry (default 7 days from now)
    expires_at = datetime.now(UTC) + timedelta(days=settings.action_token_expiry_days)

    # Create token record
    action_token = ActionToken(
        token=token,
        lead_id=lead_id,
        action_type=action_type,
        required_status=required_status,
        expires_at=expires_at,
    )
    db.add(action_token)
    commit_and_refresh(db, action_token)

    logger.info(f"Generated action token for lead {lead_id}, action {action_type}")

    return token


def get_action_url(token: str) -> str:
    """
    Generate the full action URL for a token.

    Args:
        token: Action token

    Returns:
        Full URL (e.g., https://example.com/a/abc123...)
    """
    return f"{settings.action_token_base_url}/a/{token}"


def validate_action_token(db: Session, token: str) -> tuple[ActionToken | None, str | None]:
    """
    Validate an action token.

    Args:
        db: Database session
        token: Token to validate

    Returns:
        Tuple of (ActionToken object if valid, error message if invalid)
    """
    stmt = select(ActionToken).where(ActionToken.token == token)
    action_token = db.execute(stmt).scalar_one_or_none()

    if not action_token:
        return None, ERR_INVALID_TOKEN

    if action_token.used:
        return None, ERR_ALREADY_USED

    return _validate_action_token_checks(db, action_token)


def mark_token_used(db: Session, token: str) -> bool:
    """
    Mark an action token as used (single-use enforcement).

    Args:
        db: Database session
        token: Token to mark as used

    Returns:
        True if successful, False otherwise
    """
    stmt = select(ActionToken).where(ActionToken.token == token)
    action_token = db.execute(stmt).scalar_one_or_none()

    if not action_token:
        return False

    action_token.used = True
    action_token.used_at = datetime.now(UTC)
    db.commit()

    return True


def generate_action_tokens_for_lead(
    db: Session,
    lead_id: int,
    lead_status: str,
) -> dict[str, str]:
    """
    Generate all action tokens for a lead based on current status.
    Used when consultation completes (Mode B) to send WhatsApp summary with action links.

    Args:
        db: Database session
        lead_id: Lead ID
        lead_status: Current lead status

    Returns:
        Dict mapping action_type to action URL
    """
    tokens = {}

    # Generate tokens based on status and available actions
    if lead_status == "PENDING_APPROVAL":
        # Can approve or reject
        tokens["approve"] = get_action_url(
            generate_action_token(db, lead_id, "approve", "PENDING_APPROVAL")
        )
        tokens["reject"] = get_action_url(
            generate_action_token(db, lead_id, "reject", "PENDING_APPROVAL")
        )

    elif lead_status == "AWAITING_DEPOSIT":
        # Can send deposit link
        tokens["send_deposit"] = get_action_url(
            generate_action_token(db, lead_id, "send_deposit", "AWAITING_DEPOSIT")
        )

    elif lead_status == "DEPOSIT_PAID":
        # Can send booking link
        tokens["send_booking_link"] = get_action_url(
            generate_action_token(db, lead_id, "send_booking_link", "DEPOSIT_PAID")
        )

    elif lead_status in ("BOOKING_LINK_SENT", "BOOKING_PENDING"):
        # Can mark as booked (BOOKING_PENDING = Phase 1 status after deposit paid)
        tokens["mark_booked"] = get_action_url(
            generate_action_token(db, lead_id, "mark_booked", lead_status)
        )

    return tokens
