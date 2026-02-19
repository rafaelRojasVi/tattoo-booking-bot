"""
Qualifying flow handlers - new lead, qualification, human/refund/delete requests, opt-out, handover, completion.
"""

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants.statuses import (
    STATUS_NEEDS_ARTIST_REPLY,
    STATUS_NEEDS_FOLLOW_UP,
    STATUS_NEEDS_MANUAL_FOLLOW_UP,
    STATUS_PENDING_APPROVAL,
    STATUS_QUALIFYING,
    STATUS_TOUR_CONVERSION_OFFERED,
    STATUS_WAITLISTED,
)
from app.db.models import Lead, LeadAnswer
from app.services.action_tokens import generate_action_tokens_for_lead
from app.services.conversation_policy import (
    is_delete_data_request_message,
    is_human_request_message,
    is_opt_out_message,
    is_refund_request_message,
)
from app.services.questions import get_question_by_index, is_last_question
from app.services.sheets import log_lead_to_sheets
from app.services.state_machine import advance_step_if_at, transition


def _get_send_whatsapp():
    """Late-binding so tests patching conversation.send_whatsapp_message take effect."""
    from app.services.conversation import send_whatsapp_message

    return send_whatsapp_message


async def _handle_new_lead(
    db: Session,
    lead: Lead,
    dry_run: bool,
) -> dict:
    """Handle a new lead - start the qualification flow (Phase 1)."""
    # Transition to QUALIFYING (state machine sets qualifying_started_at if not set)
    transition(db, lead, STATUS_QUALIFYING)
    lead.current_step = 0
    db.commit()
    db.refresh(lead)

    # Get first question
    question = get_question_by_index(0)
    if not question:
        return {
            "status": "error",
            "message": "No questions configured",
        }

    # Send welcome message + first question (single message, voice applied)
    from app.services.message_composer import compose_message

    welcome_msg = compose_message(
        "WELCOME",
        {"lead_id": lead.id, "question_text": question.text},
    )

    await _get_send_whatsapp()(
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
    *,
    has_media: bool = False,
) -> dict:
    """Handle a lead in QUALIFYING state - save answer and ask next question."""
    current_step = lead.current_step

    # Get the question we're currently on (the one they're answering)
    current_question = get_question_by_index(current_step)
    if not current_question:
        # Shouldn't happen, but handle gracefully (QUALIFYING -> NEEDS_MANUAL_FOLLOW_UP)
        transition(db, lead, STATUS_NEEDS_MANUAL_FOLLOW_UP)
        return {
            "status": "error",
            "message": "Invalid question step",
        }

    # Outside 24h window: send template fallback, do not save or advance
    from app.services.whatsapp_window import is_within_24h_window

    is_within, _ = is_within_24h_window(lead)
    if not is_within:
        from app.services.whatsapp_templates import (
            get_template_for_next_steps,
            get_template_params_next_steps_reply_to_continue,
        )
        from app.services.whatsapp_window import send_with_window_check

        await send_with_window_check(
            db=db,
            lead=lead,
            message=current_question.text,
            template_name=get_template_for_next_steps(),
            template_params=get_template_params_next_steps_reply_to_continue(),
            dry_run=dry_run,
        )
        return {
            "status": "window_closed_template_sent",
            "lead_status": lead.status,
            "current_step": current_step,
            "question_key": current_question.key,
        }

    # Attachment at wrong step: if media-only (no caption), ack and reprompt; if caption present, parse it
    if has_media and current_question.key != "reference_images":
        if not (message_text and message_text.strip()):
            from app.services.message_composer import compose_message

            ack_msg = compose_message(
                "ATTACHMENT_ACK_REPROMPT",
                {"lead_id": lead.id, "question_text": current_question.text},
            )
            await _get_send_whatsapp()(
                to=lead.wa_from,
                message=ack_msg,
                dry_run=dry_run,
            )
            lead.last_bot_message_at = func.now()
            db.commit()
            return {
                "status": "attachment_ack_reprompt",
                "message": ack_msg,
                "lead_status": lead.status,
                "current_step": current_step,
                "question_key": current_question.key,
            }
        # Caption present: fall through and parse message_text (attachment already stored in webhook)

    # Check for STOP/UNSUBSCRIBE opt-out
    if is_opt_out_message(message_text):
        return await _handle_opt_out(db, lead, dry_run)

    # HUMAN / REFUND / DELETE DATA: ack and handover (no LLM)
    if is_human_request_message(message_text):
        return await _handle_human_request(db, lead, dry_run)
    if is_refund_request_message(message_text):
        return await _handle_refund_request(db, lead, dry_run)
    if is_delete_data_request_message(message_text):
        return await _handle_delete_data_request(db, lead, dry_run)

    # Wrong-field guard: at idea/placement, reject budget-only or dimensions-only
    from app.services.bundle_guard import (
        looks_like_multi_answer_bundle,
        looks_like_wrong_field_single_answer,
    )

    if looks_like_wrong_field_single_answer(message_text, current_question.key):
        from app.services.message_composer import compose_message

        wrong_field_msg = compose_message(
            "ONE_AT_A_TIME_REPROMPT",
            {"lead_id": lead.id, "question_text": current_question.text},
        )
        await _get_send_whatsapp()(
            to=lead.wa_from,
            message=wrong_field_msg,
            dry_run=dry_run,
        )
        lead.last_bot_message_at = func.now()
        db.commit()
        return {
            "status": "wrong_field_reprompt",
            "message": wrong_field_msg,
            "lead_status": lead.status,
            "current_step": current_step,
            "question_key": current_question.key,
        }

    # Multi-answer bundle guard: one at a time, do not save or advance
    # Exception: if the message is a valid single answer for the current question, skip the guard
    def _is_valid_single_answer_for_current_question() -> bool:
        if current_question.key == "dimensions":
            from app.services.estimation_service import parse_dimensions

            return parse_dimensions(message_text) is not None
        if current_question.key == "budget":
            from app.services.estimation_service import parse_budget_from_text

            return parse_budget_from_text(message_text) is not None
        if current_question.key == "location_city":
            from app.services.location_parsing import is_valid_location, parse_location_input

            parsed = parse_location_input(message_text.strip())
            return not parsed["is_flexible"] and is_valid_location(message_text.strip())
        return False

    if (
        looks_like_multi_answer_bundle(message_text, current_question_key=current_question.key)
        and not _is_valid_single_answer_for_current_question()
    ):
        from app.services.message_composer import compose_message

        one_at_a_time_msg = compose_message(
            "ONE_AT_A_TIME_REPROMPT",
            {"lead_id": lead.id, "question_text": current_question.text},
        )
        await _get_send_whatsapp()(
            to=lead.wa_from,
            message=one_at_a_time_msg,
            dry_run=dry_run,
        )
        lead.last_bot_message_at = func.now()
        db.commit()
        return {
            "status": "one_at_a_time_reprompt",
            "message": one_at_a_time_msg,
            "lead_status": lead.status,
            "current_step": current_step,
            "question_key": current_question.key,
        }

    # Phase 1: Dynamic handover check (replaces keyword trigger)
    from app.services.handover_service import get_handover_message, should_handover

    should_handover_flag, handover_reason = should_handover(message_text, lead)
    if should_handover_flag:
        transition(db, lead, STATUS_NEEDS_ARTIST_REPLY, reason=handover_reason)

        # Notify artist (idempotent - only notifies on transition)
        from app.services.artist_notifications import notify_artist_needs_reply

        await notify_artist_needs_reply(
            db=db,
            lead=lead,
            reason=handover_reason or "",
            dry_run=dry_run,
        )

        handover_msg = get_handover_message(handover_reason or "", lead_id=lead.id)
        await _get_send_whatsapp()(
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

    # Parse and validate answer based on question type
    parse_success = True
    repair_message = None

    if current_question.key == "dimensions":
        # Try to parse dimensions
        from app.services.estimation_service import parse_dimensions

        parsed_dims = parse_dimensions(message_text)
        if parsed_dims is None:
            # Parse failed - increment failure count
            from app.services.parse_repair import (
                increment_parse_failure,
                should_handover_after_failure,
                trigger_handover_after_parse_failure,
            )

            increment_parse_failure(db, lead, "dimensions")
            if should_handover_after_failure(lead, "dimensions"):
                return await trigger_handover_after_parse_failure(db, lead, "dimensions", dry_run)
            from app.services.message_composer import compose_message
            from app.services.parse_repair import get_failure_count

            repair_message = compose_message(
                "REPAIR_SIZE",
                {"lead_id": lead.id, "retry_count": get_failure_count(lead, "dimensions")},
            )
            parse_success = False
        else:
            # Parse succeeded - reset failures
            from app.services.parse_repair import reset_parse_failures

            reset_parse_failures(db, lead, "dimensions")

    elif current_question.key == "budget":
        # Try to parse budget (digits, £400, 400gbp, $500, etc.)
        from app.services.estimation_service import parse_budget_from_text
        from app.services.parse_repair import (
            get_failure_count,
            increment_parse_failure,
            should_handover_after_failure,
            trigger_handover_after_parse_failure,
        )

        budget_pence = parse_budget_from_text(message_text)
        # Reject unrealistically low amounts (< £50) to avoid "4" or "10" false positives
        if budget_pence is not None and budget_pence < 5000:
            budget_pence = None
        if budget_pence is None:
            increment_parse_failure(db, lead, "budget")
            if should_handover_after_failure(lead, "budget"):
                return await trigger_handover_after_parse_failure(db, lead, "budget", dry_run)
            from app.services.message_composer import compose_message

            repair_message = compose_message(
                "REPAIR_BUDGET",
                {"lead_id": lead.id, "retry_count": get_failure_count(lead, "budget")},
            )
            parse_success = False
        else:
            from app.services.parse_repair import reset_parse_failures

            reset_parse_failures(db, lead, "budget")

    elif current_question.key == "location_city":
        # Parse location using hardened location parsing service
        from app.services.location_parsing import is_valid_location, parse_location_input
        from app.services.parse_repair import (
            increment_parse_failure,
            reset_parse_failures,
            should_handover_after_failure,
            trigger_handover_after_parse_failure,
        )

        location_text = message_text.strip()
        parsed = parse_location_input(location_text)

        # Check if location is valid
        if parsed["is_flexible"] or not is_valid_location(location_text):
            # Parse failed (flexible, empty, or invalid)
            increment_parse_failure(db, lead, "location_city")
            if should_handover_after_failure(lead, "location_city"):
                return await trigger_handover_after_parse_failure(
                    db, lead, "location_city", dry_run
                )
            from app.services.message_composer import compose_message
            from app.services.parse_repair import get_failure_count

            repair_message = compose_message(
                "REPAIR_LOCATION",
                {"lead_id": lead.id, "retry_count": get_failure_count(lead, "location_city")},
            )
            parse_success = False
        else:
            # Parse succeeded
            reset_parse_failures(db, lead, "location_city")

            # Store city and country
            if parsed["city"]:
                # Store city in lead field
                lead.location_city = parsed["city"]

            if parsed["country"]:
                # Store country in lead field
                lead.location_country = parsed["country"]

                # Also store as LeadAnswer
                country_answer = LeadAnswer(
                    lead_id=lead.id,
                    question_key="location_country",
                    answer_text=parsed["country"],
                )
                db.add(country_answer)

            # If only country provided, may need follow-up (but accept for now)
            if parsed["is_only_country"]:
                # Accept country but note that city is missing
                # Could send soft follow-up, but for now just accept
                pass

            # If city provided but country not inferred, may need follow-up
            if parsed["city"] and not parsed["country"] and parsed["needs_follow_up"]:
                # City provided but country unknown - accept for now
                # Could send soft follow-up in future
                pass

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

    # If parse failed, send repair message and don't advance
    if not parse_success and repair_message:
        await _get_send_whatsapp()(
            to=lead.wa_from,
            message=repair_message,
            dry_run=dry_run,
        )
        lead.last_bot_message_at = func.now()
        db.commit()
        return {
            "status": "repair_needed",
            "message": repair_message,
            "lead_status": lead.status,
            "question_key": current_question.key,
        }

    # Commit answer before checking for confirmation (so _maybe_send_confirmation_summary can find it)
    db.commit()

    # Build confirmation message if we have dimensions, budget, location_city (single combined send)
    confirmation_msg = (
        _get_confirmation_summary_message(db, lead, current_question.key) if parse_success else None
    )

    # Check if this was the last question
    if is_last_question(current_step):
        # All questions answered - generate summary and move to PENDING_APPROVAL
        return await _complete_qualification(db, lead, dry_run)

    # If we have a confirmation to send, combine it with the next question in one message
    next_question = get_question_by_index(current_step + 1)
    if confirmation_msg and next_question:
        lead_id_for_step = lead.id
        success, lead = advance_step_if_at(db, lead_id_for_step, current_step)
        if not success:
            refreshed = db.get(Lead, lead_id_for_step)
            return {
                "status": "step_already_advanced",
                "lead_status": refreshed.status if refreshed else None,
                "message": "Another message was processed first",
            }
        if lead is None:
            return {
                "status": "error",
                "message": "Lead not found after step advance",
            }
        from app.services.message_composer import compose_message

        next_msg = compose_message(
            "ASK_QUESTION",
            {"lead_id": lead.id, "question_text": next_question.text},
        )
        combined = f"{confirmation_msg}\n\n{next_msg}"
        await _get_send_whatsapp()(
            to=lead.wa_from,
            message=combined,
            dry_run=dry_run,
        )
        lead.last_bot_message_at = func.now()
        db.commit()
        return {
            "status": "confirmation_sent",
            "lead_status": lead.status,
            "current_step": lead.current_step,
            "question_key": next_question.key,
        }

    # Move to next question: advance FIRST, then send (only winner sends)
    lead_id = lead.id
    next_question = get_question_by_index(current_step + 1)
    if not next_question:
        # Shouldn't happen (QUALIFYING -> NEEDS_MANUAL_FOLLOW_UP)
        transition(db, lead, STATUS_NEEDS_MANUAL_FOLLOW_UP)
        return {
            "status": "error",
            "message": "No next question found",
        }

    success, lead = advance_step_if_at(db, lead_id, current_step)
    if not success:
        refreshed = db.get(Lead, lead_id)
        return {
            "status": "step_already_advanced",
            "lead_status": refreshed.status if refreshed else None,
            "message": "Another message was processed first",
        }
    if lead is None:
        return {
            "status": "error",
            "message": "Lead not found after step advance",
        }

    from app.services.message_composer import compose_message

    next_msg = compose_message(
        "ASK_QUESTION",
        {"lead_id": lead.id, "question_text": next_question.text},
    )
    await _get_send_whatsapp()(
        to=lead.wa_from,
        message=next_msg,
        dry_run=dry_run,
    )

    lead.last_bot_message_at = func.now()
    db.commit()

    return {
        "status": "question_sent",
        "message": next_msg,
        "lead_status": lead.status,
        "current_step": lead.current_step,
        "question_key": next_question.key,
        "saved_answer": {
            "question": current_question.key,
            "answer": message_text,
        },
    }


async def _handle_human_request(db: Session, lead: Lead, dry_run: bool) -> dict:
    """Handle 'human' / 'talk to someone' — handover to artist."""
    transition(db, lead, STATUS_NEEDS_ARTIST_REPLY, reason="Client requested human/artist")
    from app.services.artist_notifications import notify_artist_needs_reply
    from app.services.message_composer import compose_message

    await notify_artist_needs_reply(
        db=db,
        lead=lead,
        reason=lead.handover_reason or "",
        dry_run=dry_run,
    )
    handover_msg = compose_message("HUMAN_HANDOVER", {"lead_id": lead.id})
    await _get_send_whatsapp()(to=lead.wa_from, message=handover_msg, dry_run=dry_run)
    lead.last_bot_message_at = func.now()
    db.commit()
    return {"status": "handover", "message": handover_msg, "lead_status": lead.status}


async def _handle_refund_request(db: Session, lead: Lead, dry_run: bool) -> dict:
    """Handle 'refund' — ack and handover to artist."""
    transition(db, lead, STATUS_NEEDS_ARTIST_REPLY, reason="Client asked about refund")
    from app.services.artist_notifications import notify_artist_needs_reply
    from app.services.message_composer import compose_message

    await notify_artist_needs_reply(
        db=db,
        lead=lead,
        reason=lead.handover_reason or "",
        dry_run=dry_run,
    )
    ack_msg = compose_message("REFUND_ACK", {"lead_id": lead.id})
    await _get_send_whatsapp()(to=lead.wa_from, message=ack_msg, dry_run=dry_run)
    lead.last_bot_message_at = func.now()
    db.commit()
    return {"status": "handover", "message": ack_msg, "lead_status": lead.status}


async def _handle_delete_data_request(db: Session, lead: Lead, dry_run: bool) -> dict:
    """Handle 'delete my data' / GDPR — ack and handover to artist."""
    transition(db, lead, STATUS_NEEDS_ARTIST_REPLY, reason="Client requested data deletion / GDPR")
    from app.services.artist_notifications import notify_artist_needs_reply
    from app.services.message_composer import compose_message

    await notify_artist_needs_reply(
        db=db,
        lead=lead,
        reason=lead.handover_reason or "",
        dry_run=dry_run,
    )
    ack_msg = compose_message("DELETE_DATA_ACK", {"lead_id": lead.id})
    await _get_send_whatsapp()(to=lead.wa_from, message=ack_msg, dry_run=dry_run)
    lead.last_bot_message_at = func.now()
    db.commit()
    return {"status": "handover", "message": ack_msg, "lead_status": lead.status}


async def _handle_opt_out(
    db: Session,
    lead: Lead,
    dry_run: bool,
) -> dict:
    """Handle STOP/UNSUBSCRIBE opt-out request - stop all outbound messages."""
    from app.constants.statuses import STATUS_OPTOUT

    transition(db, lead, STATUS_OPTOUT)

    # Send confirmation from YAML (consistent with copy)
    from app.services.message_composer import compose_message

    optout_msg = compose_message("OPT_OUT", {"lead_id": lead.id})

    await _get_send_whatsapp()(
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


def _get_confirmation_summary_message(
    db: Session,
    lead: Lead,
    just_answered_key: str,
) -> str | None:
    """
    Build micro-confirmation summary message if we just completed dimensions, budget, and location_city.
    Returns the message text or None if we should not send a confirmation.
    """
    if just_answered_key not in ["dimensions", "budget", "location_city"]:
        return None

    stmt = (
        select(LeadAnswer)
        .where(LeadAnswer.lead_id == lead.id)
        .order_by(LeadAnswer.created_at, LeadAnswer.id)
    )
    answers_list = db.execute(stmt).scalars().all()
    answers_dict = {ans.question_key: ans.answer_text for ans in answers_list}

    has_dimensions = "dimensions" in answers_dict and answers_dict["dimensions"].strip()
    has_budget = "budget" in answers_dict and answers_dict["budget"].strip()
    has_location = "location_city" in answers_dict and answers_dict["location_city"].strip()

    if not (has_dimensions and has_budget and has_location):
        return None

    from app.services.estimation_service import parse_dimensions
    from app.services.message_composer import render_message

    dimensions_text = answers_dict.get("dimensions", "")
    budget_text = answers_dict.get("budget", "")
    location_text = answers_dict.get("location_city", "")

    parsed_dims = parse_dimensions(dimensions_text)
    if parsed_dims:
        size_display = f"{parsed_dims[0]:.0f}×{parsed_dims[1]:.0f}cm"
    else:
        size_display = dimensions_text[:20]

    numbers = re.findall(r"\d+", budget_text.replace(",", ""))
    if numbers:
        budget_gbp = int(numbers[0])
        budget_display = f"£{budget_gbp}"
    else:
        budget_display = budget_text[:20]

    return render_message(
        "confirmation_summary",
        lead_id=lead.id,
        size=size_display,
        location=location_text,
        budget=budget_display,
    )


async def _maybe_send_confirmation_summary(
    db: Session,
    lead: Lead,
    just_answered_key: str,
    dry_run: bool,
) -> bool:
    """
    Send micro-confirmation summary if we just completed dimensions, budget, and location_city.
    Used when we need to send confirmation only (e.g. from tests). In the main flow we combine
    confirmation + next question into one message via _get_confirmation_summary_message.
    """
    confirmation_msg = _get_confirmation_summary_message(db, lead, just_answered_key)
    if confirmation_msg is None:
        return False

    await _get_send_whatsapp()(
        to=lead.wa_from,
        message=confirmation_msg,
        dry_run=dry_run,
    )
    lead.last_bot_message_at = func.now()
    db.commit()
    return True


async def _handle_artist_handover(
    db: Session,
    lead: Lead,
    dry_run: bool,
) -> dict:
    """Handle ARTIST handover request - pause bot and notify artist."""
    transition(db, lead, STATUS_NEEDS_ARTIST_REPLY, reason="Client requested artist handover")

    # Notify artist (idempotent - only notifies on transition)
    from app.services.artist_notifications import notify_artist_needs_reply

    await notify_artist_needs_reply(
        db=db,
        lead=lead,
        reason="Client requested artist handover",
        dry_run=dry_run,
    )

    # Ask for handover preference
    from app.services.message_composer import render_message

    handover_msg = render_message("handover_question", lead_id=lead.id)

    await _get_send_whatsapp()(
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
    import logging

    from app.services.estimation_service import estimate_project
    from app.services.region_service import country_to_region, region_min_budget
    from app.services.tour_service import closest_upcoming_city, format_tour_offer, is_city_on_tour

    logger = logging.getLogger(__name__)

    # Get all answers (order_by so latest-wins per key is deterministic)
    stmt = (
        select(LeadAnswer)
        .where(LeadAnswer.lead_id == lead.id)
        .order_by(LeadAnswer.created_at, LeadAnswer.id)
    )
    answers_list = db.execute(stmt).scalars().all()
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
        handover_reason = "Cover-up/rework requires creative assessment"
        lead.qualifying_completed_at = func.now()
        db.commit()
        db.refresh(lead)
        transition(db, lead, STATUS_NEEDS_ARTIST_REPLY, reason=handover_reason)

        # Notify artist (idempotent - only notifies on transition)
        from app.services.artist_notifications import notify_artist_needs_reply

        await notify_artist_needs_reply(
            db=db,
            lead=lead,
            reason=handover_reason,
            dry_run=dry_run,
        )

        from app.services.message_composer import render_message

        handover_msg = render_message("handover_coverup", lead_id=lead.id)

        await _get_send_whatsapp()(
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
    category, deposit_amount, estimated_days = estimate_project(
        dimensions_text=dimensions_text,
        complexity_level=complexity_level,
        is_coverup=is_coverup,
        placement=placement,
    )

    lead.estimated_category = category
    lead.estimated_deposit_amount = deposit_amount
    lead.estimated_days = estimated_days  # Store estimated days (for XL projects)
    lead.complexity_level = complexity_level

    # Store location and derive region
    lead.location_city = location_city
    lead.location_country = location_country
    region = country_to_region(location_country)
    lead.region_bucket = region
    min_budget = region_min_budget(region)
    lead.min_budget_amount = min_budget

    # Compute and store pricing estimates (internal use only)
    from app.services.pricing_service import calculate_price_range

    if category and region:
        price_range = calculate_price_range(
            region=region,
            category=category,
            include_trace=True,
        )
        lead.estimated_price_min_pence = price_range.min_pence
        lead.estimated_price_max_pence = price_range.max_pence
        lead.pricing_trace_json = price_range.trace

    # Store Instagram handle
    if instagram_handle:
        lead.instagram_handle = instagram_handle.replace("@", "").strip()

    # Parse budget
    budget_amount = None
    try:
        # Extract number from budget text
        numbers = re.findall(r"\d+", budget_text.replace(",", ""))
        if numbers:
            budget_amount = int(numbers[0]) * 100  # Convert to pence
    except (ValueError, IndexError):
        pass

    # Check budget vs minimum
    if budget_amount and budget_amount < min_budget:
        lead.below_min_budget = True
        lead.qualifying_completed_at = func.now()
        db.commit()
        db.refresh(lead)
        # Set NEEDS_FOLLOW_UP (do NOT auto-decline)
        transition(db, lead, STATUS_NEEDS_FOLLOW_UP)

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
        from app.services.message_composer import render_message

        budget_msg = render_message(
            "budget_below_minimum",
            lead_id=lead.id,
            min_gbp=min_gbp,
        )

        await _get_send_whatsapp()(
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
            lead.offered_tour_city = tour_stop.city
            lead.offered_tour_dates_text = f"{tour_stop.start_date.strftime('%B %d')} - {tour_stop.end_date.strftime('%B %d, %Y')}"
            lead.qualifying_completed_at = func.now()
            db.commit()
            db.refresh(lead)
            transition(db, lead, STATUS_TOUR_CONVERSION_OFFERED)

            tour_msg = format_tour_offer(tour_stop)
            await _get_send_whatsapp()(
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
            lead.waitlisted = True
            lead.qualifying_completed_at = func.now()
            db.commit()
            db.refresh(lead)
            transition(db, lead, STATUS_WAITLISTED)

            waitlist_msg = (
                f"I don't have {requested_city} scheduled yet. "
                f"I'll add you to the waitlist and let you know when I'm planning to visit!"
            )
            await _get_send_whatsapp()(
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
    db.commit()
    db.refresh(lead)
    transition(db, lead, STATUS_PENDING_APPROVAL)

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

    await _get_send_whatsapp()(
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
