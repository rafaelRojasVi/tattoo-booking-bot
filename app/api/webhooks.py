from fastapi import APIRouter, Request, Response, HTTPException, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.deps import get_db
from app.services.leads import get_or_create_lead

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
    payload = await request.json()

    # Try to extract sender ("from") and message body
    wa_from = None
    text = None

    try:
        entry = payload.get("entry", [])[0]
        change = entry.get("changes", [])[0]
        value = change.get("value", {})

        messages = value.get("messages", [])
        if messages:
            wa_from = messages[0].get("from")
            text = (messages[0].get("text") or {}).get("body")
    except Exception:
        pass

    # If it's not a message event, just ack (delivery receipts etc.)
    if not wa_from:
        return {"received": True, "type": "non-message-event"}

    lead = get_or_create_lead(db, wa_from=wa_from)

    return {
        "received": True,
        "lead_id": lead.id,
        "wa_from": wa_from,
        "text": text,
    }
