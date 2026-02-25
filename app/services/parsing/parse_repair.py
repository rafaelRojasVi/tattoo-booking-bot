"""
Parse repair service - handles soft repair messages and two-strikes handover logic.
"""

import logging
from typing import Literal, cast

from sqlalchemy.orm import Session

from app.db.helpers import commit_and_refresh
from app.db.models import Lead
from app.constants.statuses import STATUS_NEEDS_ARTIST_REPLY

logger = logging.getLogger(__name__)

# Fields that can have parse failures
ParseableField = Literal["dimensions", "budget", "location_city", "slot"]
MAX_FAILURES = 3  # Retry 1 = gentle, retry 2 = short+example+boundary, retry 3 = handover


def increment_parse_failure(db: Session, lead: Lead, field: ParseableField) -> int:
    """
    Increment parse failure count for a field and return the new count.

    Args:
        db: Database session
        lead: Lead object
        field: Field that failed to parse

    Returns:
        New failure count for this field
    """
    if lead.parse_failure_counts is None:
        lead.parse_failure_counts = {}

    current_count = lead.parse_failure_counts.get(field, 0)
    new_count = current_count + 1
    lead.parse_failure_counts[field] = new_count

    # Mark JSON field as modified for SQLAlchemy
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(lead, "parse_failure_counts")

    commit_and_refresh(db, lead)

    logger.info(f"Lead {lead.id}: Parse failure for '{field}' (count: {new_count})")
    return cast(int, new_count)


def reset_parse_failures(db: Session, lead: Lead, field: ParseableField) -> None:
    """
    Reset parse failure count for a field (when parsing succeeds).

    Args:
        db: Database session
        lead: Lead object
        field: Field that was successfully parsed
    """
    if lead.parse_failure_counts is None:
        return

    if field in lead.parse_failure_counts:
        lead.parse_failure_counts[field] = 0
        # Mark JSON field as modified for SQLAlchemy
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(lead, "parse_failure_counts")
        commit_and_refresh(db, lead)
        logger.info(f"Lead {lead.id}: Reset parse failures for '{field}'")


def get_failure_count(lead: Lead, field: ParseableField) -> int:
    """Get current failure count for a field."""
    if lead.parse_failure_counts is None:
        return 0
    return cast(int, lead.parse_failure_counts.get(field, 0))


def should_handover_after_failure(lead: Lead, field: ParseableField) -> bool:
    """
    Check if we should handover after a parse failure (three-strikes rule).

    Args:
        lead: Lead object
        field: Field that failed to parse

    Returns:
        True if we should handover (count >= MAX_FAILURES), False otherwise
    """
    count = get_failure_count(lead, field)
    return count >= MAX_FAILURES


async def trigger_handover_after_parse_failure(
    db: Session,
    lead: Lead,
    field: ParseableField,
    dry_run: bool = True,
) -> dict:
    """
    Trigger handover after MAX_FAILURES parse failures on the same field.

    Args:
        db: Database session
        lead: Lead object
        field: Field that failed to parse twice
        dry_run: Whether to actually send messages

    Returns:
        dict with handover status
    """
    from sqlalchemy import func

    from app.services.integrations.artist_notifications import notify_artist_needs_reply
    from app.services.messaging.message_composer import render_message
    from app.services.messaging.messaging import send_whatsapp_message
    from app.services.conversation.state_machine import transition

    failure_reason = f"Unable to parse {field} after {MAX_FAILURES} attempts"
    transition(db, lead, STATUS_NEEDS_ARTIST_REPLY, reason=failure_reason)

    # Notify artist with context
    await notify_artist_needs_reply(
        db=db,
        lead=lead,
        reason=failure_reason,
        dry_run=dry_run,
    )

    # Send bridge message to client
    bridge_msg = render_message("handover_bridge", lead_id=lead.id)
    await send_whatsapp_message(
        to=lead.wa_from,
        message=bridge_msg,
        dry_run=dry_run,
    )
    lead.last_bot_message_at = func.now()
    db.commit()

    logger.warning(
        f"Lead {lead.id}: Handover triggered after {MAX_FAILURES} parse failures for '{field}'"
    )

    return {
        "status": "handover_parse_failure",
        "message": bridge_msg,
        "lead_status": lead.status,
        "field": field,
        "reason": failure_reason,
    }
