"""
Time window collection service - handles collecting preferred time windows when no slots available.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Lead, LeadAnswer
from app.services.conversation import STATUS_NEEDS_ARTIST_REPLY
from app.services.messaging import send_whatsapp_message

logger = logging.getLogger(__name__)

# Question key for preferred time windows
PREFERRED_TIME_WINDOWS_KEY = "preferred_time_windows"


def format_time_windows_request(lead_id: int | None = None) -> str:
    """
    Format the request message asking for preferred time windows.

    Args:
        lead_id: Lead ID for deterministic variant selection

    Returns:
        Formatted message string
    """
    from app.services.message_composer import render_message

    return render_message("time_window_request", lead_id=lead_id)


def count_time_windows(lead: Lead, db: Session) -> int:
    """
    Count how many time windows have been collected.

    Args:
        lead: Lead object
        db: Database session

    Returns:
        Number of time windows collected
    """
    stmt = select(LeadAnswer).where(
        LeadAnswer.lead_id == lead.id,
        LeadAnswer.question_key == PREFERRED_TIME_WINDOWS_KEY,
    )
    answers = db.execute(stmt).scalars().all()
    return len(answers)


async def collect_time_window(
    db: Session,
    lead: Lead,
    message_text: str,
    dry_run: bool = True,
) -> dict:
    """
    Collect a preferred time window from the user.

    Args:
        db: Database session
        lead: Lead object
        message_text: User's message with time window
        dry_run: Whether to actually send WhatsApp messages

    Returns:
        dict with status and next action
    """
    # Ensure status is COLLECTING_TIME_WINDOWS (enforced via state machine)
    from app.services.conversation import STATUS_COLLECTING_TIME_WINDOWS
    from app.services.state_machine import transition

    if lead.status != STATUS_COLLECTING_TIME_WINDOWS:
        transition(db, lead, STATUS_COLLECTING_TIME_WINDOWS)

    # Store the time window as an answer
    answer = LeadAnswer(
        lead_id=lead.id,
        question_key=PREFERRED_TIME_WINDOWS_KEY,
        answer_text=message_text.strip(),
    )
    db.add(answer)
    lead.last_client_message_at = func.now()
    db.commit()
    db.refresh(lead)

    # Count collected windows
    window_count = count_time_windows(lead, db)

    # Check if we have enough (2-3 windows)
    if window_count >= 2:
        # We have enough - transition to NEEDS_ARTIST_REPLY and notify artist
        from app.services.artist_notifications import notify_artist_needs_reply
        from app.services.state_machine import transition

        reason = (
            f"Collected {window_count} preferred time windows - no calendar slots available"
        )
        transition(db, lead, STATUS_NEEDS_ARTIST_REPLY, reason=reason)

        # Notify artist with summary
        try:
            await notify_artist_needs_reply(
                db=db,
                lead=lead,
                reason=f"Collected {window_count} preferred time windows - no calendar slots available",
                dry_run=dry_run,
            )
        except Exception as e:
            logger.error(f"Failed to notify artist for lead {lead.id}: {e}")

        # Send confirmation to client
        from app.services.message_composer import render_message

        confirmation_msg = render_message(
            "time_window_collected",
            lead_id=lead.id,
            window_count=window_count,
        )
        await send_whatsapp_message(
            to=lead.wa_from,
            message=confirmation_msg,
            dry_run=dry_run,
        )
        lead.last_bot_message_at = func.now()
        db.commit()

        from app.services.sheets import log_lead_to_sheets

        log_lead_to_sheets(db, lead)

        return {
            "status": "time_windows_collected",
            "message": confirmation_msg,
            "lead_status": lead.status,
            "window_count": window_count,
        }
    else:
        # Need more windows - ask for another
        from app.services.message_composer import render_message

        remaining = 2 - window_count
        if window_count == 0:
            follow_up_msg = render_message("time_window_follow_up", lead_id=lead.id)
        else:
            follow_up_msg = render_message(
                "time_window_follow_up_remaining",
                lead_id=lead.id,
                remaining=remaining,
            )

        await send_whatsapp_message(
            to=lead.wa_from,
            message=follow_up_msg,
            dry_run=dry_run,
        )
        lead.last_bot_message_at = func.now()
        db.commit()

        return {
            "status": "collecting_time_windows",
            "message": follow_up_msg,
            "lead_status": lead.status,
            "window_count": window_count,
        }
