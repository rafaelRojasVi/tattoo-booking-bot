"""
Conversation flow service - handles state machine and question flow.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Lead, LeadAnswer
from app.services.action_tokens import generate_action_tokens_for_lead
from app.services.messaging import format_summary_message, send_whatsapp_message
from app.services.questions import (
    get_question_by_index,
    is_last_question,
)
from app.services.sheets import log_lead_to_sheets

logger = logging.getLogger(__name__)


# Core statuses (Phase 1 proposal lifecycle)
STATUS_NEW = "NEW"
STATUS_QUALIFYING = "QUALIFYING"
STATUS_PENDING_APPROVAL = "PENDING_APPROVAL"
STATUS_AWAITING_DEPOSIT = "AWAITING_DEPOSIT"
STATUS_DEPOSIT_PAID = "DEPOSIT_PAID"
STATUS_BOOKING_PENDING = "BOOKING_PENDING"  # Phase 1: replaces BOOKING_LINK_SENT
STATUS_BOOKED = "BOOKED"

# Operational statuses
STATUS_NEEDS_ARTIST_REPLY = "NEEDS_ARTIST_REPLY"
STATUS_NEEDS_FOLLOW_UP = "NEEDS_FOLLOW_UP"
STATUS_REJECTED = "REJECTED"

# Housekeeping statuses
STATUS_ABANDONED = "ABANDONED"
STATUS_STALE = "STALE"
STATUS_OPTOUT = "OPTOUT"  # Client opted out (STOP/UNSUBSCRIBE)

# Travel/tour statuses (Phase 1)
STATUS_TOUR_CONVERSION_OFFERED = "TOUR_CONVERSION_OFFERED"
STATUS_WAITLISTED = "WAITLISTED"

# Payment-related statuses (future features)
STATUS_DEPOSIT_EXPIRED = "DEPOSIT_EXPIRED"  # Deposit link sent but not paid after X days
STATUS_REFUNDED = "REFUNDED"  # Stripe refund event or manual refund
STATUS_CANCELLED = "CANCELLED"  # Client cancels after paying / before booking

# Legacy (kept for backward compatibility)
STATUS_NEEDS_MANUAL_FOLLOW_UP = "NEEDS_MANUAL_FOLLOW_UP"  # Maps to NEEDS_FOLLOW_UP
STATUS_BOOKING_LINK_SENT = "BOOKING_LINK_SENT"  # Legacy - maps to BOOKING_PENDING


async def handle_inbound_message(
    db: Session,
    lead: Lead,
    message_text: str,
    dry_run: bool = True,
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
                event_type="needs_artist_reply",
                dry_run=dry_run,
            )

        # Send safe response (only if within 24h window)
        if is_within:
            safe_message = "Thanks — Jonah will reply shortly."
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
        return await _handle_qualifying_lead(db, lead, message_text, dry_run)

    elif lead.status == STATUS_PENDING_APPROVAL:
        # Waiting for artist approval - acknowledge
        return {
            "status": "pending_approval",
            "message": "Thanks! I'm reviewing your request and will get back to you soon.",
            "lead_status": lead.status,
        }

    elif lead.status == STATUS_AWAITING_DEPOSIT:
        # Approved, waiting for deposit payment
        # Client may be responding to slot suggestions or asking about deposit
        message_upper = message_text.strip().upper()

        # Check if client is selecting a slot (simple pattern matching)
        # In Phase 1, we'll handle basic slot selection responses
        # For now, acknowledge and remind about deposit
        return {
            "status": "awaiting_deposit",
            "message": "Thanks! Please check your messages for the deposit link to secure your booking. If you need it resent, let me know!",
            "lead_status": lead.status,
        }

    elif lead.status == STATUS_DEPOSIT_PAID:
        # Deposit paid, waiting for booking
        return {
            "status": "deposit_paid",
            "message": "Thanks for your deposit! I'll send you a booking link shortly.",
            "lead_status": lead.status,
        }

    elif lead.status == STATUS_BOOKING_PENDING:
        # Deposit paid, waiting for manual booking
        return {
            "status": "booking_pending",
            "message": "Thanks for your deposit! Jonah will confirm your date in the calendar and message you.",
            "lead_status": lead.status,
        }

    elif lead.status == STATUS_BOOKING_LINK_SENT:
        # Legacy status - map to BOOKING_PENDING
        lead.status = STATUS_BOOKING_PENDING
        db.commit()
        return {
            "status": "booking_pending",
            "message": "Thanks for your deposit! Jonah will confirm your date in the calendar and message you.",
            "lead_status": lead.status,
        }

    elif lead.status == STATUS_TOUR_CONVERSION_OFFERED:
        # Client needs to accept/decline tour offer
        message_upper = message_text.strip().upper()
        if message_upper in ["YES", "Y", "ACCEPT", "OK", "SURE"]:
            # Accept tour offer - continue with offered city
            lead.location_city = lead.offered_tour_city
            lead.tour_offer_accepted = True
            lead.status = STATUS_PENDING_APPROVAL
            lead.pending_approval_at = func.now()
            db.commit()

            accept_msg = (
                f"Great! I'll proceed with your booking for {lead.offered_tour_city}. "
                f"Jonah will review and get back to you soon."
            )
            await send_whatsapp_message(
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
            lead.status = STATUS_WAITLISTED
            lead.waitlisted = True
            db.commit()

            decline_msg = (
                f"I'll add you to the waitlist for {lead.requested_city}. "
                f"I'll let you know when I'm planning to visit!"
            )
            await send_whatsapp_message(
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
            return {
                "status": "tour_offer_pending",
                "message": "Please reply 'yes' to book for the tour city, or 'no' to be waitlisted.",
                "lead_status": lead.status,
            }

    elif lead.status == STATUS_WAITLISTED:
        # Client is waitlisted
        return {
            "status": "waitlisted",
            "message": "You're on the waitlist. I'll contact you when I'm planning to visit your city!",
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
        # Check for CONTINUE to resume flow
        if message_text.strip().upper() == "CONTINUE":
            # Resume qualification flow
            lead.status = STATUS_QUALIFYING
            db.commit()
            db.refresh(lead)
            # Continue with current question
            next_question = get_question_by_index(lead.current_step)
            if next_question:
                await send_whatsapp_message(
                    to=lead.wa_from,
                    message=f"Great! Let's continue.\n\n{next_question.text}",
                    dry_run=dry_run,
                )
                lead.last_bot_message_at = func.now()
                db.commit()
                return {
                    "status": "resumed",
                    "message": next_question.text,
                    "lead_status": lead.status,
                    "current_step": lead.current_step,
                }
            else:
                # No question found - reset to start
                lead.status = STATUS_QUALIFYING
                lead.current_step = 0
                db.commit()
                return await _handle_new_lead(db, lead, dry_run)

        # Handover to artist - bot paused (for any other message)
        return {
            "status": "artist_reply",
            "message": "I've paused the automated flow. The artist will reply to you directly.",
            "lead_status": lead.status,
        }

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
        # Client opted out - allow them to opt back in by sending any message
        if message_text.strip().upper() in ["START", "RESUME", "CONTINUE", "YES"]:
            # Opt back in - reset to NEW to restart
            lead.status = STATUS_NEW
            lead.current_step = 0
            db.commit()
            return await _handle_new_lead(db, lead, dry_run)
        else:
            # Still opted out - acknowledge but don't send automated messages
            return {
                "status": "opted_out",
                "message": "You're currently unsubscribed. Send 'START' to resume.",
                "lead_status": lead.status,
            }

    elif lead.status in [STATUS_ABANDONED, STATUS_STALE]:
        # Inactive leads - allow restart
        lead.status = STATUS_NEW
        lead.current_step = 0
        db.commit()
        return await _handle_new_lead(db, lead, dry_run)

    else:
        # Unknown status - reset to NEW
        lead.status = STATUS_NEW
        lead.current_step = 0
        db.commit()
        return await _handle_new_lead(db, lead, dry_run)


async def _handle_new_lead(
    db: Session,
    lead: Lead,
    dry_run: bool,
) -> dict:
    """Handle a new lead - start the qualification flow (Phase 1)."""
    # Set status to QUALIFYING and track start time
    lead.status = STATUS_QUALIFYING
    lead.current_step = 0
    lead.qualifying_started_at = func.now()
    db.commit()
    db.refresh(lead)

    # Get first question
    question = get_question_by_index(0)
    if not question:
        return {
            "status": "error",
            "message": "No questions configured",
        }

    # Send welcome message + first question
    welcome_msg = f"👋 Hi! Thanks for reaching out. Let's get some details about your tattoo idea.\n\n{question.text}"

    await send_whatsapp_message(
        to=lead.wa_from,
        message=welcome_msg,
        dry_run=dry_run,
    )

    lead.last_bot_message_at = func.now()
    db.commit()

    return {
        "status": "question_sent",
        "message": welcome_msg,
        "lead_status": lead.status,
        "current_step": lead.current_step,
        "question_key": question.key,
    }


async def _handle_qualifying_lead(
    db: Session,
    lead: Lead,
    message_text: str,
    dry_run: bool,
) -> dict:
    """Handle a lead in QUALIFYING state - save answer and ask next question."""
    current_step = lead.current_step

    # Get the question we're currently on (the one they're answering)
    current_question = get_question_by_index(current_step)
    if not current_question:
        # Shouldn't happen, but handle gracefully
        lead.status = STATUS_NEEDS_MANUAL_FOLLOW_UP
        db.commit()
        return {
            "status": "error",
            "message": "Invalid question step",
        }

    # Check for STOP/UNSUBSCRIBE opt-out
    message_upper = message_text.strip().upper()
    if message_upper in ["STOP", "UNSUBSCRIBE", "OPT OUT", "OPTOUT"]:
        return await _handle_opt_out(db, lead, dry_run)

    # Phase 1: Dynamic handover check (replaces keyword trigger)
    from app.services.handover_service import get_handover_message, should_handover

    should_handover_flag, handover_reason = should_handover(message_text, lead)
    if should_handover_flag:
        lead.status = STATUS_NEEDS_ARTIST_REPLY
        lead.handover_reason = handover_reason
        lead.needs_artist_reply_at = func.now()
        db.commit()

        # Notify artist (idempotent - only notifies on transition)
        from app.services.artist_notifications import notify_artist_needs_reply

        await notify_artist_needs_reply(
            db=db,
            lead=lead,
            reason=handover_reason,
            dry_run=dry_run,
        )

        handover_msg = get_handover_message(handover_reason)
        await send_whatsapp_message(
            to=lead.wa_from,
            message=handover_msg,
            dry_run=dry_run,
        )
        lead.last_bot_message_at = func.now()
        db.commit()
        return {
            "status": "handover",
            "message": handover_msg,
            "lead_status": lead.status,
            "reason": handover_reason,
        }

    # Save the answer
    answer = LeadAnswer(
        lead_id=lead.id,
        question_key=current_question.key,
        answer_text=message_text,
    )
    db.add(answer)

    # Phase 1: Store specific answers in lead fields
    if current_question.key == "coverup":
        coverup_upper = message_text.strip().upper()
        if coverup_upper in ["YES", "Y", "TRUE", "1"]:
            # Coverup detected - will be handled in _complete_qualification
            pass

    # Update last client message timestamp
    lead.last_client_message_at = func.now()

    # Check if this was the last question
    if is_last_question(current_step):
        # All questions answered - generate summary and move to AWAITING_DEPOSIT
        return await _complete_qualification(db, lead, dry_run)

    # Move to next question
    lead.current_step = current_step + 1
    db.commit()
    db.refresh(lead)

    # Get next question
    next_question = get_question_by_index(lead.current_step)
    if not next_question:
        # Shouldn't happen
        lead.status = STATUS_NEEDS_MANUAL_FOLLOW_UP
        db.commit()
        return {
            "status": "error",
            "message": "No next question found",
        }

    # Send next question
    await send_whatsapp_message(
        to=lead.wa_from,
        message=next_question.text,
        dry_run=dry_run,
    )

    # Update last bot message timestamp
    lead.last_bot_message_at = func.now()
    db.commit()

    return {
        "status": "question_sent",
        "message": next_question.text,
        "lead_status": lead.status,
        "current_step": lead.current_step,
        "question_key": next_question.key,
        "saved_answer": {
            "question": current_question.key,
            "answer": message_text,
        },
    }


async def _handle_opt_out(
    db: Session,
    lead: Lead,
    dry_run: bool,
) -> dict:
    """Handle STOP/UNSUBSCRIBE opt-out request - stop all outbound messages."""
    # Set status to OPTOUT
    lead.status = STATUS_OPTOUT
    db.commit()
    db.refresh(lead)

    # Send confirmation message (one last message to confirm opt-out)
    optout_msg = (
        "You've been unsubscribed. You won't receive any more automated messages from us.\n\n"
        "If you change your mind, just send us a message and we can resume."
    )

    await send_whatsapp_message(
        to=lead.wa_from,
        message=optout_msg,
        dry_run=dry_run,
    )

    lead.last_bot_message_at = func.now()
    db.commit()

    # Log to Google Sheets
    log_lead_to_sheets(db, lead)

    return {
        "status": "opted_out",
        "message": optout_msg,
        "lead_status": lead.status,
    }


async def _handle_artist_handover(
    db: Session,
    lead: Lead,
    dry_run: bool,
) -> dict:
    """Handle ARTIST handover request - pause bot and notify artist."""
    # Set status to NEEDS_ARTIST_REPLY
    lead.status = STATUS_NEEDS_ARTIST_REPLY
    lead.handover_reason = "Client requested artist handover"
    lead.needs_artist_reply_at = func.now()
    db.commit()
    db.refresh(lead)

    # Notify artist (idempotent - only notifies on transition)
    from app.services.artist_notifications import notify_artist_needs_reply

    await notify_artist_needs_reply(
        db=db,
        lead=lead,
        reason="Client requested artist handover",
        dry_run=dry_run,
    )

    # Ask for handover preference
    handover_msg = (
        "I've paused the automated flow so the artist can reply directly.\n\n"
        "Do you prefer a quick chat or a call?\n"
        "And what's the main thing you'd like to clarify? (1 sentence)"
    )

    await send_whatsapp_message(
        to=lead.wa_from,
        message=handover_msg,
        dry_run=dry_run,
    )

    lead.last_bot_message_at = func.now()
    db.commit()

    return {
        "status": "artist_handover",
        "message": handover_msg,
        "lead_status": lead.status,
    }


async def _complete_qualification(
    db: Session,
    lead: Lead,
    dry_run: bool,
) -> dict:
    """Complete qualification - Phase 1: run estimation, region checks, tour logic, then move to PENDING_APPROVAL."""
    from app.services.estimation_service import estimate_project
    from app.services.region_service import country_to_region, region_min_budget
    from app.services.tour_service import closest_upcoming_city, format_tour_offer, is_city_on_tour

    # Get all answers
    stmt = select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)
    answers_list = db.execute(stmt).scalars().all()

    # Build answers dict
    answers_dict = {ans.question_key: ans.answer_text for ans in answers_list}

    # Extract key answers
    dimensions_text = answers_dict.get("dimensions", "")
    complexity_text = answers_dict.get("complexity", "")
    coverup_text = answers_dict.get("coverup", "").upper()
    placement = answers_dict.get("placement", "")
    location_city = answers_dict.get("location_city", "")
    location_country = answers_dict.get("location_country", "")
    travel_city = answers_dict.get("travel_city", "").strip()
    budget_text = answers_dict.get("budget", "")
    instagram_handle = answers_dict.get("instagram_handle", "").strip()

    # Parse complexity (1-3)
    complexity_level = None
    try:
        if complexity_text:
            complexity_level = int(complexity_text.strip()[0])  # Take first digit
            if complexity_level not in [1, 2, 3]:
                complexity_level = 2  # Default to medium
    except (ValueError, IndexError):
        complexity_level = 2

    # Check if coverup
    is_coverup = coverup_text in ["YES", "Y", "TRUE", "1"]

    # Handle coverup immediately - set NEEDS_ARTIST_REPLY
    if is_coverup:
        lead.status = STATUS_NEEDS_ARTIST_REPLY
        handover_reason = "Cover-up/rework requires creative assessment"
        lead.handover_reason = handover_reason
        lead.needs_artist_reply_at = func.now()
        lead.qualifying_completed_at = func.now()
        db.commit()

        # Notify artist (idempotent - only notifies on transition)
        from app.services.artist_notifications import notify_artist_needs_reply

        await notify_artist_needs_reply(
            db=db,
            lead=lead,
            reason=handover_reason,
            dry_run=dry_run,
        )

        handover_msg = (
            "I've paused the automated flow so Jonah can assess your cover-up request.\n\n"
            "Would you prefer a quick call or chat?\n\n"
            "Please share 2-3 time windows that work for you (and your timezone)."
        )

        await send_whatsapp_message(
            to=lead.wa_from,
            message=handover_msg,
            dry_run=dry_run,
        )
        lead.last_bot_message_at = func.now()
        db.commit()
        log_lead_to_sheets(db, lead)
        return {
            "status": "handover_coverup",
            "message": handover_msg,
            "lead_status": lead.status,
        }

    # Run estimation
    category, deposit_amount = estimate_project(
        dimensions_text=dimensions_text,
        complexity_level=complexity_level,
        is_coverup=is_coverup,
        placement=placement,
    )

    lead.estimated_category = category
    lead.estimated_deposit_amount = deposit_amount
    lead.complexity_level = complexity_level

    # Store location and derive region
    lead.location_city = location_city
    lead.location_country = location_country
    region = country_to_region(location_country)
    lead.region_bucket = region
    min_budget = region_min_budget(region)
    lead.min_budget_amount = min_budget

    # Store Instagram handle
    if instagram_handle:
        lead.instagram_handle = instagram_handle.replace("@", "").strip()

    # Parse budget
    budget_amount = None
    try:
        # Extract number from budget text
        import re

        numbers = re.findall(r"\d+", budget_text.replace(",", ""))
        if numbers:
            budget_amount = int(numbers[0]) * 100  # Convert to pence
    except (ValueError, IndexError):
        pass

    # Check budget vs minimum
    if budget_amount and budget_amount < min_budget:
        lead.below_min_budget = True
        # Set NEEDS_FOLLOW_UP (do NOT auto-decline)
        lead.status = STATUS_NEEDS_FOLLOW_UP
        lead.needs_follow_up_at = func.now()
        lead.qualifying_completed_at = func.now()
        db.commit()

        min_gbp = min_budget / 100
        budget_gbp = budget_amount / 100

        # Notify artist (idempotent - only notifies on transition)
        from app.services.artist_notifications import notify_artist_needs_follow_up

        reason = f"Budget below minimum (Min £{min_gbp:.0f}, Budget £{budget_gbp:.0f})"
        await notify_artist_needs_follow_up(
            db=db,
            lead=lead,
            reason=reason,
            dry_run=dry_run,
        )
        budget_msg = (
            f"Thanks! Based on your location, the minimum booking value is *£{min_gbp:.0f}*. "
            f"Your budget may need adjusting. Jonah can review options—do you want to continue?"
        )

        await send_whatsapp_message(
            to=lead.wa_from,
            message=budget_msg,
            dry_run=dry_run,
        )
        lead.last_bot_message_at = func.now()
        db.commit()
        log_lead_to_sheets(db, lead)
        return {
            "status": "needs_follow_up_budget",
            "message": budget_msg,
            "lead_status": lead.status,
        }

    # Check tour city logic
    requested_city = (
        travel_city
        if travel_city and travel_city.lower() not in ["same", "none", "n/a"]
        else location_city
    )
    lead.requested_city = requested_city

    if not is_city_on_tour(requested_city, location_country):
        # City not on tour - offer conversion
        tour_stop = closest_upcoming_city(requested_city, location_country)
        if tour_stop:
            lead.status = STATUS_TOUR_CONVERSION_OFFERED
            lead.offered_tour_city = tour_stop.city
            lead.offered_tour_dates_text = f"{tour_stop.start_date.strftime('%B %d')} - {tour_stop.end_date.strftime('%B %d, %Y')}"
            lead.qualifying_completed_at = func.now()
            db.commit()

            tour_msg = format_tour_offer(tour_stop)
            await send_whatsapp_message(
                to=lead.wa_from,
                message=tour_msg,
                dry_run=dry_run,
            )
            lead.last_bot_message_at = func.now()
            db.commit()
            log_lead_to_sheets(db, lead)
            return {
                "status": "tour_conversion_offered",
                "message": tour_msg,
                "lead_status": lead.status,
            }
        else:
            # No upcoming tour - waitlist
            lead.status = STATUS_WAITLISTED
            lead.waitlisted = True
            lead.qualifying_completed_at = func.now()
            db.commit()

            waitlist_msg = (
                f"I don't have {requested_city} scheduled yet. "
                f"I'll add you to the waitlist and let you know when I'm planning to visit!"
            )
            await send_whatsapp_message(
                to=lead.wa_from,
                message=waitlist_msg,
                dry_run=dry_run,
            )
            lead.last_bot_message_at = func.now()
            db.commit()
            log_lead_to_sheets(db, lead)
            return {
                "status": "waitlisted",
                "message": waitlist_msg,
                "lead_status": lead.status,
            }

    # All checks passed - complete qualification
    lead.qualifying_completed_at = func.now()
    lead.pending_approval_at = func.now()
    lead.status = STATUS_PENDING_APPROVAL

    # Generate summary (Phase 1 format)
    from app.services.summary import (
        extract_phase1_summary_context,
    )
    from app.services.summary import (
        format_summary_message as format_phase1_summary,
    )

    summary_ctx = extract_phase1_summary_context(lead)
    summary = format_phase1_summary(summary_ctx)
    lead.summary_text = summary

    # Send completion message with estimated category
    category_display = category.title()
    completion_msg = (
        f"✅ Perfect! I've received all your details.\n\n"
        f"Based on your answers, this looks like a *{category_display}* project. Jonah will confirm.\n\n"
        f"I'll review your request and get back to you soon. "
        f"If approved, I'll send you a deposit link to secure your booking.\n\n"
        f"Thanks for your patience! 🙏"
    )

    await send_whatsapp_message(
        to=lead.wa_from,
        message=completion_msg,
        dry_run=dry_run,
    )

    lead.last_bot_message_at = func.now()
    db.commit()
    db.refresh(lead)

    # Log to Sheets
    log_lead_to_sheets(db, lead)

    # Generate action tokens for Mode B
    action_tokens = generate_action_tokens_for_lead(db, lead.id, lead.status)

    # Phase 1: Send WhatsApp summary to artist (Mode B)
    from app.services.artist_notifications import send_artist_summary

    try:
        await send_artist_summary(
            db=db,
            lead=lead,
            answers_dict=answers_dict,
            action_tokens=action_tokens,
            dry_run=dry_run,
        )
    except Exception as e:
        # Log error but don't fail the completion
        logger.error(f"Failed to send artist summary for lead {lead.id}: {e}")

    return {
        "status": "completed",
        "message": completion_msg,
        "lead_status": lead.status,
        "current_step": lead.current_step,
        "summary": answers_dict,
        "estimated_category": category,
        "estimated_deposit": deposit_amount,
        "action_tokens": action_tokens,
    }


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

    # Get all answers
    stmt = select(LeadAnswer).where(LeadAnswer.lead_id == lead_id).order_by(LeadAnswer.created_at)
    answers_list = db.execute(stmt).scalars().all()

    answers_dict = {ans.question_key: ans.answer_text for ans in answers_list}

    summary_text = format_summary_message(answers_dict) if answers_dict else None

    return {
        "lead_id": lead.id,
        "wa_from": lead.wa_from,
        "status": lead.status,
        "current_step": lead.current_step,
        "answers": answers_dict,
        "summary_text": summary_text,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
    }
