"""
WhatsApp 24-hour window handling and template message support.

WhatsApp Business messaging follows a customer "care window":
- Within ~24 hours of client's last message: can send free-form messages
- Outside 24-hour window: must use pre-approved template messages
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.constants.event_types import (
    EVENT_TEMPLATE_FALLBACK_USED,
    EVENT_WHATSAPP_SEND_FAILURE,
    whatsapp_template_not_configured_event_type,
)
from app.db.models import Lead

logger = logging.getLogger(__name__)

# WhatsApp 24-hour window (in hours)
WHATSAPP_WINDOW_HOURS = 24


def is_within_24h_window(lead: Lead) -> tuple[bool, datetime | None]:
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

    now = datetime.now(UTC)
    last_message = lead.last_client_message_at

    # Handle timezone-aware/naive comparison
    if last_message.tzinfo is None:
        last_message = last_message.replace(tzinfo=UTC)

    window_expires_at = last_message + timedelta(hours=WHATSAPP_WINDOW_HOURS)
    is_within = now < window_expires_at

    return is_within, window_expires_at


async def send_with_window_check(
    db: Session,
    lead: Lead,
    message: str,
    template_name: str | None = None,
    template_params: dict | None = None,
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
    from app.services.conversation import STATUS_OPTOUT
    from app.services.messaging import send_whatsapp_message

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
        # Apply voice pack to free-form messages
        from app.services.tone import apply_voice

        message_with_voice = apply_voice(message, is_template=False)

        outbox = None
        if not dry_run:
            from app.services.outbox_service import write_outbox

            outbox = write_outbox(db, lead.id, lead.wa_from, message_with_voice)

        try:
            result = await send_whatsapp_message(
                to=lead.wa_from,
                message=message_with_voice,
                dry_run=dry_run,
            )
            if outbox:
                from app.services.outbox_service import mark_outbox_sent

                mark_outbox_sent(db, outbox)
            result["window_status"] = "open"
            result["window_expires_at"] = (
                window_expires_at.isoformat() if window_expires_at else None
            )
            return result
        except Exception as e:
            if outbox:
                from app.services.outbox_service import mark_outbox_failed

                mark_outbox_failed(db, outbox, e)
            # Log WhatsApp send failure
            from app.services.system_event_service import error

            error(
                db=db,
                event_type=EVENT_WHATSAPP_SEND_FAILURE,
                lead_id=lead.id,
                payload={"to": lead.wa_from},
                exc=e,
            )
            raise
    # Window closed - need template message
    elif template_name:
        # Check if template is configured (graceful degradation)
        from app.services.template_registry import get_all_required_templates

        required_templates = get_all_required_templates()
        if template_name not in required_templates:
            # Template not configured - graceful degradation
            from app.core.config import settings
            from app.services.metrics import record_window_closed

            record_window_closed(
                lead_id=lead.id, message_type=f"template_not_configured_{template_name}"
            )

            # Log SystemEvent (structured logging)
            from app.services.system_event_service import warn

            warn(
                db=db,
                event_type=whatsapp_template_not_configured_event_type(template_name),
                lead_id=lead.id,
                payload={
                    "template_name": template_name,
                    "wa_from": lead.wa_from,
                    "lead_status": lead.status,
                    "message_preview": message[:100] if message else None,
                },
            )
            logger.error(
                f"SYSTEM_EVENT: Template '{template_name}' not configured for lead {lead.id}. "
                f"Message outside 24h window blocked. Lead: {lead.wa_from}, Status: {lead.status}"
            )

            # Notify artist if notifications enabled
            if settings.feature_notifications_enabled and settings.artist_whatsapp_number:
                try:
                    from app.services.artist_notifications import send_system_alert

                    await send_system_alert(
                        message=(
                            f"⚠️ Template '{template_name}' not configured. "
                            f"Message to lead {lead.id} ({lead.wa_from}) blocked outside 24h window. "
                            f"Please configure template in WhatsApp Manager."
                        ),
                        dry_run=dry_run,
                    )
                except Exception as e:
                    logger.error(f"Failed to notify artist about missing template: {e}")

            # Don't send message - graceful degradation
            return {
                "status": "window_closed_template_not_configured",
                "message_id": None,
                "to": lead.wa_from,
                "message": message,
                "template_name": template_name,
                "window_status": "closed",
                "window_expires_at": window_expires_at.isoformat() if window_expires_at else None,
                "warning": f"24-hour window expired. Template '{template_name}' required but not configured.",
            }

        # Template is configured - try to send
        outbox = None
        if not dry_run:
            from app.services.outbox_service import write_outbox

            outbox = write_outbox(
                db, lead.id, lead.wa_from, message,
                template_name=template_name,
                template_params=template_params or {},
            )
        try:
            result = await send_template_message(
                to=lead.wa_from,
                template_name=template_name,
                template_params=template_params or {},
                dry_run=dry_run,
            )
            if outbox:
                from app.services.outbox_service import mark_outbox_sent

                mark_outbox_sent(db, outbox)
            result["window_status"] = "closed_template_used"
            result["window_expires_at"] = (
                window_expires_at.isoformat() if window_expires_at else None
            )

            # Log template fallback usage
            from app.services.system_event_service import info

            info(
                db=db,
                event_type=EVENT_TEMPLATE_FALLBACK_USED,
                lead_id=lead.id,
                payload={
                    "template_name": template_name,
                    "window_expires_at": window_expires_at.isoformat()
                    if window_expires_at
                    else None,
                },
            )

            return result
        except Exception as e:
            if outbox:
                from app.services.outbox_service import mark_outbox_failed

                mark_outbox_failed(db, outbox, e)
            # Template send failed - log and degrade gracefully
            from app.core.config import settings
            from app.services.metrics import record_window_closed

            record_window_closed(
                lead_id=lead.id, message_type=f"template_send_failed_{template_name}"
            )
            logger.error(
                f"SYSTEM_EVENT: Failed to send template '{template_name}' to lead {lead.id}. "
                f"Error: {e}"
            )

            # Notify artist
            if settings.feature_notifications_enabled and settings.artist_whatsapp_number:
                try:
                    from app.services.artist_notifications import send_system_alert

                    await send_system_alert(
                        message=(
                            f"⚠️ Failed to send template '{template_name}' to lead {lead.id}. "
                            f"Error: {str(e)[:100]}"
                        ),
                        dry_run=dry_run,
                    )
                except Exception:
                    pass  # Don't fail if alert send fails

            return {
                "status": "window_closed_template_send_failed",
                "message_id": None,
                "to": lead.wa_from,
                "message": message,
                "template_name": template_name,
                "window_status": "closed",
                "window_expires_at": window_expires_at.isoformat() if window_expires_at else None,
                "error": str(e),
                "warning": "24-hour window expired. Template send failed.",
            }
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
            for _key, value in template_params.items():
                body_params.append({"type": "text", "text": str(value)})

            if body_params:
                components.append(
                    {
                        "type": "body",
                        "parameters": body_params,
                    }
                )

        from app.services.whatsapp_templates import TEMPLATE_LANGUAGE_CODE

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": TEMPLATE_LANGUAGE_CODE},  # Use configured language code
                "components": components if components else None,
            },
        }

        # Remove components if empty
        if not components:
            payload["template"].pop("components", None)

        from app.services.http_client import create_httpx_client

        async with create_httpx_client() as client:
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
