from fastapi import APIRouter, Request, Response, HTTPException
from app.core.config import settings

router = APIRouter()


@router.get("/whatsapp")
def whatsapp_verify(
    hub_mode: str | None = None,
    hub_verify_token: str | None = None,
    hub_challenge: str | None = None,
):
    # Meta sends: hub.mode, hub.verify_token, hub.challenge
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return Response(content=hub_challenge or "", media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp")
async def whatsapp_inbound(request: Request):
    payload = await request.json()
    # TODO: parse WhatsApp message and pass into AI flow
    return {"received": True, "payload_keys": list(payload.keys())}
