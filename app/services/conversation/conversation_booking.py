"""
Booking flow handlers - slot selection, tour conversion offer, needs artist reply (CONTINUE/holding).
"""

from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.constants.event_types import EVENT_SLOT_UNAVAILABLE_AFTER_SELECTION
from app.constants.statuses import (
    STATUS_COLLECTING_TIME_WINDOWS,
    STATUS_PENDING_APPROVAL,
    STATUS_QUALIFYING,
    STATUS_WAITLISTED,
)
from app.db.models import Lead
from app.services.conversation_policy import (
    handover_hold_cooldown_elapsed,
    is_opt_out_message,
    normalize_message,
)
from app.services.questions import get_question_by_index
from app.services.sheets import log_lead_to_sheets
from app.services.state_machine import transition
from app.utils.datetime_utils import dt_replace_utc

# Rate-limit holding message during handover (avoid spamming client while artist replies)
HANDOVER_HOLD_REPLY_COOLDOWN_HOURS = 6


def _get_send_whatsapp():
    """Late-binding so tests patching conversation.send_whatsapp_message take effect."""
    from app.services.conversation import send_whatsapp_message

    return send_whatsapp_message


async def _handle_booking_pending(
    db: Session,
    lead: Lead,
    message_text: str,
    dry_run: bool,
) -> dict:
    """
    Handle lead in BOOKING_PENDING - slot selection logic.
    Deposit paid, waiting for slot selection.
    """
    # Check if client is selecting a slot
    if lead.suggested_slots_json:
        # Convert JSON slots back to datetime objects for parsing
        from app.services.slot_parsing import parse_slot_selection_logged

        slots = []
        for slot_json in lead.suggested_slots_json:
            slots.append(
                {
                    "start": datetime.fromisoformat(slot_json["start"]),
                    "end": datetime.fromisoformat(slot_json["end"]),
                }
            )

        # Try to parse slot selection (pass db/lead_id for observability)
        selected_index = parse_slot_selection_logged(
            message_text, slots, max_slots=8, db=db, lead_id=lead.id
        )

        if selected_index is not None:
            # Valid selection - use stored slots (don't fail as unavailable unless no stored slots)
            selected_slot = slots[selected_index - 1]  # Convert 1-based to 0-based

            # Only re-check availability if calendar is enabled AND we have stored slots
            # Otherwise, trust the stored slots
            slot_available = True  # Default: trust stored slots

            from app.core.config import settings
            from app.services.calendar_service import get_available_slots

            if settings.feature_calendar_enabled and slots:
                # Re-check availability for the selected time window
                try:
                    available_slots = get_available_slots(
                        time_min=selected_slot["start"],
                        time_max=selected_slot["end"],
                        duration_minutes=settings.booking_duration_minutes,
                    )

                    # Check if selected slot is still in available slots
                    slot_available = False
                    for avail_slot in available_slots:
                        if (
                            avail_slot["start"] == selected_slot["start"]
                            and avail_slot["end"] == selected_slot["end"]
                        ):
                            slot_available = True
                            break
                except Exception as e:
                    # If calendar check fails, fall back to trusting stored slots
                    import logging

                    logger = logging.getLogger(__name__)
                    logger.warning(f"Calendar availability check failed, using stored slot: {e}")
                    slot_available = True

                if not slot_available:
                    # Slot no longer available - trigger fallback
                    from app.services.system_event_service import warn

                    warn(
                        db=db,
                        event_type=EVENT_SLOT_UNAVAILABLE_AFTER_SELECTION,
                        lead_id=lead.id,
                        payload={
                            "selected_slot_index": selected_index,
                            "selected_slot_start": selected_slot["start"].isoformat(),
                            "selected_slot_end": selected_slot["end"].isoformat(),
                        },
                    )

                    # Trigger fallback: collect time windows or ask for another option
                    from app.services.message_composer import render_message

                    fallback_msg = render_message(
                        "slot_unavailable_fallback",
                        lead_id=lead.id,
                    )
                    await _get_send_whatsapp()(
                        to=lead.wa_from,
                        message=fallback_msg,
                        dry_run=dry_run,
                    )
                    lead.last_bot_message_at = func.now()

                    # Transition to collecting time windows (enforced via state machine)
                    transition(db, lead, STATUS_COLLECTING_TIME_WINDOWS)

                    return {
                        "status": "slot_unavailable",
                        "message": fallback_msg,
                        "lead_status": lead.status,
                    }

            # Slot is available - proceed with confirmation
            lead.selected_slot_start_at = selected_slot["start"]
            lead.selected_slot_end_at = selected_slot["end"]
            lead.last_client_message_at = func.now()
            db.commit()

            # Send confirmation to client
            from app.services.message_composer import render_message

            confirmation_msg = render_message(
                "confirmation_slot",
                lead_id=lead.id,
                slot_number=selected_index,
            )
            await _get_send_whatsapp()(
                to=lead.wa_from,
                message=confirmation_msg,
                dry_run=dry_run,
            )
            lead.last_bot_message_at = func.now()
            db.commit()

            # Notify artist that slot was selected
            from app.services.artist_notifications import notify_artist_slot_selected

            await notify_artist_slot_selected(
                db=db,
                lead=lead,
                selected_slot=selected_slot,
                slot_number=selected_index,
                dry_run=dry_run,
            )

            return {
                "status": "slot_selected",
                "message": confirmation_msg,
                "lead_status": lead.status,
                "slot_number": selected_index,
            }
        else:
            # Couldn't parse - send repair message
            from app.services.parse_repair import (
                increment_parse_failure,
                should_handover_after_failure,
                trigger_handover_after_parse_failure,
            )

            increment_parse_failure(db, lead, "slot")
            db.refresh(lead)  # Refresh to get updated parse_failure_counts
            if should_handover_after_failure(lead, "slot"):
                return await trigger_handover_after_parse_failure(db, lead, "slot", dry_run)

            # Send soft repair message (retry_count for short+boundary variant on retry 2)
            from app.services.message_composer import compose_message, render_message
            from app.services.parse_repair import get_failure_count

            repair_msg = compose_message(
                "REPAIR_SLOT",
                {"lead_id": lead.id, "retry_count": get_failure_count(lead, "slot")},
            )
            await _get_send_whatsapp()(
                to=lead.wa_from,
                message=repair_msg,
                dry_run=dry_run,
            )
            lead.last_bot_message_at = func.now()
            db.commit()

            return {
                "status": "repair_needed",
                "message": repair_msg,
                "lead_status": lead.status,
                "question_key": "slot",
            }

    # No slots suggested yet, or just acknowledge
    from app.services.message_composer import render_message

    return {
        "status": "booking_pending",
        "message": render_message("booking_pending", lead_id=lead.id),
        "lead_status": lead.status,
    }


async def _handle_tour_conversion_offered(
    db: Session,
    lead: Lead,
    message_text: str,
    dry_run: bool,
) -> dict:
    """
    Handle lead in TOUR_CONVERSION_OFFERED - client accepts or declines tour offer.
    """
    message_upper = message_text.strip().upper()
    if message_upper in ["YES", "Y", "ACCEPT", "OK", "SURE"]:
        # Accept tour offer - continue with offered city
        lead.location_city = lead.offered_tour_city
        lead.tour_offer_accepted = True
        db.commit()
        db.refresh(lead)
        transition(db, lead, STATUS_PENDING_APPROVAL)

        from app.services.message_composer import render_message

        accept_msg = render_message(
            "tour_accept",
            lead_id=lead.id,
            city=lead.offered_tour_city,
        )
        await _get_send_whatsapp()(
            to=lead.wa_from,
            message=accept_msg,
            dry_run=dry_run,
        )
        lead.last_bot_message_at = func.now()
        db.commit()
        log_lead_to_sheets(db, lead)
        return {
            "status": "tour_accepted",
            "message": accept_msg,
            "lead_status": lead.status,
        }
    elif message_upper in ["NO", "N", "DECLINE"]:
        # Decline - waitlist for requested city
        lead.tour_offer_accepted = False
        lead.waitlisted = True
        db.commit()
        db.refresh(lead)
        transition(db, lead, STATUS_WAITLISTED)

        from app.services.message_composer import render_message

        decline_msg = render_message(
            "tour_decline",
            lead_id=lead.id,
            city=lead.requested_city,
        )
        await _get_send_whatsapp()(
            to=lead.wa_from,
            message=decline_msg,
            dry_run=dry_run,
        )
        lead.last_bot_message_at = func.now()
        db.commit()
        log_lead_to_sheets(db, lead)
        return {
            "status": "waitlisted",
            "message": decline_msg,
            "lead_status": lead.status,
        }
    else:
        # Unclear response - ask for clarification
        from app.services.message_composer import render_message

        return {
            "status": "tour_offer_pending",
            "message": render_message("tour_prompt", lead_id=lead.id),
            "lead_status": lead.status,
        }


async def _handle_needs_artist_reply(
    db: Session,
    lead: Lead,
    message_text: str,
    dry_run: bool,
) -> dict:
    """
    Handle lead in NEEDS_ARTIST_REPLY - opt-out wins, CONTINUE resumes, else holding message.
    """
    from app.services.conversation_qualifying import _handle_new_lead, _handle_opt_out

    # Opt-out wins even during handover (STOP/UNSUBSCRIBE must be honored)
    if is_opt_out_message(message_text):
        return await _handle_opt_out(db, lead, dry_run)

    # Check for CONTINUE to resume flow
    if normalize_message(message_text) == "CONTINUE":
        # Resume qualification flow (enforced via state machine)
        transition(db, lead, STATUS_QUALIFYING)
        # Continue with current question
        next_question = get_question_by_index(lead.current_step)
        if next_question:
            from app.services.message_composer import compose_message

            continue_msg = compose_message(
                "ASK_QUESTION",
                {"lead_id": lead.id, "question_text": next_question.text},
            )
            await _get_send_whatsapp()(
                to=lead.wa_from,
                message=continue_msg,
                dry_run=dry_run,
            )
            lead.last_bot_message_at = func.now()
            db.commit()
            return {
                "status": "resumed",
                "message": continue_msg,
                "lead_status": lead.status,
                "current_step": lead.current_step,
            }
        else:
            # No question found - reset to start
            transition(db, lead, STATUS_QUALIFYING)
            lead.current_step = 0
            db.commit()
            db.refresh(lead)
            return await _handle_new_lead(db, lead, dry_run)

    # Handover to artist - bot paused (for any other message)
    # Rate-limit holding reply: send at most once per cooldown window
    holding_msg = "I've paused the automated flow. The artist will reply to you directly."
    last_hold_at = dt_replace_utc(lead.handover_last_hold_reply_at)
    now_utc = datetime.now(UTC)
    send_hold = handover_hold_cooldown_elapsed(
        last_hold_at, now_utc, HANDOVER_HOLD_REPLY_COOLDOWN_HOURS
    )
    if send_hold:
        await _get_send_whatsapp()(
            to=lead.wa_from,
            message=holding_msg,
            dry_run=dry_run,
        )
        # App-time UTC so comparison (now_utc - last_hold_at) is independent of DB timezone. Strict: update only on send; anti-spam alternative: update even on failure.
        lead.handover_last_hold_reply_at = now_utc
        lead.last_bot_message_at = func.now()
        db.commit()

    return {
        "status": "artist_reply",
        "message": holding_msg,
        "lead_status": lead.status,
    }
