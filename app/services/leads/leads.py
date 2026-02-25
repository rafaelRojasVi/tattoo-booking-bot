from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.constants.statuses import (
    STATUS_AWAITING_DEPOSIT,
    STATUS_BOOKING_LINK_SENT,
    STATUS_DEPOSIT_PAID,
    STATUS_NEEDS_ARTIST_REPLY,
    STATUS_PENDING_APPROVAL,
    STATUS_QUALIFYING,
)
from app.db.helpers import commit_and_refresh
from app.db.models import Lead
from app.services.integrations.sheets import log_lead_to_sheets

# Active statuses - leads in these statuses should be reused
ACTIVE_STATUSES = {
    STATUS_QUALIFYING,
    STATUS_NEEDS_ARTIST_REPLY,
    STATUS_PENDING_APPROVAL,
    STATUS_AWAITING_DEPOSIT,
    STATUS_DEPOSIT_PAID,
    STATUS_BOOKING_LINK_SENT,
}

# Inactive statuses - leads in these statuses allow new lead creation
INACTIVE_STATUSES = {
    "BOOKED",
    "REJECTED",
    "ABANDONED",
    "STALE",
    "NEEDS_FOLLOW_UP",
    "OPTOUT",  # Opted out - can create new lead if they message again
    "DEPOSIT_EXPIRED",
    "REFUNDED",
    "CANCELLED",
}


def get_lead_or_none(db: Session, lead_id: int) -> Lead | None:
    """
    Load a lead by ID. Returns None if not found.

    Use when the caller will handle "not found" (e.g. return tuple, log, raise).
    """
    return db.get(Lead, lead_id)


def get_or_create_lead(db: Session, wa_from: str) -> Lead:
    """
    Get existing lead or create a new one.

    Policy:
    - If active lead exists (status in ACTIVE_STATUSES) → reuse it
    - If only inactive leads exist (BOOKED, REJECTED, etc.) → create new lead
    - If no leads exist → create new lead

    Args:
        db: Database session
        wa_from: WhatsApp phone number

    Returns:
        Lead object

    Raises:
        SQLAlchemyError: If database operation fails
        ValueError: If wa_from is invalid
    """
    if not wa_from or not isinstance(wa_from, str):
        raise ValueError("wa_from must be a non-empty string")

    try:
        # Get all leads for this phone number, ordered by most recent first
        stmt = select(Lead).where(Lead.wa_from == wa_from).order_by(desc(Lead.created_at))
        leads = db.execute(stmt).scalars().all()

        # Check for active leads first
        for lead in leads:
            if lead.status in ACTIVE_STATUSES:
                # Active lead exists - reuse it
                return lead

        # No active leads found - check if we should create new or reuse most recent inactive
        # Policy: If most recent lead is inactive, create a new lead (allows multiple enquiries)
        if leads:
            most_recent = leads[0]
            if most_recent.status in INACTIVE_STATUSES:
                # Most recent is inactive - create new lead
                pass  # Fall through to create new lead
            else:
                # Most recent is in some other status (shouldn't happen, but be safe)
                # Reuse it to be safe
                return most_recent

        # No leads exist OR most recent is inactive - create new lead
        lead = Lead(wa_from=wa_from, status="NEW")
        db.add(lead)
        commit_and_refresh(db, lead)

        log_lead_to_sheets(db, lead)

        return lead
    except SQLAlchemyError:
        db.rollback()
        raise
