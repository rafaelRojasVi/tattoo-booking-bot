from fastapi import APIRouter, Request, Response, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.config import settings
from app.db.deps import get_db
from app.db.models import ProcessedMessage, Lead
from app.services.leads import get_or_create_lead
from app.services.conversation import (
    handle_inbound_message,
    STATUS_DEPOSIT_PAID,
    STATUS_AWAITING_DEPOSIT,
)
from app.services.stripe_service import verify_webhook_signature
from app.services.sheets import log_lead_to_sheets
from app.services.messaging import send_whatsapp_message, format_payment_confirmation_message
from app.services.safety import check_and_record_processed_event, update_lead_status_if_matches
from sqlalchemy import func
import asyncio
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/whatsapp")
def whatsapp_verify(
    hub_mode: str | None = None,
    hub_verify_token: str | None = None,
    hub_challenge: str | None = None,
):
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return Response(content=hub_challenge or "", media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp")
async def whatsapp_inbound(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception as e:
        # Invalid JSON payload
        return JSONResponse(
            status_code=400,
            content={"received": False, "error": "Invalid JSON payload"}
        )

    # Try to extract sender ("from") and message body
    wa_from = None
    text = None
    message_type = None

    try:
        entry = payload.get("entry", [])
        if not entry:
            return {"received": True, "type": "empty-entry"}
        
        change = entry[0].get("changes", [])
        if not change:
            return {"received": True, "type": "empty-changes"}
        
        value = change[0].get("value", {})

        messages = value.get("messages", [])
        message_id = None
        if messages:
            # WhatsApp can send multiple messages in one payload - process most recent first
            # Sort by timestamp if available, otherwise use first message
            # WhatsApp messages have 'timestamp' field (Unix timestamp)
            if len(messages) > 1:
                # Sort by timestamp (most recent first)
                messages = sorted(
                    messages,
                    key=lambda m: m.get("timestamp", 0),
                    reverse=True
                )
                logger.info(f"Received {len(messages)} messages in one payload, processing most recent first")
            
            message = messages[0]  # Process most recent message
            message_id = message.get("id")  # WhatsApp message ID for idempotency
            wa_from = message.get("from")
            message_type = message.get("type", "text")  # Default to text if not specified
            
            # Extract text from different message types
            if message_type == "text":
                text = (message.get("text") or {}).get("body")
            elif message_type in ["image", "video", "audio", "document"]:
                # Media messages - extract caption if available
                text = message.get("caption") or f"[{message_type} message]"
            elif message_type == "location":
                location = message.get("location", {})
                text = f"[Location: {location.get('latitude')}, {location.get('longitude')}]"
            else:
                text = f"[{message_type} message]"
    except (KeyError, IndexError, TypeError) as e:
        # Malformed payload structure
        return {"received": True, "type": "malformed-payload", "error": str(e)}

    # If it's not a message event, just ack (delivery receipts etc.)
    # But check for empty string specifically (which is invalid)
    if wa_from == "":
        return JSONResponse(
            status_code=400,
            content={"received": False, "error": "Invalid phone number format"}
        )
    
    if not wa_from:
        return {"received": True, "type": "non-message-event"}

    # Validate phone number format (basic check)
    if not isinstance(wa_from, str) or len(wa_from.strip()) < 10:
        return JSONResponse(
            status_code=400,
            content={"received": False, "error": "Invalid phone number format"}
        )

    # Idempotency check: if we have a message_id, check if we've already processed it
    if message_id:
        stmt = select(ProcessedMessage).where(ProcessedMessage.message_id == message_id)
        existing = db.execute(stmt).scalar_one_or_none()
        if existing:
            # Already processed - return success without reprocessing
            return {
                "received": True,
                "type": "duplicate",
                "message_id": message_id,
                "processed_at": existing.processed_at.isoformat() if existing.processed_at else None,
            }

    try:
        lead = get_or_create_lead(db, wa_from=wa_from)
    except Exception as e:
        # Database error
        return JSONResponse(
            status_code=500,
            content={"received": False, "error": "Database error", "detail": str(e)}
        )

    # Handle the conversation flow (only if we have text to process)
    if text:
        try:
            # Check message timestamp to prevent processing out-of-order messages
            # If message is older than last_client_message_at, ignore it (already processed)
            message_timestamp = None
            if messages and messages[0].get("timestamp"):
                from datetime import datetime, timezone
                message_timestamp = datetime.fromtimestamp(
                    int(messages[0]["timestamp"]),
                    tz=timezone.utc
                )
                
                if lead.last_client_message_at:
                    last_message_time = lead.last_client_message_at
                    if last_message_time.tzinfo is None:
                        last_message_time = last_message_time.replace(tzinfo=timezone.utc)
                    
                    # If this message is older than last processed message, skip it
                    if message_timestamp < last_message_time:
                        logger.info(
                            f"Ignoring out-of-order message {message_id} for lead {lead.id}. "
                            f"Message timestamp: {message_timestamp}, Last message: {last_message_time}"
                        )
                        return {
                            "received": True,
                            "type": "out_of_order",
                            "message_id": message_id,
                            "lead_id": lead.id,
                            "reason": "Message timestamp is older than last processed message",
                        }
            
            # Use dry_run setting from config (defaults to True)
            conversation_result = await handle_inbound_message(
                db=db,
                lead=lead,
                message_text=text,
                dry_run=settings.whatsapp_dry_run,
            )
            
            # Mark message as processed (idempotency)
            if message_id:
                processed = ProcessedMessage(
                    message_id=message_id,
                    event_type="whatsapp.message",
                    lead_id=lead.id,
                )
                db.add(processed)
                db.commit()
            
            return {
                "received": True,
                "lead_id": lead.id,
                "wa_from": wa_from,
                "text": text,
                "message_type": message_type,
                "conversation": conversation_result,
            }
        except Exception as e:
            # Log error but don't fail the webhook
            return {
                "received": True,
                "lead_id": lead.id,
                "wa_from": wa_from,
                "text": text,
                "message_type": message_type,
                "error": f"Conversation handling failed: {str(e)}",
            }
    
    # If no text (e.g., just an image without caption), just acknowledge
    return {
        "received": True,
        "lead_id": lead.id,
        "wa_from": wa_from,
        "text": text,
        "message_type": message_type,
    }


@router.post("/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Handle Stripe webhook events (payment confirmations).
    
    Handles:
    - checkout.session.completed: Deposit payment confirmed
    """
    # Get raw body for signature verification
    body = await request.body()
    signature = request.headers.get("stripe-signature")
    
    if not signature:
        return JSONResponse(
            status_code=400,
            content={"error": "Missing stripe-signature header"}
        )
    
    try:
        # Verify webhook signature
        event = verify_webhook_signature(body, signature)
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid webhook signature: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Webhook verification failed: {str(e)}"}
        )
    
    # Handle the event
    event_type = event["type"]
    event_data = event["data"]["object"]
    
    # Idempotency: Stripe sends idempotency key in event id
    event_id = event.get("id")
    
    if event_type == "checkout.session.completed":
        # Payment confirmed - update lead status
        checkout_session_id = event_data.get("id")
        client_reference_id = event_data.get("client_reference_id")  # Contains lead_id
        metadata = event_data.get("metadata", {})
        
        # Get lead_id from metadata or client_reference_id
        lead_id = None
        if metadata and "lead_id" in metadata:
            lead_id = int(metadata["lead_id"])
        elif client_reference_id:
            lead_id = int(client_reference_id)
        
        if not lead_id:
            return JSONResponse(
                status_code=400,
                content={"error": "No lead_id found in checkout session"}
            )
        
        # Find the lead
        lead = db.get(Lead, lead_id)
        if not lead:
            return JSONResponse(
                status_code=404,
                content={"error": f"Lead {lead_id} not found"}
            )
        
        # Verify checkout_session_id matches (prevent payment applied to wrong lead)
        if lead.stripe_checkout_session_id:
            if lead.stripe_checkout_session_id != checkout_session_id:
                logger.error(
                    f"Checkout session ID mismatch for lead {lead_id}. "
                    f"Expected: {lead.stripe_checkout_session_id}, Got: {checkout_session_id}"
                )
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "Checkout session ID mismatch",
                        "lead_id": lead_id,
                        "expected_session_id": lead.stripe_checkout_session_id,
                        "received_session_id": checkout_session_id,
                    }
                )
        
        # Idempotency: Check if this Stripe event was already processed
        is_duplicate, processed = check_and_record_processed_event(
            db=db,
            event_id=event_id,
            event_type="stripe.checkout.session.completed",
            lead_id=lead_id,
        )
        
        if is_duplicate:
            return {
                "received": True,
                "type": "duplicate",
                "lead_id": lead_id,
                "checkout_session_id": checkout_session_id,
                "event_id": event_id,
            }
        
        # Atomic status-locked update (prevents race conditions)
        # Only update if lead is still in AWAITING_DEPOSIT
        payment_intent_id = event_data.get("payment_intent")
        update_values = {
            "stripe_payment_status": "paid",
            "stripe_checkout_session_id": checkout_session_id,
            "deposit_paid_at": func.now(),
        }
        if payment_intent_id:
            update_values["stripe_payment_intent_id"] = payment_intent_id
        
        success, lead = update_lead_status_if_matches(
            db=db,
            lead_id=lead_id,
            expected_status=STATUS_AWAITING_DEPOSIT,  # Must be awaiting deposit
            new_status=STATUS_DEPOSIT_PAID,
            **update_values,
        )
        
        if not success:
            # Status mismatch - lead may have been updated by another process
            db.refresh(lead)
            if lead.status == STATUS_DEPOSIT_PAID:
                # Already processed by another request - return success
                return {
                    "received": True,
                    "type": "duplicate",
                    "lead_id": lead_id,
                    "checkout_session_id": checkout_session_id,
                    "message": "Lead already in DEPOSIT_PAID status",
                }
            # Unexpected status - log and return error
            return JSONResponse(
                status_code=400,
                content={
                    "error": f"Lead {lead_id} is in status '{lead.status}', expected '{STATUS_AWAITING_DEPOSIT}'"
                }
            )
        
        # Log to Google Sheets
        log_lead_to_sheets(db, lead)
        
        # Send WhatsApp confirmation message to client (with 24h window check)
        if lead.deposit_amount_pence:
            from app.services.whatsapp_window import send_with_window_check
            confirmation_message = format_payment_confirmation_message(lead.deposit_amount_pence)
            
            # Send message (async function in sync context)
            try:
                asyncio.run(send_with_window_check(
                    db=db,
                    lead=lead,
                    message=confirmation_message,
                    template_name="payment_confirmation",  # Template if window closed
                    dry_run=settings.whatsapp_dry_run,
                ))
            except RuntimeError:
                # Event loop already running, use different approach
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, send_whatsapp_message(
                        to=lead.wa_from,
                        message=confirmation_message,
                        dry_run=settings.whatsapp_dry_run,
                    ))
                    future.result()
            
            # Update last bot message timestamp
            lead.last_bot_message_at = func.now()
            db.commit()
            db.refresh(lead)
        
        
        return {
            "received": True,
            "type": "checkout.session.completed",
            "lead_id": lead_id,
            "checkout_session_id": checkout_session_id,
            "status": lead.status,
        }
    
    # For other event types, just acknowledge
    return {
        "received": True,
        "type": event_type,
        "message": "Event received but not handled",
    }
