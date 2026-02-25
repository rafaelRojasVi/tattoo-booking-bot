# Implementation Summary — Tattoo Booking Bot

A specific, exhaustive summary of everything implemented in the tattoo-booking-bot codebase.

---

## 1. Project Overview

- **Purpose:** WhatsApp-based tattoo consultation and booking system. Qualifies leads via guided questions, collects deposit via Stripe, and supports artist approval and slot selection.
- **Stack:** FastAPI, PostgreSQL, SQLAlchemy/Alembic, Stripe API, WhatsApp Business API, optional Google Sheets and Google Calendar.
- **Tests:** 390+ tests (pytest). CI (GitHub Actions), quality workflow (ruff, mypy, bandit, pip-audit).

---

## 2. Tech Stack & Configuration

### Core

- **Framework:** FastAPI
- **DB:** PostgreSQL via SQLAlchemy 2.x (Mapped, declarative), Alembic migrations
- **Config:** `pydantic-settings` from `.env`; `app/core/config.py` — `Settings` with validation and fail-fast for required vars
- **Production checks (startup):** `APP_ENV=production` requires: `ADMIN_API_KEY`, `WHATSAPP_APP_SECRET`, `STRIPE_WEBHOOK_SECRET`, `DEMO_MODE=false`

### Integrations (feature-flagged)

- **WhatsApp:** `whatsapp_access_token`, `whatsapp_phone_number_id`, `whatsapp_verify_token`, `whatsapp_app_secret` (signature verification), `whatsapp_dry_run`
- **Stripe:** `stripe_secret_key`, `stripe_webhook_secret`, `stripe_deposit_amount_pence`, `stripe_success_url`, `stripe_cancel_url`
- **Google Sheets:** `google_sheets_enabled`, `google_sheets_spreadsheet_id`, `google_sheets_credentials_json`; gated by `feature_sheets_enabled`
- **Google Calendar:** `google_calendar_enabled`, `google_calendar_id`, `google_calendar_credentials_json`, `booking_duration_minutes`, `slot_suggestions_count`; gated by `feature_calendar_enabled`
- **Supabase Storage:** `supabase_url`, `supabase_service_role_key`, `supabase_storage_bucket` for reference image uploads

### Feature flags

- `feature_sheets_enabled`, `feature_calendar_enabled`, `feature_reminders_enabled`, `feature_notifications_enabled`, `feature_panic_mode_enabled`
- `demo_mode` (enables `/demo/*`; must be false in production)
- `pilot_mode_enabled`, `pilot_allowlist_numbers` (restrict consultation to allowlisted WhatsApp numbers)

### Other config

- **Action tokens (Mode B):** `action_token_base_url`, `action_token_expiry_days` (default 7)
- **Artist:** `artist_whatsapp_number` (for notifications with action links)
- **Deposit rules:** `deposit_rule_version` (e.g. `v1`), `stripe_deposit_amount_pence`
- **Rate limiting:** `rate_limit_enabled`, `rate_limit_requests`, `rate_limit_window_seconds` (middleware on `/admin`, `/a/`)

---

## 3. Database Models & Migrations

### Tables

- **`leads`** — Main lead entity. Fields include:
  - Identity: `id`, `channel` (default `whatsapp`), `wa_from`, `status`, `current_step`
  - Location: `location_city`, `location_country`, `region_bucket` (UK, EUROPE, ROW)
  - Tour: `requested_city`, `requested_country`, `offered_tour_city`, `offered_tour_dates_text`, `tour_offer_accepted`, `waitlisted`
  - Size/budget: `size_category`, `size_measurement`, `budget_range_text`, `min_budget_amount`, `below_min_budget`
  - Estimation: `complexity_level` (1–3), `estimated_category` (SMALL, MEDIUM, LARGE, XL), `estimated_days`, `estimated_deposit_amount`, `estimated_price_min_pence`, `estimated_price_max_pence`, `pricing_trace_json`
  - Other qual: `instagram_handle`, `summary_text`
  - Deposit: `deposit_amount_pence`, `stripe_checkout_session_id`, `deposit_checkout_expires_at`, `stripe_payment_intent_id`, `stripe_payment_status`, `deposit_paid_at`, `deposit_sent_at`, `deposit_amount_locked_at`, `deposit_rule_version`
  - Booking: `booking_link`, `booking_tool`, `booking_link_sent_at`, `booked_at`, `booking_pending_at`
  - Calendar: `calendar_event_id`, `calendar_start_at`, `calendar_end_at`, `suggested_slots_json`, `selected_slot_start_at`, `selected_slot_end_at`
  - Timestamps: `last_client_message_at`, `last_bot_message_at`, reminder fields, funnel timestamps (`qualifying_started_at`, `pending_approval_at`, `needs_follow_up_at`, etc.), `approved_at`, `rejected_at`, `last_admin_action`, `last_admin_action_at`, `admin_notes`
  - Handover: `handover_reason`, `preferred_handover_channel`, `call_availability_notes`, `parse_failure_counts` (JSON per-field failure counts)
  - Audit: `created_at`, `updated_at`

- **`lead_answers`** — One row per answered question: `lead_id`, `question_key`, `answer_text`, optional `message_id`, `media_id`, `media_url`, `created_at`

- **`processed_messages`** — Idempotency: `message_id` (unique), `event_type`, `lead_id`, `processed_at`. Used for WhatsApp message IDs and Stripe event IDs.

- **`action_tokens`** — Mode B links: `token` (unique), `lead_id`, `action_type`, `required_status`, `used`, `used_at`, `expires_at`, `created_at`

- **`system_events`** — Observability: `created_at`, `level` (INFO/WARN/ERROR), `event_type`, `lead_id`, `payload` (JSON)

- **`attachments`** — Reference images: `lead_id`, `lead_answer_id`, `whatsapp_media_id`, `provider` (e.g. supabase), `bucket`, `object_key`, `content_type`, `size_bytes`, `upload_status` (PENDING/UPLOADED/FAILED), `upload_attempts`, `last_attempt_at`, `uploaded_at`, `failed_at`, `last_error`, `created_at`

### Migrations (versions under `migrations/versions/`)

- Create leads table, `current_step`, lead_answers
- Phase 1 fields (tour, estimation, deposit, booking, handover, etc.)
- Estimated days, slot selection fields (`selected_slot_start_at`/`end_at`), parse failure tracking, pricing estimate fields, deposit locking audit fields, `deposit_checkout_expires_at`, system_events table, attachments table, notification timestamps, unique constraints/indexes

---

## 4. API Endpoints

### Webhooks (`/webhooks`)

- **`GET /webhooks/whatsapp`** — Meta verification: query `hub.mode`, `hub.verify_token`, `hub.challenge`; return challenge if token matches.
- **`POST /webhooks/whatsapp`** — Inbound WhatsApp messages. Signature verification (if `whatsapp_app_secret`), body parsing, idempotency by message ID (check then record after success), lead lookup/create by `wa_from`, pilot allowlist check, STOP/UNSUBSCRIBE → opt-out, then `handle_inbound_message()`. SystemEvent on signature or processing failure.
- **`POST /webhooks/stripe`** — Stripe events. Signature verification, idempotency by event ID. Handles `checkout.session.completed`: validate session/lead, transition to DEPOSIT_PAID (state machine), commit DB first, then Sheets update and WhatsApp send; record processed event last. SystemEvent on signature or webhook failure.

### Admin (`/admin`) — require `X-Admin-API-Key`

- **`GET /admin/leads`** — List leads (filter, pagination).
- **`GET /admin/leads/{id}`** — Lead detail.
- **`POST /admin/leads/{id}/approve`** — Approve lead (status-locked, state machine transition to AWAITING_DEPOSIT).
- **`POST /admin/leads/{id}/reject`** — Reject lead (transition to REJECTED).
- **`POST /admin/leads/{id}/send-deposit`** — Create Stripe Checkout Session, store session ID and expiry, send deposit link via WhatsApp, transition to AWAITING_DEPOSIT (or keep); idempotent by checkout session.
- **`POST /admin/leads/{id}/send-booking-link`** — Send booking URL (e.g. Fresha), set BOOKING_PENDING.
- **`POST /admin/leads/{id}/mark-booked`** — Mark lead as BOOKED.
- **`GET /admin/metrics`** — In-memory metrics (e.g. event counts).
- **`GET /admin/funnel`** — Funnel metrics (counts by status).
- **`GET /admin/events`** — System events list (optional `limit`, `lead_id`).
- **`GET /admin/leads/{id}/debug`** — Debug view for a lead (state, answers, handover context).
- **`POST /admin/sweep-expired-deposits`** — Mark leads with expired deposit links (e.g. >24h since `deposit_sent_at`) as DEPOSIT_EXPIRED; for cron/workers.

### Actions — Mode B (`/a/{token}`)

- **`GET /a/{token}`** — Confirmation page: validate token (unused, not expired, status match), show confirm/cancel.
- **`POST /a/{token}`** — Execute action: same validation, then approve/reject/send_deposit/send_booking_link/mark_booked; token marked used.

### Health & readiness

- **`GET /health`** — Returns ok, template names, feature flags, integration flags (no DB).
- **`GET /ready`** — DB connectivity (`SELECT 1`); 503 if DB unavailable.

### Demo (`/demo`) — only when `DEMO_MODE=true`

- **`POST /demo/client/send`** — Simulate client sending a message (body: phone, text).
- **`GET /demo/artist/inbox`** — List leads for artist demo view.
- **`POST /demo/stripe/pay`** — Simulate Stripe checkout completion (lead_id, session_id).
- **`GET /demo/client`** — HTML page for client demo.
- **`GET /demo/artist`** — HTML page for artist demo.

---

## 5. Services (by file)

- **`action_tokens`** — Generate/validate single-use, expiry- and status-locked tokens; build action URL. Used for approve/reject/send_deposit/send_booking_link/mark_booked.
- **`artist_notifications`** — Notify artist (WhatsApp): summary + action links; uses handover packet and message composer.
- **`calendar_rules`** — Load rules from `config/calendar_rules.yml` (e.g. slot rules by category).
- **`calendar_service`** — Read-only Google Calendar: fetch free/busy, suggest N slots (configurable), format for client; no calendar write. Fallback when no slots → collect time windows; logs `calendar.no_slots_fallback` SystemEvent.
- **`conversation`** — Main flow: `handle_inbound_message()` by status (NEW → QUALIFYING → …). Handles: question flow, parsing (dimensions, budget, location, slot), parse_repair + two-strikes handover, budget minimum + tour conversion/waitlist, summary build, artist notify, Sheets log, action token generation, slot suggestions, slot selection, deposit link send, opt-out (STOP/UNSUBSCRIBE → OPTOUT), panic mode (log + notify only). Uses state_machine for transitions.
- **`funnel_metrics_service`** — Funnel metrics over last N days: new_leads, qualifying_started, qualifying_completed, pending_approval, awaiting_deposit, deposit_paid, booked, rejected, abandoned, etc.; used by `GET /admin/funnel`.
- **`estimation_service`** — Parse dimensions (cm/inches), area, complexity (1–3); classify category (SMALL, MEDIUM, LARGE, XL) and optional estimated_days for XL; compute estimated_deposit_amount (pence). Used when qualifying completes.
- **`handover_packet`** — Build artist handover dict: last 5 answers, parse_failure_counts, size/budget/location, category/deposit/price range, tour context, status, current question key.
- **`handover_service`** — Trigger handover when parse failures exceed threshold (two-strikes): set status NEEDS_ARTIST_REPLY, set handover_reason, optional notify artist.
- **`http_client`** — Shared HTTP client with timeouts for external APIs.
- **`leads`** — CRUD/query helpers for leads (e.g. by wa_from, active lead reuse for multiple enquiries).
- **`location_parsing`** — Parse city/country from free text; normalize for region_bucket.
- **`media_upload`** — Download WhatsApp media, upload to Supabase (or configured provider), create/update Attachment record; retries and status tracking (PENDING/UPLOADED/FAILED).
- **`message_composer`** — Build WhatsApp message bodies (e.g. summary, slot list, deposit link, booking link).
- **`messaging`** — Wrapper around WhatsApp send; `format_summary_message`, `send_whatsapp_message` (delegates to whatsapp_window).
- **`metrics`** — In-memory counters for events (e.g. webhook received, messages sent).
- **`parse_repair`** — Per-field parse failure count (`dimensions`, `budget`, `location_city`, `slot`); increment/reset; two-strikes (MAX_FAILURES=2) triggers handover via handover_service.
- **`pricing_service`** — Internal-only price range from category + region (UK/EU/ROW hourly rates); min/max pence and trace; stored on lead (estimated_price_min/max_pence, pricing_trace_json).
- **`questions`** — `CONSULTATION_QUESTIONS`: idea, placement, dimensions, style, complexity (1–3), coverup, reference_images, budget, location_city, location_country, instagram_handle, travel_city, timing; helpers (get_question_by_index, is_last_question, required count).
- **`region_service`** — Map country/city to region_bucket (UK, EUROPE, ROW) and hourly rate (pence).
- **`reminders`** — Idempotent reminders: qualifying (12h / 36h) via `reminder_qualifying_sent_at`; booking (24h / 72h) via `reminder_booking_sent_24h_at` / `reminder_booking_sent_72h_at`; uses processed_messages event_id to avoid duplicates; sends via WhatsApp (template if outside 24h window).
- **`safety`** — Idempotency: `check_processed_event()`, `record_processed_event()` (no combined check-and-record before side effects); atomic status update with optional row lock; logs `atomic_update.conflict` on status mismatch.
- **`sheets`** — Google Sheets: `log_lead_to_sheets` (upsert by lead_id), `update_lead_status_in_sheets` on status change; feature-flag and stub when disabled.
- **`slot_parsing`** — Parse user slot choice: number (1–8), “option N”, “number N”, day+time, time-only; returns 1-based index into slots list.
- **`state_machine`** — Allowed transitions between all statuses; `transition(db, lead, to_status, lock_row=True)` with SELECT FOR UPDATE; TERMINAL_STATES and STATE_SEMANTICS (ABANDONED, STALE, OPTOUT, WAITLISTED, BOOKED, REJECTED).
- **`stripe_service`** — Create Checkout Session (amount, success/cancel URL, metadata lead_id); optional expiry; store checkout_session_id and deposit_checkout_expires_at on lead.
- **`summary`** — Build text summary of lead (answers, category, deposit, location, etc.) for artist.
- **`system_event_service`** — `info()`, `warn()`, `error()` to write to `system_events` (event_type, lead_id, payload).
- **`template_check`** — Startup validation: required WhatsApp template names present in config; `startup_check_templates()`.
- **`template_registry`** / **`whatsapp_templates`** — Template name and parameter mapping for outbound messages (e.g. post-approval, reminder, deposit link).
- **`time_window_collection`** — Parse preferred time windows (e.g. “next 2–4 weeks”, “Monday morning”) when calendar has no slots; stored for later use.
- **`tone`** — Copy/tone constants for bot messages.
- **`tour_service`** — Tour conversion: offer tour city/dates when client not in artist city; accept/decline → waitlist or continue.
- **`whatsapp_window`** — 24h session window: `is_within_24h_window(lead)`; if outside, send via template (template name + params); logs `template.fallback_used`; on send failure logs `whatsapp.send_failure` SystemEvent.
- **`whatsapp_verification`** — Webhook signature verification using app secret.

### Copy and config

- **`app/copy/en_GB.yml`** — Locale copy for messages.
- **`app/config/calendar_rules.yml`** — Calendar/slot rules.
- **`app/config/voice_pack.yml`** — Voice/tone config.

### Jobs and middleware

- **`app/jobs/sweep_pending_uploads.py`** — Sweep for PENDING attachments and retry upload (for cron/worker).
- **`app/middleware/rate_limit.py`** — Rate limit middleware for `/admin` and `/a/` (configurable requests per window).

---

## 6. Conversation Flow & State Machine

### Statuses (from `conversation.py`)

- **NEW** → first message starts QUALIFYING.
- **QUALIFYING** → question steps; can go to PENDING_APPROVAL, NEEDS_ARTIST_REPLY, NEEDS_FOLLOW_UP, TOUR_CONVERSION_OFFERED, ABANDONED, STALE, OPTOUT.
- **PENDING_APPROVAL** → artist approves → AWAITING_DEPOSIT; or reject → REJECTED; or NEEDS_ARTIST_REPLY / NEEDS_FOLLOW_UP / ABANDONED / STALE.
- **AWAITING_DEPOSIT** → deposit link sent; Stripe payment → DEPOSIT_PAID; or DEPOSIT_EXPIRED, REJECTED, NEEDS_ARTIST_REPLY, NEEDS_FOLLOW_UP, ABANDONED, STALE.
- **DEPOSIT_PAID** → send booking link → BOOKING_PENDING; or REJECTED, NEEDS_ARTIST_REPLY, NEEDS_FOLLOW_UP, ABANDONED, STALE.
- **BOOKING_PENDING** → artist marks booked → BOOKED; or REJECTED, etc.
- **COLLECTING_TIME_WINDOWS** — when calendar has no slots; collect preferred windows then continue.
- **TOUR_CONVERSION_OFFERED** — tour offered; accept/decline → waitlist or continue.
- **WAITLISTED**, **REJECTED**, **BOOKED**, **ABANDONED**, **STALE**, **OPTOUT** — terminal or housekeeping.

Transitions are centralized in `state_machine.py` with `ALLOWED_TRANSITIONS`; production uses `transition(..., lock_row=True)` (SELECT FOR UPDATE).

### Question flow (Phase 1)

1. Idea → 2. Placement → 3. Dimensions → 4. Style → 5. Complexity (1/2/3) → 6. Coverup → 7. Reference images → 8. Budget → 9. Location city → 10. Location country → 11. Instagram → 12. Travel city → 13. Timing.  
Parsing: dimensions (estimation_service), budget (min check, region), location (location_parsing, region_bucket). Two-strikes parse failure → handover. Budget below minimum → tour conversion or waitlist. On completion: summary, estimate category/deposit, log to Sheets, notify artist with action tokens, transition to PENDING_APPROVAL.

### Slot selection (Phase 2)

After approval, calendar_service suggests N slots; user replies with number or “option N” etc.; slot_parsing returns index; lead gets `selected_slot_start_at` / `selected_slot_end_at`. Deposit link sent after slot selection (or after approval if no calendar). No calendar hold (TTL) and no creation of calendar event on booking.

---

## 7. Phase 1 — “Secretary + Safety Gate” (Implemented)

| Feature | Implementation |
|--------|----------------|
| Guided WhatsApp consultation | `conversation.py` + `questions.py`: 13 questions, step-by-step; answers in `lead_answers`. |
| Parse repair + two-strikes handover | `parse_repair.py` (per-field counts, MAX_FAILURES=2); `handover_service` sets NEEDS_ARTIST_REPLY and handover_reason; `handover_packet` for context. |
| Budget minimum + tour / waitlist | Budget check in conversation; `tour_service` for tour offer; waitlist when declined or no tour. |
| Lead summary to artist | `summary.py`; `artist_notifications` + `message_composer`; optional action links (Mode B). |
| Google Sheets logging | `sheets.py`: `log_lead_to_sheets`, `update_lead_status_in_sheets`; feature flag; upsert by lead_id. |
| Secure action links (approve/reject/send_deposit/send_booking_link/mark_booked) | `action_tokens.py` + `api/actions.py`: single-use, expiry, status-locked; GET confirm page, POST execute. |
| Calendar read-only slot suggestions | `calendar_service.py`: fetch slots, format and send; no calendar write. |
| Stripe deposit after approval + webhook | Deposit link sent after approve; `webhooks.py` handles `checkout.session.completed`, idempotency, state transition, then Sheets + WhatsApp. |

---

## 8. Phase 2 — “Secretary Fully Books” (Partial)

| Feature | Status | Implementation |
|--------|--------|----------------|
| Client selects slot in chat | Done | `slot_parsing.py`, conversation: by number, “option N”, day/time; `selected_slot_start_at`/`end_at` on lead. |
| Holds / anti-double-booking (TTL) | Not done | No calendar hold with TTL. |
| Deposit tied to selected slot | Done | Deposit flow uses lead; `selected_slot_*` stored; no separate hold entity. |
| Google Calendar write (create event) | Not done | `calendar_service`: read-only; no `events.insert`. |
| Post-payment confirmation (client + artist) | Done | Stripe webhook updates lead; notifications/messaging for client and artist. |
| Retry/recovery for payment/calendar | Partial | Stripe: idempotency, SystemEvent, commit-before-side-effects; calendar write N/A. |
| Sheets updated with booking status | Done | `log_lead_to_sheets`, `update_lead_status_in_sheets` on status changes. |
| Slot → deposit → confirmed booking + calendar event | Partial | Slot → deposit → BOOKED path exists; **calendar event creation missing**. |

---

## 9. Phase 3 — “Marketing / Re-engagement” (Partial)

| Feature | Status | Implementation |
|--------|--------|----------------|
| Broadcast campaigns | Not done | No broadcast/campaign sender. |
| Segmentation (waitlisted, abandoned, etc.) | Not done | Lead flags (e.g. waitlisted) exist; no segmentation service for campaigns. |
| Automated follow-ups (nurture, “still interested?”) | Partial | `reminders.py`: qualifying reminder (12h/36h), booking reminder (24h/72h); not full nurture sequences or campaign-driven. |
| Opt-in/opt-out (STOP, consent) | Done | `conversation.py`: STOP/UNSUBSCRIBE → `_handle_opt_out`, OPTOUT, confirmation. |
| Message templates strategy | Done | `whatsapp_templates`, `template_check`, `template_registry` for approved templates. |
| Campaign tags + conversion metrics in Sheets | Not done | Funnel/metrics exist; no campaign tags or campaign-level conversion logging. |

---

## 10. Security & Reliability

- **Admin API:** In production, `ADMIN_API_KEY` required; server refuses to start if missing.
- **Action tokens:** Single-use, time-limited, status-locked; confirm page before execute.
- **Idempotency:** WhatsApp by message_id, Stripe by event_id; **check** first, **process**, then **record** after success (no record-before-side-effects).
- **State machine:** All status changes via `state_machine.transition()`; optional row lock (SELECT FOR UPDATE) to avoid races.
- **Side effects after commit:** DB commit first; then Sheets, WhatsApp; failures logged, not rolled back; processed event recorded last.
- **Stripe:** Webhook signature verification; checkout session and lead validated before applying.
- **WhatsApp:** Optional signature verification with `whatsapp_app_secret`; SystemEvent on failure.
- **Rate limiting:** Middleware on `/admin` and `/a/` (configurable).
- **Pilot mode:** Restrict who can start consultation to allowlisted numbers.

---

## 11. Observability

- **SystemEvent:** DB table and `system_event_service`; used for: `whatsapp.send_failure`, `template.fallback_used`, `whatsapp.signature_verification_failure`, `stripe.signature_verification_failure`, `stripe.webhook_failure`, `whatsapp.webhook_failure`, `atomic_update.conflict`, `calendar.no_slots_fallback`. Admin: `GET /admin/events?limit=&lead_id=`.
- **Metrics:** In-memory counters; `GET /admin/metrics`.
- **Funnel:** `GET /admin/funnel` (counts by status).
- **Debug:** `GET /admin/leads/{id}/debug` (state, answers, handover context).
- **Correlation:** Correlation IDs on webhook handling for tracing (where implemented).

---

## 12. Testing

- **Location:** `tests/`; 390+ tests.
- **Notable suites:** e2e (phase1 happy path, full flow), webhooks (WhatsApp, Stripe, idempotency, ordering), state_machine, conversation, phase1 services (calendar, reminders, sheets, stripe, summary, templates), admin actions, action tokens, go-live guardrails, deposit expiry/locking, slot parsing/selection, pricing, handover packet, parse_repair, system_events, media/image handling, pilot mode, production validation, demo mode, correlation IDs, debug endpoint, time windows, XL deposit logic.
- **CI:** GitHub Actions (e.g. `ci.yml`, `quality.yml`); Docker test run via `docker-compose.test.yml`.

---

## 13. Deployment & Operations

- **Docker:** `Dockerfile`, `docker-compose.yml`, `docker-compose.test.yml`, `docker-compose.prod.yml`.
- **Render:** `render.yaml` blueprint; `docs/deployment/DEPLOYMENT_RENDER.md`.
- **Runbooks:** `docs/runbooks/runbook_go_live.md` (pre-launch checklist, recovery), `docs/runbooks/ops_runbook.md`.
- **Health:** `/health` (no DB), `/ready` (DB); suitable for load balancers and orchestration.
- **Cron-style:** `POST /admin/sweep-expired-deposits` (expire deposit links); `app/jobs/sweep_pending_uploads.py` (retry attachment uploads). Scripts: `scripts/smoke_workers.sh`, `scripts/whatsapp_smoke.py`, etc.

---

## 14. Not Implemented (Summary)

- **Phase 2:** Calendar TTL holds; Google Calendar event creation on confirmed booking.
- **Phase 3:** Broadcast campaigns; segmentation service; campaign tags and conversion metrics in Sheets; full nurture sequences.
- **Other:** Optimistic concurrency (version column); retry queue for failed side effects; moving side effects to a job queue; concurrent-update integration tests (as called out in CRITICAL_FIXES_SUMMARY).

---

This document is the single place for a specific, exhaustive list of what is implemented and what is not in the tattoo-booking-bot codebase.
