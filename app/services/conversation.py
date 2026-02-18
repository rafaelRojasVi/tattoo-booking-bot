"""
Conversation flow service - handles state machine and question flow.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants.event_types import EVENT_NEEDS_ARTIST_REPLY
from app.constants.statuses import (
    STATUS_ABANDONED,
    STATUS_AWAITING_DEPOSIT,
    STATUS_BOOKED,
    STATUS_BOOKING_LINK_SENT,
    STATUS_BOOKING_PENDING,
    STATUS_CANCELLED,
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
    STATUS_REFUNDED,
    STATUS_REJECTED,
    STATUS_STALE,
    STATUS_TOUR_CONVERSION_OFFERED,
    STATUS_WAITLISTED,
)
from app.db.models import Lead, LeadAnswer
from app.services.conversation_booking import (
    HANDOVER_HOLD_REPLY_COOLDOWN_HOURS,
    _handle_booking_pending,
    _handle_needs_artist_reply,
    _handle_tour_conversion_offered,
)
from app.services.conversation_qualifying import (
    _complete_qualification,
    _handle_new_lead,
    _handle_qualifying_lead,
    _maybe_send_confirmation_summary,
)
from app.services.messaging import format_summary_message, send_whatsapp_message
from app.services.state_machine import transition
from app.utils.datetime_utils import iso_or_none

logger = logging.getLogger(__name__)

# Re-export STATUS_* for backward compatibility (tests and other modules may import from here)
# Prefer app.constants.statuses for new code.
# Re-export handlers for tests
__all__ = [
    "HANDOVER_HOLD_REPLY_COOLDOWN_HOURS",
    "STATUS_ABANDONED",
    "STATUS_AWAITING_DEPOSIT",
    "STATUS_BOOKED",
    "STATUS_BOOKING_LINK_SENT",
    "STATUS_BOOKING_PENDING",
    "STATUS_CANCELLED",
    "STATUS_COLLECTING_TIME_WINDOWS",
    "STATUS_DEPOSIT_EXPIRED",
    "STATUS_DEPOSIT_PAID",
    "STATUS_NEEDS_ARTIST_REPLY",
    "STATUS_NEEDS_FOLLOW_UP",
    "STATUS_NEEDS_MANUAL_FOLLOW_UP",
    "STATUS_NEW",
    "STATUS_OPTOUT",
    "STATUS_PENDING_APPROVAL",
    "STATUS_QUALIFYING",
    "STATUS_REFUNDED",
    "STATUS_REJECTED",
    "STATUS_STALE",
    "STATUS_TOUR_CONVERSION_OFFERED",
    "STATUS_WAITLISTED",
    "_complete_qualification",
    "_handle_qualifying_lead",
    "_maybe_send_confirmation_summary",
]


async def handle_inbound_message(
    db: Session,
    lead: Lead,
    message_text: str,
    dry_run: bool = True,
    *,
    has_media: bool = False,
) -> dict:
    """
    Handle an inbound message based on lead's current state.

    Args:
        db: Database session
        lead: Lead object
        message_text: Incoming message text
        dry_run: Whether to actually send WhatsApp messages

    Returns:
        dict with status, next_message, and state info
    """
    from app.core.config import settings

    # Panic Mode: pause automation, only log + notify artist
    if settings.feature_panic_mode_enabled:
        logger.warning(
            f"PANIC MODE ENABLED - Lead {lead.id} received message but automation paused"
        )

        # Check window BEFORE updating timestamp (to see if we can send response)
        from app.services.whatsapp_window import is_within_24h_window

        is_within, _ = is_within_24h_window(lead)

        # Still log the message
        lead.last_client_message_at = func.now()
        db.commit()
        db.refresh(lead)

        # Notify artist (if notifications enabled)
        if settings.feature_notifications_enabled:
            from app.services.artist_notifications import notify_artist

            await notify_artist(
                db=db,
                lead=lead,
                event_type=EVENT_NEEDS_ARTIST_REPLY,
                dry_run=dry_run,
            )

        # Send safe response (only if within 24h window)
        if is_within:
            from app.services.message_composer import render_message

            safe_message = render_message("panic_mode_response", lead_id=lead.id)
            await send_whatsapp_message(
                to=lead.wa_from,
                message=safe_message,
                dry_run=dry_run,
            )
            lead.last_bot_message_at = func.now()
            db.commit()

        return {
            "status": "panic_mode",
            "message": "Automation paused (panic mode)",
            "lead_status": lead.status,
        }

    if lead.status == STATUS_NEW:
        return await _handle_new_lead(db, lead, dry_run)

    elif lead.status == STATUS_QUALIFYING:
        return await _handle_qualifying_lead(db, lead, message_text, dry_run, has_media=has_media)

    elif lead.status == STATUS_PENDING_APPROVAL:
        # Waiting for artist approval - acknowledge
        from app.services.message_composer import render_message

        return {
            "status": "pending_approval",
            "message": render_message("pending_approval", lead_id=lead.id),
            "lead_status": lead.status,
        }

    elif lead.status == STATUS_AWAITING_DEPOSIT:
        # Approved, waiting for deposit payment
        # Client may be responding to slot suggestions or asking about deposit
        # Check if client is selecting a slot (simple pattern matching)
        # In Phase 1, we'll handle basic slot selection responses
        # For now, acknowledge and remind about deposit
        from app.services.message_composer import render_message

        return {
            "status": "awaiting_deposit",
            "message": render_message("awaiting_deposit", lead_id=lead.id),
            "lead_status": lead.status,
        }

    elif lead.status == STATUS_DEPOSIT_PAID:
        # Deposit paid, waiting for booking
        from app.services.message_composer import render_message

        return {
            "status": "deposit_paid",
            "message": render_message("deposit_paid", lead_id=lead.id),
            "lead_status": lead.status,
        }

    elif lead.status == STATUS_BOOKING_PENDING:
        return await _handle_booking_pending(db, lead, message_text, dry_run)

    elif lead.status == STATUS_COLLECTING_TIME_WINDOWS:
        # Collecting preferred time windows (fallback when no slots available)
        from app.services.time_window_collection import collect_time_window

        return await collect_time_window(db, lead, message_text, dry_run)

    elif lead.status == STATUS_BOOKING_LINK_SENT:
        # Legacy status - map to BOOKING_PENDING (enforced via state machine)
        transition(db, lead, STATUS_BOOKING_PENDING)
        return {
            "status": "booking_pending",
            "message": "Thanks for your deposit! Jonah will confirm your date in the calendar and message you.",
            "lead_status": lead.status,
        }

    elif lead.status == STATUS_TOUR_CONVERSION_OFFERED:
        return await _handle_tour_conversion_offered(db, lead, message_text, dry_run)

    elif lead.status == STATUS_WAITLISTED:
        # Client is waitlisted
        from app.services.message_composer import render_message

        return {
            "status": "waitlisted",
            "message": render_message("tour_waitlisted", lead_id=lead.id),
            "lead_status": lead.status,
        }

    elif lead.status == STATUS_BOOKED:
        # Already booked
        return {
            "status": "booked",
            "message": "Your booking is confirmed! I'll see you soon. 🎉",
            "lead_status": lead.status,
        }

    elif lead.status == STATUS_NEEDS_ARTIST_REPLY:
        return await _handle_needs_artist_reply(db, lead, message_text, dry_run)

    elif lead.status in [STATUS_NEEDS_FOLLOW_UP, STATUS_NEEDS_MANUAL_FOLLOW_UP]:
        # Needs human intervention
        return {
            "status": "manual_followup",
            "message": "A team member will reach out to you shortly.",
            "lead_status": lead.status,
        }

    elif lead.status == STATUS_REJECTED:
        return {
            "status": "rejected",
            "message": "Thank you for your interest. Unfortunately, we're unable to proceed at this time.",
            "lead_status": lead.status,
        }

    elif lead.status == STATUS_OPTOUT:
        # Client opted out - allow them to opt back in (restart policy: OPTOUT -> NEW)
        if message_text.strip().upper() in ["START", "RESUME", "CONTINUE", "YES"]:
            transition(db, lead, STATUS_NEW)
            lead.current_step = 0
            db.commit()
            db.refresh(lead)
            return await _handle_new_lead(db, lead, dry_run)
        else:
            # Still opted out - acknowledge but don't send automated messages
            from app.services.message_composer import render_message

            return {
                "status": "opted_out",
                "message": render_message("opt_out_prompt", lead_id=lead.id),
                "lead_status": lead.status,
            }

    elif lead.status in [STATUS_ABANDONED, STATUS_STALE]:
        # Inactive leads - allow restart (ABANDONED/STALE -> NEW)
        # Update last_client_message_at so 24h window opens for next message
        lead.last_client_message_at = func.now()
        transition(db, lead, STATUS_NEW)
        lead.current_step = 0
        db.commit()
        db.refresh(lead)
        return await _handle_new_lead(db, lead, dry_run)

    else:
        # Unknown status - reset to NEW (bypass state machine for recovery; status not in ALLOWED_TRANSITIONS)
        lead.status = STATUS_NEW
        lead.current_step = 0
        db.commit()
        db.refresh(lead)
        return await _handle_new_lead(db, lead, dry_run)


def get_lead_summary(db: Session, lead_id: int) -> dict:
    """
    Get structured summary of a lead's consultation.

    Args:
        db: Database session
        lead_id: Lead ID

    Returns:
        dict with status, current_step, answers, and formatted summary
    """
    stmt = select(Lead).where(Lead.id == lead_id)
    lead = db.execute(stmt).scalar_one_or_none()

    if not lead:
        return {"error": "Lead not found"}

    # Get all answers (created_at, id so "latest wins" is deterministic when timestamps tie)
    stmt_answers = (
        select(LeadAnswer)
        .where(LeadAnswer.lead_id == lead_id)
        .order_by(LeadAnswer.created_at, LeadAnswer.id)
    )
    answers_list = db.execute(stmt_answers).scalars().all()

    answers_dict = {ans.question_key: ans.answer_text for ans in answers_list}

    summary_text = format_summary_message(answers_dict) if answers_dict else None

    return {
        "lead_id": lead.id,
        "wa_from": lead.wa_from,
        "status": lead.status,
        "current_step": lead.current_step,
        "answers": answers_dict,
        "summary_text": summary_text,
        "created_at": iso_or_none(lead.created_at),
        "updated_at": iso_or_none(lead.updated_at),
    }
