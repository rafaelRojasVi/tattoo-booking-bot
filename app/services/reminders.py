"""
Reminder service with idempotency tracking.

Handles reminders for:
- Abandoned leads (client stopped replying during consultation)
- Stale leads (pending approval too long)
- Deposit paid but no booking (follow-up reminders)
"""
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.db.models import Lead
from app.services.safety import check_and_record_processed_event
from app.services.whatsapp_window import send_with_window_check
from app.services.conversation import (
    STATUS_QUALIFYING,
    STATUS_DEPOSIT_PAID,
    STATUS_BOOKING_LINK_SENT,
    STATUS_OPTOUT,
)

logger = logging.getLogger(__name__)


def check_and_send_qualifying_reminder(
    db: Session,
    lead: Lead,
    hours_since_last_message: int = 24,
    dry_run: bool = True,
) -> dict:
    """
    Check if lead needs a qualifying reminder and send it (idempotent).
    
    Args:
        db: Database session
        lead: Lead object
        hours_since_last_message: Hours to wait before sending reminder
        dry_run: Whether to actually send
        
    Returns:
        dict with status and reminder info
    """
    # Don't send reminders to opted-out leads
    if lead.status == STATUS_OPTOUT:
        return {"status": "skipped", "reason": "Lead has opted out"}
    
    if lead.status != STATUS_QUALIFYING:
        return {"status": "skipped", "reason": f"Lead not in {STATUS_QUALIFYING} status"}
    
    if lead.reminder_qualifying_sent_at:
        return {"status": "already_sent", "sent_at": lead.reminder_qualifying_sent_at.isoformat()}
    
    # Check if enough time has passed
    if not lead.last_client_message_at:
        return {"status": "skipped", "reason": "No last client message timestamp"}
    
    now = datetime.now(timezone.utc)
    last_message = lead.last_client_message_at
    if last_message.tzinfo is None:
        last_message = last_message.replace(tzinfo=timezone.utc)
    
    hours_passed = (now - last_message).total_seconds() / 3600
    
    if hours_passed < hours_since_last_message:
        return {"status": "not_due", "hours_passed": hours_passed}
    
    # Check idempotency - use event ID based on lead and reminder type
    event_id = f"reminder_qualifying_{lead.id}_{hours_since_last_message}h"
    is_duplicate, processed = check_and_record_processed_event(
        db=db,
        event_id=event_id,
        event_type="reminder.qualifying.24h",
        lead_id=lead.id,
    )
    
    if is_duplicate:
        logger.info(f"Reminder already sent for lead {lead.id} (event {event_id})")
        return {"status": "duplicate", "event_id": event_id}
    
    # Send reminder
    reminder_message = (
        "👋 Hi! Just checking in - are you still interested in booking a tattoo?\n\n"
        "If so, please reply and we can continue with your consultation. "
        "If not, no worries - just let me know!"
    )
    
    import asyncio
    try:
        result = asyncio.run(send_with_window_check(
            db=db,
            lead=lead,
            message=reminder_message,
            template_name="reminder_qualifying",  # Template name if window closed
            dry_run=dry_run,
        ))
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, send_with_window_check(
                db=db,
                lead=lead,
                message=reminder_message,
                template_name="reminder_qualifying",
                dry_run=dry_run,
            ))
            result = future.result()
    
    # Update lead timestamp
    lead.reminder_qualifying_sent_at = func.now()
    db.commit()
    db.refresh(lead)
    
    return {
        "status": "sent",
        "event_id": event_id,
        "result": result,
        "sent_at": lead.reminder_qualifying_sent_at.isoformat() if lead.reminder_qualifying_sent_at else None,
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
        return {"status": "already_sent", "sent_at": lead.reminder_booking_sent_24h_at.isoformat()}
    if reminder_type == "72h" and lead.reminder_booking_sent_72h_at:
        return {"status": "already_sent", "sent_at": lead.reminder_booking_sent_72h_at.isoformat()}
    
    # Check if enough time has passed since booking link was sent
    if not lead.booking_link_sent_at:
        return {"status": "skipped", "reason": "No booking link sent timestamp"}
    
    now = datetime.now(timezone.utc)
    booking_link_sent = lead.booking_link_sent_at
    if booking_link_sent.tzinfo is None:
        booking_link_sent = booking_link_sent.replace(tzinfo=timezone.utc)
    
    hours_passed = (now - booking_link_sent).total_seconds() / 3600
    
    if hours_passed < hours_since_booking_link:
        return {"status": "not_due", "hours_passed": hours_passed}
    
    # Check idempotency
    event_id = f"reminder_booking_{lead.id}_{reminder_type}"
    is_duplicate, processed = check_and_record_processed_event(
        db=db,
        event_id=event_id,
        event_type=f"reminder.booking.{reminder_type}",
        lead_id=lead.id,
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
        result = asyncio.run(send_with_window_check(
            db=db,
            lead=lead,
            message=reminder_message,
            template_name="reminder_booking",  # Template name if window closed
            template_params={"booking_url": booking_url} if booking_url else None,
            dry_run=dry_run,
        ))
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, send_with_window_check(
                db=db,
                lead=lead,
                message=reminder_message,
                template_name="reminder_booking",
                template_params={"booking_url": booking_url} if booking_url else None,
                dry_run=dry_run,
            ))
            result = future.result()
    
    # Update lead timestamp
    if reminder_type == "24h":
        lead.reminder_booking_sent_24h_at = func.now()
    elif reminder_type == "72h":
        lead.reminder_booking_sent_72h_at = func.now()
    
    db.commit()
    db.refresh(lead)
    
    return {
        "status": "sent",
        "event_id": event_id,
        "result": result,
        "sent_at": (lead.reminder_booking_sent_24h_at if reminder_type == "24h" 
                   else lead.reminder_booking_sent_72h_at).isoformat() if (
            lead.reminder_booking_sent_24h_at if reminder_type == "24h" 
            else lead.reminder_booking_sent_72h_at
        ) else None,
    }
