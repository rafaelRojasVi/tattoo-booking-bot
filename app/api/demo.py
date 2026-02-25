"""
Demo endpoints for local testing and demonstrations.

These endpoints are only available when DEMO_MODE=true.
In production (DEMO_MODE=false), all endpoints return 404.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.constants.event_types import EVENT_STRIPE_CHECKOUT_SESSION_COMPLETED
from app.api.dependencies import get_lead_or_404
from app.core.config import settings
from app.db.deps import get_db
from app.db.helpers import commit_and_refresh
from app.db.models import Lead, LeadAnswer
from app.services.action_tokens import generate_action_tokens_for_lead
from app.services.conversation import get_lead_summary, handle_inbound_message
from app.services.leads import get_or_create_lead
from app.services.conversation.questions import CONSULTATION_QUESTIONS, get_question_by_index
from app.utils.datetime_utils import iso_or_none

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


def _build_demo_messages(db: Session, lead: Lead) -> list[dict]:
    """Build conversation history for demo: bot questions + client answers interleaved."""
    question_by_key = {q.key: q.text for q in CONSULTATION_QUESTIONS}
    stmt = (
        select(LeadAnswer)
        .where(LeadAnswer.lead_id == lead.id)
        .order_by(LeadAnswer.created_at.asc())
    )
    answers = list(db.execute(stmt).scalars().all())
    messages = []
    for a in answers:
        q_text = question_by_key.get(a.question_key, a.question_key)
        messages.append({"role": "bot", "text": q_text})
        messages.append({"role": "client", "text": a.answer_text})
    # If there is a "next" question (current step not yet answered), add it as last bot message
    if lead.current_step is not None:
        next_q = get_question_by_index(lead.current_step)
        if next_q and (not answers or answers[-1].question_key != next_q.key):
            messages.append({"role": "bot", "text": next_q.text})
    return messages


class DemoClientSendRequest(BaseModel):
    """Request body for demo client send endpoint."""

    from_number: str
    text: str
    # Optional: simulate reference image (e.g. paste URL or "yes" with link)
    image_url: str | None = None


class DemoStripePayRequest(BaseModel):
    """Request body for demo Stripe payment endpoint."""

    lead_id: int | None = None
    checkout_session_id: str | None = None


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

    # If image_url provided (demo reference image), append to text so flow accepts it
    message_text = request.text.strip()
    if request.image_url and request.image_url.strip():
        message_text = message_text or f"[Reference image: {request.image_url.strip()}]"

    if not message_text:
        raise HTTPException(status_code=400, detail="text or image_url is required")

    try:
        # Get or create lead (same as WhatsApp webhook)
        lead = get_or_create_lead(db, wa_from=wa_from)

        # Handle conversation flow (same as WhatsApp webhook)
        # In demo mode, whatsapp_dry_run is always True (logs only)
        conversation_result = await handle_inbound_message(
            db=db,
            lead=lead,
            message_text=message_text,
            dry_run=True,  # Always dry-run in demo mode
        )

        db.refresh(lead)

        # Include conversation history for client demo UI
        messages = _build_demo_messages(db, lead)

        return {
            "received": True,
            "lead_id": lead.id,
            "wa_from": wa_from,
            "text": message_text,
            "conversation": conversation_result,
            "lead_status": lead.status,
            "messages": messages,
        }
    except Exception as e:
        logger.error(
            f"Demo client send failed - from={wa_from}, error_type={type(e).__name__}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Error processing message: {str(e)}") from e


@router.get("/lead/{lead_id}/messages")
async def demo_lead_messages(
    lead: Lead = Depends(get_lead_or_404),
    db: Session = Depends(get_db),
    demo_mode: bool = Depends(require_demo_mode),
):
    """
    Get conversation history for a lead (for demo client UI).
    Returns bot questions + client answers interleaved.
    """
    messages = _build_demo_messages(db, lead)
    return {
        "lead_id": lead.id,
        "wa_from": lead.wa_from,
        "status": lead.status,
        "current_step": lead.current_step,
        "messages": messages,
    }


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
            "last_message_at": iso_or_none(lead.last_client_message_at),
            "updated_at": iso_or_none(lead.updated_at),
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
    from sqlalchemy import func

    from app.services.conversation import STATUS_AWAITING_DEPOSIT, STATUS_BOOKING_PENDING
    from app.services.safety import check_and_record_processed_event

    # Check idempotency (simulate event ID)
    event_id = f"evt_demo_{lead.id}"
    is_duplicate, _ = check_and_record_processed_event(
        db=db,
        event_id=event_id,
        event_type=EVENT_STRIPE_CHECKOUT_SESSION_COMPLETED,
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
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead not found")
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

    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    commit_and_refresh(db, lead)

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
    Demo client HTML page - chat-style form to send messages, full conversation history.
    Supports optional reference image URL for the reference_images question.
    """
    html = """
<!DOCTYPE html>
<html>
<head>
    <title>Demo Client - Tattoo Booking Bot</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 560px; margin: 0 auto; padding: 16px; background: #f5f5f5; }
        h1 { font-size: 1.25rem; color: #333; margin-bottom: 8px; }
        .status-bar { font-size: 0.85rem; color: #666; margin-bottom: 12px; }
        #messages { background: #fff; border-radius: 12px; padding: 12px; min-height: 200px; max-height: 50vh; overflow-y: auto; margin-bottom: 12px; box-shadow: 0 1px 2px rgba(0,0,0,0.06); }
        .message { padding: 10px 12px; margin: 6px 0; border-radius: 12px; max-width: 85%; white-space: pre-wrap; word-break: break-word; }
        .bot-message { background: #e3f2fd; margin-right: auto; border-bottom-left-radius: 4px; }
        .client-message { background: #dcf8c6; margin-left: auto; border-bottom-right-radius: 4px; }
        .message .role { font-size: 0.7rem; color: #666; margin-bottom: 2px; }
        .form-group { margin-bottom: 10px; }
        label { display: block; font-size: 0.85rem; font-weight: 600; color: #333; margin-bottom: 4px; }
        input[type="text"], textarea { width: 100%; padding: 10px 12px; box-sizing: border-box; border: 1px solid #ddd; border-radius: 8px; font-size: 1rem; }
        textarea { resize: vertical; min-height: 60px; }
        .hint { font-size: 0.75rem; color: #888; margin-top: 2px; }
        button { background: #25D366; color: #fff; padding: 12px 20px; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; width: 100%; }
        button:hover { background: #20bd5a; }
        .response { margin-top: 12px; padding: 12px; border-radius: 8px; font-size: 0.9rem; }
        .error { background: #ffebee; color: #c62828; }
        .success { background: #e8f5e9; color: #2e7d32; }
    </style>
</head>
<body>
    <h1>Demo — Client chat</h1>
    <div class="status-bar" id="statusBar">Use the same phone number to continue a conversation. Status will update after each message.</div>
    
    <div id="messages">
        <div id="messageList"></div>
    </div>
    <div class="form-group" style="margin-bottom: 12px;">
        <label for="loadLeadId">Load conversation (after refresh)</label>
        <div style="display: flex; gap: 8px;">
            <input type="number" id="loadLeadId" placeholder="Lead ID" style="flex: 1;">
            <button type="button" id="loadBtn" style="width: auto;">Load</button>
        </div>
    </div>
    
    <form id="sendForm">
        <div class="form-group">
            <label for="from_number">Your number (e.g. +441234567890)</label>
            <input type="text" id="from_number" name="from_number" value="+441234567890" required>
        </div>
        <div class="form-group">
            <label for="text">Message</label>
            <textarea id="text" name="text" rows="2" placeholder="Type your message..."></textarea>
            <div class="hint">For &quot;reference images&quot; you can type &quot;no&quot; or paste an IG/image URL here, or use the field below.</div>
        </div>
        <div class="form-group">
            <label for="image_url">Reference image URL (optional)</label>
            <input type="text" id="image_url" name="image_url" placeholder="https://... (simulates sending an image)">
        </div>
        <button type="submit">Send</button>
    </form>
    
    <div id="response" class="response" style="display:none;"></div>
    
    <script>
        const form = document.getElementById('sendForm');
        const responseDiv = document.getElementById('response');
        const messageList = document.getElementById('messageList');
        const statusBar = document.getElementById('statusBar');
        
        function renderMessages(messages) {
            messageList.innerHTML = '';
            if (!messages || messages.length === 0) return;
            messages.forEach(function(m) {
                const div = document.createElement('div');
                div.className = 'message ' + (m.role === 'bot' ? 'bot-message' : 'client-message');
                const role = m.role === 'bot' ? 'Bot' : 'You';
                div.innerHTML = '<span class="role">' + role + '</span><br>' + (m.text || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                messageList.appendChild(div);
            });
            messageList.parentElement.scrollTop = messageList.parentElement.scrollHeight;
        }
        
        document.getElementById('loadBtn').addEventListener('click', async function() {
            const leadId = document.getElementById('loadLeadId').value.trim();
            if (!leadId) return;
            try {
                const r = await fetch('/demo/lead/' + leadId + '/messages');
                const d = await r.json();
                if (r.ok && d.messages) {
                    renderMessages(d.messages);
                    statusBar.textContent = 'Status: ' + d.status + ' — Lead #' + d.lead_id;
                } else {
                    responseDiv.className = 'response error';
                    responseDiv.style.display = 'block';
                    responseDiv.textContent = 'Could not load (invalid Lead ID or no messages).';
                }
            } catch (err) {
                responseDiv.className = 'response error';
                responseDiv.style.display = 'block';
                responseDiv.textContent = 'Error: ' + err.message;
            }
        });
        
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const fromNumber = document.getElementById('from_number').value.trim();
            const text = document.getElementById('text').value.trim();
            const imageUrl = document.getElementById('image_url').value.trim();
            if (!text && !imageUrl) {
                responseDiv.className = 'response error';
                responseDiv.style.display = 'block';
                responseDiv.textContent = 'Enter a message or a reference image URL.';
                return;
            }
            try {
                const body = { from_number: fromNumber, text: text || ' ' };
                if (imageUrl) body.image_url = imageUrl;
                const response = await fetch('/demo/client/send', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                const data = await response.json();
                if (response.ok) {
                    responseDiv.className = 'response success';
                    responseDiv.style.display = 'block';
                    responseDiv.innerHTML = 'Status: <strong>' + data.lead_status + '</strong> &middot; Lead #' + data.lead_id;
                    if (data.messages && data.messages.length) renderMessages(data.messages);
                    document.getElementById('text').value = '';
                    document.getElementById('image_url').value = '';
                    document.getElementById('loadLeadId').value = data.lead_id;
                    statusBar.textContent = 'Status: ' + data.lead_status + ' — Lead #' + data.lead_id;
                } else {
                    responseDiv.className = 'response error';
                    responseDiv.style.display = 'block';
                    responseDiv.textContent = 'Error: ' + (data.detail && (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) || 'Unknown');
                }
            } catch (err) {
                responseDiv.className = 'response error';
                responseDiv.style.display = 'block';
                responseDiv.textContent = 'Error: ' + err.message;
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
            <td>{lead["lead_id"]}</td>
            <td>{lead["wa_from"]}</td>
            <td>{lead["status"]}</td>
            <td>{lead["last_message_at"] or "N/A"}</td>
            <td><small>{summary_short}</small></td>
            <td>{action_buttons or "<em>No actions available</em>"}</td>
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
