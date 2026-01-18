"""
Demo endpoints for local testing and demonstrations.

These endpoints are only available when DEMO_MODE=true.
In production (DEMO_MODE=false), all endpoints return 404.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.deps import get_db
from app.db.models import Lead
from app.services.action_tokens import generate_action_tokens_for_lead
from app.services.conversation import get_lead_summary, handle_inbound_message
from app.services.leads import get_or_create_lead

logger = logging.getLogger(__name__)

router = APIRouter()


def require_demo_mode():
    """
    Dependency that enforces DEMO_MODE must be enabled.
    
    Raises:
        HTTPException: 404 if DEMO_MODE is False
    """
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Not found")


class DemoClientSendRequest(BaseModel):
    """Request body for demo client send endpoint."""
    from_number: str
    text: str


class DemoStripePayRequest(BaseModel):
    """Request body for demo Stripe payment endpoint."""
    lead_id: Optional[int] = None
    checkout_session_id: Optional[str] = None


@router.post("/client/send")
async def demo_client_send(
    request: DemoClientSendRequest,
    db: Session = Depends(get_db),
    demo_mode: bool = Depends(require_demo_mode),
):
    """
    Demo client send message endpoint.
    Routes messages into the same conversation handler used by WhatsApp webhook.
    
    In demo mode, external integrations are automatically mocked/disabled.
    """
    # Normalize phone number (remove + and spaces)
    wa_from = request.from_number.replace("+", "").replace(" ", "").strip()
    
    if not wa_from:
        raise HTTPException(status_code=400, detail="from_number is required")
    
    try:
        # Get or create lead (same as WhatsApp webhook)
        lead = get_or_create_lead(db, wa_from=wa_from)
        
        # Handle conversation flow (same as WhatsApp webhook)
        # In demo mode, whatsapp_dry_run is always True (logs only)
        conversation_result = await handle_inbound_message(
            db=db,
            lead=lead,
            message_text=request.text,
            dry_run=True,  # Always dry-run in demo mode
        )
        
        db.refresh(lead)
        
        return {
            "received": True,
            "lead_id": lead.id,
            "wa_from": wa_from,
            "text": request.text,
            "conversation": conversation_result,
            "lead_status": lead.status,
        }
    except Exception as e:
        logger.error(
            f"Demo client send failed - from={wa_from}, error_type={type(e).__name__}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Error processing message: {str(e)}")


@router.get("/artist/inbox")
async def demo_artist_inbox(
    db: Session = Depends(get_db),
    demo_mode: bool = Depends(require_demo_mode),
):
    """
    Demo artist inbox endpoint.
    Returns list of leads ordered by updated_at desc, with Phase 1 summary + action links.
    """
    # Get all leads ordered by most recently updated first
    stmt = select(Lead).order_by(desc(Lead.updated_at)).limit(50)
    leads = db.execute(stmt).scalars().all()
    
    inbox_items = []
    
    for lead in leads:
        # Get lead summary
        summary = get_lead_summary(db, lead.id)
        
        # Generate action links based on current status
        action_tokens = generate_action_tokens_for_lead(db, lead.id, lead.status)
        
        # Build inbox item
        item = {
            "lead_id": lead.id,
            "wa_from": lead.wa_from,
            "status": lead.status,
            "last_message_at": lead.last_client_message_at.isoformat() if lead.last_client_message_at else None,
            "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
            "summary": summary.get("summary_text") if summary else None,
            "answers": summary.get("answers", {}) if summary else {},
            "action_links": action_tokens,
        }
        inbox_items.append(item)
    
    return {
        "leads": inbox_items,
        "count": len(inbox_items),
    }


@router.post("/stripe/pay")
async def demo_stripe_pay(
    request: DemoStripePayRequest,
    db: Session = Depends(get_db),
    demo_mode: bool = Depends(require_demo_mode),
):
    """
    Optional: Simulate Stripe webhook success for a given lead_id or checkout_session_id.
    Useful for testing payment flow in demo mode.
    """
    lead = None
    
    if request.lead_id:
        lead = db.get(Lead, request.lead_id)
    elif request.checkout_session_id:
        stmt = select(Lead).where(Lead.stripe_checkout_session_id == request.checkout_session_id)
        lead = db.execute(stmt).scalar_one_or_none()
    else:
        raise HTTPException(
            status_code=400, detail="Either lead_id or checkout_session_id is required"
        )
    
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Import stripe webhook handler logic (simplified for demo)
    from app.services.safety import check_and_record_processed_event
    from app.services.conversation import STATUS_AWAITING_DEPOSIT, STATUS_BOOKING_PENDING
    from sqlalchemy import func
    
    # Check idempotency (simulate event ID)
    event_id = f"evt_demo_{lead.id}"
    is_duplicate, _ = check_and_record_processed_event(
        db=db,
        event_id=event_id,
        event_type="stripe.checkout.session.completed",
        lead_id=lead.id,
    )
    
    if is_duplicate:
        return {
            "received": True,
            "type": "duplicate",
            "lead_id": lead.id,
            "message": "Payment already processed",
        }
    
    # Update lead status (same as real Stripe webhook)
    from app.services.safety import update_lead_status_if_matches
    
    success, lead = update_lead_status_if_matches(
        db=db,
        lead_id=lead.id,
        expected_status=STATUS_AWAITING_DEPOSIT,
        new_status=STATUS_BOOKING_PENDING,
        stripe_payment_status="paid",
        deposit_paid_at=func.now(),
    )
    
    if not success:
        db.refresh(lead)
        if lead.status == "BOOKING_PENDING":
            return {
                "received": True,
                "type": "duplicate",
                "lead_id": lead.id,
                "message": "Lead already in BOOKING_PENDING status",
            }
        raise HTTPException(
            status_code=400,
            detail=f"Lead {lead.id} is in status '{lead.status}', expected '{STATUS_AWAITING_DEPOSIT}'",
        )
    
    db.commit()
    db.refresh(lead)
    
    return {
        "received": True,
        "type": "checkout.session.completed",
        "lead_id": lead.id,
        "status": lead.status,
        "message": "Payment simulated successfully",
    }


@router.get("/client", response_class=HTMLResponse)
async def demo_client_page_html(demo_mode: bool = Depends(require_demo_mode)):
    """
    Demo client HTML page - simple form to send messages.
    """
    html = """
<!DOCTYPE html>
<html>
<head>
    <title>Demo Client - Tattoo Booking Bot</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; font-weight: bold; }
        input[type="text"], textarea { width: 100%; padding: 8px; box-sizing: border-box; }
        button { background: #007bff; color: white; padding: 10px 20px; border: none; cursor: pointer; }
        button:hover { background: #0056b3; }
        .response { margin-top: 20px; padding: 15px; background: #f0f0f0; border-radius: 5px; }
        .error { background: #ffe6e6; color: #cc0000; }
        .success { background: #e6ffe6; color: #006600; }
        #messages { margin-top: 20px; }
        .message { padding: 10px; margin: 5px 0; border-radius: 5px; }
        .bot-message { background: #e3f2fd; margin-left: 20px; }
        .client-message { background: #fff3e0; margin-right: 20px; }
    </style>
</head>
<body>
    <h1>Demo Client - Send Messages</h1>
    
    <form id="sendForm">
        <div class="form-group">
            <label for="from_number">Phone Number (e.g., +441234567890):</label>
            <input type="text" id="from_number" name="from_number" value="+441234567890" required>
        </div>
        
        <div class="form-group">
            <label for="text">Message:</label>
            <textarea id="text" name="text" rows="3" placeholder="Type your message here..." required></textarea>
        </div>
        
        <button type="submit">Send Message</button>
    </form>
    
    <div id="response" class="response" style="display:none;"></div>
    
    <div id="messages">
        <h3>Conversation:</h3>
        <div id="messageList"></div>
    </div>
    
    <script>
        const form = document.getElementById('sendForm');
        const responseDiv = document.getElementById('response');
        const messageList = document.getElementById('messageList');
        
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const fromNumber = document.getElementById('from_number').value;
            const text = document.getElementById('text').value;
            
            try {
                const response = await fetch('/demo/client/send', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ from_number: fromNumber, text: text })
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    responseDiv.className = 'response success';
                    responseDiv.style.display = 'block';
                    responseDiv.innerHTML = `<strong>Success!</strong><br>
                        Status: ${data.lead_status}<br>
                        Lead ID: ${data.lead_id}<br>
                        Bot Response: ${data.conversation?.message || 'No response'}`;
                    
                    // Add messages to conversation
                    const clientMsg = document.createElement('div');
                    clientMsg.className = 'message client-message';
                    clientMsg.textContent = `You: ${text}`;
                    messageList.appendChild(clientMsg);
                    
                    if (data.conversation?.message) {
                        const botMsg = document.createElement('div');
                        botMsg.className = 'message bot-message';
                        botMsg.textContent = `Bot: ${data.conversation.message}`;
                        messageList.appendChild(botMsg);
                    }
                    
                    document.getElementById('text').value = '';
                } else {
                    responseDiv.className = 'response error';
                    responseDiv.style.display = 'block';
                    responseDiv.textContent = `Error: ${data.detail || 'Unknown error'}`;
                }
            } catch (error) {
                responseDiv.className = 'response error';
                responseDiv.style.display = 'block';
                responseDiv.textContent = `Error: ${error.message}`;
            }
        });
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html)


@router.get("/artist", response_class=HTMLResponse)
async def demo_artist_page_html(
    db: Session = Depends(get_db),
    demo_mode: bool = Depends(require_demo_mode),
):
    """
    Demo artist HTML page - inbox with leads and action buttons.
    """
    # Get inbox data
    inbox_response = await demo_artist_inbox(db=db, demo_mode=True)
    leads = inbox_response["leads"]
    
    # Build HTML table
    leads_html = ""
    for lead in leads:
        summary_text = lead.get("summary", "No summary available") or "No summary available"
        summary_short = summary_text[:200] + "..." if len(summary_text) > 200 else summary_text
        
        action_buttons = ""
        for action_type, action_url in lead.get("action_links", {}).items():
            action_label = action_type.replace("_", " ").title()
            action_buttons += f'<a href="{action_url}" class="btn">{action_label}</a> '
        
        leads_html += f"""
        <tr>
            <td>{lead['lead_id']}</td>
            <td>{lead['wa_from']}</td>
            <td>{lead['status']}</td>
            <td>{lead['last_message_at'] or 'N/A'}</td>
            <td><small>{summary_short}</small></td>
            <td>{action_buttons or '<em>No actions available</em>'}</td>
        </tr>
        """
    
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Demo Artist Inbox - Tattoo Booking Bot</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 1200px; margin: 20px auto; padding: 20px; }}
        h1 {{ color: #333; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #007bff; color: white; }}
        tr:hover {{ background: #f5f5f5; }}
        .btn {{ display: inline-block; padding: 5px 10px; margin: 2px; background: #28a745; color: white; text-decoration: none; border-radius: 3px; font-size: 12px; }}
        .btn:hover {{ background: #218838; }}
        #refresh {{
            margin-bottom: 20px;
            padding: 10px 20px;
            background: #007bff;
            color: white;
            border: none;
            cursor: pointer;
            border-radius: 5px;
        }}
        #refresh:hover {{ background: #0056b3; }}
        .status-pending {{ color: #ff9800; font-weight: bold; }}
        .status-qualifying {{ color: #2196f3; font-weight: bold; }}
        .status-booked {{ color: #4caf50; font-weight: bold; }}
    </style>
</head>
<body>
    <h1>Demo Artist Inbox</h1>
    <button id="refresh" onclick="location.reload()">Refresh Inbox</button>
    
    <table>
        <thead>
            <tr>
                <th>Lead ID</th>
                <th>Phone</th>
                <th>Status</th>
                <th>Last Message</th>
                <th>Summary</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {leads_html if leads_html else '<tr><td colspan="6"><em>No leads found</em></td></tr>'}
        </tbody>
    </table>
    
    <script>
        // Auto-refresh every 30 seconds
        setTimeout(() => location.reload(), 30000);
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html)

