"""
Reminder service with idempotency tracking.

Handles reminders for:
- Abandoned leads (client stopped replying during consultation)
- Stale leads (pending approval too long)
- Deposit paid but no booking (follow-up reminders)
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.constants.event_types import reminder_booking_event_type, reminder_qualifying_event_type
from app.constants.providers import PROVIDER_REMINDER
from app.db.helpers import commit_and_refresh
from app.db.models import Lead
from app.constants.statuses import (
    STATUS_ABANDONED,
    STATUS_AWAITING_DEPOSIT,
    STATUS_BOOKING_LINK_SENT,
    STATUS_BOOKING_PENDING,
    STATUS_DEPOSIT_EXPIRED,
    STATUS_DEPOSIT_PAID,
    STATUS_NEEDS_FOLLOW_UP,
    STATUS_OPTOUT,
    STATUS_PENDING_APPROVAL,
    STATUS_QUALIFYING,
    STATUS_STALE,
)
from app.services.safety import check_and_record_processed_event
from app.services.messaging.whatsapp_window import send_with_window_check
from app.utils.datetime_utils import dt_replace_utc, iso_or_none

logger = logging.getLogger(__name__)


def check_and_send_qualifying_reminder(
    db: Session,
    lead: Lead,
    reminder_number: int = 1,  # 1 or 2
    dry_run: bool = True,
) -> dict:
    """
    Phase 1: Check if lead needs a qualifying reminder and send it (idempotent).
    Reminder #1 at 12h, Reminder #2 at 36h.

    Args:
        db: Database session
        lead: Lead object
        reminder_number: Which reminder (1 or 2)
        dry_run: Whether to actually send

    Returns:
        dict with status and reminder info
    """
    from app.core.config import settings

    # Feature flag check
    if not settings.feature_reminders_enabled:
        logger.debug(
            f"Reminders feature disabled (feature flag) - skipping reminder {reminder_number} for lead {lead.id}"
        )
        return {"status": "skipped", "reason": "Reminders feature disabled"}

    # Don't send reminders to opted-out leads
    if lead.status == STATUS_OPTOUT:
        return {"status": "skipped", "reason": "Lead has opted out"}

    if lead.status != STATUS_QUALIFYING:
        return {"status": "skipped", "reason": f"Lead not in {STATUS_QUALIFYING} status"}

    # Phase 1 timing: 12h for reminder 1, 36h for reminder 2
    hours_threshold = 12 if reminder_number == 1 else 36

    # Check if already sent (track separately for each reminder)
    if reminder_number == 1 and lead.reminder_qualifying_sent_at:
        return {"status": "already_sent", "sent_at": iso_or_none(lead.reminder_qualifying_sent_at)}
    # For reminder 2, we'd need a separate field - for now use reminder_booking_sent_24h_at as temp
    # TODO: Add reminder_qualifying_sent_2_at field

    # Check if enough time has passed
    if not lead.last_client_message_at:
        return {"status": "skipped", "reason": "No last client message timestamp"}

    now = datetime.now(UTC)
    last_message = dt_replace_utc(lead.last_client_message_at)
    if last_message is None:
        return {"status": "skipped", "reason": "No last client message timestamp"}
    hours_passed = (now - last_message).total_seconds() / 3600

    if hours_passed < hours_threshold:
        return {"status": "not_due", "hours_passed": hours_passed, "threshold": hours_threshold}

    # Check idempotency
    event_id = f"reminder_qualifying_{lead.id}_{reminder_number}_{hours_threshold}h"
    is_duplicate, processed = check_and_record_processed_event(
        db=db,
        event_id=event_id,
        event_type=reminder_qualifying_event_type(reminder_number),
        lead_id=lead.id,
        provider=PROVIDER_REMINDER,
    )

    if is_duplicate:
        logger.info(
            f"Reminder {reminder_number} already sent for lead {lead.id} (event {event_id})"
        )
        return {"status": "duplicate", "event_id": event_id}

    # Send reminder
    from app.services.messaging.whatsapp_templates import (
        get_template_for_reminder_2,
        get_template_params_consultation_reminder_2_final,
    )

    if reminder_number == 1:
        reminder_message = (
            "👋 Hi! Just checking in - are you still interested in booking a tattoo?\n\n"
            "If so, please reply and we can continue with your consultation. "
            "If not, no worries - just let me know!"
        )
        template_name = None  # Reminder 1 is within 12h, should be within window
        template_params = None
    else:  # reminder 2 (final) - 36h, likely outside window
        reminder_message = (
            "👋 Hi! This is a final check-in - are you still interested?\n\n"
            "If so, please reply to continue. Otherwise, I'll assume you're not ready right now."
        )
        template_name = get_template_for_reminder_2()
        # Get client name if available (from answers or default)
        client_name = None  # TODO: Extract from lead.answers if available
        template_params = get_template_params_consultation_reminder_2_final(client_name=client_name)

    import asyncio

    try:
        result = asyncio.run(
            send_with_window_check(
                db=db,
                lead=lead,
                message=reminder_message,
                template_name=template_name,
                template_params=template_params,
                dry_run=dry_run,
            )
        )
    except RuntimeError:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run,
                send_with_window_check(
                    db=db,
                    lead=lead,
                    message=reminder_message,
                    template_name=template_name,
                    template_params=template_params,
                    dry_run=dry_run,
                ),
            )
            result = future.result()

    # Update lead timestamp
    if reminder_number == 1:
        lead.reminder_qualifying_sent_at = func.now()
    # TODO: Add field for reminder 2
    commit_and_refresh(db, lead)

    return {
        "status": "sent",
        "event_id": event_id,
        "result": result,
        "reminder_number": reminder_number,
        "sent_at": iso_or_none(lead.reminder_qualifying_sent_at)
        if lead.reminder_qualifying_sent_at
        else None,
    }


def check_and_mark_abandoned(
    db: Session,
    lead: Lead,
    hours_threshold: int = 48,
) -> dict:
    """
    Phase 1: Mark lead as abandoned if inactive for 48h during qualification.

    Args:
        db: Database session
        lead: Lead object
        hours_threshold: Hours of inactivity before abandoning (default 48)

    Returns:
        dict with status
    """
    if lead.status != STATUS_QUALIFYING:
        return {"status": "skipped", "reason": f"Lead not in {STATUS_QUALIFYING} status"}

    if lead.abandoned_at:
        return {"status": "already_abandoned", "abandoned_at": iso_or_none(lead.abandoned_at)}

    if not lead.last_client_message_at:
        return {"status": "skipped", "reason": "No last client message timestamp"}

    now = datetime.now(UTC)
    last_message = dt_replace_utc(lead.last_client_message_at)
    if last_message is None:
        return {"status": "skipped", "reason": "No last client message timestamp"}
    hours_passed = (now - last_message).total_seconds() / 3600

    if hours_passed < hours_threshold:
        return {"status": "not_due", "hours_passed": hours_passed}

    # Mark as abandoned
    lead.status = STATUS_ABANDONED
    lead.abandoned_at = func.now()
    db.commit()

    return {
        "status": "abandoned",
        "abandoned_at": iso_or_none(lead.abandoned_at),
    }


def check_and_mark_stale(
    db: Session,
    lead: Lead,
    days_threshold: int = 3,
) -> dict:
    """
    Phase 1: Mark lead as stale if PENDING_APPROVAL for 3 days.

    Args:
        db: Database session
        lead: Lead object
        days_threshold: Days before marking stale (default 3)

    Returns:
        dict with status
    """
    if lead.status != STATUS_PENDING_APPROVAL:
        return {"status": "skipped", "reason": f"Lead not in {STATUS_PENDING_APPROVAL} status"}

    if lead.stale_at:
        return {"status": "already_stale", "stale_at": iso_or_none(lead.stale_at)}

    if not lead.pending_approval_at:
        return {"status": "skipped", "reason": "No pending_approval_at timestamp"}

    now = datetime.now(UTC)
    pending_since = dt_replace_utc(lead.pending_approval_at)
    if pending_since is None:
        return {"status": "skipped", "reason": "No pending_approval_at timestamp"}
    days_passed = (now - pending_since).total_seconds() / (3600 * 24)

    if days_passed < days_threshold:
        return {"status": "not_due", "days_passed": days_passed}

    # Mark as stale
    lead.status = STATUS_STALE
    lead.stale_at = func.now()
    db.commit()

    return {
        "status": "stale",
        "stale_at": iso_or_none(lead.stale_at),
    }


def check_and_send_booking_reminder(
    db: Session,
    lead: Lead,
    hours_since_booking_link: int = 24,
    reminder_type: str = "24h",  # "24h" or "72h"
    dry_run: bool = True,
) -> dict:
    """
    Check if lead needs a booking reminder and send it (idempotent).

    Args:
        db: Database session
        lead: Lead object
        hours_since_booking_link: Hours to wait before sending reminder
        reminder_type: Type of reminder ("24h" or "72h")
        dry_run: Whether to actually send

    Returns:
        dict with status and reminder info
    """
    if lead.status not in [STATUS_DEPOSIT_PAID, STATUS_BOOKING_LINK_SENT]:
        return {"status": "skipped", "reason": "Lead not in correct status for booking reminder"}

    # Don't send reminders to opted-out leads
    if lead.status == STATUS_OPTOUT:
        return {"status": "skipped", "reason": "Lead has opted out"}

    # Check if already sent
    if reminder_type == "24h" and lead.reminder_booking_sent_24h_at:
        return {"status": "already_sent", "sent_at": iso_or_none(lead.reminder_booking_sent_24h_at)}
    if reminder_type == "72h" and lead.reminder_booking_sent_72h_at:
        return {"status": "already_sent", "sent_at": iso_or_none(lead.reminder_booking_sent_72h_at)}

    # Check if enough time has passed since booking link was sent
    if not lead.booking_link_sent_at:
        return {"status": "skipped", "reason": "No booking link sent timestamp"}

    now = datetime.now(UTC)
    booking_link_sent = dt_replace_utc(lead.booking_link_sent_at)
    if booking_link_sent is None:
        return {"status": "skipped", "reason": "No booking link sent timestamp"}
    hours_passed = (now - booking_link_sent).total_seconds() / 3600

    if hours_passed < hours_since_booking_link:
        return {"status": "not_due", "hours_passed": hours_passed}

    # Check idempotency
    event_id = f"reminder_booking_{lead.id}_{reminder_type}"
    is_duplicate, processed = check_and_record_processed_event(
        db=db,
        event_id=event_id,
        event_type=reminder_booking_event_type(reminder_type),
        lead_id=lead.id,
        provider=PROVIDER_REMINDER,
    )

    if is_duplicate:
        logger.info(f"Reminder already sent for lead {lead.id} (event {event_id})")
        return {"status": "duplicate", "event_id": event_id}

    # Send reminder
    booking_url = lead.booking_link or "your booking link"
    reminder_message = (
        f"📅 *Booking Reminder*\n\n"
        f"Hi! Just a friendly reminder to book your appointment.\n\n"
        f"Please use this link to schedule: {booking_url}\n\n"
        f"If you have any questions, just let me know!"
    )

    import asyncio

    try:
        result = asyncio.run(
            send_with_window_check(
                db=db,
                lead=lead,
                message=reminder_message,
                template_name="reminder_booking",  # Template name if window closed
                template_params={"booking_url": booking_url} if booking_url else None,
                dry_run=dry_run,
            )
        )
    except RuntimeError:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run,
                send_with_window_check(
                    db=db,
                    lead=lead,
                    message=reminder_message,
                    template_name="reminder_booking",
                    template_params={"booking_url": booking_url} if booking_url else None,
                    dry_run=dry_run,
                ),
            )
            result = future.result()

    # Update lead timestamp
    if reminder_type == "24h":
        lead.reminder_booking_sent_24h_at = func.now()
    elif reminder_type == "72h":
        lead.reminder_booking_sent_72h_at = func.now()

    commit_and_refresh(db, lead)

    return {
        "status": "sent",
        "event_id": event_id,
        "result": result,
        "sent_at": iso_or_none(
            lead.reminder_booking_sent_24h_at
            if reminder_type == "24h"
            else lead.reminder_booking_sent_72h_at
        ),
    }


def check_and_mark_deposit_expired(
    db: Session,
    lead: Lead,
    hours_threshold: int = 24,
) -> dict:
    """
    Check if deposit link has expired (24h since deposit_sent_at) and mark as DEPOSIT_EXPIRED.

    Args:
        db: Database session
        lead: Lead object
        hours_threshold: Hours before marking expired (default 24)

    Returns:
        dict with status
    """
    if lead.status != STATUS_AWAITING_DEPOSIT:
        return {"status": "skipped", "reason": f"Lead not in {STATUS_AWAITING_DEPOSIT} status"}

    if lead.deposit_paid_at:
        # Already paid, don't mark as expired
        return {"status": "skipped", "reason": "Deposit already paid"}

    if not lead.deposit_sent_at:
        return {"status": "skipped", "reason": "No deposit_sent_at timestamp"}

    now = datetime.now(UTC)
    deposit_sent = dt_replace_utc(lead.deposit_sent_at)
    if deposit_sent is None:
        return {"status": "skipped", "reason": "No deposit_sent_at timestamp"}
    hours_passed = (now - deposit_sent).total_seconds() / 3600

    if hours_passed < hours_threshold:
        return {"status": "not_due", "hours_passed": hours_passed}

    # Mark as expired
    lead.status = STATUS_DEPOSIT_EXPIRED
    db.commit()

    logger.info(f"Marked lead {lead.id} as DEPOSIT_EXPIRED (sent {hours_passed:.1f}h ago)")

    return {
        "status": "expired",
        "hours_passed": hours_passed,
    }


def check_and_mark_booking_pending_stale(
    db: Session,
    lead: Lead,
    hours_threshold: int = 72,
    dry_run: bool = True,
) -> dict:
    """
    Phase 1: Check if BOOKING_PENDING lead has been pending too long (72h) and set NEEDS_FOLLOW_UP.
    This pings the artist (not the client) because artist owns booking.

    Args:
        db: Database session
        lead: Lead object
        hours_threshold: Hours to wait before marking as needs follow-up (default 72h)
        dry_run: Whether to actually send notifications

    Returns:
        dict with status
    """
    if lead.status != STATUS_BOOKING_PENDING:
        return {"status": "skipped", "reason": f"Lead not in {STATUS_BOOKING_PENDING} status"}

    if lead.status == STATUS_NEEDS_FOLLOW_UP:
        return {"status": "already_needs_follow_up"}

    if not lead.booking_pending_at:
        return {"status": "skipped", "reason": "No booking_pending_at timestamp"}

    now = datetime.now(UTC)
    pending_since = dt_replace_utc(lead.booking_pending_at)
    if pending_since is None:
        return {"status": "skipped", "reason": "No booking_pending_at timestamp"}
    hours_passed = (now - pending_since).total_seconds() / 3600

    if hours_passed < hours_threshold:
        return {"status": "not_due", "hours_passed": hours_passed}

    # Set NEEDS_FOLLOW_UP and notify artist
    lead.status = STATUS_NEEDS_FOLLOW_UP
    lead.needs_follow_up_at = func.now()
    db.commit()

    # Notify artist (idempotent - only notifies on transition)
    import asyncio

    from app.services.integrations.artist_notifications import notify_artist_needs_follow_up

    try:
        asyncio.run(
            notify_artist_needs_follow_up(
                db=db,
                lead=lead,
                reason=f"Booking pending {int(hours_passed)}h (artist owns booking)",
                dry_run=dry_run,
            )
        )
    except RuntimeError:
        # Event loop already running, use different approach
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run,
                notify_artist_needs_follow_up(
                    db=db,
                    lead=lead,
                    reason=f"Booking pending {int(hours_passed)}h (artist owns booking)",
                    dry_run=dry_run,
                ),
            )
            future.result()

    return {
        "status": "needs_follow_up",
        "needs_follow_up_at": iso_or_none(lead.needs_follow_up_at),
    }
