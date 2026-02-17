"""
Calendar service - Phase 1 calendar slot suggestions and optional detection for bookings.
"""

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.constants.event_types import EVENT_CALENDAR_NO_SLOTS_FALLBACK
from app.core.config import settings
from app.db.models import Lead

logger = logging.getLogger(__name__)


def find_event_by_lead_tag(
    lead_id: int,
    time_min: datetime | None = None,
    time_max: datetime | None = None,
) -> dict | None:
    """
    Search Google Calendar for events with [LEAD-<lead_id>] tag.

    Args:
        lead_id: Lead ID to search for
        time_min: Start of search window (default: today)
        time_max: End of search window (default: today + 90 days)

    Returns:
        Event dict with id, start, end if found, None otherwise
    """
    # Phase 1: This is a stub that would integrate with Google Calendar API
    # For now, return None (actual implementation requires Google Calendar API setup)

    if not settings.google_sheets_enabled:
        logger.debug("Google Calendar integration not enabled")
        return None

    # TODO: Implement Google Calendar API integration
    # 1. Authenticate with service account
    # 2. Search events in time range
    # 3. Look for [LEAD-<lead_id>] in title or description
    # 4. Return first match

    logger.info(f"Calendar search for LEAD-{lead_id} not yet implemented")
    return None


def poll_pending_bookings(db: Session, dry_run: bool = True) -> list[dict]:
    """
    Poll calendar for pending bookings and auto-mark as booked.

    Args:
        db: Database session
        dry_run: Whether to actually update leads

    Returns:
        List of dicts with lead_id and result
    """
    from sqlalchemy import select

    from app.services.conversation import STATUS_BOOKING_PENDING

    # Find all leads in BOOKING_PENDING with deposit_paid_at set
    stmt = select(Lead).where(
        Lead.status == STATUS_BOOKING_PENDING,
        Lead.deposit_paid_at.isnot(None),
    )
    pending_leads = db.execute(stmt).scalars().all()

    results = []
    time_min = datetime.now(UTC)
    time_max = time_min + timedelta(days=90)

    for lead in pending_leads:
        event = find_event_by_lead_tag(lead.id, time_min, time_max)

        if event:
            if not dry_run:
                # Update lead
                lead.status = "BOOKED"
                lead.calendar_event_id = event.get("id")
                lead.calendar_start_at = event.get("start")
                lead.calendar_end_at = event.get("end")
                lead.booked_at = datetime.now(UTC)
                db.commit()

                # Send WhatsApp confirmation (optional)
                # from app.services.messaging import send_whatsapp_message
                # await send_whatsapp_message(...)

            results.append(
                {
                    "lead_id": lead.id,
                    "status": "booked",
                    "event_id": event.get("id"),
                }
            )
        else:
            results.append(
                {
                    "lead_id": lead.id,
                    "status": "not_found",
                }
            )

    return results


def extract_lead_id_from_event(event_title: str, event_description: str = "") -> int | None:
    """
    Extract lead ID from calendar event title or description.

    Looks for pattern: [LEAD-<id>]

    Args:
        event_title: Event title
        event_description: Event description

    Returns:
        Lead ID if found, None otherwise
    """
    text = f"{event_title} {event_description}"
    pattern = r"\[LEAD-(\d+)\]"
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None

    return None


def get_available_slots(
    time_min: datetime | None = None,
    time_max: datetime | None = None,
    duration_minutes: int | None = None,
    max_results: int | None = None,
    category: str | None = None,
) -> list[dict[str, datetime]]:
    """
    Get available time slots from Google Calendar.

    Phase 1: Reads calendar free/busy and finds available slots.
    Applies calendar rules (working hours, buffers, lookahead).

    Args:
        time_min: Start of search window (default: now + minimum_advance_hours)
        time_max: End of search window (default: now + lookahead_days)
        duration_minutes: Duration of each slot (default: from rules based on category)
        max_results: Maximum number of slots to return (default: from config)
        category: Estimated category (SMALL, MEDIUM, LARGE, XL) for duration

    Returns:
        List of dicts with 'start' and 'end' datetime objects
        Example: [{'start': datetime(...), 'end': datetime(...)}, ...]
    """
    from app.services.calendar_rules import (
        get_lookahead_days,
        get_minimum_advance_hours,
        get_session_duration,
        get_timezone,
        is_within_working_hours,
    )

    # Load rules
    tz = get_timezone()
    lookahead_days = get_lookahead_days()
    min_advance_hours = get_minimum_advance_hours()

    # Set defaults based on rules
    now = datetime.now(tz)
    if time_min is None:
        time_min = now + timedelta(hours=min_advance_hours)
    if time_max is None:
        time_max = now + timedelta(days=lookahead_days)
    if duration_minutes is None:
        duration_minutes = get_session_duration(category)

    # Ensure timezone-aware
    if time_min.tzinfo is None:
        time_min = tz.localize(time_min)
    if time_max.tzinfo is None:
        time_max = tz.localize(time_max)

    if not settings.google_calendar_enabled or not settings.google_calendar_id:
        logger.debug("Google Calendar integration not enabled - returning mock slots")
        # Return mock slots for testing/development (with rules applied)
        return _get_mock_available_slots(
            time_min=time_min,
            time_max=time_max,
            duration_minutes=duration_minutes,
            max_results=max_results or settings.slot_suggestions_count,
            tz=tz,
            is_within_working_hours=is_within_working_hours,
        )

    # TODO: Implement real Google Calendar API integration
    # 1. Authenticate with service account using google_calendar_credentials_json
    # 2. Call Calendar API freebusy.query to get busy times
    # 3. Find gaps in schedule that fit duration_minutes
    # 4. Filter to business hours using is_within_working_hours
    # 5. Apply buffers
    # 6. Return up to max_results slots

    logger.info("Google Calendar API integration not yet implemented - using mock slots")
    return _get_mock_available_slots(
        time_min=time_min,
        time_max=time_max,
        duration_minutes=duration_minutes,
        max_results=max_results or settings.slot_suggestions_count,
        tz=tz,
        is_within_working_hours=is_within_working_hours,
    )


def _get_mock_available_slots(
    time_min: datetime,
    time_max: datetime,
    duration_minutes: int,
    max_results: int,
    tz: Any | None = None,
    is_within_working_hours: Callable | None = None,
) -> list[dict[str, datetime]]:
    """
    Generate mock available slots for testing/development.

    Creates slots starting from time_min, respecting working hours if rules are provided.
    """
    from app.services.calendar_rules import (
        get_timezone,
    )
    from app.services.calendar_rules import (
        is_within_working_hours as default_is_within,
    )

    if tz is None:
        tz = get_timezone()
    if is_within_working_hours is None:
        is_within_working_hours = default_is_within

    slots = []
    current_date = time_min.replace(hour=0, minute=0, second=0, microsecond=0)
    if current_date <= time_min:
        current_date += timedelta(days=1)  # Start from tomorrow

    # Default time slots (will be filtered by working hours if rules exist)
    time_slots = [10, 14, 16]  # 10am, 2pm, 4pm

    while len(slots) < max_results and current_date < time_max:
        for hour in time_slots:
            slot_start = current_date.replace(hour=hour, minute=0)
            if slot_start.tzinfo is None:
                slot_start = tz.localize(slot_start)
            slot_end = slot_start + timedelta(minutes=duration_minutes)

            # Check if within working hours
            if not is_within_working_hours(slot_start, tz):
                continue

            if slot_start >= time_min and slot_end <= time_max:
                slots.append(
                    {
                        "start": slot_start,
                        "end": slot_end,
                    }
                )

                if len(slots) >= max_results:
                    break

        current_date += timedelta(days=2)  # Every 2 days

    return slots


def format_slot_suggestions(
    slots: list[dict[str, datetime]],
    lead_id: int | None = None,
) -> str:
    """
    Format available slots as numbered options (1-8) with local timezone label.

    Args:
        slots: List of slot dicts with 'start' and 'end' datetime objects

    Returns:
        Formatted message string with numbered options
    """
    from app.services.message_composer import render_message

    if not slots:
        return render_message("slot_suggestions_empty", lead_id=lead_id)

    from app.services.calendar_rules import get_timezone

    tz = get_timezone()
    tz_name = start.tzname() if (start := slots[0]["start"]).tzinfo else tz.zone

    header = render_message(
        "slot_suggestions_header",
        lead_id=lead_id,
        tz_name=tz_name,
    )
    footer = render_message("slot_suggestions_footer", lead_id=lead_id)

    message_lines = [header]

    # Format up to 8 slots as numbered options
    for i, slot in enumerate(slots[:8], 1):
        start = slot["start"]
        end = slot["end"]

        # Format date and time
        date_str = start.strftime("%A, %B %d")
        time_str = start.strftime("%I:%M %p")
        end_time_str = end.strftime("%I:%M %p")

        message_lines.append(f"*{i}.* {date_str} - {time_str} to {end_time_str}")

    message_lines.append(footer)

    return "\n".join(message_lines)


async def send_slot_suggestions_to_client(
    db: Session,
    lead: Lead,
    dry_run: bool = True,
) -> bool:
    """
    Get available slots and send them to the client via WhatsApp.

    Called after deposit is paid (BOOKING_PENDING status).

    Args:
        db: Database session
        lead: Lead object
        dry_run: Whether to actually send WhatsApp messages

    Returns:
        True if successful, False otherwise
    """
    from app.core.config import settings

    # Feature flag check
    if not settings.feature_calendar_enabled:
        logger.debug(
            f"Calendar feature disabled (feature flag) - skipping slot suggestions for lead {lead.id}"
        )
        return False

    try:
        # Get available slots
        slots = get_available_slots(
            duration_minutes=settings.booking_duration_minutes,
            max_results=settings.slot_suggestions_count,
            category=lead.estimated_category,
        )

        # Handle empty slots - fallback: ask for preferred time windows
        if not slots:
            logger.info(
                f"No available slots found for lead {lead.id} - asking for preferred time windows"
            )
            # Log system event for calendar no-slots fallback
            from app.services.system_event_service import info

            info(
                db=db,
                event_type=EVENT_CALENDAR_NO_SLOTS_FALLBACK,
                lead_id=lead.id,
                payload={
                    "duration_minutes": settings.booking_duration_minutes,
                    "category": lead.estimated_category,
                },
            )
            from sqlalchemy import func

            from app.services.conversation import STATUS_COLLECTING_TIME_WINDOWS
            from app.services.state_machine import transition
            from app.services.time_window_collection import format_time_windows_request
            from app.services.whatsapp_templates import (
                get_template_for_next_steps,
                get_template_params_next_steps_reply_to_continue,
            )
            from app.services.whatsapp_window import send_with_window_check

            # Set status to collecting time windows (enforced via state machine)
            transition(db, lead, STATUS_COLLECTING_TIME_WINDOWS)

            # Ask for preferred time windows
            request_message = format_time_windows_request(lead_id=lead.id)

            await send_with_window_check(
                db=db,
                lead=lead,
                message=request_message,
                template_name=get_template_for_next_steps(),
                template_params=get_template_params_next_steps_reply_to_continue(),
                dry_run=dry_run or settings.whatsapp_dry_run,
            )

            lead.last_bot_message_at = func.now()
            db.commit()
            from app.services.sheets import log_lead_to_sheets

            log_lead_to_sheets(db, lead)

            return False  # Return False to indicate no slots sent

        # Store suggested slots as JSON (so we can match user's selection later)
        # Convert datetime objects to ISO strings for JSON serialization
        slots_json = []
        for slot in slots:
            slots_json.append(
                {
                    "start": slot["start"].isoformat(),
                    "end": slot["end"].isoformat(),
                }
            )
        lead.suggested_slots_json = slots_json
        db.commit()

        # Format message
        message = format_slot_suggestions(slots, lead_id=lead.id)

        # Send via WhatsApp (with 24h window check)
        from app.services.whatsapp_templates import (
            get_template_for_next_steps,
            get_template_params_next_steps_reply_to_continue,
        )
        from app.services.whatsapp_window import send_with_window_check

        await send_with_window_check(
            db=db,
            lead=lead,
            message=message,
            template_name=get_template_for_next_steps(),  # Re-open window template
            template_params=get_template_params_next_steps_reply_to_continue(),
            dry_run=dry_run or settings.whatsapp_dry_run,
        )

        # Update last bot message timestamp
        from sqlalchemy import func

        lead.last_bot_message_at = func.now()
        db.commit()

        logger.info(f"Sent {len(slots)} slot suggestions to lead {lead.id}")
        return True

    except Exception as e:
        logger.error(f"Failed to send slot suggestions to lead {lead.id}: {e}")
        return False
