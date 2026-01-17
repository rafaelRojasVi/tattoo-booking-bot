"""
Action token service - generates and validates secure tokens for Mode B (WhatsApp action links).

Action token requirements:
- Single-use tokens (marked as used after confirmation)
- Expiry (default 7 days, configurable)
- Status-locked (lead must be in correct status)
- Confirm/Cancel page before execution
"""
import secrets
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.db.models import ActionToken, Lead
from app.core.config import settings

logger = logging.getLogger(__name__)


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
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.action_token_expiry_days)
    
    # Create token record
    action_token = ActionToken(
        token=token,
        lead_id=lead_id,
        action_type=action_type,
        required_status=required_status,
        expires_at=expires_at,
    )
    db.add(action_token)
    db.commit()
    db.refresh(action_token)
    
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
    # Find token
    stmt = select(ActionToken).where(ActionToken.token == token)
    action_token = db.execute(stmt).scalar_one_or_none()
    
    if not action_token:
        return None, "Invalid token"
    
    # Check if already used (single-use)
    if action_token.used:
        return None, "This action link has already been used"
    
    # Check expiry (handle both timezone-aware and naive datetimes)
    now = datetime.now(timezone.utc)
    expires = action_token.expires_at
    # Ensure both are timezone-aware for comparison
    if expires.tzinfo is None:
        # If expires_at is naive, assume it's UTC
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        return None, "This action link has expired"
    
    # Get lead and check status (status-locked)
    lead = db.get(Lead, action_token.lead_id)
    if not lead:
        return None, "Lead not found"
    
    if lead.status != action_token.required_status:
        return None, f"Cannot perform this action. Lead is in status '{lead.status}', but requires '{action_token.required_status}'"
    
    return action_token, None


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
    action_token.used_at = datetime.now(timezone.utc)
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
    
    elif lead_status == "BOOKING_LINK_SENT":
        # Can mark as booked
        tokens["mark_booked"] = get_action_url(
            generate_action_token(db, lead_id, "mark_booked", "BOOKING_LINK_SENT")
        )
    
    return tokens
