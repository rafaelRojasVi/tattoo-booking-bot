"""
Artist notification service - sends WhatsApp summaries and notifications to artist.
"""

import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Lead
from app.services.messaging import send_whatsapp_message

logger = logging.getLogger(__name__)


async def send_system_alert(message: str, dry_run: bool = True) -> dict:
    """
    Send a system alert to the artist (for critical system issues).

    Args:
        message: Alert message to send
        dry_run: Whether to actually send

    Returns:
        dict with status
    """
    from app.core.config import settings
    from app.services.messaging import send_whatsapp_message

    if not settings.artist_whatsapp_number:
        logger.warning("Artist WhatsApp number not configured - system alert not sent")
        return {"status": "skipped", "reason": "artist_whatsapp_number not configured"}

    try:
        result = await send_whatsapp_message(
            to=settings.artist_whatsapp_number,
            message=f"🔔 *System Alert*\n\n{message}",
            dry_run=dry_run,
        )
        logger.info(f"System alert sent to artist: {message[:50]}...")
        return result
    except Exception as e:
        logger.error(f"Failed to send system alert to artist: {e}")
        raise


def format_artist_summary(
    lead: Lead, answers_dict: dict[str, str], action_tokens: dict[str, str]
) -> str:
    """
    Format a WhatsApp summary message for the artist with action links.

    Uses Phase 1 summary format with all key fields.

    Args:
        lead: Lead object
        answers_dict: Dict mapping question_key to answer_text (optional, will use lead.answers if not provided)
        action_tokens: Dict mapping action_type to action URL

    Returns:
        Formatted message string
    """
    from app.services.summary import extract_phase1_summary_context, format_summary_message

    # If answers_dict is provided, temporarily add to lead.answers for context extraction
    # (extract_phase1_summary_context reads from lead.answers)
    original_answers = list(lead.answers)
    if answers_dict:
        # Create temporary LeadAnswer objects for context extraction
        from app.db.models import LeadAnswer

        temp_answers = []
        for key, value in answers_dict.items():
            # Check if answer already exists
            existing = next((a for a in lead.answers if a.question_key == key), None)
            if not existing:
                temp_answer = LeadAnswer(
                    lead_id=lead.id,
                    question_key=key,
                    answer_text=value,
                )
                temp_answers.append(temp_answer)
                lead.answers.append(temp_answer)

    try:
        # Extract Phase 1 context
        ctx = extract_phase1_summary_context(lead)

        # Format summary
        message = format_summary_message(ctx)
    finally:
        # Restore original answers
        if answers_dict:
            lead.answers = original_answers

    # Add action links
    if action_tokens:
        message += "\n*Actions:*\n"
        if "approve" in action_tokens:
            message += f"✅ Approve: {action_tokens['approve']}\n"
        if "reject" in action_tokens:
            message += f"❌ Reject: {action_tokens['reject']}\n"
        if "send_deposit" in action_tokens:
            message += f"💳 Send deposit: {action_tokens['send_deposit']}\n"
        if "mark_booked" in action_tokens:
            message += f"📅 Mark booked: {action_tokens['mark_booked']}\n"

    return message


async def send_artist_summary(
    db: Session,
    lead: Lead,
    answers_dict: dict[str, str],
    action_tokens: dict[str, str],
    dry_run: bool = True,
) -> bool:
    """
    Send WhatsApp summary to artist when consultation completes.

    Args:
        db: Database session
        lead: Lead object
        answers_dict: Dict mapping question_key to answer_text
        action_tokens: Dict mapping action_type to action URL
        dry_run: Whether to actually send WhatsApp messages

    Returns:
        True if successful, False otherwise
    """
    if not settings.artist_whatsapp_number:
        logger.debug("Artist WhatsApp number not configured - skipping summary")
        return False

    try:
        # Format summary message
        message = format_artist_summary(lead, answers_dict, action_tokens)

        # Send to artist
        await send_whatsapp_message(
            to=settings.artist_whatsapp_number,
            message=message,
            dry_run=dry_run or settings.whatsapp_dry_run,
        )

        logger.info(f"Sent artist summary for lead {lead.id}")
        return True

    except Exception as e:
        logger.error(f"Failed to send artist summary for lead {lead.id}: {e}")
        return False


async def notify_artist(
    db: Session,
    lead: Lead,
    event_type: str,
    dry_run: bool = True,
) -> bool:
    """
    Send notification to artist for various events.

    Args:
        db: Database session
        lead: Lead object
        event_type: Type of event (pending_approval, deposit_paid, needs_artist_reply, needs_follow_up)
        dry_run: Whether to actually send WhatsApp messages

    Returns:
        True if successful, False otherwise
    """
    from app.core.config import settings

    # Feature flag check
    if not settings.feature_notifications_enabled:
        logger.debug(
            f"Notifications feature disabled (feature flag) - skipping {event_type} notification for lead {lead.id}"
        )
        return False

    if not settings.artist_whatsapp_number:
        logger.debug("Artist WhatsApp number not configured - skipping notification")
        return False

    try:
        messages = {
            "pending_approval": f"📋 Lead #{lead.id} is ready for review (PENDING_APPROVAL)",
            "deposit_paid": f"💰 Deposit paid for Lead #{lead.id}",
            "needs_artist_reply": f"💬 Lead #{lead.id} needs artist reply",
            "needs_follow_up": f"⚠️ Lead #{lead.id} needs follow-up",
        }

        message = messages.get(event_type)
        if not message:
            logger.warning(f"Unknown event type: {event_type}")
            return False

        await send_whatsapp_message(
            to=settings.artist_whatsapp_number,
            message=message,
            dry_run=dry_run or settings.whatsapp_dry_run,
        )

        logger.info(f"Sent {event_type} notification to artist for lead {lead.id}")
        return True

    except Exception as e:
        logger.error(f"Failed to send {event_type} notification to artist for lead {lead.id}: {e}")
        return False


async def notify_artist_slot_selected(
    db: Session,
    lead: Lead,
    selected_slot: dict,
    slot_number: int,
    dry_run: bool = True,
) -> bool:
    """
    Notify artist when client selects a slot.

    Args:
        db: Database session
        lead: Lead object
        selected_slot: Dict with 'start' and 'end' datetime objects
        slot_number: Selected slot number (1-based)
        dry_run: Whether to actually send WhatsApp messages

    Returns:
        True if notification sent, False otherwise
    """
    if not settings.artist_whatsapp_number:
        logger.debug("Artist WhatsApp number not configured - skipping notification")
        return False

    try:
        from datetime import datetime

        # Format slot time
        start = selected_slot["start"]
        if isinstance(start, str):
            start = datetime.fromisoformat(start)
        end = selected_slot["end"]
        if isinstance(end, str):
            end = datetime.fromisoformat(end)

        date_str = start.strftime("%A, %B %d")
        time_str = start.strftime("%I:%M %p")
        end_time_str = end.strftime("%I:%M %p")

        # Build notification message
        lines = [
            f"✅ *Lead #{lead.id} selected slot*\n",
            f"*Slot {slot_number}:* {date_str} - {time_str} to {end_time_str}",
            "",
        ]

        # Add lead summary
        from app.services.summary import extract_phase1_summary_context, format_summary_message

        ctx = extract_phase1_summary_context(lead)
        summary = format_summary_message(ctx)
        lines.append(summary)

        # Add action links
        from app.services.action_tokens import generate_action_tokens_for_lead

        action_tokens = generate_action_tokens_for_lead(db, lead.id, lead.status)
        if action_tokens:
            lines.append("\n*Actions:*")
            if "approve" in action_tokens:
                lines.append(f"✅ Approve: {action_tokens['approve']}")
            if "reject" in action_tokens:
                lines.append(f"❌ Reject: {action_tokens['reject']}")

        message = "\n".join(lines)

        # Send notification
        await send_whatsapp_message(
            to=settings.artist_whatsapp_number,
            message=message,
            dry_run=dry_run or settings.whatsapp_dry_run,
        )

        logger.info(f"Sent slot selection notification to artist for lead {lead.id}")
        return True

    except Exception as e:
        logger.error(f"Failed to send slot selection notification for lead {lead.id}: {e}")
        return False


async def notify_artist_needs_reply(
    db: Session,
    lead: Lead,
    reason: str,
    dry_run: bool = True,
) -> bool:
    """
    Notify artist when lead needs artist reply (idempotent - only notifies once per transition).

    Args:
        db: Database session
        lead: Lead object
        reason: Handover reason (e.g., "cover-up", "high complexity", "client question outside flow")
        dry_run: Whether to actually send WhatsApp messages

    Returns:
        True if notification sent, False if already notified or failed
    """
    from sqlalchemy import func

    from app.services.action_tokens import generate_action_tokens_for_lead
    from app.services.summary import extract_phase1_summary_context, format_summary_message

    # Idempotency check: only notify if we haven't notified for this transition
    if lead.needs_artist_reply_notified_at is not None:
        logger.debug(f"Already notified artist for lead {lead.id} needs_artist_reply - skipping")
        return False

    if not settings.artist_whatsapp_number:
        logger.debug("Artist WhatsApp number not configured - skipping notification")
        return False

    try:
        # Client name from answers (e.g. name, client_name) for artist context
        client_name = None
        for a in lead.answers:
            if a.question_key in ("name", "client_name"):
                client_name = (a.answer_text or "").strip() or None
                break

        # Build notification message: lead id, contact, name, then reason
        lines = [
            f"⚠️ *Lead #{lead.id} needs you*\n",
            f"*Contact:* {lead.wa_from}",
            f"*Name:* {client_name or '—'}",
            "",
        ]

        # Reason
        if reason:
            lines.append(f"*Reason:* {reason}")

        # Client preference (if captured)
        if lead.preferred_handover_channel:
            channel_display = "quick call" if lead.preferred_handover_channel == "CALL" else "chat"
            lines.append(f"*Client prefers:* {channel_display}")
            if lead.call_availability_notes:
                lines.append(f"*Availability:* {lead.call_availability_notes[:100]}")

        # Preferred time windows (if collected)
        from sqlalchemy import select

        from app.db.models import LeadAnswer
        from app.services.time_window_collection import PREFERRED_TIME_WINDOWS_KEY

        stmt = (
            select(LeadAnswer)
            .where(
                LeadAnswer.lead_id == lead.id,
                LeadAnswer.question_key == PREFERRED_TIME_WINDOWS_KEY,
            )
            .order_by(LeadAnswer.created_at)
        )
        time_window_answers = db.execute(stmt).scalars().all()

        if time_window_answers:
            lines.append("")  # Blank line
            lines.append("*Preferred Time Windows:*")
            for i, answer in enumerate(time_window_answers, 1):
                lines.append(f"{i}. {answer.answer_text}")

        # Last N inbound messages (for context)
        stmt = (
            select(LeadAnswer)
            .where(LeadAnswer.lead_id == lead.id)
            .order_by(LeadAnswer.created_at.desc())
            .limit(3)
        )
        recent_answers = db.execute(stmt).scalars().all()
        if recent_answers:
            lines.append("")  # Blank line
            lines.append("*Last Messages:*")
            for answer in reversed(recent_answers):  # Show oldest first
                lines.append(f"• {answer.question_key}: {answer.answer_text[:80]}")

        # Parse failure context (if available)
        if lead.parse_failure_counts:
            failures = {k: v for k, v in lead.parse_failure_counts.items() if v > 0}
            if failures:
                lines.append("")  # Blank line
                lines.append("*Parse Failures:*")
                for field, count in failures.items():
                    lines.append(f"• {field}: {count} attempt(s)")

        lines.append("")  # Blank line

        # Phase 1 summary block
        ctx = extract_phase1_summary_context(lead)
        summary = format_summary_message(ctx)
        lines.append(summary)

        # Action links
        action_tokens = generate_action_tokens_for_lead(db, lead.id, lead.status)
        if action_tokens:
            lines.append("\n*Actions:*")
            # For NEEDS_ARTIST_REPLY, we might want to add "Mark handled" or "Resume flow" actions
            # For now, just show the lead summary - artist can access via Sheets/admin

        message = "\n".join(lines)

        # Send notification
        await send_whatsapp_message(
            to=settings.artist_whatsapp_number,
            message=message,
            dry_run=dry_run or settings.whatsapp_dry_run,
        )

        # Mark as notified
        lead.needs_artist_reply_notified_at = func.now()
        db.commit()

        logger.info(f"Sent needs_artist_reply notification to artist for lead {lead.id}")
        return True

    except Exception as e:
        logger.error(
            f"Failed to send needs_artist_reply notification to artist for lead {lead.id}: {e}"
        )
        return False


async def notify_artist_needs_follow_up(
    db: Session,
    lead: Lead,
    reason: str,
    dry_run: bool = True,
) -> bool:
    """
    Notify artist when lead needs follow-up (idempotent - only notifies once per transition).

    Args:
        db: Database session
        lead: Lead object
        reason: Follow-up reason (e.g., "Budget below minimum (Min £500, Budget £350)", "Booking pending 72h")
        dry_run: Whether to actually send WhatsApp messages

    Returns:
        True if notification sent, False if already notified or failed
    """
    from sqlalchemy import func

    from app.services.action_tokens import generate_action_tokens_for_lead, get_action_url
    from app.services.summary import extract_phase1_summary_context, format_summary_message

    # Idempotency check: only notify if we haven't notified for this transition
    if lead.needs_follow_up_notified_at is not None:
        logger.debug(f"Already notified artist for lead {lead.id} needs_follow_up - skipping")
        return False

    if not settings.artist_whatsapp_number:
        logger.debug("Artist WhatsApp number not configured - skipping notification")
        return False

    try:
        # Build notification message
        lines = [
            f"🔔 *Lead #{lead.id} needs follow-up*\n",
        ]

        # Reason
        if reason:
            lines.append(f"*Reason:* {reason}")

        lines.append("")  # Blank line

        # Phase 1 summary block
        ctx = extract_phase1_summary_context(lead)
        summary = format_summary_message(ctx)
        lines.append(summary)

        # Action links
        action_tokens = generate_action_tokens_for_lead(db, lead.id, lead.status)
        if action_tokens:
            lines.append("\n*Actions:*")
            for action_type, token in action_tokens.items():
                action_url = get_action_url(token)
                if action_type == "approve":
                    lines.append(f"✅ Approve: {action_url}")
                elif action_type == "reject":
                    lines.append(f"❌ Reject: {action_url}")
                elif action_type == "send_deposit":
                    lines.append(f"💳 Send deposit: {action_url}")

        message = "\n".join(lines)

        # Send notification
        await send_whatsapp_message(
            to=settings.artist_whatsapp_number,
            message=message,
            dry_run=dry_run or settings.whatsapp_dry_run,
        )

        # Mark as notified
        lead.needs_follow_up_notified_at = func.now()
        db.commit()

        logger.info(f"Sent needs_follow_up notification to artist for lead {lead.id}")
        return True

    except Exception as e:
        logger.error(
            f"Failed to send needs_follow_up notification to artist for lead {lead.id}: {e}"
        )
        return False
