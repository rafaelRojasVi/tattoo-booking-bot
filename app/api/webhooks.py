from fastapi import APIRouter, Request, Response, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.config import settings
from app.db.deps import get_db
from app.db.models import ProcessedMessage
from app.services.leads import get_or_create_lead
from app.services.conversation import handle_inbound_message

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
            message = messages[0]
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
