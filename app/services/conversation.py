"""
Conversation flow service - handles state machine and question flow.
"""

from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.db.models import Lead, LeadAnswer
from app.services.questions import (
    get_question_by_index,
    get_total_questions,
    is_last_question,
)
from app.services.messaging import send_whatsapp_message, format_summary_message
from app.services.sheets import log_lead_to_sheets
from app.services.action_tokens import generate_action_tokens_for_lead


# Core statuses (proposal lifecycle)
STATUS_NEW = "NEW"
STATUS_QUALIFYING = "QUALIFYING"
STATUS_PENDING_APPROVAL = "PENDING_APPROVAL"
STATUS_AWAITING_DEPOSIT = "AWAITING_DEPOSIT"
STATUS_DEPOSIT_PAID = "DEPOSIT_PAID"
STATUS_BOOKING_LINK_SENT = "BOOKING_LINK_SENT"
STATUS_BOOKED = "BOOKED"

# Operational statuses
STATUS_NEEDS_ARTIST_REPLY = "NEEDS_ARTIST_REPLY"
STATUS_NEEDS_FOLLOW_UP = "NEEDS_FOLLOW_UP"
STATUS_REJECTED = "REJECTED"

# Housekeeping statuses
STATUS_ABANDONED = "ABANDONED"
STATUS_STALE = "STALE"
STATUS_OPTOUT = "OPTOUT"  # Client opted out (STOP/UNSUBSCRIBE)

# Payment-related statuses (future features)
STATUS_DEPOSIT_EXPIRED = "DEPOSIT_EXPIRED"  # Deposit link sent but not paid after X days
STATUS_REFUNDED = "REFUNDED"  # Stripe refund event or manual refund
STATUS_CANCELLED = "CANCELLED"  # Client cancels after paying / before booking

# Legacy (kept for backward compatibility)
STATUS_NEEDS_MANUAL_FOLLOW_UP = "NEEDS_MANUAL_FOLLOW_UP"  # Maps to NEEDS_FOLLOW_UP


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
        return {
            "status": "awaiting_deposit",
            "message": "Please check your messages for the deposit link. If you need it resent, let me know!",
            "lead_status": lead.status,
        }
    
    elif lead.status == STATUS_DEPOSIT_PAID:
        # Deposit paid, waiting for booking
        return {
            "status": "deposit_paid",
            "message": "Thanks for your deposit! I'll send you a booking link shortly.",
            "lead_status": lead.status,
        }
    
    elif lead.status == STATUS_BOOKING_LINK_SENT:
        # Booking link sent, waiting for client to book
        return {
            "status": "booking_link_sent",
            "message": "Please use the booking link I sent to schedule your appointment.",
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
    """Handle a new lead - start the qualification flow."""
    # Set status to QUALIFYING
    lead.status = STATUS_QUALIFYING
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
    
    # Send welcome message + first question
    welcome_msg = f"👋 Hi! Thanks for reaching out. Let's get some details about your tattoo idea.\n\n{question.text}"
    
    await send_whatsapp_message(
        to=lead.wa_from,
        message=welcome_msg,
        dry_run=dry_run,
    )
    
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
    
    # Check for ARTIST handover request
    if message_upper == "ARTIST":
        return await _handle_artist_handover(db, lead, dry_run)
    
    # Save the answer
    answer = LeadAnswer(
        lead_id=lead.id,
        question_key=current_question.key,
        answer_text=message_text,
    )
    db.add(answer)
    
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
    db.commit()
    db.refresh(lead)
    
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
    """Complete qualification - generate summary and move to PENDING_APPROVAL."""
    # Get all answers
    stmt = select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)
    answers_list = db.execute(stmt).scalars().all()
    
    # Build answers dict
    answers_dict = {ans.question_key: ans.answer_text for ans in answers_list}
    
    # For now, we'll compute these in a helper function (to be implemented)
    
    # Generate summary
    summary = format_summary_message(answers_dict)
    
    # Cache summary text
    lead.summary_text = summary
    
    # Send completion message to client
    completion_msg = (
        "✅ Perfect! I've received all your details.\n\n"
        "I'll review your request and get back to you soon. "
        "If approved, I'll send you a deposit link to secure your booking.\n\n"
        "Thanks for your patience! 🙏"
    )
    
    await send_whatsapp_message(
        to=lead.wa_from,
        message=completion_msg,
        dry_run=dry_run,
    )
    
    # Update lead status to PENDING_APPROVAL (not AWAITING_DEPOSIT)
    # AWAITING_DEPOSIT comes after artist approval
    lead.status = STATUS_PENDING_APPROVAL
    lead.last_bot_message_at = func.now()
    db.commit()
    db.refresh(lead)
    
    # This is when consultation completes and lead is ready for artist review
    log_lead_to_sheets(db, lead)
    
    # Generate action tokens for Mode B (WhatsApp action links)
    # These can be included in the WhatsApp summary sent to artist
    action_tokens = generate_action_tokens_for_lead(db, lead.id, lead.status)
    
    # For Mode B: Send WhatsApp summary with action links
    # For Mode A: Just update Sheets (artist uses Sheets as control center)
    # This will be implemented when admin actions are added
    
    return {
        "status": "completed",
        "message": completion_msg,
        "lead_status": lead.status,
        "current_step": lead.current_step,
        "summary": answers_dict,
        "action_tokens": action_tokens,  # Include tokens for Mode B
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
