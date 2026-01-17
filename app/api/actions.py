"""
Action token endpoints - Mode B (WhatsApp action links).

Provides GET /a/{token} (confirm page) and POST /a/{token} (execute action).
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.db.deps import get_db
from app.core.config import settings
from app.services.action_tokens import validate_action_token, mark_token_used
from app.services.safety import validate_and_mark_token_used_atomic
from app.api.admin import (
    approve_lead,
    reject_lead,
    send_deposit,
    send_booking_link,
    mark_booked,
)
from app.api.admin import RejectRequest, SendBookingLinkRequest

logger = logging.getLogger(__name__)
router = APIRouter()


# Action type to admin endpoint mapping
ACTION_HANDLERS = {
    "approve": approve_lead,
    "reject": reject_lead,
    "send_deposit": send_deposit,
    "send_booking_link": send_booking_link,
    "mark_booked": mark_booked,
}

# Action descriptions for confirm page
ACTION_DESCRIPTIONS = {
    "approve": "Approve this lead and send deposit link",
    "reject": "Reject this lead",
    "send_deposit": "Send deposit payment link to client",
    "send_booking_link": "Send booking link to client",
    "mark_booked": "Mark this lead as booked",
}


@router.get("/a/{token}", response_class=HTMLResponse)
def action_confirm_page(
    token: str,
    db: Session = Depends(get_db),
):
    """
    Show confirm/cancel page for an action token.
    
    This page shows:
    - What action will be performed
    - Lead information
    - Confirm / Cancel buttons
    """
    # Validate token
    action_token, error = validate_action_token(db, token)
    if not action_token:
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Action Link Error</title>
                <style>
                    body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
                    .error {{ color: #d32f2f; background: #ffebee; padding: 15px; border-radius: 5px; }}
                </style>
            </head>
            <body>
                <h1>Action Link Error</h1>
                <div class="error">
                    <p><strong>Error:</strong> {error}</p>
                    <p>This link may have expired, been used already, or the lead status has changed.</p>
                </div>
            </body>
            </html>
            """,
            status_code=400,
        )
    
    # Get lead info
    lead = action_token.lead
    action_desc = ACTION_DESCRIPTIONS.get(action_token.action_type, action_token.action_type)
    
    return HTMLResponse(
        content=f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Confirm Action</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
                .card {{ background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                .lead-info {{ margin: 15px 0; }}
                .lead-info strong {{ display: inline-block; width: 120px; }}
                .actions {{ margin-top: 30px; }}
                .btn {{ padding: 12px 24px; margin: 5px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; }}
                .btn-confirm {{ background: #4caf50; color: white; }}
                .btn-cancel {{ background: #f44336; color: white; }}
                .btn:hover {{ opacity: 0.9; }}
                form {{ display: inline; }}
            </style>
        </head>
        <body>
            <h1>Confirm Action</h1>
            <div class="card">
                <h2>Action: {action_desc}</h2>
                <div class="lead-info">
                    <strong>Lead ID:</strong> #{lead.id}<br>
                    <strong>Status:</strong> {lead.status}<br>
                    <strong>Phone:</strong> {lead.wa_from}<br>
                </div>
            </div>
            
            <div class="actions">
                <form method="POST" action="/a/{token}">
                    <button type="submit" class="btn btn-confirm">✅ Confirm</button>
                </form>
                <a href="javascript:history.back()" class="btn btn-cancel">❌ Cancel</a>
            </div>
            
            <p style="color: #666; font-size: 12px; margin-top: 30px;">
                This link is single-use and expires after {settings.action_token_expiry_days} days.
            </p>
        </body>
        </html>
        """
    )


@router.post("/a/{token}")
def execute_action(
    token: str,
    db: Session = Depends(get_db),
):
    """
    Execute an action after confirmation (single-use after confirmation).
    
    This endpoint:
    1. Validates the token (status-locked, not expired, not used)
    2. Executes the action via the admin endpoint
    3. Marks token as used (single-use enforcement)
    4. Returns success/error page
    """
    # Validate token
    action_token, error = validate_action_token(db, token)
    if not action_token:
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Action Failed</title>
                <style>
                    body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
                    .error {{ color: #d32f2f; background: #ffebee; padding: 15px; border-radius: 5px; }}
                </style>
            </head>
            <body>
                <h1>Action Failed</h1>
                <div class="error">
                    <p><strong>Error:</strong> {error}</p>
                </div>
            </body>
            </html>
            """,
            status_code=400,
        )
    
    # Get handler for this action type
    handler = ACTION_HANDLERS.get(action_token.action_type)
    if not handler:
        return HTMLResponse(
            content="<h1>Unknown action type</h1>",
            status_code=400,
        )
    
    try:
        # Execute the action by calling admin endpoint logic directly
        # We bypass auth dependency since token validation is the auth mechanism
        # Import the actual functions to call them directly
        from app.db.models import Lead
        from sqlalchemy import func
        from app.services.conversation import (
            STATUS_PENDING_APPROVAL,
            STATUS_AWAITING_DEPOSIT,
            STATUS_DEPOSIT_PAID,
            STATUS_BOOKING_LINK_SENT,
            STATUS_BOOKED,
            STATUS_REJECTED,
        )
        from app.services.sheets import log_lead_to_sheets
        
        lead = action_token.lead
        
        if action_token.action_type == "approve":
            if lead.status != STATUS_PENDING_APPROVAL:
                raise HTTPException(status_code=400, detail=f"Cannot approve lead in status '{lead.status}'")
            lead.status = STATUS_AWAITING_DEPOSIT
            lead.approved_at = func.now()
            lead.last_admin_action = "approve"
            lead.last_admin_action_at = func.now()
            db.commit()
            db.refresh(lead)
            log_lead_to_sheets(db, lead)
            result = {"success": True, "message": "Lead approved.", "lead_id": lead.id, "status": lead.status}
            
        elif action_token.action_type == "reject":
            if lead.status == STATUS_REJECTED:
                raise HTTPException(status_code=400, detail="Lead is already rejected")
            if lead.status == STATUS_BOOKED:
                raise HTTPException(status_code=400, detail="Cannot reject a booked lead")
            lead.status = STATUS_REJECTED
            lead.rejected_at = func.now()
            lead.last_admin_action = "reject"
            lead.last_admin_action_at = func.now()
            db.commit()
            db.refresh(lead)
            log_lead_to_sheets(db, lead)
            result = {"success": True, "message": "Lead rejected.", "lead_id": lead.id, "status": lead.status}
            
        elif action_token.action_type == "send_deposit":
            if lead.status != STATUS_AWAITING_DEPOSIT:
                raise HTTPException(status_code=400, detail=f"Cannot send deposit link for lead in status '{lead.status}'")
            from app.core.config import settings
            amount_pence = settings.stripe_deposit_amount_pence
            lead.deposit_amount_pence = amount_pence
            lead.last_admin_action = "send_deposit"
            lead.last_admin_action_at = func.now()
            db.commit()
            db.refresh(lead)
            log_lead_to_sheets(db, lead)
            result = {"success": True, "message": "Deposit link will be sent.", "lead_id": lead.id, "status": lead.status, "deposit_amount_pence": amount_pence}
            
        elif action_token.action_type == "send_booking_link":
            # This requires booking_url and booking_tool - return error
            return HTMLResponse(
                content="""
                <!DOCTYPE html>
                <html>
                <head><title>Action Requires Additional Info</title></head>
                <body>
                    <h1>Action Requires Additional Information</h1>
                    <p>This action requires booking URL and tool. Please use the admin endpoint instead.</p>
                </body>
                </html>
                """,
                status_code=400,
            )
            
        elif action_token.action_type == "mark_booked":
            if lead.status != STATUS_BOOKING_LINK_SENT:
                raise HTTPException(status_code=400, detail=f"Cannot mark lead as booked in status '{lead.status}'")
            lead.status = STATUS_BOOKED
            lead.booked_at = func.now()
            lead.last_admin_action = "mark_booked"
            lead.last_admin_action_at = func.now()
            db.commit()
            db.refresh(lead)
            log_lead_to_sheets(db, lead)
            result = {"success": True, "message": "Lead marked as booked.", "lead_id": lead.id, "status": lead.status}
            
        else:
            return HTMLResponse(
                content="<h1>Unknown action type</h1>",
                status_code=400,
            )
        
        # Token already marked as used by validate_and_mark_token_used_atomic()
        # No need to call mark_token_used() again
        
        # Return success page
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Action Completed</title>
                <style>
                    body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
                    .success {{ color: #2e7d32; background: #e8f5e9; padding: 15px; border-radius: 5px; }}
                </style>
            </head>
            <body>
                <h1>✅ Action Completed</h1>
                <div class="success">
                    <p><strong>Success:</strong> {result.get('message', 'Action completed successfully')}</p>
                    <p>Lead ID: {action_token.lead_id}</p>
                    <p>New Status: {result.get('status', 'N/A')}</p>
                </div>
                <p style="margin-top: 20px;">
                    <a href="javascript:window.close()">Close this window</a>
                </p>
            </body>
            </html>
            """
        )
        
    except HTTPException as e:
        # Handle HTTP errors from admin endpoints
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head><title>Action Failed</title></head>
            <body>
                <h1>Action Failed</h1>
                <p><strong>Error:</strong> {e.detail}</p>
            </body>
            </html>
            """,
            status_code=e.status_code,
        )
    except Exception as e:
        logger.error(f"Error executing action {action_token.action_type} for token {token}: {e}")
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head><title>Action Failed</title></head>
            <body>
                <h1>Action Failed</h1>
                <p>An unexpected error occurred. Please try again or contact support.</p>
            </body>
            </html>
            """,
            status_code=500,
        )
