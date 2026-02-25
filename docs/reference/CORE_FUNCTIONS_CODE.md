# Core functions — source code

Full source for each of the 33 core functions, in review order. See [CORE_FUNCTION_REVIEW_PLAN.md](CORE_FUNCTION_REVIEW_PLAN.md) in this folder for the table and glossary. Paths verified against the repo.

---

## 1. lifespan — `app.main.lifespan`

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    from app.core.config import settings
    from app.services.messaging.template_check import startup_check_templates

    required_settings = [
        "database_url",
        "whatsapp_verify_token",
        "whatsapp_access_token",
        "whatsapp_phone_number_id",
        "stripe_secret_key",
        "stripe_webhook_secret",
    ]
    missing = [key for key in required_settings if not getattr(settings, key, None)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Please check your .env file or environment configuration."
        )

    if settings.app_env == "production":
        production_errors = []
        if not settings.admin_api_key:
            production_errors.append("ADMIN_API_KEY is required in production. ...")
        if not settings.whatsapp_app_secret:
            production_errors.append("WHATSAPP_APP_SECRET is required in production ...")
        # ... (stripe_webhook_secret, demo_mode checks)
        if production_errors:
            error_message = (...)
            logger.error(error_message)
            raise RuntimeError(error_message)

    logger.info("Startup: Configuration loaded - ...")
    if settings.demo_mode:
        logger.warning("DEMO MODE ENABLED - DO NOT USE IN PROD")
    template_status = startup_check_templates()
    logger.info(f"Startup: Template check completed - ...")
    yield
```

---

## 2. get_db — `app.db.deps.get_db`

```python
def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

---

## 3. get_lead_or_404 — `app.api.dependencies.get_lead_or_404`

```python
def get_lead_or_404(lead_id: int, db: Session = Depends(get_db)) -> Lead:
    """
    Resolve lead by path parameter lead_id; raise 404 if not found.
    Use as a dependency on routes with path parameter {lead_id}.
    """
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead
```

---

## 4. _verify_whatsapp_webhook — `app.api.webhooks._verify_whatsapp_webhook`

```python
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
```

---

## 5. _verify_stripe_webhook — `app.api.webhooks._verify_stripe_webhook`

```python
async def _verify_stripe_webhook(
    request: Request, db: Session
) -> tuple[dict | None, JSONResponse | None]:
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
```

---

## 6–7. whatsapp_inbound / stripe_webhook

**whatsapp_inbound** (`app.api.webhooks.whatsapp_inbound`): ~330 lines. Flow: correlation_id log → `_verify_whatsapp_webhook` → parse JSON → extract entry/changes/value/messages → idempotency (ProcessedMessage insert or duplicate return) → `get_or_create_lead` → pilot check → out-of-order check → `handle_inbound_message` → Attachment creation + background `attempt_upload_attachment_job`.  
**Full source:** `app/api/webhooks.py` lines 149–484.

**stripe_webhook** (`app.api.webhooks.stripe_webhook`): ~290 lines. Flow: `_verify_stripe_webhook` → event_type/data → lead_id from metadata/client_reference_id → session_id mismatch check → `check_processed_event` → `update_lead_status_if_matches` (AWAITING_DEPOSIT → DEPOSIT_PAID) → set BOOKING_PENDING → background sheets → `send_with_window_check` (confirmation) → notify_artist → `record_processed_event`.  
**Full source:** `app/api/webhooks.py` lines 487–789.

---

## 8. handle_inbound_message — `app.services.conversation.handle_inbound_message`

```python
async def handle_inbound_message(
    db: Session,
    lead: Lead,
    message_text: str,
    dry_run: bool = True,
    *,
    has_media: bool = False,
) -> dict:
    """Route by lead.status to NEW/QUALIFYING/booking/handover handlers."""
    from app.core.config import settings

    if settings.feature_panic_mode_enabled:
        # ... panic: log message, notify artist, send safe response
        return {"status": "panic_mode", "message": "Automation paused (panic mode)", "lead_status": lead.status}

    if lead.status == STATUS_NEW:
        return await _handle_new_lead(db, lead, dry_run)
    elif lead.status == STATUS_QUALIFYING:
        return await _handle_qualifying_lead(db, lead, message_text, dry_run, has_media=has_media)
    elif lead.status == STATUS_PENDING_APPROVAL:
        return {"status": "pending_approval", "message": render_message("pending_approval", lead_id=lead.id), "lead_status": lead.status}
    elif lead.status == STATUS_AWAITING_DEPOSIT:
        return {"status": "awaiting_deposit", "message": render_message("awaiting_deposit", lead_id=lead.id), "lead_status": lead.status}
    elif lead.status == STATUS_DEPOSIT_PAID:
        return {"status": "deposit_paid", "message": render_message("deposit_paid", lead_id=lead.id), "lead_status": lead.status}
    elif lead.status == STATUS_BOOKING_PENDING:
        return await _handle_booking_pending(db, lead, message_text, dry_run)
    elif lead.status == STATUS_COLLECTING_TIME_WINDOWS:
        return await collect_time_window(db, lead, message_text, dry_run)
    elif lead.status == STATUS_BOOKING_LINK_SENT:
        transition(db, lead, STATUS_BOOKING_PENDING)
        return {"status": "booking_pending", "message": "...", "lead_status": lead.status}
    elif lead.status == STATUS_TOUR_CONVERSION_OFFERED:
        return await _handle_tour_conversion_offered(db, lead, message_text, dry_run)
    elif lead.status == STATUS_WAITLISTED:
        return {"status": "waitlisted", "message": render_message("tour_waitlisted", lead_id=lead.id), "lead_status": lead.status}
    elif lead.status == STATUS_BOOKED:
        return {"status": "booked", "message": "Your booking is confirmed! ...", "lead_status": lead.status}
    elif lead.status == STATUS_NEEDS_ARTIST_REPLY:
        return await _handle_needs_artist_reply(db, lead, message_text, dry_run)
    elif lead.status in [STATUS_NEEDS_FOLLOW_UP, STATUS_NEEDS_MANUAL_FOLLOW_UP]:
        return {"status": "manual_followup", "message": "A team member will reach out ...", "lead_status": lead.status}
    elif lead.status == STATUS_REJECTED:
        return {"status": "rejected", "message": "Thank you for your interest. ...", "lead_status": lead.status}
    elif lead.status == STATUS_OPTOUT:
        if is_opt_back_in_message(message_text):
            transition(db, lead, STATUS_NEW)
            lead.current_step = 0
            commit_and_refresh(db, lead)
            return await _handle_new_lead(db, lead, dry_run)
        return {"status": "opted_out", "message": render_message("opt_out_prompt", lead_id=lead.id), "lead_status": lead.status}
    elif lead.status in [STATUS_ABANDONED, STATUS_STALE]:
        lead.last_client_message_at = func.now()
        transition(db, lead, STATUS_NEW)
        lead.current_step = 0
        commit_and_refresh(db, lead)
        return await _handle_new_lead(db, lead, dry_run)
    else:
        lead.status = STATUS_NEW
        lead.current_step = 0
        commit_and_refresh(db, lead)
        return await _handle_new_lead(db, lead, dry_run)
```

**Full source:** `app/services/conversation/conversation.py` lines 88–293.

---

## 9. transition — `app.services.conversation.state_machine.transition`

```python
def transition(
    db: Session,
    lead: Lead,
    to_status: str,
    reason: str | None = None,
    update_timestamp: bool = True,
    lock_row: bool = True,
) -> bool:
    lead_id = lead.id
    from_status = lead.status
    if not is_transition_allowed(from_status, to_status):
        logger.warning(f"Invalid status transition attempted: {from_status} -> {to_status} for lead {lead.id}")
        raise ValueError(f"Invalid status transition: {from_status} -> {to_status}. ...")
    if lock_row:
        stmt = select(Lead).where(Lead.id == lead_id).with_for_update()
        locked_lead = db.execute(stmt).scalar_one_or_none()
        if not locked_lead:
            raise ValueError(f"Lead {lead_id} not found")
        if locked_lead.status != from_status:
            logger.warning(f"Lead {lead_id} status changed during transition: ...")
            raise ValueError(f"Lead status changed during transition. ...")
        lead = locked_lead
    lead.status = to_status
    if update_timestamp:
        now = func.now()
        if to_status == STATUS_QUALIFYING and not lead.qualifying_started_at:
            lead.qualifying_started_at = now
        elif to_status == STATUS_PENDING_APPROVAL:
            lead.pending_approval_at = now
        # ... (other status-specific timestamps)
    if reason and to_status == STATUS_NEEDS_ARTIST_REPLY:
        lead.handover_reason = reason
    commit_and_refresh(db, lead)
    logger.info(f"Lead {lead.id} transitioned: {from_status} -> {to_status}" + (f" (reason: {reason})" if reason else ""))
    return True
```

**Full source:** `app/services/conversation/state_machine.py` lines 199–304.

---

## 10. advance_step_if_at — `app.services.conversation.state_machine.advance_step_if_at`

```python
def advance_step_if_at(
    db: Session,
    lead_id: int,
    expected_step: int,
) -> tuple[bool, Lead | None]:
    # Safety guard: detect pending changes before UPDATE
    n_new, n_dirty, n_deleted = len(db.new), len(db.dirty), len(db.deleted)
    if n_new or n_dirty or n_deleted:
        warn(db=db, event_type=EVENT_ADVANCE_STEP_PENDING_CHANGES, lead_id=lead_id, payload={...})
    stmt = (
        update(Lead)
        .where(Lead.id == lead_id)
        .where(Lead.current_step == expected_step)
        .values(current_step=expected_step + 1)
    )
    result = db.execute(stmt)
    db.commit()
    if getattr(result, "rowcount", 0) == 0:
        lead = get_lead_or_none(db, lead_id)
        if lead and lead.current_step != expected_step:
            warn(db=db, event_type=EVENT_ATOMIC_UPDATE_CONFLICT, lead_id=lead_id, payload={...})
        return False, None
    lead = get_lead_or_none(db, lead_id)
    if not lead:
        return False, None
    db.refresh(lead)
    logger.info(f"Lead {lead_id} step advanced: {expected_step} -> {lead.current_step}")
    return True, lead
```

**Full source:** `app/services/conversation/state_machine.py` lines 306–374.

---

## 11. _handle_qualifying_lead — `app.services.conversation.conversation_qualifying._handle_qualifying_lead`

**Summary:** Gets current question by step; checks 24h window (if closed, sends template and returns); handles attachment-at-wrong-step ack; opt-out → _handle_opt_out; human/refund/delete-data → handover; bundle guards (wrong field, multi-answer); parses answer; on reference_images step handles media; advances step with advance_step_if_at; saves LeadAnswer; at last question calls _complete_qualification (transition to PENDING_APPROVAL); otherwise sends next question.  
**Full source:** `app/services/conversation/conversation_qualifying.py` lines 85–~980 (long function).

---

## 12. _handle_booking_pending — `app.services.conversation.conversation_booking._handle_booking_pending`

**Summary:** If lead has suggested_slots_json, parses slot selection (parse_slot_selection_logged); if valid selection re-checks calendar availability; if slot unavailable → transition to COLLECTING_TIME_WINDOWS and send fallback; if available sets selected_slot_* and sends confirmation; handles tour conversion offered and NEEDS_ARTIST_REPLY branches.  
**Full source:** `app/services/conversation/conversation_booking.py` lines 40–~375.

---

## 13. get_or_create_lead — `app.services.leads.leads.get_or_create_lead`

```python
def get_or_create_lead(db: Session, wa_from: str) -> Lead:
    if not wa_from or not isinstance(wa_from, str):
        raise ValueError("wa_from must be a non-empty string")
    try:
        stmt = select(Lead).where(Lead.wa_from == wa_from).order_by(desc(Lead.created_at))
        leads = db.execute(stmt).scalars().all()
        for lead in leads:
            if lead.status in ACTIVE_STATUSES:
                return lead
        if leads:
            most_recent = leads[0]
            if most_recent.status in INACTIVE_STATUSES:
                pass  # fall through to create
            else:
                return most_recent
        lead = Lead(wa_from=wa_from, status="NEW")
        db.add(lead)
        commit_and_refresh(db, lead)
        log_lead_to_sheets(db, lead)
        return lead
    except SQLAlchemyError:
        db.rollback()
        raise
```

**Full source:** `app/services/leads/leads.py` lines 50–106.

---

## 14. update_lead_status_if_matches — `app.services.safety.update_lead_status_if_matches`

```python
def update_lead_status_if_matches(
    db: Session, lead_id: int, expected_status: str, new_status: str, **updates
) -> tuple[bool, Lead | None]:
    stmt = (
        update(Lead)
        .where(Lead.id == lead_id)
        .where(Lead.status == expected_status)
        .values(status=new_status, **updates)
    )
    result = db.execute(stmt)
    db.commit()
    if getattr(result, "rowcount", 0) == 0:
        lead = get_lead_or_none(db, lead_id)
        if not lead:
            logger.warning(f"Lead {lead_id} not found for status update")
            return False, None
        record_failed_atomic_update(...)
        logger.warning(f"Lead {lead_id} status mismatch: expected '{expected_status}', got '{lead.status}'")
        warn(db=db, event_type=EVENT_ATOMIC_UPDATE_CONFLICT, lead_id=lead_id, payload={...})
        return False, lead
    lead = get_lead_or_none(db, lead_id)
    if not lead:
        return False, None
    db.refresh(lead)
    return True, lead
```

**Full source:** `app/services/safety.py` lines 31–100.

---

## 15. check_processed_event — `app.services.safety.check_processed_event`

```python
def check_processed_event(
    db: Session,
    event_id: str,
    provider: str = PROVIDER_STRIPE,
) -> tuple[bool, ProcessedMessage | None]:
    stmt = select(ProcessedMessage).where(
        ProcessedMessage.provider == provider,
        ProcessedMessage.message_id == event_id,
    )
    existing = db.execute(stmt).scalar_one_or_none()
    if existing:
        logger.info(f"Event {event_id} already processed at {existing.processed_at}")
        record_duplicate_event(event_type=existing.event_type or "unknown", event_id=event_id)
        return True, existing
    return False, None
```

---

## 16. record_processed_event — `app.services.safety.record_processed_event`

```python
def record_processed_event(
    db: Session,
    event_id: str,
    event_type: str,
    lead_id: int | None = None,
    provider: str = PROVIDER_STRIPE,
) -> ProcessedMessage:
    try:
        processed = ProcessedMessage(
            provider=provider,
            message_id=event_id,
            event_type=event_type,
            lead_id=lead_id,
        )
        db.add(processed)
        commit_and_refresh(db, processed)
        return processed
    except IntegrityError:
        db.rollback()
        stmt = select(ProcessedMessage).where(...)
        existing = db.execute(stmt).scalar_one_or_none()
        if existing:
            logger.info(f"Event {event_id} processed by concurrent request")
            return existing
        logger.error(...)
        raise
```

**Full source:** `app/services/safety.py` lines 137–186.

---

## 17. create_checkout_session — `app.services.integrations.stripe_service.create_checkout_session`

```python
def create_checkout_session(
    lead_id: int,
    amount_pence: int,
    success_url: str,
    cancel_url: str,
    metadata: dict | None = None,
) -> dict:
    try:
        session_metadata = {"lead_id": str(lead_id), "type": "deposit", "amount_pence": str(amount_pence)}
        if metadata:
            session_metadata.update(metadata)
        if "deposit_rule_version" not in session_metadata:
            session_metadata["deposit_rule_version"] = settings.deposit_rule_version
        expires_at = datetime.now(UTC) + timedelta(hours=24)
        if STRIPE_TEST_MODE and settings.stripe_secret_key == "sk_test_test":
            return {"checkout_session_id": f"cs_test_{lead_id}_{amount_pence}", "checkout_url": "...", "amount_pence": amount_pence, "expires_at": expires_at}
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price_data": {"currency": "gbp", "product_data": {"name": "Tattoo Booking Deposit", "description": f"Deposit for booking request #{lead_id}"}, "unit_amount": amount_pence}, "quantity": 1}],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=session_metadata,
            client_reference_id=str(lead_id),
            expires_at=int(expires_at.timestamp()),
        )
        return {"checkout_session_id": checkout_session.id, "checkout_url": checkout_session.url, "amount_pence": amount_pence, "expires_at": expires_at}
    except stripe.error.StripeError as e:
        logger.error(...)
        raise
```

**Full source:** `app/services/integrations/stripe_service.py` lines 23–115.

---

## 18. verify_webhook_signature — `app.services.integrations.stripe_service.verify_webhook_signature`

```python
def verify_webhook_signature(payload: bytes, signature: str) -> dict:
    if STRIPE_TEST_MODE and settings.stripe_webhook_secret == "whsec_test":
        import json
        try:
            event = json.loads(payload.decode("utf-8"))
            logger.info(f"[TEST MODE] Accepting test Stripe webhook event: {event.get('type')}")
            return cast(dict[str, Any], event)
        except Exception as e:
            raise ValueError(f"Invalid test webhook payload: {e}") from e
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, settings.stripe_webhook_secret,
        )
        return cast(dict[str, Any], event)
    except ValueError as e:
        logger.error(f"Invalid Stripe webhook signature: {e}")
        raise
    except Exception as e:
        logger.error(f"Error verifying Stripe webhook: {e}")
        raise
```

**Full source:** `app/services/integrations/stripe_service.py` lines 117–156.

---

## 19. get_available_slots — `app.services.integrations.calendar_service.get_available_slots`

**Summary:** Uses calendar_rules (timezone, lookahead, min_advance_hours, session_duration, is_within_working_hours). If calendar disabled or no calendar_id, returns _get_mock_available_slots; otherwise (when implemented) would call Google Calendar API. Currently returns mock slots with rules applied.  
**Full source:** `app/services/integrations/calendar_service.py` lines 140–224.

---

## 20. send_slot_suggestions_to_client — `app.services.integrations.calendar_service.send_slot_suggestions_to_client`

**Summary:** Feature-flag check; get_available_slots(); if no slots → transition to COLLECTING_TIME_WINDOWS, format_time_windows_request, send_with_window_check, log_lead_to_sheets, return False; else store suggested_slots_json on lead, format_slot_suggestions(), send_with_window_check, update last_bot_message_at, commit, return True.  
**Full source:** `app/services/integrations/calendar_service.py` lines 335–465.

---

## 21. log_lead_to_sheets — `app.services.integrations.sheets.log_lead_to_sheets`

**Summary:** feature_sheets_enabled check; load LeadAnswer rows for lead; build row_data (lead_id, wa_from, answers, status, timestamps, etc.); _get_sheets_service(); _upsert_lead_row_real(service, row_data, lead.id) or stub log.  
**Full source:** `app/services/integrations/sheets.py` lines 121–272.

---

## 22. send_whatsapp_message — `app.services.messaging.messaging.send_whatsapp_message`

```python
async def send_whatsapp_message(
    to: str,
    message: str,
    dry_run: bool = True,
) -> dict:
    if not dry_run:
        if not settings.whatsapp_access_token or ...:
            raise ValueError("WhatsApp access token not configured. ...")
        if not settings.whatsapp_phone_number_id or ...:
            raise ValueError("WhatsApp phone number ID not configured. ...")
    if os.environ.get("PYTEST_CURRENT_TEST") or not settings.whatsapp_access_token or ...:
        dry_run = True
    if dry_run:
        logger.info(f"[DRY-RUN] Would send WhatsApp message to {to}: {message}")
        return {"status": "dry_run", "message_id": None, "to": to, "message": message}
    try:
        url = f"https://graph.facebook.com/v18.0/{settings.whatsapp_phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}", "Content-Type": "application/json"}
        payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": message}}
        async with create_httpx_client() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            return {"status": "sent", "message_id": result.get("messages", [{}])[0].get("id"), "to": to}
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
        raise
```

**Full source:** `app/services/messaging/messaging.py` lines 12–93.

---

## 23. send_with_window_check — `app.services.messaging.whatsapp_window.send_with_window_check`

**Summary:** If lead.status == STATUS_OPTOUT return opted_out; is_within, window_expires_at = is_within_24h_window(lead); if is_within: apply_voice(message), optionally write_outbox, send_whatsapp_message, mark_outbox_sent, return result with window_status; else: send_template_message (template_name/template_params), return with window_status "closed".  
**Full source:** `app/services/messaging/whatsapp_window.py` lines 54–~130 (and send_template_message below).

---

## 24. startup_check_templates — `app.services.messaging.template_check.startup_check_templates`

**Summary:** If not whatsapp_access_token return templates_configured=[], whatsapp_enabled=False; validate_template_registry(); build templates_status; if templates_missing log CRITICAL and optionally asyncio.run(send_system_alert(...)); return dict with templates_configured, templates_missing, templates_status, registry_valid, message_types_without_templates.  
**Full source:** `app/services/messaging/template_check.py` lines 17–101.

---

## 25. attempt_upload_attachment — `app.services.integrations.media_upload.attempt_upload_attachment`

```python
async def attempt_upload_attachment(db: Session, attachment_id: int) -> None:
    attachment = db.get(Attachment, attachment_id)
    if not attachment:
        logger.warning(f"Attachment {attachment_id} not found")
        return
    if attachment.upload_status == "UPLOADED":
        return
    if attachment.upload_status == "FAILED" and attachment.upload_attempts >= 5:
        return
    attachment.upload_attempts += 1
    attachment.last_attempt_at = datetime.now(UTC)
    commit_and_refresh(db, attachment)
    media_id = attachment.whatsapp_media_id
    if not media_id:
        attachment.last_error = "Missing whatsapp_media_id"
        ...
        db.commit()
        return
    try:
        media_bytes, content_type = await _download_whatsapp_media(media_id)
        bucket = settings.supabase_storage_bucket or "reference-images"
        object_key = f"leads/{attachment.lead_id}/{attachment.id}"
        await _upload_to_supabase(bucket, object_key, media_bytes, content_type)
        attachment.upload_status = "UPLOADED"
        attachment.uploaded_at = datetime.now(UTC)
        attachment.bucket = bucket
        attachment.object_key = object_key
        attachment.content_type = content_type
        attachment.size_bytes = len(media_bytes)
        attachment.last_error = None
        commit_and_refresh(db, attachment)
    except Exception as e:
        db.rollback()
        db.refresh(attachment)
        attachment.last_error = str(e)[:500]
        if attachment.upload_attempts >= 5:
            attachment.upload_status = "FAILED"
            attachment.failed_at = datetime.now(UTC)
        db.commit()
        error(db=db, event_type=EVENT_MEDIA_UPLOAD_FAILURE, lead_id=attachment.lead_id, payload={...})
```

**Full source:** `app/services/integrations/media_upload.py` lines 23–110.

---

## 26. check_and_send_qualifying_reminder — `app.services.messaging.reminders.check_and_send_qualifying_reminder`

**Summary:** feature_reminders_enabled, STATUS_OPTOUT, STATUS_QUALIFYING checks; 12h/36h threshold; already_sent check; hours_passed vs threshold; check_and_record_processed_event for idempotency; build reminder message and template (reminder 2 uses template); asyncio.run(send_with_window_check(...)); set reminder_qualifying_sent_at (reminder 1), commit_and_refresh; return status/sent_at.  
**Full source:** `app/services/messaging/reminders.py` lines 40–181.

---

## 27. check_and_mark_abandoned — `app.services.messaging.reminders.check_and_mark_abandoned`

```python
def check_and_mark_abandoned(
    db: Session,
    lead: Lead,
    hours_threshold: int = 48,
) -> dict:
    if lead.status != STATUS_QUALIFYING:
        return {"status": "skipped", "reason": f"Lead not in {STATUS_QUALIFYING} status"}
    if lead.abandoned_at:
        return {"status": "already_abandoned", "abandoned_at": iso_or_none(lead.abandoned_at)}
    if not lead.last_client_message_at:
        return {"status": "skipped", "reason": "No last client message timestamp"}
    now = datetime.now(UTC)
    last_message = dt_replace_utc(lead.last_client_message_at)
    ...
    hours_passed = (now - last_message).total_seconds() / 3600
    if hours_passed < hours_threshold:
        return {"status": "not_due", "hours_passed": hours_passed}
    lead.status = STATUS_ABANDONED
    lead.abandoned_at = func.now()
    db.commit()
    return {"status": "abandoned", "abandoned_at": iso_or_none(lead.abandoned_at)}
```

**Full source:** `app/services/messaging/reminders.py` lines 184–225.

---

## 28. approve_lead — `app.api.admin.approve_lead`

```python
@router.post("/leads/{lead_id}/approve")
async def approve_lead(
    lead: Lead = Depends(get_lead_or_404),
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    success, lead = update_lead_status_if_matches(
        db=db,
        lead_id=lead.id,
        expected_status=STATUS_PENDING_APPROVAL,
        new_status=STATUS_AWAITING_DEPOSIT,
        approved_at=func.now(),
        last_admin_action="approve",
        last_admin_action_at=func.now(),
    )
    if not success:
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        raise HTTPException(status_code=400, detail=status_mismatch_detail_admin("approve lead", lead.status, STATUS_PENDING_APPROVAL))
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    log_lead_to_sheets(db, lead)
    try:
        await send_slot_suggestions_to_client(db=db, lead=lead, dry_run=settings.whatsapp_dry_run)
    except Exception as e:
        logger.error(f"Failed to send slot suggestions to lead {lead.id}: {e}")
    try:
        await notify_artist(db=db, lead=lead, event_type=EVENT_PENDING_APPROVAL, dry_run=settings.whatsapp_dry_run)
    except Exception as e:
        logger.error(f"Failed to notify artist of approval for lead {lead.id}: {e}")
    return {"success": True, "message": "Lead approved. Slot suggestions sent to client.", "lead_id": lead.id, "status": lead.status}
```

**Full source:** `app/api/admin.py` lines 223–289.

---

## 29. send_booking_link — `app.api.admin.send_booking_link`

```python
@router.post("/leads/{lead_id}/send-booking-link")
def send_booking_link(
    request: SendBookingLinkRequest,
    lead: Lead = Depends(get_lead_or_404),
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    success, lead = update_lead_status_if_matches(
        db=db, lead_id=lead.id,
        expected_status=STATUS_DEPOSIT_PAID,
        new_status=STATUS_BOOKING_LINK_SENT,
        booking_link=request.booking_url,
        booking_tool=request.booking_tool,
        booking_link_sent_at=func.now(),
        last_admin_action="send_booking_link",
        last_admin_action_at=func.now(),
    )
    if not success:
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        raise HTTPException(status_code=400, detail=status_mismatch_detail_admin("send booking link for lead", lead.status, STATUS_DEPOSIT_PAID))
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    log_lead_to_sheets(db, lead)
    return {"success": True, "message": "Booking link will be sent (not yet implemented).", "lead_id": lead.id, "status": lead.status, "booking_link": request.booking_url}
```

**Full source:** `app/api/admin.py` lines 466–512.

---

## 30. mark_booked — `app.api.admin.mark_booked`

```python
@router.post("/leads/{lead_id}/mark-booked")
def mark_booked(
    lead: Lead = Depends(get_lead_or_404),
    db: Session = Depends(get_db),
    _auth: bool = Security(get_admin_auth),
):
    from app.services.conversation import STATUS_BOOKING_PENDING
    success, lead = update_lead_status_if_matches(
        db=db, lead_id=lead.id,
        expected_status=STATUS_BOOKING_PENDING,
        new_status=STATUS_BOOKED,
        booked_at=func.now(),
        last_admin_action="mark_booked",
        last_admin_action_at=func.now(),
    )
    if not success:
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        if lead.status == STATUS_BOOKING_LINK_SENT:
            lead.status = STATUS_BOOKED
            lead.booked_at = func.now()
            lead.last_admin_action = "mark_booked"
            lead.last_admin_action_at = func.now()
            commit_and_refresh(db, lead)
        else:
            raise HTTPException(status_code=400, detail=status_mismatch_detail_admin("mark lead as booked", lead.status, STATUS_BOOKING_PENDING))
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    log_lead_to_sheets(db, lead)
    return {"success": True, "message": "Lead marked as booked.", "lead_id": lead.id, "status": lead.status}
```

**Full source:** `app/api/admin.py` lines 515–568.

---

## 31. execute_action — `app.api.actions.execute_action`

**Summary:** POST /a/{token}. validate_action_token(db, token); if error return HTML error page; handler = ACTION_HANDLERS[action_token.action_type]; then inline logic for approve/reject/send_deposit/send_booking_link/mark_booked (status checks, lead updates, commit_and_refresh, log_lead_to_sheets, result dict); return HTML success page with result message.  
**Full source:** `app/api/actions.py` lines 138–~335.

---

## 32. validate_action_token — `app.services.action_tokens.validate_action_token`

```python
def validate_action_token(db: Session, token: str) -> tuple[ActionToken | None, str | None]:
    stmt = select(ActionToken).where(ActionToken.token == token)
    action_token = db.execute(stmt).scalar_one_or_none()
    if not action_token:
        return None, ERR_INVALID_TOKEN
    if action_token.used:
        return None, ERR_ALREADY_USED
    return _validate_action_token_checks(db, action_token)


def _validate_action_token_checks(
    db: Session, action_token: ActionToken
) -> tuple[ActionToken | None, str | None]:
    now = datetime.now(UTC)
    expires = dt_replace_utc(action_token.expires_at)
    if expires is None or now > expires:
        return None, ERR_EXPIRED
    lead = get_lead_or_none(db, action_token.lead_id)
    if not lead:
        return None, ERR_LEAD_NOT_FOUND
    if lead.status != action_token.required_status:
        return None, _err_status_mismatch(lead.status, action_token.required_status)
    return action_token, None
```

**Full source:** `app/services/action_tokens.py` lines 40–59, 116–136.

---

## 33. commit_and_refresh — `app.db.helpers.commit_and_refresh`

```python
def commit_and_refresh(db: Session, *instances) -> None:
    """
    Commit the transaction and refresh each given instance.
    Use only where the code already did db.commit() followed by db.refresh(instance).
    """
    db.commit()
    for obj in instances:
        if obj is not None:
            db.refresh(obj)
```

**Full source:** `app/db/helpers.py` lines 6–14.
