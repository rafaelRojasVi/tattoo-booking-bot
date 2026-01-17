from fastapi import APIRouter, Depends, HTTPException, Security
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from typing import Optional

from app.db.deps import get_db
from app.db.models import Lead
from app.services.conversation import (
    get_lead_summary,
    STATUS_PENDING_APPROVAL,
    STATUS_AWAITING_DEPOSIT,
    STATUS_DEPOSIT_PAID,
    STATUS_BOOKING_LINK_SENT,
    STATUS_BOOKED,
    STATUS_REJECTED,
)
from app.api.auth import get_admin_auth
from app.services.sheets import log_lead_to_sheets
from app.services.messaging import send_whatsapp_message, format_deposit_link_message
from app.services.safety import update_lead_status_if_matches

router = APIRouter()


# Request models
class RejectRequest(BaseModel):
    reason: Optional[str] = None


class SendDepositRequest(BaseModel):
    amount_pence: Optional[int] = None  # Optional override, defaults to tier calculation


class SendBookingLinkRequest(BaseModel):
    booking_url: str
    booking_tool: str = "FRESHA"  # FRESHA, CALENDLY, GCAL, OTHER


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


@router.get("/leads")
def list_leads(
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    leads = db.execute(select(Lead).order_by(Lead.created_at.desc())).scalars().all()
    return [
        {
            "id": l.id,
            "wa_from": l.wa_from,
            "status": l.status,
            "current_step": l.current_step,
            "created_at": l.created_at,
        }
        for l in leads
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
def approve_lead(
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
            detail=f"Cannot approve lead in status '{lead.status}'. Lead must be in '{STATUS_PENDING_APPROVAL}'."
        )
    
    log_lead_to_sheets(db, lead)
    
    
    return {
        "success": True,
        "message": "Lead approved. Deposit link will be sent (not yet implemented).",
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
def send_deposit(
    lead_id: int,
    request: Optional[SendDepositRequest] = None,
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
            detail=f"Cannot send deposit link for lead in status '{lead.status}'. Lead must be in '{STATUS_AWAITING_DEPOSIT}'."
        )
    
    # Calculate deposit amount (if not provided)
    amount_pence = request.amount_pence if request and request.amount_pence else None
    if not amount_pence:
        # For now, use default
        from app.core.config import settings
        amount_pence = settings.stripe_deposit_amount_pence
    
    lead.deposit_amount_pence = amount_pence
    lead.last_admin_action = "send_deposit"
    lead.last_admin_action_at = func.now()
    db.commit()
    db.refresh(lead)
    
    # Create Stripe checkout session
    from app.services.stripe_service import create_checkout_session
    from app.core.config import settings
    
    checkout_result = create_checkout_session(
        lead_id=lead.id,
        amount_pence=amount_pence,
        success_url=settings.stripe_success_url,
        cancel_url=settings.stripe_cancel_url,
        metadata={
            "wa_from": lead.wa_from,
            "status": lead.status,
        },
    )
    
    # Store checkout session ID
    lead.stripe_checkout_session_id = checkout_result["checkout_session_id"]
    db.commit()
    db.refresh(lead)
    
    log_lead_to_sheets(db, lead)
    
    # Send WhatsApp message with deposit link (with 24h window check)
    from app.services.whatsapp_window import send_with_window_check
    deposit_message = format_deposit_link_message(
        checkout_result["checkout_url"],
        amount_pence
    )
    
    # Send message (async function in sync context)
    import asyncio
    try:
        asyncio.run(send_with_window_check(
            db=db,
            lead=lead,
            message=deposit_message,
            template_name="deposit_link",  # Template if window closed
            dry_run=settings.whatsapp_dry_run,
        ))
    except RuntimeError:
        # Event loop already running, use different approach
        import nest_asyncio
        try:
            nest_asyncio.apply()
            asyncio.run(send_whatsapp_message(
                to=lead.wa_from,
                message=deposit_message,
                dry_run=settings.whatsapp_dry_run,
            ))
        except ImportError:
            # Fallback: create new event loop in thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, send_whatsapp_message(
                    to=lead.wa_from,
                    message=deposit_message,
                    dry_run=settings.whatsapp_dry_run,
                ))
                future.result()
    
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
            detail=f"Cannot send booking link for lead in status '{lead.status}'. Lead must be in '{STATUS_DEPOSIT_PAID}'."
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
    Mark lead as booked - transitions from BOOKING_LINK_SENT to BOOKED.
    Status-locked: only works from BOOKING_LINK_SENT.
    """
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Atomic status-locked update (prevents race conditions)
    # BOOKED can only be set manually - no external events can set this
    success, lead = update_lead_status_if_matches(
        db=db,
        lead_id=lead_id,
        expected_status=STATUS_BOOKING_LINK_SENT,
        new_status=STATUS_BOOKED,
        booked_at=func.now(),
        last_admin_action="mark_booked",
        last_admin_action_at=func.now(),
    )
    
    if not success:
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        raise HTTPException(
            status_code=400,
            detail=f"Cannot mark lead as booked in status '{lead.status}'. Lead must be in '{STATUS_BOOKING_LINK_SENT}'."
        )
    
    log_lead_to_sheets(db, lead)
    
    
    return {
        "success": True,
        "message": "Lead marked as booked.",
        "lead_id": lead.id,
        "status": lead.status,
    }
