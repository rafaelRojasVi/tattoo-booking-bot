# Core Function Review Plan

An ordered list of 33 core functions to re-learn the codebase. Review in the order listed: entrypoints → webhook verification → conversation flow → leads/state → payments → calendar/sheets → messaging → attachments → reminders → admin/actions → DB. All paths below were checked against the repo.

**Source code for each function:** See [CORE_FUNCTIONS_CODE.md](CORE_FUNCTIONS_CODE.md) in this folder for full code or excerpts and file:line references, in the same order.

---

## Glossary of key types

| Type | Location | Purpose |
|------|----------|---------|
| **Lead** | `app.db.models.Lead` | Central entity: WhatsApp contact, status, step, answers, deposit/booking fields, timestamps. |
| **Attachment** | `app.db.models.Attachment` | WhatsApp media (image/video/etc.) linked to a lead; upload status and Supabase storage keys. |
| **OutboxMessage** | `app.db.models.OutboxMessage` | Durable send intent when outbox is enabled; status PENDING/SENT/FAILED, retry tracking. |
| **ActionToken** | `app.db.models.ActionToken` | One-time token for email/SMS action links (approve, reject, send_deposit, mark_booked); ties to lead + action_type. |
| **ProcessedMessage** | `app.db.models.ProcessedMessage` | Idempotency: (provider, message_id) for WhatsApp; (provider, event_id) for Stripe and other events. |

---

## Key status constants and where transitions are enforced

- **Constants:** `app.constants.statuses` — e.g. `STATUS_NEW`, `STATUS_QUALIFYING`, `STATUS_PENDING_APPROVAL`, `STATUS_AWAITING_DEPOSIT`, `STATUS_DEPOSIT_PAID`, `STATUS_BOOKING_PENDING`, `STATUS_BOOKED`, `STATUS_NEEDS_ARTIST_REPLY`, `STATUS_REJECTED`, `STATUS_OPTOUT`, etc.
- **Allowed transitions:** `app.services.conversation.state_machine.ALLOWED_TRANSITIONS` (dict: from_status → list of to_status).
- **Enforcement:**
  - **Conversation flow (bot-driven):** `app.services.conversation.state_machine.transition(db, lead, new_status)` — used from `conversation_qualifying`, `conversation_booking`, `conversation`, `time_window_collection`, `calendar_service`, `parse_repair`. All bot-driven status changes go through this.
  - **Admin / external (status-locked):** `app.services.safety.update_lead_status_if_matches(db, lead_id, expected_status, new_status, **kwargs)` — used from `app.api.admin` (approve, send_booking_link, mark_booked) and `app.api.webhooks` (Stripe deposit + mark booked). Ensures atomic compare-and-set so only the expected current status can transition.

---

## Numbered review list (one function per step)

### 1. Entrypoints and app lifecycle

| # | Function | Full import path | Layer | One-sentence purpose | Depends on | Returns / side effects | Why core |
|---|----------|------------------|-------|----------------------|------------|------------------------|----------|
| 1 | `lifespan` | `app.main.lifespan` | API | Startup/shutdown: validate env (DB, WhatsApp, Stripe, production guards), run template startup check. | settings, template_check | Async context manager; raises if config invalid | App won't start or will start in bad config without it. |
| 2 | `get_db` | `app.db.deps.get_db` | DB | Yield a DB session per request; close on exit. | SessionLocal | Generator yielding Session | Every request that touches DB depends on this. |
| 3 | `get_lead_or_404` | `app.api.dependencies.get_lead_or_404` | API | Resolve `lead_id` path param to Lead or raise 404. | get_db, Lead | Lead or HTTPException(404) | All admin/lead-scoped routes use it; wrong behavior breaks auth and UX. |

---

### 2. Webhooks (entry + verification)

| # | Function | Full import path | Layer | One-sentence purpose | Depends on | Returns / side effects | Why core |
|---|----------|------------------|-------|----------------------|------------|------------------------|----------|
| 4 | `whatsapp_inbound` | `app.api.webhooks.whatsapp_inbound` | API | POST /whatsapp: verify signature, parse JSON, idempotency, route to handle_inbound_message or ack. | _verify_whatsapp_webhook, get_or_create_lead, handle_inbound_message, ProcessedMessage | JSONResponse; enqueues background work | Single WhatsApp ingestion entry; breaks all inbound messaging. |
| 5 | `_verify_whatsapp_webhook` | `app.api.webhooks._verify_whatsapp_webhook` | API | Read body, check X-Hub-Signature-256, verify; on failure log + system event and return 403. | request.body, verify_whatsapp_signature, app.services.metrics.system_event_service.warn, _wa_error_response | (raw_body, None) or (None, JSONResponse) | All WhatsApp webhook security; wrong = reject valid or accept forgeries. |
| 6 | `stripe_webhook` | `app.api.webhooks.stripe_webhook` | API | POST /stripe: verify signature, parse event, idempotency, handle checkout.session.completed (deposit/mark booked). | _verify_stripe_webhook, update_lead_status_if_matches, check_processed_event, record_processed_event | JSONResponse; updates lead status, background tasks | Single Stripe ingestion; breaks payment and booking confirmation. |
| 7 | `_verify_stripe_webhook` | `app.api.webhooks._verify_stripe_webhook` | API | Read body, require stripe-signature, verify; on failure log + system event and return error response. | request.body, verify_webhook_signature, app.services.metrics.system_event_service.warn/error, _stripe_error_response | (event_dict, None) or (None, JSONResponse) | All Stripe webhook security. |

---

### 3. Conversation (state machine and message handling)

| # | Function | Full import path | Layer | One-sentence purpose | Depends on | Returns / side effects | Why core |
|---|----------|------------------|-------|----------------------|------------|------------------------|----------|
| 8 | `handle_inbound_message` | `app.services.conversation.handle_inbound_message` | Service | Route by lead.status to NEW/QUALIFYING/booking/handover handlers; return status + next message. | Lead, state machine, _handle_new_lead, _handle_qualifying_lead, _handle_booking_pending, send_whatsapp_message, commit_and_refresh | dict (status, message, lead_status, etc.) | Central router for all bot conversation logic; wrong routing breaks flow. |
| 9 | `transition` | `app.services.conversation.state_machine.transition` | Service | Check ALLOWED_TRANSITIONS, optionally advance step, UPDATE lead in DB (with locking), commit+refresh. | ALLOWED_TRANSITIONS, get_lead_or_none, commit_and_refresh | None; mutates lead.status (and optional step/fields) | Every bot-driven status change; wrong = invalid states or races. |
| 10 | `advance_step_if_at` | `app.services.conversation.state_machine.advance_step_if_at` | Service | If lead is at a given step for a given status, advance step and persist. | get_lead_or_none | bool (whether advanced) | Qualifying/booking step progression; breaks multi-step flows. |
| 11 | `_handle_qualifying_lead` | `app.services.conversation.conversation_qualifying._handle_qualifying_lead` | Service | Process one message during QUALIFYING: parse answer, policy (opt-out, human request), handover, complete qualification. | transition, parsing, conversation_policy, handover_service, _complete_qualification | dict | Core qualifying flow; wrong = bad answers or wrong status. |
| 12 | `_handle_booking_pending` | `app.services.conversation.conversation_booking._handle_booking_pending` | Service | Process message in BOOKING_PENDING: slot selection, time windows, tour, or handover. | transition, time_window_collection, calendar_service, tour_service | dict | Post-deposit booking flow; wrong = no slot collection or wrong status. |

---

### 4. Leads and state (lookup and atomic status)

| # | Function | Full import path | Layer | One-sentence purpose | Depends on | Returns / side effects | Why core |
|---|----------|------------------|-------|----------------------|------------|------------------------|----------|
| 13 | `get_or_create_lead` | `app.services.leads.leads.get_or_create_lead` | Service | Get Lead by wa_from or create new (NEW status); used by webhook. | db, Lead | Lead | Every WhatsApp message needs a lead; duplicates or wrong lead break flow. |
| 14 | `update_lead_status_if_matches` | `app.services.safety.update_lead_status_if_matches` | Service | Atomic UPDATE lead SET … WHERE id=? AND status=?; return (success, lead). | db, Lead, func.now() | (bool, Lead \| None) | Admin and Stripe use it for status-locked transitions; races without it. |
| 15 | `check_processed_event` | `app.services.safety.check_processed_event` | Service | Check if (provider, event_id) exists in ProcessedMessage (read-only). | db, ProcessedMessage | (is_duplicate: bool, processed_or_none) | Idempotency for Stripe/events; wrong = duplicate payments or double transitions. |
| 16 | `record_processed_event` | `app.services.safety.record_processed_event` | Service | Insert ProcessedMessage(provider, event_id); used after handling. | db, ProcessedMessage | None | Idempotency; must pair with check to avoid duplicates. |

---

### 5. Payments (Stripe)

| # | Function | Full import path | Layer | One-sentence purpose | Depends on | Returns / side effects | Why core |
|---|----------|------------------|-------|----------------------|------------|------------------------|----------|
| 17 | `create_checkout_session` | `app.services.integrations.stripe_service.create_checkout_session` | Integration | Create Stripe Checkout Session for deposit; return URL and store session ID on lead. | Stripe API, Lead | session URL / session id; mutates lead (stripe_checkout_session_id, etc.) | Deposit flow; wrong = no payment or wrong amount/session. |
| 18 | `verify_webhook_signature` | `app.services.integrations.stripe_service.verify_webhook_signature` | Integration | Verify stripe-signature header against raw body; return parsed event dict or raise. | Stripe SDK, webhook secret | dict (event) or raises ValueError/Exception | Stripe webhook authenticity; wrong = accept forgeries or reject valid. |

---

### 6. Calendar and Sheets

| # | Function | Full import path | Layer | One-sentence purpose | Depends on | Returns / side effects | Why core |
|---|----------|------------------|-------|----------------------|------------|------------------------|----------|
| 19 | `get_available_slots` | `app.services.integrations.calendar_service.get_available_slots` | Integration | Fetch available calendar slots (or mock) for a date range. | Google Calendar / mock | list of slot dicts | Slot suggestions and booking; wrong = no slots or wrong dates. |
| 20 | `send_slot_suggestions_to_client` | `app.services.integrations.calendar_service.send_slot_suggestions_to_client` | Integration | Format slots and send WhatsApp message(s) to client (e.g. after approval). | get_available_slots, messaging, lead | None; sends message | Post-approval UX; wrong = client doesn't get slots. |
| 21 | `log_lead_to_sheets` | `app.services.integrations.sheets.log_lead_to_sheets` | Integration | Upsert lead data to Google Sheet (summary, status, etc.). | Google Sheets API, Lead | bool | Reporting and ops; wrong = missing or wrong sheet data. |

---

### 7. Messaging and templates

| # | Function | Full import path | Layer | One-sentence purpose | Depends on | Returns / side effects | Why core |
|---|----------|------------------|-------|----------------------|------------|------------------------|----------|
| 22 | `send_whatsapp_message` | `app.services.messaging.messaging.send_whatsapp_message` | Service | Send text to WhatsApp Business API (or dry_run); optional outbox. | WhatsApp API, settings, outbox_service | None | All outbound text; wrong = no messages or wrong recipient. |
| 23 | `send_with_window_check` | `app.services.messaging.whatsapp_window.send_with_window_check` | Service | Check 24h messaging window; send message or template as required; log/metrics. | is_within_24h_window, send_whatsapp_message, send_template_message | None | Complies with WhatsApp policy; wrong = block or policy violation. |
| 24 | `startup_check_templates` | `app.services.messaging.template_check.startup_check_templates` | Service | On startup, verify required WhatsApp templates exist and are approved. | WhatsApp API / config | dict (template status) | App may refuse to start if templates missing; wrong = silent send failures. |

---

### 8. Attachments

| # | Function | Full import path | Layer | One-sentence purpose | Depends on | Returns / side effects | Why core |
|---|----------|------------------|-------|----------------------|------------|------------------------|----------|
| 25 | `attempt_upload_attachment` | `app.services.integrations.media_upload.attempt_upload_attachment` | Integration | Download media from WhatsApp, upload to Supabase, update Attachment (status, keys). | db, Attachment, WhatsApp media API, Supabase | None; mutates Attachment | Reference images for leads; wrong = missing media or stuck PENDING. |

---

### 9. Reminders and housekeeping

| # | Function | Full import path | Layer | One-sentence purpose | Depends on | Returns / side effects | Why core |
|---|----------|------------------|-------|----------------------|------------|------------------------|----------|
| 26 | `check_and_send_qualifying_reminder` | `app.services.messaging.reminders.check_and_send_qualifying_reminder` | Service | If lead in QUALIFYING and no reply for X hours, send reminder and set reminder_qualifying_sent_at. | db, Lead, send_whatsapp_message / templates | None | Reduces abandoned leads; wrong = spam or no reminder. |
| 27 | `check_and_mark_abandoned` | `app.services.messaging.reminders.check_and_mark_abandoned` | Service | If QUALIFYING and no reply for Y hours, transition to ABANDONED. | db, direct status update | None | Funnel hygiene; wrong = leads stuck or wrongly abandoned. |

---

### 10. Admin and actions

| # | Function | Full import path | Layer | One-sentence purpose | Depends on | Returns / side effects | Why core |
|---|----------|------------------|-------|----------------------|------------|------------------------|----------|
| 28 | `approve_lead` | `app.api.admin.approve_lead` | API | Status-locked: PENDING_APPROVAL → AWAITING_DEPOSIT; send slot suggestions + notify artist. | get_lead_or_404, update_lead_status_if_matches, log_lead_to_sheets, calendar, artist_notifications | JSON response | Main artist approval; wrong = no deposit or wrong status. |
| 29 | `send_booking_link` | `app.api.admin.send_booking_link` | API | Status-locked: DEPOSIT_PAID → BOOKING_LINK_SENT; store booking_url/tool. | get_lead_or_404, update_lead_status_if_matches, log_lead_to_sheets | JSON response | Sends client to booking tool; wrong = wrong link or status. |
| 30 | `mark_booked` | `app.api.admin.mark_booked` | API | Status-locked: BOOKING_PENDING (or legacy BOOKING_LINK_SENT) → BOOKED. | get_lead_or_404, update_lead_status_if_matches, log_lead_to_sheets | JSON response | Closes loop; wrong = lead never marked booked. |
| 31 | `execute_action` | `app.api.actions.execute_action` | API | Resolve action token, validate (used/expired/status); run approve/reject/send_deposit/mark_booked logic. | validate_action_token, admin logic inline, commit_and_refresh | HTML/JSON response | Email/SMS action links; wrong = broken links or security. |
| 32 | `validate_action_token` | `app.services.action_tokens.validate_action_token` | Service | Load token, check used/expired/lead/status; return (token, None) or (None, error_message). | db, ActionToken, Lead | (ActionToken \| None, str \| None) | All action-link security; wrong = reuse or wrong lead. |

---

### 11. DB helpers

| # | Function | Full import path | Layer | One-sentence purpose | Depends on | Returns / side effects | Why core |
|---|----------|------------------|-------|----------------------|------------|------------------------|----------|
| 33 | `commit_and_refresh` | `app.db.helpers.commit_and_refresh` | DB | db.commit() then db.refresh(instance) for each; used after mutating ORM objects. | Session | None | Used everywhere after updates; wrong = stale objects or rollback bugs. |

---

## Suggested review order (by step number)

Review in order **1 → 33** so that:

1. You see **entrypoints and DB** first (main, get_db, get_lead_or_404).
2. Then **webhooks and their verification** (whatsapp_inbound, _verify_whatsapp_webhook, stripe_webhook, _verify_stripe_webhook).
3. Then **conversation flow** (handle_inbound_message, transition, advance_step_if_at, _handle_qualifying_lead, _handle_booking_pending).
4. Then **leads and state** (get_or_create_lead, update_lead_status_if_matches, check_processed_event, record_processed_event).
5. Then **payments** (create_checkout_session, verify_webhook_signature).
6. Then **calendar/sheets** (get_available_slots, send_slot_suggestions_to_client, log_lead_to_sheets).
7. Then **messaging** (send_whatsapp_message, send_with_window_check, startup_check_templates).
8. Then **attachments** (attempt_upload_attachment).
9. Then **reminders** (check_and_send_qualifying_reminder, check_and_mark_abandoned).
10. Then **admin/actions** (approve_lead, send_booking_link, mark_booked, execute_action, validate_action_token).
11. Finally **DB helper** (commit_and_refresh).

This follows a real request: **Webhook → verify → get_or_create_lead → handle_inbound_message → transition / advance_step_if_at → …** and then admin/Stripe paths that use **update_lead_status_if_matches** and **check/record_processed_event**.

---

## Where to find the code

- **[CORE_FUNCTIONS_CODE.md](CORE_FUNCTIONS_CODE.md)** (this folder) — Code for all 33 functions (full or excerpt + file:line reference), in the same order as the table above.
