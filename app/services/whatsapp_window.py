"""
WhatsApp 24-hour window handling and template message support.

WhatsApp Business messaging follows a customer "care window":
- Within ~24 hours of client's last message: can send free-form messages
- Outside 24-hour window: must use pre-approved template messages
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from app.db.models import Lead

logger = logging.getLogger(__name__)

# WhatsApp 24-hour window (in hours)
WHATSAPP_WINDOW_HOURS = 24


def is_within_24h_window(lead: Lead) -> Tuple[bool, Optional[datetime]]:
    """
    Check if we're within the 24-hour messaging window for a lead.
    
    Args:
        lead: Lead object with last_client_message_at timestamp
        
    Returns:
        Tuple of (is_within_window: bool, window_expires_at: datetime | None)
        If last_client_message_at is None, returns (True, None) - assume window is open
    """
    if not lead.last_client_message_at:
        # No previous message - window is open
        return True, None
    
    now = datetime.now(timezone.utc)
    last_message = lead.last_client_message_at
    
    # Handle timezone-aware/naive comparison
    if last_message.tzinfo is None:
        last_message = last_message.replace(tzinfo=timezone.utc)
    
    window_expires_at = last_message + timedelta(hours=WHATSAPP_WINDOW_HOURS)
    is_within = now < window_expires_at
    
    return is_within, window_expires_at


async def send_with_window_check(
    db: Session,
    lead: Lead,
    message: str,
    template_name: Optional[str] = None,
    template_params: Optional[dict] = None,
    dry_run: bool = True,
) -> dict:
    """
    Send WhatsApp message with 24-hour window checking.
    If window is closed, attempts to use template message.
    
    Args:
        db: Database session
        lead: Lead object
        message: Message text to send
        template_name: Optional template name (if window is closed)
        template_params: Optional template parameters
        dry_run: Whether to actually send
        
    Returns:
        dict with status, message_id, and window info
    """
    from app.services.messaging import send_whatsapp_message
    from app.services.conversation import STATUS_OPTOUT
    
    # Check if lead has opted out - block all outbound messages
    if lead.status == STATUS_OPTOUT:
        logger.info(f"Lead {lead.id} ({lead.wa_from}) has opted out - message not sent")
        return {
            "status": "opted_out",
            "message_id": None,
            "to": lead.wa_from,
            "message": message,
            "warning": "Lead has opted out. Message blocked.",
        }
    
    is_within, window_expires_at = is_within_24h_window(lead)
    
    if is_within:
        # Within window - send free-form message
        result = await send_whatsapp_message(
            to=lead.wa_from,
            message=message,
            dry_run=dry_run,
        )
        result["window_status"] = "open"
        result["window_expires_at"] = window_expires_at.isoformat() if window_expires_at else None
        return result
    else:
        # Window closed - need template message
        if template_name:
            # Try to send template message
            result = await send_template_message(
                to=lead.wa_from,
                template_name=template_name,
                template_params=template_params or {},
                dry_run=dry_run,
            )
            result["window_status"] = "closed_template_used"
            result["window_expires_at"] = window_expires_at.isoformat() if window_expires_at else None
            return result
        else:
            # No template available - graceful degradation
            from app.services.metrics import record_window_closed
            record_window_closed(lead_id=lead.id, message_type="no_template")
            logger.warning(
                f"24h window closed for lead {lead.id} ({lead.wa_from}), "
                f"but no template provided. Message logged but not sent."
            )
            return {
                "status": "window_closed_no_template",
                "message_id": None,
                "to": lead.wa_from,
                "message": message,
                "window_status": "closed",
                "window_expires_at": window_expires_at.isoformat() if window_expires_at else None,
                "warning": "24-hour window expired. Template message required but not provided.",
            }


async def send_template_message(
    to: str,
    template_name: str,
    template_params: dict,
    dry_run: bool = True,
) -> dict:
    """
    Send a WhatsApp template message (for use outside 24-hour window).
    
    Args:
        to: WhatsApp phone number
        template_name: Name of the approved template
        template_params: Template parameters (if template has placeholders)
        dry_run: Whether to actually send
        
    Returns:
        dict with status and message_id
    """
    from app.core.config import settings
    
    if dry_run:
        logger.info(
            f"[DRY-RUN] Would send WhatsApp template '{template_name}' to {to} "
            f"with params: {template_params}"
        )
        return {
            "status": "dry_run_template",
            "message_id": None,
            "to": to,
            "template_name": template_name,
            "template_params": template_params,
        }
    
    try:
        import httpx
        
        url = f"https://graph.facebook.com/v18.0/{settings.whatsapp_phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {settings.whatsapp_access_token}",
            "Content-Type": "application/json",
        }
        
        # Build template message payload
        components = []
        if template_params:
            # Convert params to template components
            # Format depends on template structure - simplified here
            body_params = []
            for key, value in template_params.items():
                body_params.append({"type": "text", "text": str(value)})
            
            if body_params:
                components.append({
                    "type": "body",
                    "parameters": body_params,
                })
        
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "en"},  # Default to English, can be configured
                "components": components if components else None,
            },
        }
        
        # Remove components if empty
        if not components:
            payload["template"].pop("components", None)
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            
            from app.services.metrics import record_template_message_used
            record_template_message_used(template_name=template_name, success=True)
            
            return {
                "status": "sent_template",
                "message_id": result.get("messages", [{}])[0].get("id"),
                "to": to,
                "template_name": template_name,
            }
    except Exception as e:
        from app.services.metrics import record_template_message_used
        record_template_message_used(template_name=template_name, success=False)
        logger.error(f"Failed to send WhatsApp template message: {e}")
        raise
