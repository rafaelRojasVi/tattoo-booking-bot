import logging
from datetime import UTC

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.constants.event_types import (
    EVENT_DEPOSIT_PAID,
    EVENT_PILOT_MODE_BLOCKED,
    EVENT_SHEETS_BACKGROUND_DB_ERROR,
    EVENT_SHEETS_BACKGROUND_LOG_FAILURE,
    EVENT_STRIPE_CHECKOUT_SESSION_COMPLETED,
    EVENT_STRIPE_SESSION_ID_MISMATCH,
    EVENT_STRIPE_SIGNATURE_VERIFICATION_FAILURE,
    EVENT_STRIPE_WEBHOOK_FAILURE,
    EVENT_WHATSAPP_MESSAGE,
    EVENT_WHATSAPP_SIGNATURE_VERIFICATION_FAILURE,
    EVENT_WHATSAPP_WEBHOOK_FAILURE,
)
from app.constants.providers import PROVIDER_WHATSAPP
from app.core.config import settings
from app.db.deps import get_db
from app.db.helpers import commit_and_refresh
from app.db.models import Lead, ProcessedMessage
from app.services.conversation import (
    STATUS_AWAITING_DEPOSIT,
    STATUS_DEPOSIT_PAID,
    STATUS_NEEDS_ARTIST_REPLY,
    handle_inbound_message,
)
from app.services.integrations.sheets import log_lead_to_sheets
from app.services.integrations.stripe_service import verify_webhook_signature
from app.services.leads import get_or_create_lead
from app.services.messaging.messaging import format_payment_confirmation_message
from app.services.messaging.whatsapp_verification import verify_whatsapp_signature
from app.services.safety import update_lead_status_if_matches
from app.utils.datetime_utils import dt_replace_utc, iso_or_none

logger = logging.getLogger(__name__)

router = APIRouter()


def _wa_error_response(status_code: int, error: str, **content_extras) -> JSONResponse:
    """Build JSONResponse for WhatsApp webhook errors: {"received": False, "error": ...}."""
    content: dict = {"received": False, "error": error, **content_extras}
    return JSONResponse(status_code=status_code, content=content)


def _stripe_error_response(status_code: int, error: str, **content_extras) -> JSONResponse:
    """Build JSONResponse for Stripe webhook errors: {"error": ...}."""
    content: dict = {"error": error, **content_extras}
    return JSONResponse(status_code=status_code, content=content)


async def _verify_whatsapp_webhook(
    request: Request, db: Session
) -> tuple[bytes | None, JSONResponse | None]:
    """
    Read raw body, verify WhatsApp webhook signature.
    Returns (raw_body, None) on success; (None, error_response) on failure.
    """
    raw_body = await request.body()
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not verify_whatsapp_signature(raw_body, signature_header):
        logger.warning("WhatsApp webhook signature verification failed - rejecting request")
        from app.services.metrics.system_event_service import warn

        warn(
            db=db,
            event_type=EVENT_WHATSAPP_SIGNATURE_VERIFICATION_FAILURE,
            lead_id=None,
            payload={"has_signature_header": signature_header is not None},
        )
        return None, _wa_error_response(403, "Invalid webhook signature")
    return raw_body, None


async def _verify_stripe_webhook(
    request: Request, db: Session
) -> tuple[dict | None, JSONResponse | None]:
    """
    Read raw body, check stripe-signature header, verify Stripe webhook signature.
    Returns (event_dict, None) on success; (None, error_response) on failure.
    """
    body = await request.body()
    signature = request.headers.get("stripe-signature")
    if not signature:
        return None, _stripe_error_response(400, "Missing stripe-signature header")
    try:
        event = verify_webhook_signature(body, signature)
    except ValueError as e:
        logger.warning(f"Invalid Stripe webhook signature: {str(e)}")
        from app.services.metrics.system_event_service import warn

        warn(
            db=db,
            event_type=EVENT_STRIPE_SIGNATURE_VERIFICATION_FAILURE,
            lead_id=None,
            payload={"error": str(e)[:200]},
        )
        return None, _stripe_error_response(400, "Invalid webhook signature")
    except Exception as e:
        logger.error(
            f"Stripe webhook verification failed unexpectedly - "
            f"error_type={type(e).__name__}: {str(e)}",
            exc_info=True,
        )
        return None, _stripe_error_response(500, "Webhook verification failed")
    return event, None


def _is_processed_message_unique_violation(exc: IntegrityError) -> bool:
    """
    Return True only if the IntegrityError is a unique-constraint violation
    on ProcessedMessage(provider, message_id). Re-raise otherwise to avoid hiding real DB bugs.
    """
    orig = exc.orig
    if orig is None:
        return False
    # Postgres: SQLSTATE 23505 = unique_violation; optionally match constraint name
    if hasattr(orig, "pgcode") and orig.pgcode == "23505":
        err_msg = str(orig).lower() if orig else ""
        if "ix_processed_messages_provider_message_id" in err_msg:
            return True
        # ProcessedMessage has only one unique constraint; in this insert context, 23505 is ours
        return True
    # SQLite: check error message
    err_msg = str(orig).lower() if orig else ""
    if "unique constraint" in err_msg or "unique constraint failed" in err_msg:
        return True
    return False


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
async def whatsapp_inbound(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # Use correlation ID from middleware (X-Correlation-ID or generated)
    from app.middleware.correlation_id import get_correlation_id

    correlation_id = get_correlation_id(request)
    logger.info(
        f"whatsapp.inbound_received correlation_id={correlation_id}",
        extra={
            "correlation_id": correlation_id,
            "event_type": "whatsapp.inbound_received",
        },
    )

    raw_body, err_response = await _verify_whatsapp_webhook(request, db)
    if err_response is not None:
        return err_response

    # Parse JSON payload after signature verification
    try:
        import json

        payload = json.loads(raw_body.decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as e:
        # Invalid JSON payload
        logger.warning(f"Invalid JSON payload in WhatsApp webhook: {e}")
        return _wa_error_response(400, "Invalid JSON payload")

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
                messages = sorted(messages, key=lambda m: m.get("timestamp", 0), reverse=True)
                logger.info(
                    f"Received {len(messages)} messages in one payload, processing most recent first"
                )

            message = messages[0]  # Process most recent message
            message_id = message.get("id")  # WhatsApp message ID for idempotency
            wa_from = message.get("from")
            message_type = message.get("type", "text")  # Default to text if not specified

            # Extract text from different message types
            media_id = None
            if message_type == "text":
                text = (message.get("text") or {}).get("body")
            elif message_type in ["image", "video", "audio", "document"]:
                # Media messages - extract caption if available
                text = message.get("caption") or f"[{message_type} message]"
                # Extract media ID for reference images
                media_data = message.get(message_type, {})
                media_id = media_data.get("id") if isinstance(media_data, dict) else None
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
        return _wa_error_response(400, "Invalid phone number format")

    if not wa_from:
        return {"received": True, "type": "non-message-event"}

    # Validate phone number format (basic check)
    if not isinstance(wa_from, str) or len(wa_from.strip()) < 10:
        return _wa_error_response(400, "Invalid phone number format")

    # Idempotency: insert ProcessedMessage FIRST (before any processing).
    # Only treat unique-constraint violation on (provider, message_id) as duplicate.
    processed_msg = None
    if message_id:
        try:
            processed_msg = ProcessedMessage(
                provider=PROVIDER_WHATSAPP,
                message_id=message_id,
                event_type=EVENT_WHATSAPP_MESSAGE,
                lead_id=None,  # Will update after we have lead
            )
            db.add(processed_msg)
            db.flush()
        except IntegrityError as e:
            if not _is_processed_message_unique_violation(e):
                raise  # Re-raise to avoid hiding real DB bugs
            db.rollback()
            stmt = select(ProcessedMessage).where(
                ProcessedMessage.provider == PROVIDER_WHATSAPP,
                ProcessedMessage.message_id == message_id,
            )
            existing = db.execute(stmt).scalar_one_or_none()
            existing_ts = iso_or_none(existing.processed_at) if existing else None
            return {
                "received": True,
                "type": "duplicate",
                "message_id": message_id,
                "processed_at": existing_ts,
            }

    try:
        lead = get_or_create_lead(db, wa_from=wa_from)
    except Exception as e:
        # Database error - log full context for debugging
        logger.error(
            f"Database error in WhatsApp webhook for {wa_from}: {type(e).__name__}: {e}",
            exc_info=True,
        )
        return _wa_error_response(500, "Database error", detail=str(e))

    # Pilot mode check: if enabled, only allowlisted numbers can start consultation
    if settings.pilot_mode_enabled:
        # Parse allowlist (comma-separated, strip whitespace)
        allowlist_numbers = [
            num.strip() for num in settings.pilot_allowlist_numbers.split(",") if num.strip()
        ]

        if wa_from not in allowlist_numbers:
            # Number not allowlisted - send polite message and log event
            pilot_message = (
                "Thank you for your interest! We're currently in pilot mode with limited availability. "
                "We'll be in touch soon when we're ready to accept new bookings. "
                "Thank you for your patience!"
            )

            # Send polite message (async function in async context)
            try:
                from app.services.messaging.messaging import send_whatsapp_message

                await send_whatsapp_message(
                    to=wa_from,
                    message=pilot_message,
                    dry_run=settings.whatsapp_dry_run,
                )
            except Exception as e:
                logger.error(f"Failed to send pilot mode message to {wa_from}: {e}")

            # Log system event
            from app.services.metrics.system_event_service import info

            info(
                db=db,
                event_type=EVENT_PILOT_MODE_BLOCKED,
                lead_id=lead.id if lead else None,
                payload={
                    "wa_from": wa_from,
                    "allowlist_numbers": allowlist_numbers,
                },
            )

            # Update lead_id on ProcessedMessage we inserted at start
            if processed_msg:
                processed_msg.lead_id = lead.id
            db.commit()

            return {
                "received": True,
                "type": "pilot_mode_blocked",
                "lead_id": lead.id if lead else None,
                "wa_from": wa_from,
                "message": "Pilot mode: number not in allowlist",
            }

    # Handle the conversation flow (only if we have text to process)
    if text:
        try:
            # Check message timestamp to prevent processing out-of-order messages
            # If message is older than last_client_message_at, ignore it (already processed)
            message_timestamp = None
            if messages and messages[0].get("timestamp"):
                from datetime import datetime

                message_timestamp = datetime.fromtimestamp(int(messages[0]["timestamp"]), tz=UTC)

                last_message_time = dt_replace_utc(lead.last_client_message_at)
                if last_message_time is not None:
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
            has_media = bool(media_id and message_type in ["image", "document"])
            conversation_result = await handle_inbound_message(
                db=db,
                lead=lead,
                message_text=text,
                dry_run=settings.whatsapp_dry_run,
                has_media=has_media,
            )

            # Update lead_id on ProcessedMessage we inserted at start (idempotency)
            if processed_msg:
                processed_msg.lead_id = lead.id
            db.commit()

            # Create Attachment record for media messages (reference images)
            if media_id and message_type in ["image", "document"]:
                from app.db.models import Attachment

                # Create Attachment with PENDING status
                attachment = Attachment(
                    lead_id=lead.id,
                    whatsapp_media_id=media_id,
                    upload_status="PENDING",
                    upload_attempts=0,
                    provider="supabase",
                    content_type=None,  # Will be determined during download
                )
                db.add(attachment)
                commit_and_refresh(db, attachment)

                # Schedule background task to attempt upload once
                # Sweeper will handle retries if this fails
                # Use job wrapper since background tasks run in separate context
                from app.services.integrations.media_upload import attempt_upload_attachment_job

                background_tasks.add_task(attempt_upload_attachment_job, attachment.id)

            return {
                "received": True,
                "lead_id": lead.id,
                "wa_from": wa_from,
                "text": text,
                "message_type": message_type,
                "conversation": conversation_result,
            }
        except Exception as e:
            # Log error with structured context for debugging
            # Note: We return success to WhatsApp to prevent retries, but log the error
            logger.error(
                f"Conversation handling failed for WhatsApp webhook - "
                f"lead_id={lead.id}, message_id={message_id}, "
                f"wa_from={wa_from}, error_type={type(e).__name__}: {str(e)}",
                exc_info=True,
            )
            # Log system event for WhatsApp webhook failure
            from app.services.metrics.system_event_service import error

            error(
                db=db,
                event_type=EVENT_WHATSAPP_WEBHOOK_FAILURE,
                lead_id=lead.id if lead else None,
                payload={"message_id": message_id, "wa_from": wa_from},
                exc=e,
            )
            return {
                "received": True,
                "lead_id": lead.id,
                "wa_from": wa_from,
                "text": text,
                "message_type": message_type,
                "error": "Conversation handling failed",
            }

    # If no text (e.g., just an image without caption), create attachment and still run conversation
    # so we can send "Got it, I've saved the image. For this step I need: ..." when not on reference_images
    if media_id and message_type in ["image", "document"]:
        from app.db.models import Attachment

        # Create Attachment with PENDING status
        attachment = Attachment(
            lead_id=lead.id,
            whatsapp_media_id=media_id,
            upload_status="PENDING",
            upload_attempts=0,
            provider="supabase",
            content_type=None,  # Will be determined during download
        )
        db.add(attachment)
        commit_and_refresh(db, attachment)

        from app.services.integrations.media_upload import attempt_upload_attachment_job

        background_tasks.add_task(attempt_upload_attachment_job, attachment.id)

        conversation_result = await handle_inbound_message(
            db=db,
            lead=lead,
            message_text="",
            dry_run=settings.whatsapp_dry_run,
            has_media=True,
        )
        return {
            "received": True,
            "lead_id": lead.id,
            "wa_from": wa_from,
            "text": text,
            "message_type": message_type,
            "conversation": conversation_result,
        }

    return {
        "received": True,
        "lead_id": lead.id,
        "wa_from": wa_from,
        "text": text,
        "message_type": message_type,
    }


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Handle Stripe webhook events (payment confirmations).

    Handles:
    - checkout.session.completed: Deposit payment confirmed
    """
    event, err_response = await _verify_stripe_webhook(request, db)
    if err_response is not None:
        return err_response

    # Handle the event
    event_type = event.get("type")
    data = event.get("data")
    event_data = data.get("object") if isinstance(data, dict) else None
    if event_data is None:
        return _stripe_error_response(400, "Malformed event: missing data.object")

    # Idempotency: Stripe sends idempotency key in event id
    event_id = event.get("id")

    if event_type == "checkout.session.completed":
        # Payment confirmed - update lead status
        checkout_session_id = event_data.get("id")
        client_reference_id = event_data.get("client_reference_id")  # Contains lead_id
        metadata = event_data.get("metadata", {})

        # Get lead_id from metadata or client_reference_id (safe parse - reject invalid)
        def _safe_parse_lead_id(val) -> int | None:
            if val is None:
                return None
            s = str(val).strip()
            if not s:
                return None
            try:
                n = int(s)
                if n != float(s):  # Reject "1.5" etc
                    return None
                return n if n > 0 else None
            except (ValueError, TypeError):
                return None

        lead_id = None
        if metadata and "lead_id" in metadata:
            lead_id = _safe_parse_lead_id(metadata["lead_id"])
        if lead_id is None and client_reference_id:
            lead_id = _safe_parse_lead_id(client_reference_id)

        if lead_id is None or lead_id <= 0:
            return _stripe_error_response(400, "No lead_id found in checkout session")

        # Find the lead
        lead = db.get(Lead, lead_id)
        if not lead:
            return _stripe_error_response(404, f"Lead {lead_id} not found")

        # Verify checkout_session_id matches (prevent payment applied to wrong lead)
        if lead.stripe_checkout_session_id:
            if lead.stripe_checkout_session_id != checkout_session_id:
                logger.error(
                    f"Checkout session ID mismatch for lead {lead_id}. "
                    f"Expected: {lead.stripe_checkout_session_id}, Got: {checkout_session_id}"
                )
                # Log SystemEvent for session_id mismatch
                from app.services.metrics.system_event_service import error

                error(
                    db=db,
                    event_type=EVENT_STRIPE_SESSION_ID_MISMATCH,
                    lead_id=lead_id,
                    payload={
                        "expected_session_id": lead.stripe_checkout_session_id,
                        "received_session_id": checkout_session_id,
                        "event_id": event_id,
                    },
                )
                return _stripe_error_response(
                    400,
                    "Checkout session ID mismatch",
                    lead_id=lead_id,
                    expected_session_id=lead.stripe_checkout_session_id,
                    received_session_id=checkout_session_id,
                )

        # CRITICAL FIX: Check idempotency FIRST (read-only check)
        from app.services.safety import check_processed_event, record_processed_event

        event_id_str = str(event_id) if event_id else None
        if not event_id_str:
            return _stripe_error_response(400, "Stripe event has no id")
        is_duplicate, processed = check_processed_event(db, event_id_str)
        if is_duplicate:
            return {
                "received": True,
                "type": "duplicate",
                "lead_id": lead_id,
                "checkout_session_id": checkout_session_id,
                "event_id": event_id_str,
            }

        # Phase 1: Atomic status-locked update (prevents race conditions)
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
            if lead is None:
                return _stripe_error_response(404, f"Lead {lead_id} not found")
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
            # Allow NEEDS_ARTIST_REPLY -> DEPOSIT_PAID: client paid while artist had handover
            if lead.status == STATUS_NEEDS_ARTIST_REPLY:
                success, lead = update_lead_status_if_matches(
                    db=db,
                    lead_id=lead_id,
                    expected_status=STATUS_NEEDS_ARTIST_REPLY,
                    new_status=STATUS_DEPOSIT_PAID,
                    **update_values,
                )
                if success:
                    db.refresh(lead)
            if not success:
                if lead is None:
                    return _stripe_error_response(404, f"Lead {lead_id} not found")
                # Log Stripe webhook failure due to status mismatch
                from app.services.metrics.system_event_service import error

                error(
                    db=db,
                    event_type=EVENT_STRIPE_WEBHOOK_FAILURE,
                    lead_id=lead_id,
                    payload={
                        "event_type": event_type,
                        "checkout_session_id": checkout_session_id,
                        "expected_status": STATUS_AWAITING_DEPOSIT,
                        "actual_status": lead.status,
                        "reason": "status_mismatch",
                    },
                )
                # Optional: Notify artist if notifications enabled
                if settings.feature_notifications_enabled and settings.artist_whatsapp_number:
                    try:
                        from app.services.integrations.artist_notifications import send_system_alert

                        await send_system_alert(
                            message=(
                                f"⚠️ Stripe payment received for lead {lead_id} "
                                f"but lead is in unexpected status '{lead.status}' "
                                f"(expected '{STATUS_AWAITING_DEPOSIT}'). "
                                f"Payment not processed. Please review."
                            ),
                            dry_run=settings.whatsapp_dry_run,
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify artist about unexpected status: {e}")
                return _stripe_error_response(
                    400,
                    f"Lead {lead_id} is in status '{lead.status}', expected '{STATUS_AWAITING_DEPOSIT}'",
                )

        if lead is None:
            return _stripe_error_response(404, f"Lead {lead_id} not found")

        # Phase 1: After deposit paid, set to BOOKING_PENDING (not BOOKING_LINK_SENT)
        from app.services.conversation import STATUS_BOOKING_PENDING

        lead.status = STATUS_BOOKING_PENDING
        lead.booking_pending_at = func.now()
        commit_and_refresh(db, lead)

        # CRITICAL FIX: Side effects happen AFTER commit
        # 1. DB transaction committed (status updated)
        # 2. Now do external calls (Sheets, WhatsApp)
        # 3. Finally record as processed (so if we crash, we can retry)

        # Log to Google Sheets in background (non-blocking)
        # Pass lead_id and correlation_id for tracing
        from app.middleware.correlation_id import get_correlation_id

        cid = get_correlation_id(request)
        background_tasks.add_task(
            _log_lead_to_sheets_background, lead_id=lead_id, correlation_id=cid
        )

        # Phase 1: Send WhatsApp confirmation message to client (with 24h window check)
        if lead.deposit_amount_pence:
            from app.services.messaging.whatsapp_window import send_with_window_check

            confirmation_message = format_payment_confirmation_message(
                lead.deposit_amount_pence, lead_id=lead.id
            )

            # Phase 1: Add policy reminder
            confirmation_message += (
                "\n\n*Important:* Your deposit is non-refundable. "
                "You can reschedule once. No-shows forfeit the deposit.\n\n"
                "Jonah will confirm your date in the calendar and message you."
            )

            # Send message (async function in sync context)
            from app.services.messaging.whatsapp_templates import (
                get_template_for_deposit_confirmation,
                get_template_params_deposit_received_next_steps,
            )

            client_name = None  # TODO: Extract from lead.answers if available
            try:
                await send_with_window_check(
                    db=db,
                    lead=lead,
                    message=confirmation_message,
                    template_name=get_template_for_deposit_confirmation(),
                    template_params=get_template_params_deposit_received_next_steps(
                        client_name=client_name
                    ),
                    dry_run=settings.whatsapp_dry_run,
                )
            except Exception as e:
                # Log error with context but don't fail the webhook
                logger.error(
                    f"Failed to send confirmation message - "
                    f"lead_id={lead_id}, checkout_session_id={checkout_session_id}, "
                    f"error_type={type(e).__name__}: {str(e)}",
                    exc_info=True,
                )

            # Update last bot message timestamp
            lead.last_bot_message_at = func.now()
            commit_and_refresh(db, lead)

            # Phase 1: Notify artist that deposit was paid
            from app.services.integrations.artist_notifications import notify_artist

            try:
                await notify_artist(
                    db=db,
                    lead=lead,
                    event_type=EVENT_DEPOSIT_PAID,
                    dry_run=settings.whatsapp_dry_run,
                )
            except Exception as e:
                # Log error with context but don't fail the webhook
                logger.error(
                    f"Failed to notify artist of deposit payment - "
                    f"lead_id={lead_id}, checkout_session_id={checkout_session_id}, "
                    f"error_type={type(e).__name__}: {str(e)}",
                    exc_info=True,
                )

        # CRITICAL FIX: Record as processed ONLY after all side effects succeed
        # If we crash before this, Stripe will retry and we'll process again (correct)
        try:
            record_processed_event(
                db=db,
                event_id=event_id_str,
                event_type=EVENT_STRIPE_CHECKOUT_SESSION_COMPLETED,
                lead_id=lead_id,
            )
        except Exception as e:
            # If recording fails, log but don't fail the webhook
            # The worst case is we process it twice (which idempotency handles)
            logger.error(f"Failed to record processed event {event_id}: {e}")

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


def _log_lead_to_sheets_background(lead_id: int, correlation_id: str | None = None) -> None:
    """
    Background task to log lead to Google Sheets.

    Opens a fresh DB session to avoid reusing request-scoped session.
    Logs a system event (ERROR level) on failure so failures aren't silent.

    Args:
        lead_id: Lead ID to log
        correlation_id: Optional correlation ID for request tracing
    """
    if correlation_id:
        from app.middleware.correlation_id import set_correlation_id

        set_correlation_id(correlation_id)
    from app.db.models import Lead
    from app.db.session import SessionLocal
    from app.services.metrics.system_event_service import error as log_system_error

    # Create a new DB session for the background task
    db = SessionLocal()
    try:
        try:
            lead = db.get(Lead, lead_id)
            if lead:
                try:
                    log_lead_to_sheets(db, lead)
                except Exception as e:
                    # Log both to logger and SystemEvent for visibility
                    logger.error(
                        f"Failed to log lead {lead_id} to Sheets in background: {e}",
                        exc_info=True,
                    )
                    # Log SystemEvent(ERROR) so failures are visible in admin/metrics
                    try:
                        log_system_error(
                            db=db,
                            event_type=EVENT_SHEETS_BACKGROUND_LOG_FAILURE,
                            lead_id=lead_id,
                            exc=e,
                        )
                    except Exception as event_error:
                        # If SystemEvent logging fails, at least log to logger
                        logger.error(f"Failed to log SystemEvent for Sheets failure: {event_error}")
            else:
                logger.warning(f"Lead {lead_id} not found for Sheets logging")
        except Exception as e:
            # Handle database errors gracefully (e.g., in test environments)
            logger.warning(
                f"Database error in background Sheets logging for lead {lead_id}: {e}",
                exc_info=True,
            )
            # Log SystemEvent for database errors too
            try:
                log_system_error(
                    db=db,
                    event_type=EVENT_SHEETS_BACKGROUND_DB_ERROR,
                    lead_id=lead_id,
                    exc=e,
                )
            except Exception:
                # If SystemEvent logging fails, ignore (already logged to logger)
                pass
    finally:
        db.close()
