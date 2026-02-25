# Ops Quickstart — For Jonah (Client)

One-page reference for day-to-day operation of the Tattoo Booking Bot.

---

## Where to See Leads

| Source | What you see |
|--------|--------------|
| **Google Sheets** | All leads logged with status, answers, booking info. Enable with `GOOGLE_SHEETS_ENABLED=true` and configured spreadsheet. |
| **Admin API** | `GET /admin/leads` (requires `X-Admin-API-Key`). Use for API clients or debugging. |
| **Artist WhatsApp** | Handover summaries (when `ARTIST_WHATSAPP_NUMBER` is set) — brief summaries for leads that need a reply. |

---

## Scheduled Jobs (Cron)

Run these on a schedule (e.g. Render Cron or external cron).

### Retention cleanup (recommended: daily)

Keeps `system_events` from growing unbounded.

```bash
curl -X POST "https://YOUR-DOMAIN/admin/events/retention-cleanup?retention_days=90" \
  -H "X-Admin-API-Key: YOUR_ADMIN_KEY"
```

**Response:** `{"deleted": N, "retention_days": 90}`

### Outbox retry (when `OUTBOX_ENABLED=true`)

Retries failed outbound messages.

```bash
curl -X POST "https://YOUR-DOMAIN/admin/outbox/retry?limit=10" \
  -H "X-Admin-API-Key: YOUR_ADMIN_KEY"
```

---

## If Templates Aren't Configured

1. Check `/health` — it reports `templates_configured` and any missing templates.
2. Missing templates cause fallbacks (e.g. outside 24h window, reminders) to fail or degrade.
3. Add templates in [Meta Business Suite](https://business.facebook.com/) → WhatsApp Manager → Message Templates. See `docs/runbooks/ops_runbook.md` for exact template names and bodies.

---

## Emergency / Fallback

| Situation | Action |
|-----------|--------|
| **Bot misbehaving** | Enable panic mode: `FEATURE_PANIC_MODE_ENABLED=true`. Bot stops automated replies but still logs messages. |
| **DB or API issues** | Check `/health` and `/ready`. Review Render logs. |
| **Need to fix something** | Contact your developer. Full runbook: `docs/runbooks/ops_runbook.md`. Ship checklist: `docs/misc/SHIP_READINESS_CHECK.md`. |

---

**Quick commands:** See `docs/runbooks/ops_runbook.md` → Quick Reference for more curl examples.
