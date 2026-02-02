"""
State machine service - defines allowed status transitions and provides transition helper.

This centralizes all status transition logic to ensure consistency and prevent invalid transitions.

IMPROVEMENTS:
- Uses SELECT FOR UPDATE to prevent race conditions
- All transitions happen in a single transaction
- Side effects (WhatsApp, Sheets) happen AFTER commit
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Lead
from app.services.conversation import (
    STATUS_ABANDONED,
    STATUS_AWAITING_DEPOSIT,
    STATUS_BOOKED,
    STATUS_BOOKING_LINK_SENT,
    STATUS_BOOKING_PENDING,
    STATUS_COLLECTING_TIME_WINDOWS,
    STATUS_DEPOSIT_EXPIRED,
    STATUS_DEPOSIT_PAID,
    STATUS_NEEDS_ARTIST_REPLY,
    STATUS_NEEDS_FOLLOW_UP,
    STATUS_NEEDS_MANUAL_FOLLOW_UP,
    STATUS_NEW,
    STATUS_OPTOUT,
    STATUS_PENDING_APPROVAL,
    STATUS_QUALIFYING,
    STATUS_REJECTED,
    STATUS_STALE,
    STATUS_TOUR_CONVERSION_OFFERED,
    STATUS_WAITLISTED,
)

logger = logging.getLogger(__name__)

# Define allowed transitions
# Format: {from_status: [allowed_to_statuses]}
ALLOWED_TRANSITIONS = {
    STATUS_NEW: [STATUS_QUALIFYING],
    STATUS_QUALIFYING: [
        STATUS_PENDING_APPROVAL,
        STATUS_NEEDS_ARTIST_REPLY,
        STATUS_NEEDS_FOLLOW_UP,
        STATUS_TOUR_CONVERSION_OFFERED,
        STATUS_WAITLISTED,  # No upcoming tour, below min budget, or waitlist
        STATUS_ABANDONED,
        STATUS_STALE,
        STATUS_OPTOUT,
        STATUS_NEEDS_MANUAL_FOLLOW_UP,
    ],
    STATUS_PENDING_APPROVAL: [
        STATUS_AWAITING_DEPOSIT,
        STATUS_REJECTED,
        STATUS_NEEDS_ARTIST_REPLY,
        STATUS_NEEDS_FOLLOW_UP,
        STATUS_ABANDONED,
        STATUS_STALE,
    ],
    STATUS_AWAITING_DEPOSIT: [
        STATUS_DEPOSIT_PAID,
        STATUS_DEPOSIT_EXPIRED,
        STATUS_REJECTED,
        STATUS_NEEDS_ARTIST_REPLY,
        STATUS_NEEDS_FOLLOW_UP,
        STATUS_ABANDONED,
        STATUS_STALE,
        STATUS_BOOKING_LINK_SENT,
        STATUS_COLLECTING_TIME_WINDOWS,  # No slots available - ask for time windows
    ],
    STATUS_DEPOSIT_PAID: [
        STATUS_BOOKING_PENDING,
        STATUS_REJECTED,
        STATUS_NEEDS_ARTIST_REPLY,
        STATUS_NEEDS_FOLLOW_UP,
        STATUS_ABANDONED,
        STATUS_STALE,
        STATUS_BOOKING_LINK_SENT,
    ],
    STATUS_BOOKING_PENDING: [
        STATUS_BOOKED,
        STATUS_REJECTED,
        STATUS_NEEDS_ARTIST_REPLY,
        STATUS_NEEDS_FOLLOW_UP,
        STATUS_ABANDONED,
        STATUS_STALE,
        STATUS_COLLECTING_TIME_WINDOWS,
    ],
    STATUS_BOOKED: [
        # Terminal state - no transitions allowed
    ],
    STATUS_REJECTED: [
        # Terminal state - no transitions allowed
    ],
    STATUS_NEEDS_ARTIST_REPLY: [
        STATUS_QUALIFYING,  # Resume flow
        STATUS_PENDING_APPROVAL,
        STATUS_AWAITING_DEPOSIT,
        STATUS_DEPOSIT_PAID,
        STATUS_BOOKING_PENDING,
        STATUS_REJECTED,
        STATUS_ABANDONED,
        STATUS_STALE,
        STATUS_OPTOUT,  # Opt-out wins even during handover (STOP/UNSUBSCRIBE)
    ],
    STATUS_NEEDS_FOLLOW_UP: [
        STATUS_PENDING_APPROVAL,
        STATUS_AWAITING_DEPOSIT,
        STATUS_DEPOSIT_PAID,
        STATUS_BOOKING_PENDING,
        STATUS_REJECTED,
        STATUS_ABANDONED,
        STATUS_STALE,
    ],
    STATUS_TOUR_CONVERSION_OFFERED: [
        STATUS_QUALIFYING,  # Tour accepted - continue qualification
        STATUS_PENDING_APPROVAL,  # Tour accepted - qualified for offered city
        STATUS_WAITLISTED,
        STATUS_REJECTED,
        STATUS_ABANDONED,
        STATUS_STALE,
    ],
    STATUS_WAITLISTED: [
        # Terminal state - no transitions allowed
    ],
    STATUS_COLLECTING_TIME_WINDOWS: [
        STATUS_NEEDS_ARTIST_REPLY,
        STATUS_BOOKING_PENDING,
    ],
    STATUS_BOOKING_LINK_SENT: [
        STATUS_BOOKING_PENDING,
    ],
    STATUS_NEEDS_MANUAL_FOLLOW_UP: [
        # Terminal / internal - no transitions
    ],
    STATUS_ABANDONED: [
        STATUS_NEW,  # Restart (user can re-engage)
    ],
    STATUS_STALE: [
        STATUS_NEW,  # Restart (user can re-engage)
    ],
    STATUS_OPTOUT: [
        STATUS_NEW,  # Restart (user sends START/RESUME/CONTINUE/YES)
    ],
    STATUS_DEPOSIT_EXPIRED: [
        STATUS_REJECTED,
        STATUS_ABANDONED,
        STATUS_STALE,
    ],
}

# Terminal state definitions (for documentation and validation)
TERMINAL_STATES = {
    STATUS_BOOKED,
    STATUS_REJECTED,
    STATUS_ABANDONED,
    STATUS_STALE,
    STATUS_WAITLISTED,
    STATUS_OPTOUT,
}

# State semantics (for documentation)
STATE_SEMANTICS = {
    STATUS_ABANDONED: "User stopped responding mid-flow (time-based)",
    STATUS_STALE: "System-level timeout / no longer actionable (e.g., too old to revive)",
    STATUS_OPTOUT: "User explicitly STOP / unsubscribed (highest priority - blocks all outbound messages)",
    STATUS_WAITLISTED: "User wants it, but you can't serve now (tour declined, waitlisted)",
    STATUS_BOOKED: "Successfully booked - terminal success state",
    STATUS_REJECTED: "Artist rejected the lead - terminal rejection state",
}


def is_transition_allowed(from_status: str, to_status: str) -> bool:
    """
    Check if a status transition is allowed.

    Args:
        from_status: Current status
        to_status: Target status

    Returns:
        True if transition is allowed, False otherwise
    """
    allowed = ALLOWED_TRANSITIONS.get(from_status, [])
    return to_status in allowed


def transition(
    db: Session,
    lead: Lead,
    to_status: str,
    reason: str | None = None,
    update_timestamp: bool = True,
    lock_row: bool = True,
) -> bool:
    """
    Transition a lead to a new status (with validation and concurrency control).

    CRITICAL: This function uses SELECT FOR UPDATE to prevent race conditions.
    All transitions happen in a single transaction.

    Args:
        db: Database session
        lead: Lead object (will be reloaded with lock if lock_row=True)
        to_status: Target status
        reason: Optional reason for transition (stored in handover_reason if applicable)
        update_timestamp: Whether to update status-specific timestamp
        lock_row: Whether to lock the row (SELECT FOR UPDATE) - should be True for production

    Returns:
        True if transition succeeded

    Raises:
        ValueError: If transition is not allowed
    """
    lead_id = lead.id
    from_status = lead.status

    # Check if transition is allowed (before locking)
    if not is_transition_allowed(from_status, to_status):
        logger.warning(
            f"Invalid status transition attempted: {from_status} -> {to_status} for lead {lead.id}"
        )
        raise ValueError(
            f"Invalid status transition: {from_status} -> {to_status}. "
            f"Allowed transitions from {from_status}: {ALLOWED_TRANSITIONS.get(from_status, [])}"
        )

    # CRITICAL FIX: Lock the row to prevent race conditions
    # Reload lead with SELECT FOR UPDATE to lock it
    if lock_row:
        stmt = select(Lead).where(Lead.id == lead_id).with_for_update()
        locked_lead = db.execute(stmt).scalar_one_or_none()
        if not locked_lead:
            raise ValueError(f"Lead {lead_id} not found")

        # Re-check status after locking (another request may have changed it)
        if locked_lead.status != from_status:
            logger.warning(
                f"Lead {lead_id} status changed during transition: "
                f"expected '{from_status}', got '{locked_lead.status}'"
            )
            raise ValueError(
                f"Lead status changed during transition. Expected '{from_status}', "
                f"but lead is now in '{locked_lead.status}'"
            )

        lead = locked_lead

    # Update status
    lead.status = to_status

    # Update status-specific timestamps
    if update_timestamp:
        now = func.now()

        if to_status == STATUS_QUALIFYING and not lead.qualifying_started_at:
            lead.qualifying_started_at = now
        elif to_status == STATUS_PENDING_APPROVAL:
            lead.pending_approval_at = now
        elif to_status == STATUS_AWAITING_DEPOSIT:
            lead.deposit_sent_at = now
        elif to_status == STATUS_DEPOSIT_PAID:
            lead.deposit_paid_at = now
        elif to_status == STATUS_BOOKING_PENDING:
            lead.booking_pending_at = now
        elif to_status == STATUS_BOOKED:
            lead.booked_at = now
        elif to_status == STATUS_REJECTED:
            lead.rejected_at = now
        elif to_status == STATUS_NEEDS_ARTIST_REPLY:
            lead.needs_artist_reply_at = now
        elif to_status == STATUS_NEEDS_FOLLOW_UP:
            lead.needs_follow_up_at = now
        elif to_status == STATUS_ABANDONED:
            lead.abandoned_at = now
        elif to_status == STATUS_STALE:
            lead.stale_at = now

    # Store reason if provided (for handover cases)
    if reason and to_status == STATUS_NEEDS_ARTIST_REPLY:
        lead.handover_reason = reason

    # Commit the transition (side effects happen AFTER this)
    db.commit()
    db.refresh(lead)

    logger.info(
        f"Lead {lead.id} transitioned: {from_status} -> {to_status}"
        + (f" (reason: {reason})" if reason else "")
    )

    return True


def advance_step_if_at(
    db: Session,
    lead_id: int,
    expected_step: int,
) -> tuple[bool, Lead | None]:
    """
    Atomically advance current_step only if it equals expected_step (prevents double-advance).

    Uses SELECT FOR UPDATE to lock the row, then updates current_step.
    Call this when advancing step after saving an answer; use returned lead for next question.

    Args:
        db: Database session
        lead_id: Lead ID
        expected_step: Step the lead must currently be on

    Returns:
        (True, updated_lead) if step was advanced, (False, None) if another request already advanced
    """
    stmt = select(Lead).where(Lead.id == lead_id).with_for_update()
    locked = db.execute(stmt).scalar_one_or_none()
    if not locked:
        return False, None
    if locked.current_step != expected_step:
        logger.debug(
            f"Lead {lead_id} step mismatch: expected {expected_step}, got {locked.current_step}"
        )
        return False, None
    locked.current_step = expected_step + 1
    db.commit()
    db.refresh(locked)
    logger.info(f"Lead {lead_id} step advanced: {expected_step} -> {locked.current_step}")
    return True, locked


def get_allowed_transitions(from_status: str) -> list[str]:
    """
    Get list of allowed transitions from a status.

    Args:
        from_status: Current status

    Returns:
        List of allowed target statuses
    """
    return ALLOWED_TRANSITIONS.get(from_status, [])


def is_terminal_state(status: str) -> bool:
    """
    Check if a status is terminal (no transitions allowed).

    Args:
        status: Status to check

    Returns:
        True if terminal, False otherwise
    """
    return status in TERMINAL_STATES


def get_state_semantics(status: str) -> str | None:
    """
    Get the semantic meaning of a status (for documentation/debugging).

    Args:
        status: Status to get semantics for

    Returns:
        Semantic description or None if not defined
    """
    return STATE_SEMANTICS.get(status)
