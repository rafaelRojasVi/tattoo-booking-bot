"""
Safety and idempotency utilities for critical operations.

Provides:
- Status-locked updates (optimistic locking)
- Idempotency checks
- Concurrency-safe operations
"""
import logging
from sqlalchemy.orm import Session
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from typing import Optional, Tuple
from app.db.models import Lead, ProcessedMessage, ActionToken

logger = logging.getLogger(__name__)


def update_lead_status_if_matches(
    db: Session,
    lead_id: int,
    expected_status: str,
    new_status: str,
    **updates
) -> Tuple[bool, Optional[Lead]]:
    """
    Atomically update lead status only if it matches expected status.
    This prevents race conditions when multiple requests try to update the same lead.
    
    Args:
        db: Database session
        lead_id: Lead ID to update
        expected_status: Status the lead must currently be in
        new_status: New status to set
        **updates: Additional fields to update (e.g., approved_at=func.now())
        
    Returns:
        Tuple of (success: bool, updated_lead: Lead | None)
        If success is False, the lead status didn't match or lead wasn't found.
    """
    # Use SQLAlchemy Core update for atomic operation
    stmt = (
        update(Lead)
        .where(Lead.id == lead_id)
        .where(Lead.status == expected_status)
        .values(status=new_status, **updates)
    )
    
    result = db.execute(stmt)
    db.commit()
    
    if result.rowcount == 0:
        # Either lead not found or status didn't match
        lead = db.get(Lead, lead_id)
        if not lead:
            logger.warning(f"Lead {lead_id} not found for status update")
            return False, None
        else:
            # Record failed atomic update for monitoring
            from app.services.metrics import record_failed_atomic_update
            record_failed_atomic_update(
                operation="update_lead_status",
                lead_id=lead_id,
                expected_status=expected_status,
                actual_status=lead.status,
            )
            logger.warning(
                f"Lead {lead_id} status mismatch: expected '{expected_status}', got '{lead.status}'"
            )
            return False, lead
    
    # Refresh and return updated lead
    lead = db.get(Lead, lead_id)
    db.refresh(lead)
    return True, lead


def check_and_record_processed_event(
    db: Session,
    event_id: str,
    event_type: str,
    lead_id: Optional[int] = None,
) -> Tuple[bool, Optional[ProcessedMessage]]:
    """
    Check if an event (webhook, action, etc.) has already been processed.
    If not, record it to prevent duplicate processing.
    
    Args:
        db: Database session
        event_id: Unique event identifier (e.g., Stripe event ID, message ID)
        event_type: Type of event (e.g., "stripe.checkout.session.completed", "whatsapp.message")
        lead_id: Optional lead ID associated with the event
        
    Returns:
        Tuple of (is_duplicate: bool, processed_message: ProcessedMessage | None)
        If is_duplicate is True, the event was already processed.
    """
    # Check if already processed
    stmt = select(ProcessedMessage).where(ProcessedMessage.message_id == event_id)
    existing = db.execute(stmt).scalar_one_or_none()
    
    if existing:
        logger.info(f"Event {event_id} (type: {event_type}) already processed at {existing.processed_at}")
        # Record duplicate event for monitoring
        from app.services.metrics import record_duplicate_event
        record_duplicate_event(event_type=event_type, event_id=event_id)
        return True, existing
    
    # Record as processed
    try:
        processed = ProcessedMessage(
            message_id=event_id,
            event_type=event_type,
            lead_id=lead_id,
        )
        db.add(processed)
        db.commit()
        db.refresh(processed)
        return False, processed
    except IntegrityError:
        # Race condition: another request processed it between check and insert
        db.rollback()
        existing = db.execute(stmt).scalar_one_or_none()
        if existing:
            logger.info(f"Event {event_id} processed by concurrent request")
            return True, existing
        # Shouldn't happen, but handle gracefully
        logger.error(f"IntegrityError recording event {event_id}, but no existing record found")
        return False, None


def validate_and_mark_token_used_atomic(
    db: Session,
    token: str,
) -> Tuple[Optional[ActionToken], str | None]:
    """
    Atomically validate and mark an action token as used.
    This prevents race conditions where two requests validate the same token simultaneously.
    
    Args:
        db: Database session
        token: Token to validate and mark as used
        
    Returns:
        Tuple of (ActionToken | None, error_message | None)
        If token is None, validation failed or token was already used.
    """
    from datetime import datetime, timezone
    from sqlalchemy import update
    
    # First, try to atomically mark as used (only if not already used)
    stmt = (
        update(ActionToken)
        .where(ActionToken.token == token)
        .where(ActionToken.used.is_(False))  # Only if not already used
        .values(used=True, used_at=datetime.now(timezone.utc))
    )
    
    result = db.execute(stmt)
    db.commit()
    
    if result.rowcount == 0:
        # Token doesn't exist or already used
        stmt = select(ActionToken).where(ActionToken.token == token)
        action_token = db.execute(stmt).scalar_one_or_none()
        if not action_token:
            return None, "Invalid token"
        if action_token.used:
            return None, "This action link has already been used"
        # Shouldn't reach here, but handle gracefully
        return None, "Token validation failed"
    
    # Token was successfully marked as used, now validate it
    stmt = select(ActionToken).where(ActionToken.token == token)
    action_token = db.execute(stmt).scalar_one_or_none()
    
    if not action_token:
        return None, "Token not found after marking as used"
    
    # Check expiry
    now = datetime.now(timezone.utc)
    expires = action_token.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        return None, "This action link has expired"
    
    # Check lead status
    lead = db.get(Lead, action_token.lead_id)
    if not lead:
        return None, "Lead not found"
    
    if lead.status != action_token.required_status:
        return None, f"Cannot perform this action. Lead is in status '{lead.status}', but requires '{action_token.required_status}'"
    
    return action_token, None
