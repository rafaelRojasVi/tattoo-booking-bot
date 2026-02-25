# Test Results & Scaling / Error Handling Report

**Generated:** 2026-02-17

---

## 1. Full Test Results

### Summary
| Metric | Value |
|--------|-------|
| **Passed** | 875 |
| **Skipped** | 2 |
| **XFailed** | 0 |
| **XPassed** | 0 |
| **Warnings** | 17 |
| **Duration** | ~11.3 seconds |

### Post-fix delta (2026-02-17)
- **Stability:** Removed XPASS and all XFAILs; suite now deterministic.
- **Async correctness:** All previously un-awaited coroutines fixed; regression guard added by treating "never awaited" as an error.
- **Idempotency hardening:** Added `(provider, message_id)` uniqueness; webhook marks processed first with `flush()`, duplicates short-circuit safely; expanded providers across Stripe/reminders.
- **Concurrency safety:** Enforced via **conditional UPDATE** step-advance (compare-and-swap). Only the request that successfully advances the step is allowed to send the next prompt. SQLite skips locking-based test; Postgres CI job runs `test_production_hardening.py -k concurrent` for real lock semantics coverage.

### Test Suites Run
- `test_golden_transcript_phase1.py` – 11 tests (Phase 1 golden transcripts)
- `test_e2e_phase1_happy_path.py` – E2E Phase 1 flow
- `test_e2e_full_flow.py` – Full qualification to booking
- `test_webhooks.py` / `test_webhooks_extended.py` – WhatsApp & Stripe webhooks
- `test_idempotency_and_out_of_order.py` – Message ordering
- `test_go_live_guardrails.py` – Production safety
- `test_state_machine.py` – Status transitions
- `test_conversation.py` – Conversation flow
- `test_system_events.py` – SystemEvent logging
- `test_production_hardening.py` / `test_production_last_mile.py` – Concurrency, side effects
- `test_phase1_services.py` – Service layer
- `test_admin_actions.py` – Admin API
- `test_action_tokens.py` – Secure links
- `test_stripe_webhook.py` – Stripe processing
- `test_http_timeouts.py` – HTTP client timeouts (worker blocking prevention)
- Plus 30+ other test files

### Golden Transcript Tests (11)
| Test | Status |
|------|--------|
| `test_golden_transcript_phase1_happy_path` | PASSED |
| `test_golden_transcript_repair_once_flow` | PASSED |
| `test_golden_transcript_handover_cooldown_and_continue_flow` | PASSED |
| `test_golden_transcript_media_wrong_step_ack_and_reprompt_flow` | PASSED |
| `test_golden_transcript_multi_answer_bundle_reprompts_and_no_advance` | PASSED |
| `test_golden_transcript_outside_24h_template_then_resume` | PASSED |
| `test_golden_transcript_multi_answer_single_message_one_at_a_time` | PASSED |
| `test_golden_transcript_user_goes_quiet_then_returns_later` | PASSED |
| `test_golden_transcript_dimensions_accepts_10x15cm_currency_advances_to_style` | PASSED |
| `test_golden_transcript_reference_images_accepts_realism_at_advances_to_budget` | PASSED |
| `test_restart_then_new_answers_override_old_answers_in_summary` | PASSED |

---

## 2. Event Structure (SystemEvents) – Scaling Assessment

### Schema
| Column | Type | Indexed | Notes |
|--------|------|---------|-------|
| `id` | Integer | PK | Auto-increment |
| `created_at` | DateTime(TZ) | Yes | Time-based queries |
| `level` | String(10) | Yes | INFO, WARN, ERROR |
| `event_type` | String(100) | Yes | e.g. `whatsapp.send_failure` |
| `lead_id` | Integer (nullable) | Yes | Lead correlation |
| `payload` | JSON | No | Additional context |

### Indexes (Scaling)
- `ix_system_events_created_at` – time-range queries
- `ix_system_events_level` – filter by severity
- `ix_system_events_event_type` – filter by type
- `ix_system_events_lead_id` – filter by lead

**Verdict:** Indexes are appropriate for common query patterns. For high volume:
- Consider partitioning by `created_at` (e.g. monthly) if events grow very large
- Add retention/archival policy (e.g. delete events older than 90 days)
- No composite index yet; `(lead_id, created_at)` could help lead-specific queries

### Event Types Logged (Coverage)
| Event Type | Level | Location | Purpose |
|------------|-------|----------|---------|
| `whatsapp.signature_verification_failure` | WARN | webhooks.py | Invalid webhook signature |
| `whatsapp.webhook_failure` | ERROR | webhooks.py | Conversation handling exception |
| `whatsapp.send_failure` | ERROR | whatsapp_window.py | Message send failed |
| `whatsapp.template_not_configured.{name}` | WARN | whatsapp_window.py | Missing template |
| `template.fallback_used` | INFO | whatsapp_window.py | 24h window closed, template used |
| `stripe.signature_verification_failure` | WARN | webhooks.py | Invalid Stripe signature |
| `stripe.session_id_mismatch` | ERROR | webhooks.py | Checkout session/lead mismatch |
| `stripe.webhook_failure` | ERROR | webhooks.py | Webhook processing failed |
| `atomic_update.conflict` | WARN | safety.py | Race condition / status mismatch |
| `calendar.no_slots_fallback` | INFO | calendar_service.py | No slots, time window fallback |
| `slot.unavailable_after_selection` | WARN | conversation.py | Slot no longer available |
| `media_upload.failure` | ERROR | media_upload.py | Supabase upload failed |
| `sheets.background_log_failure` | ERROR | webhooks.py | Sheets update failed |
| `sheets.background_db_error` | ERROR | webhooks.py | DB error during Sheets flow |
| `pilot_mode.blocked` | INFO | webhooks.py | Message from non-allowlisted number |
| `deposit_expired_sweep` | INFO | admin.py | Deposit sweep job |

---

## 3. Worker Configuration & Scaling

### Current Setup
| Component | Value |
|-----------|-------|
| **Dockerfile** | `uvicorn ... --workers ${WEB_CONCURRENCY:-2}` |
| **render.yaml** | `WEB_CONCURRENCY: "2"` |
| **docker-compose (dev)** | Single worker with `--reload` |

### Scaling Assessment
- **Workers:** Default 2 in production (Render). Can be increased via `WEB_CONCURRENCY` (e.g. 4–8 for higher load).
- **HTTP timeouts:** `app/services/http_client.py` – connect 5s, read 10s, write 5s, pool 5s. Prevents workers blocking on slow external APIs.
- **test_http_timeouts.py:** Ensures `create_httpx_client()` is used and no raw `httpx.AsyncClient()` without timeout.
- **Worker survival:** `scripts/smoke_workers.sh` verifies killing one worker does not take down the service (requires ≥2 workers).

### Recommendations
1. For higher traffic: set `WEB_CONCURRENCY=4` or higher in Render.
2. Consider Gunicorn + Uvicorn workers for production (see `docs/FAILURE_ISOLATION_ANALYSIS.md`).
3. Ensure DB connection pool size matches worker count (SQLAlchemy pool).

---

## 4. Error Handling Coverage

### SystemEvent Usage (Structured Logging)
| Module | SystemEvent Calls | Coverage |
|--------|-------------------|----------|
| `webhooks.py` | 8+ | WhatsApp/Stripe failures, Sheets/DB errors |
| `whatsapp_window.py` | 4 | send_failure, template_not_configured, template.fallback_used |
| `safety.py` | 1 | atomic_update.conflict |
| `conversation.py` | 1 | slot.unavailable_after_selection |
| `calendar_service.py` | 1 | calendar.no_slots_fallback |
| `media_upload.py` | 1 | media_upload.failure |
| `admin.py` | 2 | deposit_expired_sweep, debug lead |

### Gaps (logger.error but no SystemEvent)
- `artist_notifications.py` – artist send failures (logger only)
- `stripe_service.py` – checkout creation errors (logger only)
- `sheets.py` – Sheets API errors (logger only; webhooks path does log SystemEvent)
- `actions.py` – action token execution errors (logger only)
- `demo.py` – demo-mode errors (logger only; acceptable for dev)

### FastAPI / Global Error Handling
- No global exception handler in `main.py` – errors bubble to FastAPI default handlers.
- Webhook handlers use try/except and return appropriate HTTP codes.
- WhatsApp webhook returns 200 on processing errors to avoid Meta retries (errors logged).

### Best Practices in Use
1. **Idempotency:** ProcessedMessage, Stripe event_id – duplicate events ignored.
2. **Side-effect ordering:** DB commit before Sheets/WhatsApp; failures logged as SystemEvent.
3. **Timeouts:** All HTTP clients use explicit timeouts.
4. **Correlation IDs:** Generated for webhook requests (could be threaded to SystemEvent payloads per ARCHITECTURE_SANITY_CHECK).

---

## 5. Run Commands

```powershell
# Full test suite (SQLite)
docker compose -f docker-compose.test.yml run --rm test pytest tests/ -v

# Concurrency tests (Postgres) — SQLite skips these; run against Postgres for real lock coverage
docker compose -f docker-compose.test-postgres.yml run --rm test-postgres

# Golden transcript tests only
docker compose -f docker-compose.test.yml run --rm test pytest tests/test_golden_transcript_phase1.py -v

# System events tests
docker compose -f docker-compose.test.yml run --rm test pytest tests/test_system_events.py -v

# HTTP timeout tests (worker blocking)
docker compose -f docker-compose.test.yml run --rm test pytest tests/test_http_timeouts.py -v
```
