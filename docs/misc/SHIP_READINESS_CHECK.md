# Ship Readiness Check

Pre-launch checklist for staging and production deployment of the Tattoo Booking Bot.

---

## 1) Top-Level Checklist

| # | Area | Staging | Prod |
|---|------|---------|------|
| 1 | **WhatsApp webhook verify** | GET `/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=<TOKEN>&hub.challenge=test` returns challenge | Same |
| 2 | **WhatsApp send message** | Smoke script sends (dry-run or real); bot responds to inbound | `WHATSAPP_DRY_RUN=false` |
| 3 | **Template messages** | 24h+ window triggers template; `/health` shows templates configured | Same |
| 4 | **Stripe checkout + webhook** | Deposit link → test payment → webhook updates lead to BOOKING_PENDING | Live key + live webhook secret |
| 5 | **Outbox retry** | `POST /admin/outbox/retry` (when OUTBOX_ENABLED) retries PENDING/FAILED | Same |
| 6 | **Retention cleanup** | `POST /admin/events/retention-cleanup?retention_days=90` deletes old SystemEvents | Same; schedule daily cron |
| 7 | **Migrations** | `alembic upgrade head` before deploy | Same (preDeployCommand in Render) |
| 8 | **Health checks** | `/health` returns `ok: true`; `/ready` returns DB connected | Same |

---

## 2) Staging Checklist (Detailed)

### WhatsApp Integration

- [ ] **Webhook verification**
  - Meta Business Manager → Webhooks → Configure URL: `https://<staging-url>/webhooks/whatsapp`
  - Verify token matches `WHATSAPP_VERIFY_TOKEN`
  - Test: `curl "https://<staging-url>/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=<TOKEN>&hub.challenge=test"`
  - Expected: Response body is `test`

- [ ] **Send message**
  - Run: `docker compose exec api python scripts/whatsapp_smoke.py --to <YOUR_NUMBER>`
  - With `WHATSAPP_DRY_RUN=true`: logs "Would send" (no real send)
  - With `WHATSAPP_DRY_RUN=false`: real message sent

- [ ] **Template**
  - Wait 25+ hours after last message, or send reminder; verify template used (not free-form)
  - `/health` returns `templates_configured` list

### Stripe Integration

- [ ] **Checkout**
  - Approve lead → deposit link sent → complete test payment (Stripe test mode)
  - Expected: `checkout.session.completed` webhook received

- [ ] **Webhook**
  - Stripe Dashboard → Webhooks → Add endpoint: `https://<staging-url>/webhooks/stripe`
  - Events: `checkout.session.completed`, `payment_intent.succeeded`
  - Secret matches `STRIPE_WEBHOOK_SECRET`
  - Test: `curl -X POST https://<staging-url>/webhooks/stripe`
  - Expected: 400 (missing signature) or 200 (if valid test payload)

### Outbox & Retention

- [ ] **Outbox retry** (when `OUTBOX_ENABLED=true`)
  - `curl -X POST "https://<staging-url>/admin/outbox/retry?limit=10" -H "X-Admin-API-Key: <KEY>"`
  - Expected: `{"outbox_retry": {...}}`

- [ ] **Retention cleanup**
  - `curl -X POST "https://<staging-url>/admin/events/retention-cleanup?retention_days=90" -H "X-Admin-API-Key: <KEY>"`
  - Expected: `{"deleted": N, "retention_days": 90}`

---

## 3) Config Matrix: Staging vs Production

| Variable | Staging | Production |
|----------|---------|------------|
| `APP_ENV` | `staging` or `dev` | `production` |
| `WHATSAPP_DRY_RUN` | `true` (test) or `false` (real send) | `false` |
| `WHATSAPP_APP_SECRET` | Optional (skips verification if missing) | **Required** (enforced at startup) |
| `WHATSAPP_VERIFY_TOKEN` | Same as Meta config | Same |
| `WHATSAPP_ACCESS_TOKEN` | Test token | Production token |
| `STRIPE_SECRET_KEY` | `sk_test_...` | `sk_live_...` |
| `STRIPE_WEBHOOK_SECRET` | Test webhook secret | Live webhook secret |
| `OUTBOX_ENABLED` | `false` (optional) | `true` (recommended for durability) |
| `PILOT_MODE_ENABLED` | `true` (restrict to allowlist) | `false` (or `true` for soft launch) |
| `PILOT_ALLOWLIST_NUMBERS` | Comma-separated test numbers | Empty or allowlist |
| `DEMO_MODE` | `false` | `false` |
| `ADMIN_API_KEY` | Set (dev can be weak) | **Required** (strong random key) |
| `DATABASE_URL` | Staging DB | Production DB |
| `ACTION_TOKEN_BASE_URL` | Staging URL | Production URL |
| `STRIPE_SUCCESS_URL` / `STRIPE_CANCEL_URL` | Staging URLs | Production URLs |

---

## 4) Migration Plan

### When

- **Render:** `preDeployCommand: alembic upgrade head` runs before each deploy
- **Manual:** `docker compose exec api alembic upgrade head` or `DATABASE_URL=... alembic upgrade head`

### How

1. Ensure `DATABASE_URL` points to target DB
2. Run: `alembic upgrade head`
3. Verify: `alembic current` shows latest revision

### Rollback Steps

1. **Identify target revision:** `alembic history`
2. **Rollback one migration:** `alembic downgrade -1`
3. **Rollback to specific revision:** `alembic downgrade <revision_id>`
4. **Redeploy previous image** if migration was part of deployment
5. **Restore DB backup** if downgrade fails or data corrupted

### Pre-Migration Safety

- [ ] Create DB backup before migration
- [ ] Test migration on staging first
- [ ] Review migration for destructive (DROP, ALTER) operations
- [ ] Ensure migrations are backward-compatible where possible

---

## 5) Security Basics

| Security Control | Status | Notes |
|------------------|--------|------|
| **Rate limiting** | Enabled | `/admin` and `/a/` (action tokens): 10 req/60s per IP. In-memory; Redis for scale. |
| **WhatsApp signature verification** | Conditional | When `WHATSAPP_APP_SECRET` set: `X-Hub-Signature-256` verified via HMAC-SHA256. If unset: **skips** (dev mode). Production startup requires it. |
| **Stripe signature verification** | Required | `verify_webhook_signature` rejects invalid payloads. |
| **Admin API key** | Required in prod | `app_env=production` → startup fails if `ADMIN_API_KEY` missing. |
| **PII logging policy** | Partial | SystemEvent payloads may contain lead_id; `wa_from` in logs. No explicit masking. Retention cleanup limits exposure. |

### Signature Verification Audit (Cannot Be Disabled in Production)

| Webhook | Verification | Production Safeguard |
|---------|---------------|----------------------|
| **WhatsApp** | `verify_whatsapp_signature(raw_body, X-Hub-Signature-256)` | Startup fails if `WHATSAPP_APP_SECRET` unset. When unset, verification is skipped (dev only). |
| **Stripe** | `verify_webhook_signature(body, Stripe-Signature)` | Startup fails if `STRIPE_WEBHOOK_SECRET` unset or `whsec_test`. Test-mode bypass only when `sk_test_` key + `whsec_test` secret. |

**Conclusion:** In `APP_ENV=production`, both secrets are required and test stubs are rejected. Signature verification cannot be accidentally disabled.

### Rate Limit Details

- **Paths:** `/admin`, `/a/` (action tokens)
- **Limit:** 10 requests per 60 seconds per client IP (config: `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS`)
- **Store:** In-memory sliding window; per-instance (use Redis for multi-instance)
- **Response:** 429 Too Many Requests with `Retry-After` header

---

## 5b) Backup and Rollback

### Backup Before Deploy

```bash
# Render: use Dashboard → Database → Backups, or:
pg_dump $DATABASE_URL > backup_$(date +%Y%m%d_%H%M).sql

# Or use Render's automatic backups (paid plans)
```

### Rollback Steps

1. **Redeploy previous image** (Render: Deploys → select previous → Rollback)
2. **Database:** `alembic downgrade -1` if migration was problematic
3. **Restore backup** if data corrupted: `psql $DATABASE_URL < backup_YYYYMMDD_HHMM.sql`
4. **Verify:** `/health`, `/ready`, run smoke tests

### When to Rollback

- Health check fails after deploy
- Webhook processing errors spike (check SystemEvents)
- Migration fails or causes data loss

---

## 6) 10-Minute Go-Live Test Script

Run these commands in order. Replace `<BASE_URL>` and `<ADMIN_KEY>` with your staging/production values.

### Step 1: Health (30 sec)

```bash
curl -s https://<BASE_URL>/health | jq .
```

**Expected:** `{"ok": true, "templates_configured": [...], "features": {...}}`

---

### Step 2: Ready (30 sec)

```bash
curl -s https://<BASE_URL>/ready | jq .
```

**Expected:** `{"ok": true, "database": "connected"}`

---

### Step 3: WhatsApp Webhook Verify (30 sec)

```bash
curl -s "https://<BASE_URL>/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=YOUR_VERIFY_TOKEN&hub.challenge=test"
```

**Expected:** Response body is exactly `test` (no JSON)

---

### Step 4: Admin Auth (30 sec)

```bash
curl -s -o /dev/null -w "%{http_code}" https://<BASE_URL>/admin/leads -H "X-Admin-API-Key: <ADMIN_KEY>"
```

**Expected:** `200`

```bash
curl -s -o /dev/null -w "%{http_code}" https://<BASE_URL>/admin/leads
```

**Expected:** `401` or `403` (no key = rejected)

---

### Step 5: Send Test Message (1 min)

```bash
docker compose exec api python scripts/whatsapp_smoke.py --to YOUR_WHATSAPP_NUMBER
```

**Expected:** `✅ Result:` with `status: dry_run` or `status: ...` and message_id if real send. No exception.

---

### Step 6: Retention Cleanup (30 sec)

```bash
curl -s -X POST "https://<BASE_URL>/admin/events/retention-cleanup?retention_days=90" \
  -H "X-Admin-API-Key: <ADMIN_KEY>" | jq .
```

**Expected:** `{"deleted": N, "retention_days": 90}`

---

### Step 7: Outbox Retry (30 sec, if OUTBOX_ENABLED)

```bash
curl -s -X POST "https://<BASE_URL>/admin/outbox/retry?limit=10" \
  -H "X-Admin-API-Key: <ADMIN_KEY>" | jq .
```

**Expected:** `{"outbox_retry": {...}}`

---

### Step 8: Funnel Metrics (30 sec)

```bash
curl -s "https://<BASE_URL>/admin/funnel?days=7" -H "X-Admin-API-Key: <ADMIN_KEY>" | jq .
```

**Expected:** JSON with funnel counts by status

---

### Step 9: Slot Parse Stats (30 sec)

```bash
curl -s "https://<BASE_URL>/admin/slot-parse-stats?days=7" -H "X-Admin-API-Key: <ADMIN_KEY>" | jq .
```

**Expected:** `{"success": {...}, "reject": {...}, "total_success": N, "total_reject": N}`

---

### Step 10: End-to-End (5 min)

1. Send WhatsApp message to bot from your number
2. Complete consultation (or at least 2–3 questions)
3. Check lead in admin: `curl -s "https://<BASE_URL>/admin/leads" -H "X-Admin-API-Key: <ADMIN_KEY>" | jq .`
4. Approve lead via admin or action link
5. (Optional) Complete deposit flow if Stripe configured

**Expected:** Lead created, status advances, bot responds at each step.

---

**Total:** ~10 minutes. All green → ship-ready.
