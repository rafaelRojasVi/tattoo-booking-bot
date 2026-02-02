# Deep Audit: Handover Flow, Parsing, Message Sends, Idempotency & Release

**Scope:** NEEDS_ARTIST_REPLY (handover) flow, parsing logic, user-facing sends, idempotency/concurrency, code quality, release checklist.  
**Assumption:** Shipping tomorrow; minimal risky refactors.

---

## 1. NEEDS_ARTIST_REPLY (Handover) Flow

### 1.1 Call Graph (handover-related)

| Function | File | Role |
|---------|------|------|
| `handle_inbound_message` | `app/services/conversation.py` | Entry; branches on `lead.status`; NEEDS_ARTIST_REPLY branch first (opt-out, CONTINUE, holding) |
| `should_handover` | `app/services/handover_service.py` | Dynamic handover: ARTIST, complexity 3, coverup keywords, long questions, hesitation, price/scheduling phrases |
| `get_handover_message` | `app/services/handover_service.py` | Client-facing handover message (uses `render_message`) |
| `notify_artist_needs_reply` | `app/services/artist_notifications.py` | Builds artist packet (wa_from, client_name, reason, last messages); sends once per transition (`needs_artist_reply_notified_at`) |
| `build_handover_packet` | `app/services/handover_packet.py` | Packet: wa_from, client_name, last 5 answers (ordered), parse_failures, answers_dict (latest-wins), status, current_question_key |
| `trigger_handover_after_parse_failure` | `app/services/parse_repair.py` | After MAX_FAILURES parse failures; sets status, notifies artist, sends bridge message |
| `_handle_human_request` | `app/services/conversation.py` | HUMAN/REFUND/DELETE keywords → set NEEDS_ARTIST_REPLY, notify, send ack (compose_message) |
| `_handle_refund_request` | `app/services/conversation.py` | REFUND → handover + REFUND_ACK |
| `_handle_delete_data_request` | `app/services/conversation.py` | DELETE MY DATA / GDPR → handover + DELETE_DATA_ACK |
| `_handle_artist_handover` | `app/services/conversation.py` | **Not currently called.** ARTIST is handled by `should_handover` in main branch; this is legacy/alternative path. |
| `_complete_qualification` (coverup branch) | `app/services/conversation.py` | coverup YES → NEEDS_ARTIST_REPLY, notify, handover_coverup |
| `update_lead_status_if_matches` | `app/services/safety.py` | Stripe: AWAITING_DEPOSIT → DEPOSIT_PAID; fallback NEEDS_ARTIST_REPLY → DEPOSIT_PAID |
| Stripe `checkout.session.completed` | `app/api/webhooks.py` | Dedupes by event_id; then status update (expected AWAITING_DEPOSIT or NEEDS_ARTIST_REPLY) |

### 1.2 Entry Points That Set STATUS_NEEDS_ARTIST_REPLY

| Location | Trigger |
|----------|---------|
| `conversation.py` ~682 | `should_handover(message_text, lead)` True (ARTIST, complexity 3, coverup, long questions, hesitation, price/scheduling) |
| `conversation.py` ~963 | `_handle_human_request`: message in ["HUMAN", "TALK TO SOMEONE", ...] |
| `conversation.py` ~983 | `_handle_refund_request`: "REFUND" in message |
| `conversation.py` ~1003 | `_handle_delete_data_request`: DELETE MY DATA / GDPR phrases |
| `conversation.py` ~1150 | `_handle_artist_handover` **defined but not called**; "ARTIST" is handled by `should_handover` at ~682. |
| `conversation.py` ~1239 | `_complete_qualification`: coverup YES |
| `parse_repair.py` ~121 | `trigger_handover_after_parse_failure`: parse failure count >= MAX_FAILURES for dimensions/budget/location/slot |
| `time_window_collection.py` ~98 | Time-window collection path: handover on failure/confusion |

### 1.3 Branch Logic (NEEDS_ARTIST_REPLY) — Verified

- **No step advance or parsing** while in NEEDS_ARTIST_REPLY: the branch is `elif lead.status == STATUS_NEEDS_ARTIST_REPLY` and returns after handling (opt-out, CONTINUE, or holding). Qualifying parsing and step advance only run in `elif lead.status == STATUS_QUALIFYING`.
- **STOP/UNSUBSCRIBE**: Checked first in this branch; calls `_handle_opt_out` and returns; no holding message sent.
- **CONTINUE**: Sets `lead.status = STATUS_QUALIFYING`, gets `get_question_by_index(lead.current_step)`, sends `compose_message("ASK_QUESTION", {..., "question_text": next_question.text})`. Correct “resume” path.

### 1.4 Holding Message Cooldown

- **Implementation:** `handover_last_hold_reply_at` (timezone-aware in DB); compare with `datetime.now(UTC)`; send only if `last_hold_at is None` or `(now_utc - last_hold_at) >= timedelta(hours=6)`. Constant `HANDOVER_HOLD_REPLY_COOLDOWN_HOURS = 6` in `conversation.py` (not in config).
- **Timezone:** App uses UTC for `now_utc`; naive `last_hold_at` from DB is normalized with `.replace(tzinfo=UTC)`. Cooldown is UTC-consistent.

### 1.5 Artist Notification Packet

- **Content:** `notify_artist_needs_reply` includes: Lead #, Contact (wa_from), Name (from answers name/client_name), Reason, preferred channel/availability, preferred time windows, last N answers (question_key + answer_text), parse failures, Phase 1 summary. No separate “handover packet” struct sent; content is built in-place. `build_handover_packet` in handover_packet.py is used elsewhere (e.g. admin/debug); it includes wa_from, client_name, summary, last messages, status, current_question_key.
- **Idempotency under duplicate message_id:** Duplicate WhatsApp message_id is caught at webhook entry (`ProcessedMessage.message_id` unique); `handle_inbound_message` is never called twice for the same message. So “handover notification idempotent under duplicate message_id” is satisfied. Per-lead idempotency: `needs_artist_reply_notified_at` ensures we only send one notification per “first transition” into NEEDS_ARTIST_REPLY; it is **not** cleared on CONTINUE, so a second handover (after resume) would **not** trigger a second artist notification.

### 1.6 Stripe Webhook NEEDS_ARTIST_REPLY Fallback

- **Flow:** On `checkout.session.completed`, first try `update_lead_status_if_matches(..., expected_status=STATUS_AWAITING_DEPOSIT, new_status=STATUS_DEPOSIT_PAID)`. If that fails and `lead.status == STATUS_NEEDS_ARTIST_REPLY`, retry with `expected_status=STATUS_NEEDS_ARTIST_REPLY`, same new_status and updates. Then `lead.status = STATUS_BOOKING_PENDING` and `booking_pending_at = func.now()` (direct assign after atomic update). So payment during handover correctly moves NEEDS_ARTIST_REPLY → DEPOSIT_PAID → BOOKING_PENDING.

### 1.7 Edge Cases / Possible Misbehaviour

- **Direct status assignment:** All handover entry points set `lead.status = STATUS_NEEDS_ARTIST_REPLY` directly. They do **not** use `state_machine.transition()`. So illegal transitions are not enforced at the call site; only `state_machine` module defines ALLOWED_TRANSITIONS. Risk: a future change could set NEEDS_ARTIST_REPLY from a status that is not in ALLOWED_TRANSITIONS.
- **Resume then handover again:** If user sends CONTINUE then later triggers handover again (e.g. “ARTIST”), artist is not re-notified (needs_artist_reply_notified_at already set). May be desirable to “notify once per lead” or undesirable if artist should be notified on every handover.
- **Double notification on same transition:** If two requests both pass the “status is QUALIFYING” check and both run should_handover and both set status to NEEDS_ARTIST_REPLY before either commits, both could call `notify_artist_needs_reply`; the first sets `needs_artist_reply_notified_at`, the second skips send. So at most one notification. No double-send from race on same lead.

### 1.8 Recommendations

- **Rate-limit policy:** Move `HANDOVER_HOLD_REPLY_COOLDOWN_HOURS` to config (e.g. `app/core/config.py`) for operational tuning.
- **Admin resume:** Provide an admin or action-token “resume flow” that sets status to QUALIFYING and (optionally) sends the current question; link could be included in artist notification.
- **State machine enforcement:** Refactor handover-setting code paths to call `state_machine.transition(db, lead, STATUS_NEEDS_ARTIST_REPLY, reason=...)` instead of direct assignment, so illegal transitions raise and row locking is used where applicable.
- **Optional: clear notify flag on CONTINUE** so that a later handover (after resume) sends a fresh artist notification.

---

## 2. Parsing Logic Audit

### 2.1 parse_budget_from_text (`app/services/estimation_service.py`)

- **Accepted:** Digits with optional decimals; £ $ €; gbp/pounds/usd/dollars/eur; commas stripped; "400-500" → first number (400); "400k" → 400_000 GBP → 40_000_000 pence; "~400", "around 400"; leading/trailing spaces.
- **Rejected:** No number; zero; negative (including "-400", "£-400"); "0-200" (first number 0).
- **Ambiguous / current behaviour:** Range "400-500" → 40000 pence (first number). "1.5k" → 150000 pence (from tests). Currency assumed GBP for storage (USD/EUR stripped but treated as same scale for simplicity).
- **Silent wrong parses:** None identified; negatives and zero are rejected. Possible improvement: reject ranges where max < min or both zero.
- **Tests:** `tests/test_parser_edge_cases.py`, `tests/test_phase1_services.py`, `tests/test_edge_cases_comprehensive.py`. Suggested: explicit "400-500" → 40000, "1.5k" → 150000; "400k" → 40_000_000.

### 2.2 parse_dimensions (`app/services/estimation_service.py`)

- **Accepted:** "WxH" and "W x H" with unit (cm, inch, inches, in); unicode × normalized via `normalize_for_dimensions`; single dimension "10cm" → (10, 10). Inches converted to cm (×2.54).
- **Rejected:** "10x", "x12", empty, "not a size".
- **Ambiguous:** "10 x 12" without unit — second pattern is "single dimension with unit", so "10 x 12" may not match; tests show "10 x 12" (with space, no unit) may need a pattern that accepts optional unit. Current patterns require unit in the match. "10x12cm??" accepted (trailing junk).
- **Silent wrong parses:** None critical. Partial "10x" correctly returns None.
- **Improvement:** Add pattern for "num x num" without unit (default cm). Ensure × (U+00D7) normalized in `normalize_for_dimensions`.
- **Tests:** `test_parser_edge_cases.py`, `test_phase1_services.py`. Add test for "10 x 12" (no unit) if we add that pattern.

### 2.3 parse_slot_selection (`app/services/slot_parsing.py`)

- **Accepted:** "1".."8" (within max_slots); "option X", "number X", "#X"; day + "morning"/"afternoon" (e.g. Monday morning); time-based "10am", "2pm", "the 2pm one". Multiple distinct slot numbers (e.g. "1 or 2") → None to force repair.
- **Rejected:** 0, 9, 11; "1 or 2", "2, 4, 5"; empty; no match.
- **Ambiguous:** "I have 3 questions" → 3 (slot index); "Call me at 5" → 5. These are accepted as slot selection. "Tuesday afternoon" with slots that have Tuesday afternoon → correct index. Relative dates not parsed; slots are concrete datetimes.
- **Out-of-range:** Numbers > max_slots or > len(slots) return None.
- **Tests:** `tests/test_slot_parsing.py`, `tests/test_parser_edge_cases.py`, `tests/test_slot_selection_integration.py`. Suggested: "1 or 2" → None; "9" with max_slots=8 → None; relative "tomorrow" (if ever supported) covered separately.

### 2.4 Location (is_valid_location / parse_location_input) (`app/services/location_parsing.py`)

- **Accepted:** City + country ("London UK"); flexible keywords (flexible, anywhere, etc.); country-only; city-only with CITY_TO_COUNTRY; postcodes can appear in text (no crash).
- **Emojis:** No crash; behaviour depends on whether city/country tokens match.
- **Multiple locations:** Parser returns one city/country; multiple locations could be collapsed to first or last depending on implementation (not fully audited here).
- **Travel phrasing:** Not specifically audited; if "I'll travel to London" is passed, city extraction may or may not include "London".
- **Tests:** `tests/test_location_parsing.py`, `tests/test_parser_edge_cases.py`, `tests/test_go_live_guardrails.py`. Suggested: postcode-only string (no crash, accept or reject deterministically); emoji in string; "London, UK" vs "London UK".

### 2.5 Conversation Flow and Parse Failure

- **No advance on parse failure:** When parse fails (dimensions, budget, location, slot), `parse_success` is False and `repair_message` is set; after saving the answer and updating `last_client_message_at`, if `not parse_success and repair_message`, we send repair and return without advancing step (`repair_needed`). Step advance only happens when parse succeeded.
- **Repair → retry_count → handover:** `increment_parse_failure`; `should_handover_after_failure` triggers `trigger_handover_after_parse_failure` at threshold (MAX_FAILURES). So flow is consistent: parse failure → repair → retry → after threshold, handover.

---

## 3. User-Facing Message Sends

### 3.1 send_whatsapp_message Call Sites (categorised)

| File | Function / context | Type | Notes |
|------|--------------------|------|--------|
| conversation.py | STATUS_NEW welcome | compose_message("WELCOME", ...) | OK |
| conversation.py | Panic mode | render_message("panic_mode_response") | OK |
| conversation.py | STATUS_PENDING_APPROVAL | render_message("pending_approval") | OK |
| conversation.py | STATUS_AWAITING_DEPOSIT | render_message("awaiting_deposit") | OK |
| conversation.py | STATUS_DEPOSIT_PAID | render_message("deposit_paid") | OK |
| conversation.py | Slot repair | compose_message("REPAIR_SLOT", ...) | OK |
| conversation.py | Confirmation summary | render_message(...) | OK |
| conversation.py | STATUS_BOOKING_PENDING | render_message("booking_pending") | OK |
| conversation.py | Tour accept/decline | render_message(...) | OK |
| conversation.py | NEEDS_ARTIST_REPLY CONTINUE | compose_message("ASK_QUESTION", ...) | OK |
| conversation.py | NEEDS_ARTIST_REPLY holding | **Hardcoded** "I've paused the automated flow..." | Should be copy key |
| conversation.py | OPT_OUT prompt (return only) | render_message("opt_out_prompt") | OK |
| conversation.py | Next question (qualifying) | compose_message("ASK_QUESTION", ...) | OK |
| conversation.py | Repair (size/budget/location) | compose_message("REPAIR_*", ...) | OK |
| conversation.py | _handle_human_request | compose_message("HUMAN_HANDOVER", ...) | OK |
| conversation.py | _handle_refund_request | compose_message("REFUND_ACK", ...) | OK |
| conversation.py | _handle_delete_data_request | compose_message("DELETE_DATA_ACK", ...) | OK |
| conversation.py | _handle_opt_out | compose_message("OPT_OUT", ...) | OK |
| conversation.py | _handle_artist_handover | render_message("handover_question") | OK |
| conversation.py | _complete_qualification coverup | render_message("handover_coverup") | OK |
| conversation.py | _complete_qualification below_min_budget | render_message(...) | OK |
| artist_notifications.py | Various | Hardcoded templates (System Alert, summary lines) | By design for artist; not client copy |
| webhooks.py | Pilot mode block | **Hardcoded** pilot message | OK for pilot |
| webhooks.py | Deposit confirmation | format_payment_confirmation_message + policy reminder | Template send via send_with_window_check |
| parse_repair.py | trigger_handover_after_parse_failure | render_message("handover_bridge") | OK |
| time_window_collection.py | Time window replies | compose/render | OK |
| admin.py / calendar_service.py | Admin/calendar | Various | Context-specific |

### 3.2 Problematic Calls

- **Holding message (handover):** Hardcoded string `"I've paused the automated flow. The artist will reply to you directly."` in `conversation.py`. **Fix:** Add copy key (e.g. `handover_holding`) and use `render_message("handover_holding", lead_id=lead.id)` or `compose_message` if no variants.
- **Raw question.text:** Not used; next question is always sent via `compose_message("ASK_QUESTION", {"question_text": next_question.text})`. OK.
- **Template sends:** Deposit confirmation uses `send_with_window_check` with template name/params; message body is formatted for fallback. Template content must match Meta; do not run client-facing voice/tone on template body (only on non-template fallback if any). Current code does not apply a “voice pack” to template params; OK.

### 3.3 apply_voice / Voice Pack

- **message_composer** has variant selection and optional apply_voice; if apply_voice is used, it should not be applied to WhatsApp template parameters (Meta requires exact match). Audit: template params come from `get_template_params_*`; no apply_voice in that path. Client messages use compose_message/render_message; if apply_voice is enabled for those, ensure it’s consistent. No inconsistency flagged in current flow.

### 3.4 Refactor Plan (minimal)

- Replace the single handover holding string with a copy key and `render_message`/`compose_message`.
- Optionally: add a single helper, e.g. `send_client_message(db, lead, intent, context, dry_run)` that always uses compose_message/render_message and updates `last_bot_message_at` + commit, so all client-facing sends go through one path. Low risk for “ship tomorrow”; can be post-launch.

---

## 4. Idempotency and Concurrency

### 4.1 WhatsApp

- **Dedupe by message_id:** At webhook entry, if `message_id` is present, we look up `ProcessedMessage` by `message_id`. If found, we return 200 with `type: "duplicate"` and do not call `handle_inbound_message`. So duplicate messages do not create duplicate LeadAnswer rows or advance steps.
- **ProcessedMessage:** Stored only **after** successful `handle_inbound_message`. So if the process crashes after handling but before insert, WhatsApp retry will process again (acceptable; at-most-once would require insert-before-process, which risks dropped events).
- **Out-of-order:** We compare `message_timestamp` (from payload) with `lead.last_client_message_at`. If message is older, we return 200 with `type: "out_of_order"` and do not process. So out-of-order messages do not advance state.

### 4.2 Stripe

- **Event dedupe:** `check_processed_event(db, event_id)` before any status update. Stripe event_id stored in `ProcessedMessage.message_id` (same table, different event_type). Duplicate event_id returns 200 and does not apply updates.
- **checkout.session.completed:** lead_id from metadata or client_reference_id; session_id mismatch with lead’s stored session rejected. So payment is tied to correct lead/session.
- **Webhook retries:** After successful processing we call `record_processed_event`. Retries see duplicate event_id and return 200; no double status update, no double notifications.

### 4.3 NEEDS_ARTIST_REPLY Fallback

- **expected_status:** First try AWAITING_DEPOSIT; on failure, if status is NEEDS_ARTIST_REPLY we try again with `expected_status=STATUS_NEEDS_ARTIST_REPLY`. Only those two transitions (to DEPOSIT_PAID) are applied; no other illegal transition.

### 4.4 DB Constraints and Commit Order

- **ProcessedMessage:** `message_id` unique (enforced). Used for both WhatsApp message_id and Stripe event_id.
- **Transaction boundaries:** WhatsApp: get/create lead → handle_inbound_message → commit → add ProcessedMessage → commit. Stripe: check duplicate → update_lead_status_if_matches (commit inside) → then lead.status = BOOKING_PENDING; db.commit(); side effects (Sheets, WhatsApp); then record_processed_event. So status is committed before side effects; duplicate retries are idempotent.
- **Possible race:** Two concurrent WhatsApp messages for same lead at same step could both run handle_inbound_message (different message_ids). No SELECT FOR UPDATE in conversation step advance; step is updated with current_step + 1 and committed. Risk: double advance if two messages processed concurrently. Mitigation: out-of-order check (timestamp) reduces likelihood; full fix would be to lock lead row (e.g. state_machine.transition with lock) when advancing step.

### 4.5 Recommendations

- **DB:** Ensure `processed_messages.message_id` has a unique constraint (already present in model).
- **Stripe:** Consider a dedicated `processed_stripe_events` table with event_id unique if you want to separate concerns; not required for correctness.
- **Tests:** Add test that two concurrent handle_inbound_message calls for same lead/step result in step incremented once (or define desired behaviour and enforce with lock).

---

## 5. Code Quality (Sanity)

- **Single responsibility / boundaries:** conversation.py is large (single “flow” module); handover_service, parse_repair, artist_notifications, handover_packet are separated. Acceptable for ship.
- **Naming / status usage:** STATUS_* constants used consistently; ALLOWED_TRANSITIONS in state_machine.py is the single source of truth for allowed transitions, but call sites do not use transition().
- **Duplication:** messaging (send_whatsapp_message), conversation (orchestration), message_composer (compose/render) — clear split. Some copy keys duplicated between compose intent and YAML key (INTENT_TO_KEY); acceptable.
- **Test isolation:** Composer cache: tests that depend on variant selection should set lead_id or reset composer if needed. No global composer state that leaks across tests if each test uses its own db/lead.
- **Timezone:** Prefer `datetime.now(UTC)` and timezone-aware DB columns; naive values normalized with .replace(tzinfo=UTC) where compared. handover_last_hold_reply_at stored as timezone-aware in migration.
- **Typing / errors:** Parsers return None on failure; callers check. Optional types used. Exceptions in webhooks caught and return 4xx/5xx appropriately.
- **Config:** Cooldowns (e.g. HANDOVER_HOLD_REPLY_COOLDOWN_HOURS) and thresholds (MAX_FAILURES, min budget) are in code or env; centralising in config is a small improvement.

**Risky to change before ship:** Large refactor of conversation.py; replacing all direct status assigns with state_machine.transition (needs testing and possibly locking strategy). Safe: moving one constant to config; adding one copy key for holding message.

---

## 6. Release Checklist (WhatsApp Booking Assistant)

### Security

| Item | Where | Status |
|------|--------|--------|
| Secrets not in repo | .env / env vars; config | Ensure .env in .gitignore |
| WhatsApp webhook signature | verify_whatsapp_signature(raw_body, X-Hub-Signature-256) in webhooks.py | Implemented |
| Stripe webhook signature | verify_webhook_signature in stripe handler | Implemented |
| Admin API key | admin_api_key in config; used in admin routes | Optional; set in prod |
| Least privilege | DB user, Stripe keys, Sheets/Calendar creds | Operational |

### Operational Monitoring

| Item | Where | Status |
|------|--------|--------|
| Structured logging | logger.info/error with correlation_id / event_type in webhooks | Present |
| System events | system_event_service (warn, error, info) for signature failure, atomic conflict, etc. | Present |
| Alerting on critical failures | Optional: send_system_alert on Stripe status mismatch | Present |
| Dead letter / retries | WhatsApp/Stripe retry by provider; we return 200 on duplicate | Idempotent |

### Data Protection

| Item | Where | Status |
|------|--------|--------|
| Retention | Not implemented in code | Policy/runbook |
| Opt-out | STOP/UNSUBSCRIBE → STATUS_OPTOUT; no automated sends | conversation.py |
| Delete requests | _handle_delete_data_request → handover; artist handles | conversation.py |

### Failure Drills

| Scenario | Mitigation |
|----------|------------|
| Meta/WhatsApp outage | Webhooks fail; retries; no local change needed; document “no outbound” during outage |
| Stripe outage | Checkout fails; webhook retries; idempotent by event_id |
| Calendar API failure | feature_calendar_enabled; slot suggestion degrades; document fallback (e.g. manual slots) |

### Backup and Recovery

| Item | Where | Status |
|------|--------|--------|
| DB backup | Managed DB / hosting (e.g. Render, Supabase) | Operational |
| Rollback | Deploy previous image; migrations backward-compatible where possible | Process |

### Rate Limiting

| Item | Where | Status |
|------|--------|--------|
| Inbound spam | WhatsApp rate limits; we process one message per message_id | ProcessedMessage |
| Holding reply cooldown | 6h cooldown on handover holding message | conversation.py |

### Acceptance Criteria (Phase 1)

| Criterion | Verification |
|-----------|--------------|
| New lead gets welcome | test_e2e_phase1_happy_path / conversation flow |
| Qualifying questions in order | get_question_by_index; step advance on success |
| Parse failure → repair → handover after threshold | parse_repair + conversation |
| Handover: no step advance, CONTINUE resumes | test_handover_complications |
| Opt-out during handover | test_opt_out_works_even_during_handover |
| Stripe payment during handover | test_stripe_webhook_updates_status_even_if_handover_active |
| Deposit confirmation with template | send_with_window_check in webhooks |
| Artist notification once per handover transition | needs_artist_reply_notified_at in artist_notifications |
| Duplicate message_id → 200, no double process | ProcessedMessage at webhook entry; test_webhook_returns_200_on_duplicate_message_id |
| Latest-wins for LeadAnswer per key | order_by(created_at, id) in confirmation, complete_qualification, handover_packet; tests in test_production_hardening |

---

**Document version:** 1.0.  
**Tie-in:** Each checklist item points to file/function or notes “missing” / “operational” where appropriate.
