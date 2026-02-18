import logging

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import get_admin_auth
from app.constants.event_types import EVENT_DEPOSIT_EXPIRED_SWEEP, EVENT_PENDING_APPROVAL
from app.db.deps import get_db
from app.db.models import Lead, OutboxMessage
from app.schemas.admin import (
    RejectRequest,
    SendBookingLinkRequest,
    SendDepositRequest,
)
from app.services.conversation import (
    STATUS_AWAITING_DEPOSIT,
    STATUS_BOOKED,
    STATUS_BOOKING_LINK_SENT,
    STATUS_DEPOSIT_PAID,
    STATUS_PENDING_APPROVAL,
    STATUS_REJECTED,
    get_lead_summary,
)
from app.services.messaging import format_deposit_link_message
from app.services.safety import update_lead_status_if_matches
from app.services.sheets import log_lead_to_sheets

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/outbox")
def list_outbox_messages(
    status: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    """
    List outbox rows (e.g. FAILED) for inspection.
    Query params: status (PENDING, SENT, FAILED), limit (default 50).
    """
    from sqlalchemy import desc

    stmt = select(OutboxMessage).order_by(desc(OutboxMessage.created_at))
    if status:
        stmt = stmt.where(OutboxMessage.status == status.upper())
    stmt = stmt.limit(max(0, min(limit, 100)))  # Clamp to [0, 100]; negative -> 0
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": r.id,
            "lead_id": r.lead_id,
            "channel": r.channel,
            "status": r.status,
            "attempts": r.attempts,
            "last_error": r.last_error,
            "next_retry_at": r.next_retry_at.isoformat() if r.next_retry_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/outbox/retry")
def retry_outbox_messages(
    limit: int = 50,
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    """
    Retry due outbox rows (PENDING/FAILED with next_retry_at <= now).
    Only active when OUTBOX_ENABLED=true.
    """
    from app.services.outbox_service import retry_due_outbox_rows

    results = retry_due_outbox_rows(db, limit=limit)
    return {"outbox_retry": results}


@router.post("/test-webhook-exception")
def test_webhook_exception_simulation(
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    """
    Simulate webhook processing exception (staging only).
    Returns HTTP 200 and logs SystemEvent with correlation_id, mimicking WhatsApp webhook behavior.
    Disabled in production (APP_ENV=production).
    """
    from app.constants.event_types import EVENT_WHATSAPP_WEBHOOK_FAILURE
    from app.core.config import settings
    from app.services.system_event_service import error

    if settings.app_env == "production":
        raise HTTPException(
            status_code=404,
            detail="Test endpoint disabled in production",
        )

    try:
        raise RuntimeError("Simulated webhook processing exception (staging test)")
    except Exception as e:
        error(
            db=db,
            event_type=EVENT_WHATSAPP_WEBHOOK_FAILURE,
            lead_id=None,
            payload={"simulated": True, "message": "Staging test endpoint"},
            exc=e,
        )
        return {"received": True, "simulated": True, "error_logged": True}


@router.post("/events/retention-cleanup")
def cleanup_system_events_retention(
    retention_days: int = 90,
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    """
    Delete SystemEvents older than retention_days (default 90).
    Admin-only. Use for periodic retention or manual cleanup.
    """
    from app.services.system_event_service import cleanup_old_events

    deleted = cleanup_old_events(db, retention_days=retention_days)
    return {"deleted": deleted, "retention_days": retention_days}


@router.get("/metrics")
def get_metrics(
    _auth: bool = Security(get_admin_auth),
):
    """Get system metrics (duplicate events, failed atomic updates, etc.)."""
    from app.services.metrics import get_metrics, get_metrics_summary

    return {
        "metrics": get_metrics(),
        "summary": get_metrics_summary(),
    }


@router.get("/funnel")
def get_funnel(
    days: int = 7,
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    """
    Get funnel metrics and conversion rates.

    Args:
        days: Number of days to look back (default 7)

    Returns:
        Dict with counts and conversion rates
    """
    from app.services.funnel_metrics_service import get_funnel_metrics

    return get_funnel_metrics(db, days=days)


@router.get("/slot-parse-stats")
def get_slot_parse_stats_endpoint(
    days: int = 7,
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    """
    Get slot parse metrics: counts by matched_by and reject reason.

    Args:
        days: Number of days to look back (default 7)

    Returns:
        Dict with success/reject counts
    """
    from app.services.slot_parsing import get_slot_parse_stats

    return get_slot_parse_stats(db, last_days=days)


@router.get("/leads")
def list_leads(
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    leads = db.execute(select(Lead).order_by(Lead.created_at.desc())).scalars().all()
    return [
        {
            "id": lead.id,
            "wa_from": lead.wa_from,
            "status": lead.status,
            "current_step": lead.current_step,
            "created_at": lead.created_at,
        }
        for lead in leads
    ]


@router.get("/leads/{lead_id}")
def get_lead_detail(
    lead_id: int,
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    """Get detailed lead information including answers and summary."""
    summary = get_lead_summary(db, lead_id)

    if "error" in summary:
        raise HTTPException(status_code=404, detail=summary["error"])

    return summary


@router.post("/leads/{lead_id}/approve")
async def approve_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    """
    Approve a lead - transitions from PENDING_APPROVAL to AWAITING_DEPOSIT.
    Status-locked: only works from PENDING_APPROVAL.
    """
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Atomic status-locked update (prevents race conditions)
    success, lead = update_lead_status_if_matches(
        db=db,
        lead_id=lead_id,
        expected_status=STATUS_PENDING_APPROVAL,
        new_status=STATUS_AWAITING_DEPOSIT,
        approved_at=func.now(),
        last_admin_action="approve",
        last_admin_action_at=func.now(),
    )

    if not success:
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve lead in status '{lead.status}'. Lead must be in '{STATUS_PENDING_APPROVAL}'.",
        )

    log_lead_to_sheets(db, lead)

    # Phase 1: Send calendar slot suggestions after approval (before deposit)
    from app.core.config import settings
    from app.services.calendar_service import send_slot_suggestions_to_client

    try:
        await send_slot_suggestions_to_client(
            db=db,
            lead=lead,
            dry_run=settings.whatsapp_dry_run,
        )
    except Exception as e:
        # Log error but don't fail the approval
        logger.error(f"Failed to send slot suggestions to lead {lead_id}: {e}")

    # Phase 1: Notify artist that lead was approved
    from app.services.artist_notifications import notify_artist

    try:
        await notify_artist(
            db=db,
            lead=lead,
            event_type=EVENT_PENDING_APPROVAL,  # Actually "approved" but using existing notification
            dry_run=settings.whatsapp_dry_run,
        )
    except Exception as e:
        logger.error(f"Failed to notify artist of approval for lead {lead_id}: {e}")

    return {
        "success": True,
        "message": "Lead approved. Slot suggestions sent to client.",
        "lead_id": lead.id,
        "status": lead.status,
    }


@router.post("/leads/{lead_id}/reject")
def reject_lead(
    lead_id: int,
    request: RejectRequest,
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    """
    Reject a lead - transitions to REJECTED.
    Can be called from any status (status-locked only for approve/send-deposit/send-booking).
    """
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if lead.status == STATUS_REJECTED:
        raise HTTPException(status_code=400, detail="Lead is already rejected")

    if lead.status == STATUS_BOOKED:
        raise HTTPException(status_code=400, detail="Cannot reject a booked lead")

    # Transition to REJECTED
    lead.status = STATUS_REJECTED
    lead.rejected_at = func.now()
    lead.last_admin_action = "reject"
    lead.last_admin_action_at = func.now()
    if request.reason:
        lead.admin_notes = (lead.admin_notes or "") + f"\nRejection reason: {request.reason}"
    db.commit()
    db.refresh(lead)

    log_lead_to_sheets(db, lead)

    # TODO: Send WhatsApp message (optional, based on policy)

    return {
        "success": True,
        "message": "Lead rejected.",
        "lead_id": lead.id,
        "status": lead.status,
    }


@router.post("/leads/{lead_id}/send-deposit")
async def send_deposit(
    lead_id: int,
    request: SendDepositRequest | None = None,
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    """
    Send deposit link - creates Stripe checkout session and sends to client.
    Status-locked: only works from AWAITING_DEPOSIT.
    Note: Status remains AWAITING_DEPOSIT until webhook confirms payment.
    """
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if lead.status != STATUS_AWAITING_DEPOSIT:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot send deposit link for lead in status '{lead.status}'. Lead must be in '{STATUS_AWAITING_DEPOSIT}'.",
        )

    # Check if existing checkout session is expired
    from datetime import UTC, datetime

    if lead.stripe_checkout_session_id and lead.deposit_checkout_expires_at:
        now = datetime.now(UTC)
        # Handle timezone-aware/naive comparison
        expires_at = lead.deposit_checkout_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        if now >= expires_at:
            # Session expired - clear it and create a new one
            logger.info(
                f"Existing checkout session {lead.stripe_checkout_session_id} for lead {lead_id} "
                f"expired at {expires_at}. Creating new session."
            )
            lead.stripe_checkout_session_id = None
            lead.deposit_checkout_expires_at = None
            db.commit()
            db.refresh(lead)

    # Lock deposit amount: prefer deposit_amount_pence if already set, else estimated_deposit_amount
    # This ensures the amount is locked once approved/deposit link is generated
    from app.core.config import settings

    if lead.deposit_amount_pence:
        # Already locked - use existing value
        amount_pence = lead.deposit_amount_pence
    elif lead.estimated_deposit_amount:
        # Use estimated deposit amount
        amount_pence = lead.estimated_deposit_amount
    elif request and request.amount_pence is not None:
        # Use amount from request (validate: must be positive)
        if request.amount_pence < 1:
            raise HTTPException(
                status_code=400,
                detail="amount_pence must be a positive integer (minimum 1 pence)",
            )
        amount_pence = request.amount_pence
    else:
        # Fallback to estimated_category calculation
        from app.services.estimation_service import get_deposit_amount

        if lead.estimated_category:
            # For XL, use estimated_days if available
            estimated_days = lead.estimated_days if lead.estimated_category == "XL" else None
            amount_pence = get_deposit_amount(
                lead.estimated_category, estimated_days=estimated_days
            )
        else:
            # Final fallback to default
            amount_pence = settings.stripe_deposit_amount_pence

    # Lock the deposit amount and set audit fields
    lead.deposit_amount_pence = amount_pence
    lead.estimated_deposit_amount = amount_pence  # Ensure it's set
    lead.deposit_amount_locked_at = func.now()  # Lock timestamp
    lead.deposit_rule_version = settings.deposit_rule_version  # Store rule version
    lead.deposit_sent_at = func.now()  # Track when sent
    lead.last_admin_action = "send_deposit"
    lead.last_admin_action_at = func.now()
    db.commit()
    db.refresh(lead)

    # Create Stripe checkout session
    from app.services.stripe_service import create_checkout_session

    checkout_result = create_checkout_session(
        lead_id=lead.id,
        amount_pence=amount_pence,
        success_url=settings.stripe_success_url,
        cancel_url=settings.stripe_cancel_url,
        metadata={
            "wa_from": lead.wa_from,
            "status": lead.status,
            "deposit_rule_version": settings.deposit_rule_version,
            "amount_pence": str(amount_pence),
        },
    )

    # Store checkout session ID and expiry timestamp
    lead.stripe_checkout_session_id = checkout_result["checkout_session_id"]
    lead.deposit_checkout_expires_at = checkout_result.get("expires_at")
    db.commit()
    db.refresh(lead)

    log_lead_to_sheets(db, lead)

    # Send WhatsApp message with deposit link (with 24h window check)
    from app.services.whatsapp_templates import (
        get_template_for_next_steps,
        get_template_params_next_steps_reply_to_continue,
    )
    from app.services.whatsapp_window import send_with_window_check

    deposit_message = format_deposit_link_message(
        checkout_result["checkout_url"], amount_pence, lead_id=lead.id
    )

    await send_with_window_check(
        db=db,
        lead=lead,
        message=deposit_message,
        template_name=get_template_for_next_steps(),  # Re-open window template
        template_params=get_template_params_next_steps_reply_to_continue(),
        dry_run=settings.whatsapp_dry_run,
    )

    # Update last bot message timestamp
    lead.last_bot_message_at = func.now()
    db.commit()
    db.refresh(lead)

    return {
        "success": True,
        "message": "Deposit link created and sent via WhatsApp.",
        "lead_id": lead.id,
        "status": lead.status,
        "deposit_amount_pence": amount_pence,
        "checkout_url": checkout_result["checkout_url"],
        "checkout_session_id": checkout_result["checkout_session_id"],
    }


@router.post("/leads/{lead_id}/send-booking-link")
def send_booking_link(
    lead_id: int,
    request: SendBookingLinkRequest,
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    """
    Send booking link - transitions from DEPOSIT_PAID to BOOKING_LINK_SENT.
    Status-locked: only works from DEPOSIT_PAID.
    """
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Atomic status-locked update (prevents race conditions)
    success, lead = update_lead_status_if_matches(
        db=db,
        lead_id=lead_id,
        expected_status=STATUS_DEPOSIT_PAID,
        new_status=STATUS_BOOKING_LINK_SENT,
        booking_link=request.booking_url,
        booking_tool=request.booking_tool,
        booking_link_sent_at=func.now(),
        last_admin_action="send_booking_link",
        last_admin_action_at=func.now(),
    )

    if not success:
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        raise HTTPException(
            status_code=400,
            detail=f"Cannot send booking link for lead in status '{lead.status}'. Lead must be in '{STATUS_DEPOSIT_PAID}'.",
        )

    log_lead_to_sheets(db, lead)

    # TODO: Send WhatsApp message with booking link

    return {
        "success": True,
        "message": "Booking link will be sent (not yet implemented).",
        "lead_id": lead.id,
        "status": lead.status,
        "booking_link": request.booking_url,
    }


@router.post("/leads/{lead_id}/mark-booked")
def mark_booked(
    lead_id: int,
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    """
    Phase 1: Mark lead as booked - transitions from BOOKING_PENDING to BOOKED.
    Status-locked: only works from BOOKING_PENDING.
    """
    from app.services.conversation import STATUS_BOOKING_PENDING

    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Atomic status-locked update (prevents race conditions)
    # BOOKED can only be set manually - no external events can set this
    success, lead = update_lead_status_if_matches(
        db=db,
        lead_id=lead_id,
        expected_status=STATUS_BOOKING_PENDING,
        new_status=STATUS_BOOKED,
        booked_at=func.now(),
        last_admin_action="mark_booked",
        last_admin_action_at=func.now(),
    )

    if not success:
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        # Also allow from legacy BOOKING_LINK_SENT
        if lead.status == STATUS_BOOKING_LINK_SENT:
            lead.status = STATUS_BOOKED
            lead.booked_at = func.now()
            lead.last_admin_action = "mark_booked"
            lead.last_admin_action_at = func.now()
            db.commit()
            db.refresh(lead)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot mark lead as booked in status '{lead.status}'. Lead must be in '{STATUS_BOOKING_PENDING}'.",
            )

    log_lead_to_sheets(db, lead)

    # TODO: Send WhatsApp confirmation message

    return {
        "success": True,
        "message": "Lead marked as booked.",
        "lead_id": lead.id,
        "status": lead.status,
    }


@router.get("/events")
def get_events(
    limit: int = 100,
    lead_id: int | None = None,
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    """
    Get system events with optional filtering.

    Args:
        limit: Maximum number of events to return (default 100, max 1000)
        lead_id: Optional lead ID to filter by

    Returns:
        List of system events ordered by created_at descending
    """
    from sqlalchemy import desc

    from app.db.models import SystemEvent

    # Cap limit at 1000 for performance
    limit = min(limit, 1000)

    query = db.query(SystemEvent).order_by(desc(SystemEvent.created_at))

    if lead_id is not None:
        query = query.filter(SystemEvent.lead_id == lead_id)

    events = query.limit(limit).all()

    return [
        {
            "id": event.id,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "level": event.level,
            "event_type": event.event_type,
            "lead_id": event.lead_id,
            "payload": event.payload,
        }
        for event in events
    ]


@router.get("/debug/lead/{lead_id}")
def debug_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    """
    Debug endpoint for lead - returns comprehensive debugging information.

    Includes:
    - Full lead data
    - All answers
    - Handover packet
    - Recent system events
    - Parse failures
    - Status transition history (from timestamps)

    Args:
        lead_id: Lead ID to debug

    Returns:
        Comprehensive debug information
    """
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Get handover packet
    from app.services.handover_packet import build_handover_packet

    packet = build_handover_packet(db, lead)

    # Get all answers
    from app.db.models import LeadAnswer

    answers = (
        db.query(LeadAnswer)
        .filter(LeadAnswer.lead_id == lead_id)
        .order_by(LeadAnswer.created_at)
        .all()
    )

    # Get recent system events for this lead
    from sqlalchemy import desc

    from app.db.models import SystemEvent

    events = (
        db.query(SystemEvent)
        .filter(SystemEvent.lead_id == lead_id)
        .order_by(desc(SystemEvent.created_at))
        .limit(50)
        .all()
    )

    # Get processed messages for this lead
    from app.db.models import ProcessedMessage

    processed_messages = (
        db.query(ProcessedMessage)
        .filter(ProcessedMessage.lead_id == lead_id)
        .order_by(desc(ProcessedMessage.processed_at))
        .limit(20)
        .all()
    )

    # Build status history from timestamps
    status_history = []
    if lead.qualifying_started_at:
        status_history.append(
            {
                "status": "QUALIFYING",
                "timestamp": lead.qualifying_started_at.isoformat(),
                "type": "started",
            }
        )
    if lead.qualifying_completed_at:
        status_history.append(
            {
                "status": "QUALIFYING",
                "timestamp": lead.qualifying_completed_at.isoformat(),
                "type": "completed",
            }
        )
    if lead.pending_approval_at:
        status_history.append(
            {
                "status": "PENDING_APPROVAL",
                "timestamp": lead.pending_approval_at.isoformat(),
                "type": "entered",
            }
        )
    if lead.approved_at:
        status_history.append(
            {"status": "APPROVED", "timestamp": lead.approved_at.isoformat(), "type": "action"}
        )
    if lead.deposit_sent_at:
        status_history.append(
            {
                "status": "AWAITING_DEPOSIT",
                "timestamp": lead.deposit_sent_at.isoformat(),
                "type": "entered",
            }
        )
    if lead.deposit_paid_at:
        status_history.append(
            {
                "status": "DEPOSIT_PAID",
                "timestamp": lead.deposit_paid_at.isoformat(),
                "type": "entered",
            }
        )
    if lead.booking_pending_at:
        status_history.append(
            {
                "status": "BOOKING_PENDING",
                "timestamp": lead.booking_pending_at.isoformat(),
                "type": "entered",
            }
        )
    if lead.booked_at:
        status_history.append(
            {"status": "BOOKED", "timestamp": lead.booked_at.isoformat(), "type": "entered"}
        )
    if lead.rejected_at:
        status_history.append(
            {"status": "REJECTED", "timestamp": lead.rejected_at.isoformat(), "type": "entered"}
        )
    if lead.needs_artist_reply_at:
        status_history.append(
            {
                "status": "NEEDS_ARTIST_REPLY",
                "timestamp": lead.needs_artist_reply_at.isoformat(),
                "type": "entered",
            }
        )
    if lead.needs_follow_up_at:
        status_history.append(
            {
                "status": "NEEDS_FOLLOW_UP",
                "timestamp": lead.needs_follow_up_at.isoformat(),
                "type": "entered",
            }
        )

    status_history.sort(key=lambda x: x["timestamp"])

    return {
        "lead": {
            "id": lead.id,
            "wa_from": lead.wa_from,
            "status": lead.status,
            "current_step": lead.current_step,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
            "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        },
        "handover_packet": packet,
        "answers": [
            {
                "id": a.id,
                "question_key": a.question_key,
                "answer_text": a.answer_text,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in answers
        ],
        "system_events": [
            {
                "id": e.id,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "level": e.level,
                "event_type": e.event_type,
                "payload": e.payload,
            }
            for e in events
        ],
        "processed_messages": [
            {
                "id": pm.id,
                "message_id": pm.message_id,
                "event_type": pm.event_type,
                "processed_at": pm.processed_at.isoformat() if pm.processed_at else None,
            }
            for pm in processed_messages
        ],
        "status_history": status_history,
        "parse_failures": lead.parse_failure_counts or {},
        "timestamps": {
            "last_client_message_at": lead.last_client_message_at.isoformat()
            if lead.last_client_message_at
            else None,
            "last_bot_message_at": lead.last_bot_message_at.isoformat()
            if lead.last_bot_message_at
            else None,
        },
    }


@router.post("/sweep-expired-deposits")
def sweep_expired_deposits(
    _auth: bool = Security(get_admin_auth),
    db: Session = Depends(get_db),
    hours_threshold: int = 24,
):
    """
    Sweep expired deposits - mark leads with expired deposit links as DEPOSIT_EXPIRED.

    This endpoint can be called by:
    - Cron jobs (Render Cron, external cron services)
    - Background workers
    - Manual admin action

    Args:
        hours_threshold: Hours after deposit_sent_at to mark as expired (default: 24)

    Returns:
        Summary of sweep operation
    """
    from datetime import UTC, datetime, timedelta

    from app.services.conversation import STATUS_AWAITING_DEPOSIT
    from app.services.system_event_service import info

    # Find leads in AWAITING_DEPOSIT status with deposit_sent_at older than threshold
    cutoff_time = datetime.now(UTC) - timedelta(hours=hours_threshold)

    expired_leads = (
        db.query(Lead)
        .filter(
            Lead.status == STATUS_AWAITING_DEPOSIT,
            Lead.deposit_sent_at.isnot(None),
            Lead.deposit_sent_at < cutoff_time,
            Lead.deposit_paid_at.is_(None),  # Not yet paid
        )
        .all()
    )

    results = {
        "checked": len(expired_leads),
        "expired": 0,
        "skipped": 0,
        "errors": 0,
        "lead_ids": [],
    }

    for lead in expired_leads:
        try:
            # Use existing function from reminders service
            from app.services.reminders import check_and_mark_deposit_expired

            result = check_and_mark_deposit_expired(db, lead, hours_threshold=hours_threshold)

            if result.get("status") == "expired":
                results["expired"] += 1
                results["lead_ids"].append(lead.id)

                # Log system event
                info(
                    db=db,
                    lead_id=lead.id,
                    event_type=EVENT_DEPOSIT_EXPIRED_SWEEP,
                    payload={
                        "lead_id": lead.id,
                        "deposit_sent_at": lead.deposit_sent_at.isoformat()
                        if lead.deposit_sent_at
                        else None,
                        "hours_threshold": hours_threshold,
                    },
                )
            else:
                results["skipped"] += 1
        except Exception as e:
            logger.error(f"Error marking lead {lead.id} as expired: {e}")
            results["errors"] += 1

    db.commit()

    logger.info(
        f"Deposit expiry sweep completed: {results['expired']} expired, "
        f"{results['skipped']} skipped, {results['errors']} errors"
    )

    return {
        "success": True,
        "summary": results,
        "hours_threshold": hours_threshold,
        "cutoff_time": cutoff_time.isoformat(),
    }
