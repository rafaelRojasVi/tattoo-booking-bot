# Schedule C — Implementation Traceability

**Document type:** Evidence-backed compliance report for contract attachment  
**Reference:** Freelance Services Agreement v1.0 — 29 January 2026 (Schedule A + Schedule B)  
**Prepared:** 2 February 2026 (evidence snapshot)  
**Purpose:** Defend milestone acceptance, provide audit trail, support Phase 2 build checklist.

---

## Repository Snapshot

| Field | Value |
|-------|-------|
| **Repository** | tattoo-booking-bot |
| **Commit SHA** | `ffe2a254f01b859b3a52be01056edf59d63d5782` |
| **Branch** | master |
| **Test command** | `python -m pytest tests/ --collect-only -q` → 845 collected; `python -m pytest tests/ -q --tb=no` → 840 passed, 1 skipped, 4 xfailed |
| **Environment** | Staging/mocked for acceptance; Go-Live depends on Client-provided credentials (Clause 11). |

---

## Operational Prerequisites (Clause 11)

Acceptance testing can be performed in staging with mocked external services. **Go-Live** requires:

- Client-provided accounts and credentials: Meta WhatsApp, Stripe, Google Calendar, Google Sheets
- If not configured, acceptance can be completed in staging/mocked mode; production deployment depends on access and Client cooperation within 2 Working Days of request.

---

## Summary

Phase 1 (Schedule A) is fully implemented and covered by tests. Phase 2 (Schedule B) is partially implemented: B1 (slot selection, deposit binding, confirmation) and B4 (post-payment flow) are done; B2 (holds + TTL + concurrency) and B3 (Google Calendar event creation) are not implemented. Test count: **845 collected**, **840 passed**, **1 skipped**, **4 xfailed**. Build-quality claims (correlation IDs, health checks, Render setup, runbook, system events) are verified with file evidence.

---

## 1) Verified Numbers

### 1.1 Test count (verified)

**Command:**
```bash
python -m pytest tests/ --collect-only -q
```

**Output:** `845 tests collected`

**Run result:**
```bash
python -m pytest tests/ -q --tb=no
```
**Output:** `840 passed, 1 skipped, 4 xfailed`

**Correction:** The earlier "~840 tests" claim is accurate: 840 pass, 4 are marked xfail (expected to fail), 1 is skipped.

### 1.2 Documents in `docs/` (verified)

| Document | Exists |
|----------|--------|
| ARCHITECTURE_IMPROVEMENTS.md | ✅ |
| ARCHITECTURE_SANITY_CHECK.md | ✅ |
| CLIENT_COST_SPECIFICATION_BY_PHASE.md | ✅ |
| CONTRACT_GAP_ANALYSIS.md | ✅ |
| CONVERSATION_AND_NATURALNESS_REVIEW.md | ✅ |
| CRITICAL_FIXES_SUMMARY.md | ✅ |
| DEEP_AUDIT_HANDOVER_AND_RELEASE.md | ✅ |
| demo_script.md | ✅ |
| DEPLOYMENT_RENDER.md | ✅ |
| DEVELOPMENT_SUMMARY.md | ✅ |
| FAILURE_ISOLATION_ANALYSIS.md | ✅ |
| FILE_ORGANIZATION.md | ✅ |
| IMAGE_PIPELINE_TEST_RESULTS.md | ✅ |
| IMPLEMENTATION_SUMMARY.md | ✅ |
| ops_runbook.md | ✅ |
| PHASE_SUMMARY_AND_COSTS.md | ✅ |
| PRODUCTION_HARDENING_STATE_AND_RACE.md | ✅ |
| QUALITY_AUDIT.md | ✅ |
| runbook_go_live.md | ✅ |
| SIDE_EFFECT_ORDERING_AND_LAST_MILE_TESTS.md | ✅ |
| SYSTEM_EVENTS.md | ✅ |
| TEST_CHANGES_AND_SCOPE_ALIGNMENT.md | ✅ |
| WHATSAPP_QUICK_START.md | ✅ |
| WHATSAPP_READY.md | ✅ |
| WHATSAPP_SETUP.md | ✅ |
| WHATSAPP_TESTING_GUIDE.md | ✅ |
| WHATSAPP_VERIFICATION_CHECKLIST.md | ✅ |

---

## 2) Phase 1 — Proof per Clause

### Traceability matrix (A1–A10)

| Contract | Implementation evidence (file:Lines) | Runtime dependency | Acceptance criteria | Tests |
|----------|--------------------------------------|--------------------|---------------------|-------|
| **A1** Guided consultation | `conversation.py` L626–1004; `questions.py` L19–87; `estimation_service.py` L64–352; `location_parsing.py`. Flow: NEW → QUALIFYING; answers in `lead_answers`. | WhatsApp | Consultation works end-to-end | `test_e2e_full_flow.py`, `test_e2e_phase1_happy_path.py`, `test_conversation.py`, `test_phase1_conversation.py`, `test_golden_transcript_phase1.py` |
| **A2** Budget filtering | `region_service.py` L80–98; `conversation.py` L1338–1412 | WhatsApp | Consultation; approval gate | `test_edge_cases_comprehensive.py::test_budget_very_low`, `test_phase1_conversation.py::test_phase1_below_min_budget_sets_needs_follow_up` |
| **A3** Tour conversion + waitlist | `tour_service`; `conversation.py` L1414–1471 | WhatsApp | Consultation | `test_tour_conversion.py`, `test_phase1_conversation.py::test_phase1_tour_conversion_offered` |
| **A4** Deposit rules | `estimation_service.py` L280–315 | — | Deposit link after approval | `test_phase1_services.py`, `test_deposit_locking.py`, `test_xl_deposit_logic.py` |
| **A5** Stripe deposit after approval | `admin.py` L113–121, L231–235; `webhooks.py` L462–496 | Stripe, WhatsApp | Deposit; webhook updates status | `test_go_live_guardrails.py::test_send_deposit_*`, `test_stripe_idempotency_duplicate_event` |
| **A6** Calendar slot suggestions | `calendar_service.py` L331–465; `slot_parsing.py` | Google Calendar (read), WhatsApp | Calendar suggestions correct | `test_phase1_calendar_slots.py`, `test_calendar_edge_cases.py`, `test_slot_parsing.py` |
| **A7** Sheets + action links | `sheets.py`; `action_tokens.py` L78–120, L168–195; `actions.py` | Google Sheets, WhatsApp | Sheet logging; approval gate | `test_action_token_security.py`, `test_action_tokens.py`, `test_phase1_sheets_integration.py` |
| **A8** Dynamic handover | `conversation.py` L448–516, L740–771; `handover_service`; `parse_repair.py` | WhatsApp | Consultation | `test_handover_complications.py`, `test_handover_packet.py`, `test_go_live_guardrails.py::test_soft_repair_*` |
| **A9** Reminders/expiry | `reminders.py` L31–170, L272–390; `safety.py` — `check_and_record_processed_event` | WhatsApp (external cron invokes) | N/A (operational) | `test_phase1_reminders.py`, `test_reminders.py` |
| **A10** Voice pack | `app/copy/en_GB.yml`, `message_composer.py`, `tone.py` | — | N/A | `test_voice_pack.py`, `test_message_composer.py` |

---

### Code excerpts (key items)

#### A5 — Stripe deposit gate (approval → send deposit → webhook)

**Admin approve (status-locked):**
```python
# app/api/admin.py:113-121
success, lead = update_lead_status_if_matches(
    db=db, lead_id=lead_id,
    expected_status=STATUS_PENDING_APPROVAL,
    new_status=STATUS_AWAITING_DEPOSIT,
    approved_at=func.now(),
    last_admin_action="approve",
    last_admin_action_at=func.now(),
)
```

**Send deposit (status-locked to AWAITING_DEPOSIT):**
```python
# app/api/admin.py:231-235
if lead.status != STATUS_AWAITING_DEPOSIT:
    raise HTTPException(
        status_code=400,
        detail=f"Cannot send deposit link for lead in status '{lead.status}'. Lead must be in '{STATUS_AWAITING_DEPOSIT}'.",
    )
```

**Stripe webhook:**
```python
# app/api/webhooks.py:462-466, 485-496
if event_type == "checkout.session.completed":
    # ... get lead_id from metadata/client_reference_id
    if lead.stripe_checkout_session_id != checkout_session_id:
        # Reject session mismatch
```

#### A7 — Action tokens (single-use, expiry, status-locked)

```python
# app/services/action_tokens.py:95-119
if action_token.used:
    return None, "This action link has already been used"
if now > expires:
    return None, "This action link has expired"
if lead.status != action_token.required_status:
    return None, f"Cannot perform this action. Lead is in status '{lead.status}', but requires '{action_token.required_status}'"
```

```python
# app/services/action_tokens.py:178-181 — status-locked token generation
elif lead_status == "AWAITING_DEPOSIT":
    tokens["send_deposit"] = get_action_url(
        generate_action_token(db, lead_id, "send_deposit", "AWAITING_DEPOSIT")
    )
```

#### A8 — Handover + cooldown

```python
# app/services/conversation.py:491-510
HANDOVER_HOLD_REPLY_COOLDOWN_HOURS = 6  # constant
send_hold = last_hold_at is None or (now_utc - last_hold_at) >= timedelta(hours=HANDOVER_HOLD_REPLY_COOLDOWN_HOURS)
if send_hold:
    await send_whatsapp_message(...)
    lead.handover_last_hold_reply_at = now_utc
```

#### A9 — Reminders / idempotency

```python
# app/services/reminders.py:66-68, 90-96
hours_threshold = 12 if reminder_number == 1 else 36
event_id = f"reminder_qualifying_{lead.id}_{reminder_number}_{hours_threshold}h"
is_duplicate, processed = check_and_record_processed_event(
    db=db, event_id=event_id, event_type=f"reminder.qualifying.{reminder_number}", lead_id=lead.id,
)
```

**Scheduling mechanism:** Reminders are invoked by calling `check_and_send_qualifying_reminder` / `check_and_send_booking_reminder` etc. There is no built-in cron in the app. The design expects an external scheduler (e.g. Render cron, worker, or admin sweep) to poll/trigger these. `render.yaml` includes a commented cron for deposit sweep; a similar pattern would apply for reminder sweeps.

---

## 3) Phase 2 Gaps — Concrete Evidence

### Phase 2 acceptance status

**Phase 2 is not accepted** until B2 and B3 are implemented and Schedule B Acceptance Criteria are met.

### What exists (B1, B4)

| Item | Evidence | Explicit exclusions |
|------|----------|---------------------|
| **B1 (partial)** | `app/services/slot_parsing.py` — slot selection; `app/services/conversation.py` — COLLECTING_TIME_WINDOWS, slot selection flow; lead fields `selected_slot_start_at`, `selected_slot_end_at`, `suggested_slots_json`; deposit tied to lead. **Included:** Slot selection UX in chat, deposit binding to selected slot, confirmation messaging. | **No hold entity.** **No calendar write.** |
| **B4** | Stripe webhook updates lead; `app/services/messaging.py` — payment confirmation; `app/services/artist_notifications.py` — notify_artist; `app/services/sheets.py` — log_lead_to_sheets, update_lead_status_in_sheets | — |

### B2 — Holds with TTL: what is missing

| Gap | Detail |
|-----|--------|
| **Data model** | No `slot_hold` table; no `hold_expires_at`; selection stored only on lead |
| **TTL job** | No job to release expired holds |
| **Concurrency** | No lock or conflict check when two clients select the same slot |
| **Conflict fallback** | No behaviour for expired hold or conflict |

**Suggested implementation**

1. **Schema:** New table `slot_holds` with `lead_id`, `slot_start_at`, `slot_end_at`, `hold_expires_at`, `status` (ACTIVE/RELEASED/CONFIRMED), unique constraint on `(slot_start_at, slot_end_at)` where status=ACTIVE.
2. **Module:** `app/services/slot_hold_service.py` — `create_hold`, `release_hold`, `confirm_hold`, `is_slot_available`.
3. **TTL job:** `app/jobs/sweep_expired_holds.py` or admin endpoint `/sweep-expired-holds` called by cron; set status=RELEASED where `hold_expires_at < now`.
4. **Locking:** On create_hold, use `SELECT ... FOR UPDATE` or unique constraint + conflict handling.

**Acceptance tests to add**

- `test_slot_hold_ttl_expires_and_releases_slot`
- `test_concurrent_hold_same_slot_only_one_succeeds`
- `test_hold_expired_offers_alternative_slot`

### B3 — Google Calendar event creation: what is missing

| Gap | Detail |
|-----|--------|
| **Calendar write** | `app/services/calendar_service.py` — `find_event_by_lead_tag` is a stub (returns None); no `events.insert` |
| **Trigger** | Stripe webhook does not create calendar event on `checkout.session.completed` |
| **Retry/recovery** | No reconciliation for "paid but no event" |
| **Scope** | No Calendar write scope in Google credentials flow |

**Suggested implementation**

1. **Module:** `app/services/calendar_service.py` — add `create_event_for_lead(lead_id, slot_start, slot_end, title)` using Google Calendar API `events.insert`.
2. **Trigger:** In Stripe webhook, after status update to DEPOSIT_PAID/BOOKING_PENDING, call `create_event_for_lead` with `selected_slot_start_at`, `selected_slot_end_at`.
3. **Retry:** Store `calendar_event_id` on lead; on failure, log to `system_events`; add admin/sweep job to retry paid leads with no `calendar_event_id`.
4. **Config:** Add `GOOGLE_CALENDAR_WRITE_SCOPE` and ensure OAuth includes `calendar.events` write.

**Acceptance tests to add**

- `test_calendar_event_created_on_deposit_paid`
- `test_calendar_event_matches_selected_slot`
- `test_paid_lead_without_event_triggers_reconciliation`

---

### P0 Implementation Checklist (B2 and B3)

#### B2 — Holds with TTL

| Item | Detail |
|------|--------|
| **Schema** | Alembic migration: `slot_holds` table (`lead_id`, `slot_start_at`, `slot_end_at`, `hold_expires_at`, `status`). Unique constraint `(slot_start_at, slot_end_at)` where status=ACTIVE. |
| **Service** | `app/services/slot_hold_service.py` — `create_hold()`, `release_hold()`, `confirm_hold()`, `is_slot_available()` |
| **Integration** | Slot selection flow in `conversation.py` → call `create_hold()` before deposit; Stripe webhook → call `confirm_hold()` on payment |
| **TTL job** | `app/jobs/sweep_expired_holds.py` or admin endpoint `/sweep-expired-holds`; Render cron (see `render.yaml` commented section) |
| **Unit tests** | `tests/test_slot_hold_service.py` |
| **E2E tests** | `tests/test_slot_hold_integration.py` — `test_slot_hold_ttl_expires_and_releases_slot`, `test_concurrent_hold_same_slot_only_one_succeeds` |

#### B3 — Calendar event creation

| Item | Detail |
|------|--------|
| **Schema** | Add `calendar_event_id` to `leads` (Alembic migration) |
| **Service** | `app/services/calendar_service.py` — add `create_event_for_lead(lead_id, slot_start, slot_end, title)` using Google Calendar API `events.insert` |
| **Integration** | Stripe webhook (`webhooks.py` L462+): after status DEPOSIT_PAID/BOOKING_PENDING, call `create_event_for_lead` with `selected_slot_start_at`, `selected_slot_end_at` |
| **Retry** | Admin/sweep job for leads with `deposit_paid_at` set but `calendar_event_id` null |
| **Unit tests** | `tests/test_calendar_write.py` |
| **E2E tests** | `tests/test_calendar_event_creation.py` — `test_calendar_event_created_on_deposit_paid`, `test_calendar_event_matches_selected_slot` |

---

## 4) Build-Quality Claims — Evidence

| Claim | Exact evidence | Verdict |
|-------|----------------|---------|
| **Correlation IDs** | `app/api/webhooks.py` L50–56: `correlation_id = str(uuid.uuid4())`; L54: `logger.info(f"whatsapp.inbound_received correlation_id={correlation_id}", extra={"correlation_id": correlation_id, "event_type": "whatsapp.inbound_received"})` | ✅ Verified |
| **Health checks** | `app/main.py` L111: `@app.get("/health")`; L137: `@app.get("/ready")`; L148: `db.execute(text("SELECT 1"))` for DB connectivity | ✅ Verified |
| **Render deployment** | `render.yaml` L10: `healthCheckPath: /health`; L3–8: web service + Dockerfile; L22–27: managed PostgreSQL | ✅ Verified |
| **~840 tests** | 845 collected, 840 passed, 1 skipped, 4 xfailed | ✅ Verified |
| **Runbook** | `docs/runbook_go_live.md` — pre-launch checklist, health checks, guardrail tests, launch procedures | ✅ Verified |
| **System events** | `app/services/system_event_service.py` — `info()`, `warn()`, `error()`; `docs/SYSTEM_EVENTS.md`; events at webhook failures, atomic conflicts | ✅ Verified |
| **WhatsApp 24h template fallback** | `app/services/whatsapp_window.py` L50–186: `send_with_window_check()`; L186: `send_template_message()` when outside 24h. Test: `test_golden_transcript_outside_24h_template_then_resume` asserts template path used after simulated 25h gap. | ✅ Verified |

---

## 5) Risk Register (Contract-Relevant)

| Risk | Likelihood | Impact | Mitigation in code | Contract clause |
|------|------------|--------|--------------------|-----------------|
| **Double booking without holds** | High | High | None — B2 not implemented | Schedule B acceptance: concurrency protection |
| **Paid but no calendar event** | High | High | None — B3 not implemented | Schedule B acceptance: calendar event created |
| **Invalid status transitions** | Medium | Medium | `state_machine.transition()` used in critical paths; some direct assigns remain | Schedule A: status machine enforced |
| **Duplicate webhook processing** | Low | High | ProcessedMessage idempotency; Stripe event_id check | Idempotency |
| **Stripe session mismatch** | Low | High | Checkout session ID validated in webhook | Deposit link / webhook correctness |
| **Third-party outage (Meta, Stripe, Google)** | Medium | High | Graceful degradation; no built-in retry queue for Calendar | Clause 13: third-party responsibility |
| **Reminder sweep not run** | Medium | Medium | Reminders require external cron/worker; no built-in scheduler | A9 operational; client responsibility |
| **Action token reuse** | Low | Medium | `used` flag; status check | A7 security |

---

## Appendix — Stripe Webhook Events Handled

| Event type | Handled | Status changes |
|------------|---------|----------------|
| `checkout.session.completed` | ✅ | AWAITING_DEPOSIT or NEEDS_ARTIST_REPLY → DEPOSIT_PAID → BOOKING_PENDING |
| Other events | ❌ | Not handled; return 200 |

---

## Appendix — ALLOWED_TRANSITIONS (contract statuses)

Contract statuses referenced in Schedules A/B are implemented in `app/services/state_machine.py` `ALLOWED_TRANSITIONS`:

- NEW, QUALIFYING, PENDING_APPROVAL, AWAITING_DEPOSIT, DEPOSIT_PAID, BOOKING_PENDING, BOOKED
- NEEDS_ARTIST_REPLY, NEEDS_FOLLOW_UP, REJECTED, ABANDONED, STALE, OPTOUT
- TOUR_CONVERSION_OFFERED, WAITLISTED, COLLECTING_TIME_WINDOWS, BOOKING_LINK_SENT, DEPOSIT_EXPIRED

`transition()` is used in conversation, calendar_service, time_window_collection, parse_repair; `update_lead_status_if_matches` is used for admin/Stripe atomic updates. Some legacy paths may still assign status directly; architecture audit recommends migrating all to `transition()`.
