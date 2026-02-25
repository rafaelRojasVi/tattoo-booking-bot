# Core API functions — code reference

All main entry points of the Tattoo Booking Bot API, with code. Routes are under `/webhooks`, `/admin`, `/a/`, `/demo`; root has `/health` and `/ready`.

---

## 1. App bootstrap and root endpoints

**File:** `app/main.py`

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
        if not settings.stripe_webhook_secret or settings.stripe_webhook_secret == "whsec_test":
            production_errors.append("STRIPE_WEBHOOK_SECRET ...")
        if settings.demo_mode:
            production_errors.append("DEMO_MODE must be False in production. ...")
        if production_errors:
            raise RuntimeError("Production environment validation failed:\n\n" + "\n".join(production_errors))

    logger.info("Startup: Configuration loaded - ...")
    if settings.demo_mode:
        logger.warning("DEMO MODE ENABLED - DO NOT USE IN PROD")
    template_status = startup_check_templates()
    logger.info(f"Startup: Template check completed - {len(template_status['templates_configured'])} templates configured")
    yield

app = FastAPI(title="Tattoo Booking Bot", lifespan=lifespan)
app.add_middleware(RateLimitMiddleware, rate_limited_paths=["/admin", "/a/"])
app.add_middleware(CorrelationIdMiddleware)

@app.get("/health")
def health():
    from app.services.messaging.template_check import REQUIRED_TEMPLATES
    return {
        "ok": True,
        "templates_configured": REQUIRED_TEMPLATES,
        "features": {
            "sheets_enabled": settings.feature_sheets_enabled,
            "calendar_enabled": settings.feature_calendar_enabled,
            "reminders_enabled": settings.feature_reminders_enabled,
            "notifications_enabled": settings.feature_notifications_enabled,
            "panic_mode_enabled": settings.feature_panic_mode_enabled,
        },
        "integrations": {
            "google_sheets_enabled": settings.google_sheets_enabled,
            "google_calendar_enabled": settings.google_calendar_enabled,
        },
    }

@app.get("/ready")
def ready(db: Session = Depends(get_db)):
    from sqlalchemy import text
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "database": "connected"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return JSONResponse(status_code=503, content={"ok": False, "database": "disconnected", "error": str(e)})

app.include_router(webhooks_router, prefix="/webhooks")
app.include_router(admin_router, prefix="/admin", tags=["admin"])
app.include_router(actions_router, tags=["actions"])
app.include_router(demo_router, prefix="/demo", tags=["demo"])
```

---

## 2. Admin auth

**File:** `app/api/auth.py`

```python
API_KEY_HEADER = "X-Admin-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)

def get_admin_auth(api_key: str | None = Security(api_key_header)) -> bool:
    if settings.app_env == "production" and not settings.admin_api_key:
        raise RuntimeError(
            "ADMIN_API_KEY must be set in production environment. "
            "Set ADMIN_API_KEY environment variable or set APP_ENV=dev for development."
        )
    if not settings.admin_api_key:
        return True
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key. Provide X-Admin-API-Key header.")
    if api_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid API key.")
    return True
```

---

## 3. Webhooks

**File:** `app/api/webhooks.py`

### 3.1 WhatsApp verification (GET)

```python
@router.get("/whatsapp")
def whatsapp_verify(
    hub_mode: str | None = None,
    hub_verify_token: str | None = None,
    hub_challenge: str | None = None,
):
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return Response(content=hub_challenge or "", media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")
```

### 3.2 WhatsApp inbound (POST) — flow summary

```python
@router.post("/whatsapp")
async def whatsapp_inbound(request, background_tasks, db: Session = Depends(get_db)):
    # 1) Correlation ID
    correlation_id = get_correlation_id(request)

    # 2) Raw body + signature verification (must read before JSON)
    raw_body = await request.body()
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not verify_whatsapp_signature(raw_body, signature_header):
        warn(db, event_type=EVENT_WHATSAPP_SIGNATURE_VERIFICATION_FAILURE, ...)
        return JSONResponse(status_code=403, content={"received": False, "error": "Invalid webhook signature"})

    # 3) Parse JSON
    payload = json.loads(raw_body.decode("utf-8"))

    # 4) Extract entry -> changes -> value -> messages (most recent first); wa_from, text, message_id, message_type

    # 5) Idempotency: insert ProcessedMessage(provider, message_id) first; on unique violation return duplicate

    # 6) get_or_create_lead(db, wa_from)

    # 7) Pilot mode: if enabled and wa_from not in allowlist -> send polite message, log EVENT_PILOT_MODE_BLOCKED, return

    # 8) If text: optional out-of-order check (message timestamp < last_client_message_at -> return out_of_order)
    #    conversation_result = await handle_inbound_message(db, lead, message_text, dry_run=settings.whatsapp_dry_run, has_media=...)
    #    Update ProcessedMessage.lead_id, commit
    #    If media (image/document): create Attachment(PENDING), background_tasks.add_task(attempt_upload_attachment_job, attachment.id)
    #    return { received, lead_id, wa_from, text, message_type, conversation: conversation_result }

    # 9) If no text but media: still create Attachment, call handle_inbound_message(..., message_text="", has_media=True), return
    # 10) return { received, lead_id, wa_from, text, message_type }
```

### 3.3 Duplicate message detection (helper)

```python
def _is_processed_message_unique_violation(exc: IntegrityError) -> bool:
    orig = exc.orig
    if orig is None:
        return False
    if hasattr(orig, "pgcode") and orig.pgcode == "23505":
        return True
    err_msg = str(orig).lower() if orig else ""
    if "unique constraint" in err_msg or "unique constraint failed" in err_msg:
        return True
    return False
```

### 3.4 Stripe webhook (POST) — flow summary

```python
@router.post("/stripe")
async def stripe_webhook(request, background_tasks, db: Session = Depends(get_db)):
    body = await request.body()
    signature = request.headers.get("stripe-signature")
    if not signature:
        return JSONResponse(status_code=400, content={"error": "Missing stripe-signature header"})

    try:
        event = verify_webhook_signature(body, signature)
    except ValueError as e:
        warn(db, event_type=EVENT_STRIPE_SIGNATURE_VERIFICATION_FAILURE, ...)
        return JSONResponse(status_code=400, content={"error": "Invalid webhook signature"})

    event_type = event.get("type")
    event_data = event.get("data", {}).get("object")
    event_id = event.get("id")

    if event_type == "checkout.session.completed":
        checkout_session_id = event_data.get("id")
        lead_id = _safe_parse_lead_id(metadata.get("lead_id")) or _safe_parse_lead_id(event_data.get("client_reference_id"))
        if not lead_id or lead_id <= 0:
            return JSONResponse(status_code=400, content={"error": "No lead_id found in checkout session"})

        lead = db.get(Lead, lead_id)
        if not lead:
            return JSONResponse(status_code=404, content={"error": f"Lead {lead_id} not found"})

        # Session ID mismatch check
        if lead.stripe_checkout_session_id and lead.stripe_checkout_session_id != checkout_session_id:
            error(db, event_type=EVENT_STRIPE_SESSION_ID_MISMATCH, ...)
            return JSONResponse(status_code=400, content={"error": "Checkout session ID mismatch", ...})

        # Idempotency: check_processed_event(event_id); if duplicate return { received, type: "duplicate", ... }

        # Atomic update: update_lead_status_if_matches(lead_id, expected_status=STATUS_AWAITING_DEPOSIT, new_status=STATUS_DEPOSIT_PAID, ...)
        success, lead = update_lead_status_if_matches(db, lead_id=lead_id, expected_status=STATUS_AWAITING_DEPOSIT,
            new_status=STATUS_DEPOSIT_PAID, stripe_payment_status="paid", deposit_paid_at=func.now(), ...)

        if not success:
            if lead and lead.status == STATUS_DEPOSIT_PAID:
                return { "received": True, "type": "duplicate", ... }
            if lead and lead.status == STATUS_NEEDS_ARTIST_REPLY:
                success, lead = update_lead_status_if_matches(..., expected_status=STATUS_NEEDS_ARTIST_REPLY, new_status=STATUS_DEPOSIT_PAID, ...)
            if not success:
                error(db, event_type=EVENT_STRIPE_WEBHOOK_FAILURE, ...)
                return JSONResponse(status_code=400, content={"error": f"Lead {lead_id} is in status '{lead.status}'", ...})

        # Set BOOKING_PENDING, commit
        lead.status = STATUS_BOOKING_PENDING
        lead.booking_pending_at = func.now()
        db.commit()
        db.refresh(lead)

        background_tasks.add_task(_log_lead_to_sheets_background, lead_id=lead_id, correlation_id=get_correlation_id(request))
        # Send WhatsApp confirmation (send_with_window_check), update last_bot_message_at
        # notify_artist(EVENT_DEPOSIT_PAID)
        record_processed_event(db, event_id=event_id_str, event_type=EVENT_STRIPE_CHECKOUT_SESSION_COMPLETED, lead_id=lead_id)
        return { "received": True, "type": "checkout.session.completed", "lead_id", "checkout_session_id", "status": lead.status }

    return { "received": True, "type": event_type, "message": "Event received but not handled" }
```

### 3.5 Background Sheets logging

```python
def _log_lead_to_sheets_background(lead_id: int, correlation_id: str | None = None) -> None:
    """Background task: open fresh DB session, log_lead_to_sheets(db, lead), log SystemEvent on failure."""
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        lead = db.get(Lead, lead_id)
        if lead:
            log_lead_to_sheets(db, lead)
    except Exception as e:
        error(db, event_type=EVENT_SHEETS_BACKGROUND_LOG_FAILURE, lead_id=lead_id, payload={"error": str(e)}, exc=e)
    finally:
        db.close()
```

---

## 4. Admin endpoints

**File:** `app/api/admin.py`  
All admin routes use `_auth: bool = Security(get_admin_auth)`.

### 4.1 Outbox

```python
@router.get("/outbox")
def list_outbox_messages(status: str | None = None, limit: int = 50, db: Session = Depends(get_db), _auth=...):
    stmt = select(OutboxMessage).order_by(desc(OutboxMessage.created_at))
    if status:
        stmt = stmt.where(OutboxMessage.status == status.upper())
    stmt = stmt.limit(max(0, min(limit, 100)))
    rows = db.execute(stmt).scalars().all()
    return [{"id", "lead_id", "channel", "status", "attempts", "last_error", "next_retry_at", "created_at"} for r in rows]

@router.post("/outbox/retry")
def retry_outbox_messages(limit: int = 50, db=..., _auth=...):
    from app.services.messaging.outbox_service import retry_due_outbox_rows
    results = retry_due_outbox_rows(db, limit=limit)
    return {"outbox_retry": results}
```

### 4.2 Lead actions (core)

```python
@router.post("/leads/{lead_id}/approve")
async def approve_lead(lead_id: int, db=..., _auth=...):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    success, lead = update_lead_status_if_matches(db, lead_id=lead_id,
        expected_status=STATUS_PENDING_APPROVAL, new_status=STATUS_AWAITING_DEPOSIT,
        approved_at=func.now(), last_admin_action="approve", last_admin_action_at=func.now())
    if not success:
        raise HTTPException(status_code=400, detail=f"Cannot approve lead in status '{lead.status}'.")
    log_lead_to_sheets(db, lead)
    await send_slot_suggestions_to_client(db, lead, dry_run=settings.whatsapp_dry_run)
    await notify_artist(db, lead, event_type=EVENT_PENDING_APPROVAL, dry_run=...)
    return {"success": True, "message": "Lead approved. Slot suggestions sent to client.", "lead_id", "status": lead.status}

@router.post("/leads/{lead_id}/reject")
def reject_lead(lead_id: int, request: RejectRequest, db=..., _auth=...):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.status == STATUS_REJECTED:
        raise HTTPException(status_code=400, detail="Lead is already rejected")
    if lead.status == STATUS_BOOKED:
        raise HTTPException(status_code=400, detail="Cannot reject a booked lead")
    lead.status = STATUS_REJECTED
    lead.rejected_at = func.now()
    lead.last_admin_action = "reject"
    lead.last_admin_action_at = func.now()
    if request.reason:
        lead.admin_notes = (lead.admin_notes or "") + f"\nRejection reason: {request.reason}"
    db.commit()
    db.refresh(lead)
    log_lead_to_sheets(db, lead)
    return {"success": True, "message": "Lead rejected.", "lead_id", "status": lead.status}

@router.post("/leads/{lead_id}/send-deposit")
async def send_deposit(lead_id: int, request: SendDepositRequest | None = None, db=..., _auth=...):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.status != STATUS_AWAITING_DEPOSIT:
        raise HTTPException(status_code=400, detail=f"Cannot send deposit link for lead in status '{lead.status}'.")
    # Optional: clear expired checkout session
    amount_pence = lead.deposit_amount_pence or lead.estimated_deposit_amount or request.amount_pence or get_deposit_amount(...) or settings.stripe_deposit_amount_pence
    lead.deposit_amount_pence = amount_pence
    lead.deposit_amount_locked_at = func.now()
    lead.deposit_rule_version = settings.deposit_rule_version
    lead.deposit_sent_at = func.now()
    lead.last_admin_action = "send_deposit"
    lead.last_admin_action_at = func.now()
    db.commit()
    db.refresh(lead)
    checkout_result = create_checkout_session(lead_id=lead.id, amount_pence=amount_pence, success_url=..., cancel_url=..., metadata={...})
    lead.stripe_checkout_session_id = checkout_result["checkout_session_id"]
    lead.deposit_checkout_expires_at = checkout_result.get("expires_at")
    db.commit()
    db.refresh(lead)
    log_lead_to_sheets(db, lead)
    deposit_message = format_deposit_link_message(checkout_result["checkout_url"], amount_pence, lead_id=lead.id)
    await send_with_window_check(db, lead, message=deposit_message, template_name=..., template_params=..., dry_run=...)
    lead.last_bot_message_at = func.now()
    db.commit()
    return {"success": True, "message": "Deposit link created and sent via WhatsApp.", "lead_id", "status", "deposit_amount_pence", "checkout_url", "checkout_session_id"}

@router.post("/leads/{lead_id}/send-booking-link")
def send_booking_link(lead_id: int, request: SendBookingLinkRequest, db=..., _auth=...):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    success, lead = update_lead_status_if_matches(db, lead_id=lead_id,
        expected_status=STATUS_DEPOSIT_PAID, new_status=STATUS_BOOKING_LINK_SENT,
        booking_link=request.booking_url, booking_tool=request.booking_tool,
        booking_link_sent_at=func.now(), last_admin_action="send_booking_link", last_admin_action_at=func.now())
    if not success:
        raise HTTPException(status_code=400, detail=f"Cannot send booking link for lead in status '{lead.status}'.")
    log_lead_to_sheets(db, lead)
    return {"success": True, "message": "Booking link will be sent (not yet implemented).", "lead_id", "status", "booking_link": request.booking_url}

@router.post("/leads/{lead_id}/mark-booked")
def mark_booked(lead_id: int, db=..., _auth=...):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    success, lead = update_lead_status_if_matches(db, lead_id=lead_id,
        expected_status=STATUS_BOOKING_PENDING, new_status=STATUS_BOOKED,
        booked_at=func.now(), last_admin_action="mark_booked", last_admin_action_at=func.now())
    if not success:
        raise HTTPException(status_code=400, detail=f"Cannot mark lead as booked in status '{lead.status}'.")
    log_lead_to_sheets(db, lead)
    return {"success": True, "message": "Lead marked as booked.", "lead_id", "status": lead.status}
```

### 4.3 Admin read endpoints (summary)

- **GET /admin/leads** — list leads (optional status filter, limit).
- **GET /admin/leads/{lead_id}** — lead detail + summary via `get_lead_summary(db, lead)`.
- **GET /admin/metrics** — metrics from funnel_metrics_service.
- **GET /admin/funnel** — funnel counts by status.
- **GET /admin/slot-parse-stats** — slot parse stats (last N days).
- **GET /admin/events** — system events (optional lead_id, limit).
- **GET /admin/debug/lead/{lead_id}** — debug view for lead.
- **POST /admin/events/retention-cleanup** — cleanup system events older than retention_days.
- **POST /admin/test-webhook-exception** — staging-only: simulate webhook exception (404 in production).
- **POST /admin/sweep-expired-deposits** — sweep expired deposit checkouts (status transitions).

---

## 5. Action token endpoints (WhatsApp action links)

**File:** `app/api/actions.py`

```python
ACTION_HANDLERS = {
    "approve": approve_lead,
    "reject": reject_lead,
    "send_deposit": send_deposit,
    "send_booking_link": send_booking_link,
    "mark_booked": mark_booked,
}

@router.get("/a/{token}", response_class=HTMLResponse)
def action_confirm_page(token: str, db: Session = Depends(get_db)):
    action_token, error = validate_action_token(db, token)
    if not action_token:
        return HTMLResponse(content=error_html(error), status_code=400)
    lead = action_token.lead
    action_desc = ACTION_DESCRIPTIONS.get(action_token.action_type, action_token.action_type)
    return HTMLResponse(content=confirm_page_html(lead, action_desc, token))  # Form POST to /a/{token}

@router.post("/a/{token}")
def execute_action(token: str, db: Session = Depends(get_db)):
    action_token, error = validate_action_token(db, token)
    if not action_token:
        return HTMLResponse(content=fail_html(error), status_code=400)
    handler = ACTION_HANDLERS.get(action_token.action_type)
    if not handler:
        return HTMLResponse(content="<h1>Unknown action type</h1>", status_code=400)
    # Execute inline: approve -> status PENDING_APPROVAL -> AWAITING_DEPOSIT, approved_at, log_lead_to_sheets
    # reject -> status REJECTED, rejected_at, log_lead_to_sheets
    # send_deposit -> lock amount, deposit_amount_locked_at, log_lead_to_sheets (no Stripe/WhatsApp in action flow)
    # send_booking_link -> return 400 (use admin endpoint)
    # mark_booked -> status BOOKED, booked_at, log_lead_to_sheets
    return HTMLResponse(content=success_html(result))
```

---

## 6. Demo endpoints (DEMO_MODE only)

**File:** `app/api/demo.py`

```python
def require_demo_mode():
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Not found")

@router.post("/demo/client/send")
async def demo_client_send(request: DemoClientSendRequest, db=..., demo_mode=Depends(require_demo_mode)):
    wa_from = request.from_number.replace("+", "").replace(" ", "").strip()
    if not wa_from:
        raise HTTPException(status_code=400, detail="from_number is required")
    message_text = request.text.strip()
    if request.image_url and request.image_url.strip():
        message_text += " " + request.image_url.strip()  # Simulate reference image
    lead = get_or_create_lead(db, wa_from=wa_from)
    conversation_result = await handle_inbound_message(db=db, lead=lead, message_text=message_text, dry_run=True, has_media=bool(request.image_url))
    return {"lead_id": lead.id, "wa_from": wa_from, "text": message_text, "conversation": conversation_result}

@router.get("/demo/lead/{lead_id}/messages")
async def demo_lead_messages(lead_id: int, db=..., demo_mode=Depends(require_demo_mode)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    messages = _build_demo_messages(db, lead)
    return {"lead_id": lead_id, "messages": messages}

@router.get("/demo/artist/inbox")
async def demo_artist_inbox(db=..., demo_mode=Depends(require_demo_mode)):
    # List leads in NEEDS_ARTIST_REPLY / NEEDS_FOLLOW_UP etc. with summary
    ...

@router.post("/demo/stripe/pay")
async def demo_stripe_pay(request: DemoStripePayRequest, db=..., demo_mode=Depends(require_demo_mode)):
    # Simulate Stripe checkout.session.completed (find lead, update status, send confirmation)
    ...

@router.get("/demo/client", response_class=HTMLResponse)
async def demo_client_page_html(demo_mode=Depends(require_demo_mode)):
    # HTML page for sending messages as client
    ...

@router.get("/demo/artist", response_class=HTMLResponse)
async def demo_artist_page_html(demo_mode=Depends(require_demo_mode)):
    # HTML page for artist inbox
    ...
```

---

## Route summary

| Method | Path | Purpose |
|--------|------|--------|
| GET | /health | Health check + features/templates |
| GET | /ready | DB connectivity |
| GET | /webhooks/whatsapp | WhatsApp subscription verification |
| POST | /webhooks/whatsapp | WhatsApp inbound message |
| POST | /webhooks/stripe | Stripe webhooks (checkout.session.completed) |
| GET | /admin/outbox | List outbox messages |
| POST | /admin/outbox/retry | Retry due outbox rows |
| GET | /admin/leads | List leads |
| GET | /admin/leads/{id} | Lead detail |
| POST | /admin/leads/{id}/approve | Approve lead |
| POST | /admin/leads/{id}/reject | Reject lead |
| POST | /admin/leads/{id}/send-deposit | Send deposit link |
| POST | /admin/leads/{id}/send-booking-link | Send booking link |
| POST | /admin/leads/{id}/mark-booked | Mark as booked |
| GET | /admin/metrics, /admin/funnel, /admin/slot-parse-stats | Metrics |
| GET | /admin/events, /admin/debug/lead/{id} | Events / debug |
| POST | /admin/events/retention-cleanup | Cleanup old events |
| POST | /admin/sweep-expired-deposits | Sweep expired deposits |
| GET | /a/{token} | Action confirm page |
| POST | /a/{token} | Execute action (approve/reject/send_deposit/mark_booked) |
| POST | /demo/client/send | Demo: send message as client |
| GET | /demo/lead/{id}/messages | Demo: lead messages |
| GET | /demo/artist/inbox | Demo: artist inbox |
| POST | /demo/stripe/pay | Demo: simulate Stripe pay |
| GET | /demo/client, /demo/artist | Demo HTML pages |
