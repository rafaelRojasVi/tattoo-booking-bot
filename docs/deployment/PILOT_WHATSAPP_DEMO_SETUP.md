# Pilot WhatsApp Demo — Setup Guide

**Purpose:** Run the booking bot in production-like mode on a hosted URL, connected to Meta WhatsApp Cloud API, with pilot allowlist, for clients to test by messaging a WhatsApp number.

**Constraints:** No new features; configuration, deployment, and verification only. Code changes only if a setup blocker exists.

---

## A) Repo Facts

### Webhook route

| Item | Value |
|------|-------|
| **Webhook path** | `POST /webhooks/whatsapp` |
| **Full URL** | `https://YOUR-APP.onrender.com/webhooks/whatsapp` |
| **Verification** | `GET /webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=TOKEN&hub.challenge=CHALLENGE` |
| **Source** | `app/main.py` L162: `app.include_router(webhooks_router, prefix="/webhooks")`; `app/api/webhooks.py` L40: `@router.post("/whatsapp")` |

### Webhook verification

- **Verify token**: From `settings.whatsapp_verify_token` (env `WHATSAPP_VERIFY_TOKEN`)
- **Logic**: `app/api/webhooks.py` L29–37: if `hub_mode == "subscribe"` and `hub_verify_token == settings.whatsapp_verify_token`, return `hub_challenge` as plain text
- **Signature**: `X-Hub-Signature-256` verified via `verify_whatsapp_signature()` (requires `WHATSAPP_APP_SECRET` in production)

### WhatsApp sending (dry_run)

- **Config**: `settings.whatsapp_dry_run` (env `WHATSAPP_DRY_RUN`, default `true`)
- **Location**: `app/services/messaging.py` — `send_whatsapp_message` checks `settings.whatsapp_dry_run`; when True, logs only, no API call
- **Pilot behavior**: Set `WHATSAPP_DRY_RUN=false` for real replies

### Required env vars (startup fail-fast)

From `app/main.py` L31–39:

| Env var | Required | Purpose |
|---------|----------|---------|
| `DATABASE_URL` | Yes | PostgreSQL connection |
| `WHATSAPP_VERIFY_TOKEN` | Yes | Webhook verification |
| `WHATSAPP_ACCESS_TOKEN` | Yes | Meta API token |
| `WHATSAPP_PHONE_NUMBER_ID` | Yes | Meta phone number ID |
| `STRIPE_SECRET_KEY` | Yes | Stripe API |
| `STRIPE_WEBHOOK_SECRET` | Yes | Stripe webhook verification |
| `FRESHA_BOOKING_URL` | Yes (config) | Booking URL |
| `ADMIN_API_KEY` | Yes in prod | Admin auth |
| `WHATSAPP_APP_SECRET` | Yes in prod | Webhook signature verification |

### Pilot mode

| Env var | Default | Purpose |
|---------|---------|---------|
| `PILOT_MODE_ENABLED` | `false` | When `true`, only allowlisted numbers can start consultation |
| `PILOT_ALLOWLIST_NUMBERS` | `""` | Comma-separated numbers (country code, no `+`), e.g. `447123456789,447987654321` |

**Source**: `app/core/config.py` L76–80; `app/api/webhooks.py` L191–242.

---

## B) Render Deployment Steps

1. **Connect repo**
   - Push to GitHub
   - Render Dashboard → New → Web Service
   - Connect repo, select branch (`master`)

2. **Create PostgreSQL**
   - New → PostgreSQL
   - Name: `tattoo-booking-bot-db`
   - Copy `Internal Database URL`

3. **Web service**
   - Use existing `render.yaml` or create manually
   - **Build**: Docker (Dockerfile in repo)
   - **Environment**: `docker`
   - **Health check**: `/health`

4. **Env vars** (Web Service → Environment)
   - `DATABASE_URL` = (from PostgreSQL)
   - `APP_ENV` = `production`
   - `DEMO_MODE` = `false`
   - `WHATSAPP_VERIFY_TOKEN` = (random string, e.g. `openssl rand -hex 16`)
   - `WHATSAPP_ACCESS_TOKEN` = (from Meta)
   - `WHATSAPP_PHONE_NUMBER_ID` = (from Meta)
   - `WHATSAPP_APP_SECRET` = (from Meta)
   - `WHATSAPP_DRY_RUN` = `false` (for pilot)
   - `STRIPE_SECRET_KEY` = (Stripe test key for pilot)
   - `STRIPE_WEBHOOK_SECRET` = (Stripe webhook secret)
   - `FRESHA_BOOKING_URL` = (placeholder OK for pilot)
   - `ADMIN_API_KEY` = (e.g. `openssl rand -hex 32`)
   - `ACTION_TOKEN_BASE_URL` = `https://YOUR-SERVICE.onrender.com`
   - `PILOT_MODE_ENABLED` = `true`
   - `PILOT_ALLOWLIST_NUMBERS` = `CLIENT_NUMBER` (e.g. `447123456789`)

5. **Deploy**
   - Trigger deploy, wait for build

6. **Health checks**
   ```bash
   curl https://YOUR-SERVICE.onrender.com/health
   # Expect: {"ok":true,"templates_configured":[...],...}
   
   curl https://YOUR-SERVICE.onrender.com/ready
   # Expect: {"ok":true,"database":"connected"}
   ```

7. **Migrations**
   - Run migrations (Render shell or local with prod `DATABASE_URL`):
   ```bash
   alembic upgrade head
   ```

---

## C) Meta WhatsApp Steps

1. **Meta for Developers**
   - [developers.facebook.com/apps](https://developers.facebook.com/apps/)
   - Create app or use existing → Add product → WhatsApp

2. **API Setup**
   - WhatsApp → API Setup
   - Copy **Temporary access token** (24h expiry; for long demo use System User token)
   - Copy **Phone number ID**
   - Add client number as **test recipient** (To field)

3. **App Secret**
   - Settings → Basic → App Secret → Show → Copy

4. **Webhook**
   - WhatsApp → Configuration → Webhook
   - **Callback URL**: `https://YOUR-SERVICE.onrender.com/webhooks/whatsapp`
   - **Verify token**: Same as `WHATSAPP_VERIFY_TOKEN`
   - Subscribe: `messages`
   - Verify and Save

5. **Test**
   - Client messages the WhatsApp Business number with "Hi"
   - Bot should reply with first question (within ~24h window = free-form)

---

## D) 24h Window + Templates

### Window logic

- **Source**: `app/services/whatsapp_window.py`
- **Rule**: `last_client_message_at + 24h`; if `now < window_expires_at` → free-form; else → template required
- **Lead opt-out**: Always blocks outbound (returns `opted_out`)

### Template switch

- `send_with_window_check()` (`whatsapp_window.py` L50–269)
- If within window: `send_whatsapp_message()` (free-form)
- If outside window and `template_name`: check `get_all_required_templates()`, then `send_template_message()` or graceful degradation

### Required templates (registry)

From `app/services/template_registry.py` + `whatsapp_templates.py`:

| Template key | Used for |
|--------------|----------|
| `consultation_reminder_2_final` | 36h qualifying reminder |
| `next_steps_reply_to_continue` | Approval, deposit link, slot suggestions, no-slots fallback |
| `deposit_received_next_steps` | Deposit confirmation outside window |
| `reminder_booking` | Booking reminder (24h/72h) — **hardcoded**, not in registry |

### Template registration

- `app/services/template_registry.py`: `get_all_required_templates()` returns registry values
- `reminder_booking` is used in `reminders.py` but **not** in `TEMPLATE_REGISTRY`; booking reminder is outside registry
- `template_check.py` uses `REQUIRED_TEMPLATES` (registry + `test_template`)

### Missing templates

- If template not in `required_templates`: `send_with_window_check` returns `{"status": "window_closed_template_not_configured", ...}` — **no exception**
- Message is **not** sent
- Artist can be notified if configured

### Blocker: Reminders mark "sent" without sending

**Finding**: `check_and_send_qualifying_reminder` and `check_and_send_booking_reminder` do **not** check `result["status"]` after `send_with_window_check`. When template is not configured or window closed without successful send, they still:
- Update lead timestamp (`reminder_qualifying_sent_at`, `reminder_booking_sent_24h_at`)
- Return `{"status": "sent"}`

**Impact**: Silent failure; lead marked as reminded but no message delivered; idempotency prevents retry.

**Minimal fix** (proposed):

In `app/services/reminders.py`, after `result = asyncio.run(send_with_window_check(...))`:

1. Check `result.get("status")` for failure indicators: `window_closed_template_not_configured`, `window_closed_no_template`, `window_closed_template_send_failed`, `opted_out`
2. If failure: do **not** update lead timestamp, do **not** commit; return `{"status": "template_not_configured"}` (or similar) with `result` for debugging
3. Do **not** record processed event for these cases (or record only on successful send — requires refactor of `check_and_record_processed_event`)

**Scope**: Qualifying reminder (L157–173) and booking reminder (L369–391). Same pattern for both.

---

## E) Verification Checklist + Test Script

### Local verification

```bash
# 1. Start server (local)
python -m uvicorn app.main:app --reload
# Or: docker compose up

# 2. Health
curl http://localhost:8000/health
curl http://localhost:8000/ready

# 3. Webhook verification (replace YOUR_TOKEN)
curl "http://localhost:8000/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=test123"
# Expect: "test123" (plain text)

# 4. Key tests
python -m pytest tests/test_webhooks.py tests/test_pilot_mode.py -v -q
```

### Pilot test script (for Jonah / client)

**Pre-requisites**: Client number in `PILOT_ALLOWLIST_NUMBERS`, WhatsApp webhook configured, `WHATSAPP_DRY_RUN=false`.

| Step | Client action | Expected |
|------|---------------|----------|
| 1 | Send `Hi` | Bot: first question (idea/concept) |
| 2 | Answer: `A dragon on my arm` | Bot: next question (placement) |
| 3 | Continue answering each question | Bot: progresses through 13 questions |
| 4 | (Optional) Send `Can you do it cheaper?` mid-flow | Bot: handover message; status NEEDS_ARTIST_REPLY |
| 5 | Send `CONTINUE` (after handover) | Bot: resumes from current question |
| 6 | Complete all questions | Bot: "Thanks, I'm reviewing…"; status PENDING_APPROVAL |

**Artist inbox**: Use admin/action links to Approve, Send Deposit, Mark Booked (or `GET /admin/leads`, action token URLs).

### Client checklist (copy-paste)

1. Open WhatsApp
2. Message the bot number with: **Hi**
3. Reply to each question as prompted
4. Try going off-script: **Can you do it cheaper?** — you should get a handover message
5. Type **CONTINUE** to resume
6. Finish all questions; you should see "Thanks, I'm reviewing…"

---

## F) Blockers / Risks

### P1 — Code change recommended

1. **Reminders mark "sent" without sending**  
   When template is missing or window closed, reminders update lead and return "sent" but no message is sent. **Fix**: Check `result["status"]` in `reminders.py` and do not update timestamp / do not return "sent" on failure statuses.

### P2 — Configuration / operational

2. **Temporary access token expiry**  
   Meta temporary token expires ~24h. For multi-day pilot, use System User with long-lived token.

3. **Booking reminder template**  
   `reminder_booking` is not in the registry; ensure it exists in WhatsApp Manager if booking reminders will run outside 24h window.

4. **Render free tier cold start**  
   First request after inactivity can take ~30s; WhatsApp may retry or timeout. Paid tier reduces risk.

### P3 — Optional hardening

5. **OPTOUT restart**  
   `last_client_message_at` not updated on opt-back-in; next message may need template. Low impact for pilot.

6. **Processed-event before send**  
   Reminders record processed event before send; send failure can drop reminder. Refactor to record-after-send for strict correctness.
