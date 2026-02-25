# Operations Runbook

This document provides step-by-step instructions for setting up, deploying, and troubleshooting the Tattoo Booking Bot in production.

## Table of Contents

1. [Environment Variables Checklist](#environment-variables-checklist)
2. [WhatsApp Template Setup](#whatsapp-template-setup)
3. [Google Sheets Setup](#google-sheets-setup)
4. [Google Calendar Setup](#google-calendar-setup)
5. [Staging Verification](#staging-verification)
6. [Troubleshooting](#troubleshooting)
7. [Panic Mode Procedure](#panic-mode-procedure)

---

## Environment Variables Checklist

### Required Variables

```bash
# Database
DATABASE_URL=postgresql://user:password@host:5432/dbname

# WhatsApp Business API
WHATSAPP_VERIFY_TOKEN=<your_webhook_verify_token>
WHATSAPP_ACCESS_TOKEN=<your_access_token>
WHATSAPP_PHONE_NUMBER_ID=<your_phone_number_id>
WHATSAPP_DRY_RUN=false  # Set to false in production

# Stripe
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_SUCCESS_URL=https://yourdomain.com/success
STRIPE_CANCEL_URL=https://yourdomain.com/cancel

# Admin API Security
ADMIN_API_KEY=<strong_random_key>  # Required in production

# Application
APP_ENV=production
ACTION_TOKEN_BASE_URL=https://yourdomain.com
```

### Feature Flags

```bash
# Feature toggles (all default to true except panic mode)
FEATURE_SHEETS_ENABLED=true
FEATURE_CALENDAR_ENABLED=true
FEATURE_REMINDERS_ENABLED=true
FEATURE_NOTIFICATIONS_ENABLED=true
FEATURE_PANIC_MODE_ENABLED=false  # Only enable when needed
```

### Optional Variables

```bash
# Google Sheets (if FEATURE_SHEETS_ENABLED=true)
GOOGLE_SHEETS_ENABLED=true
GOOGLE_SHEETS_SPREADSHEET_ID=<your_spreadsheet_id>
GOOGLE_SHEETS_CREDENTIALS_JSON=<path_to_service_account_json>

# Google Calendar (if FEATURE_CALENDAR_ENABLED=true)
GOOGLE_CALENDAR_ENABLED=true
GOOGLE_CALENDAR_ID=<your_calendar_id>
GOOGLE_CALENDAR_CREDENTIALS_JSON=<path_to_service_account_json>

# Artist Notifications
ARTIST_WHATSAPP_NUMBER=<artist_phone_number>

# Action Token Expiry
ACTION_TOKEN_EXPIRY_DAYS=7
```

---

## WhatsApp Template Setup

### Step 1: Create Templates in WhatsApp Manager

1. Log into [Meta Business Suite](https://business.facebook.com/)
2. Navigate to **WhatsApp Manager** → **Message Templates**
3. Create the following templates (category: **Utility**):

#### Template 1: `consultation_reminder_2_final`

**Body:**
```
Hey {{1}} — just checking in. If you'd like to continue your tattoo enquiry, reply to this message and we'll pick up where we left off.
```

**Parameters:**
- `{{1}}` - Client name (optional)

**Language:** `en_GB` (or your preferred locale)

---

#### Template 2: `next_steps_reply_to_continue`

**Body:**
```
Your enquiry has been reviewed ✅ Reply to this message to see the next available times and continue.
```

**Parameters:**
- `{{1}}` - Client name (optional)

**Language:** `en_GB`

---

#### Template 3: `deposit_received_next_steps`

**Body:**
```
Deposit received ✅ Thanks {{1}}. Jonah will confirm your booking in Google Calendar and message you with the details shortly.
```

**Parameters:**
- `{{1}}` - Client name (optional)

**Language:** `en_GB`

---

### Step 2: Submit for Approval

1. Submit all templates for Meta approval
2. Wait for approval (typically 24-48 hours)
3. **Important:** Template names must match exactly (case-sensitive)

### Step 3: Verify Template Configuration

After deployment, check the `/health` endpoint:

```bash
curl https://yourdomain.com/health
```

Response should include:
```json
{
  "ok": true,
  "templates_configured": [
    "consultation_reminder_2_final",
    "next_steps_reply_to_continue",
    "deposit_received_next_steps"
  ],
  "templates_missing": [],
  "whatsapp_enabled": true
}
```

### Step 4: Test Template Fallback

1. Send a test message to the bot
2. Wait 25+ hours (outside 24h window)
3. Trigger a reminder or approval action
4. Verify template message is sent (not free-form)

---

## Google Sheets Setup

### Step 1: Create Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing)
3. Enable **Google Sheets API**
4. Navigate to **IAM & Admin** → **Service Accounts**
5. Click **Create Service Account**
6. Name it (e.g., `tattoo-booking-bot`)
7. Grant role: **Editor** (or custom role with Sheets permissions)
8. Click **Done**

### Step 2: Generate JSON Key

1. Click on the service account you just created
2. Go to **Keys** tab
3. Click **Add Key** → **Create new key**
4. Choose **JSON** format
5. Download the JSON file
6. **Store securely** (never commit to git)

### Step 3: Create Spreadsheet

1. Create a new Google Sheet
2. Name it (e.g., "Tattoo Booking Leads")
3. Copy the **Spreadsheet ID** from the URL:
   ```
   https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit
   ```

### Step 4: Share with Service Account

1. In the Google Sheet, click **Share**
2. Add the service account email (from JSON file: `client_email`)
3. Grant **Editor** permission
4. Click **Send**

### Step 5: Configure Environment

```bash
GOOGLE_SHEETS_ENABLED=true
GOOGLE_SHEETS_SPREADSHEET_ID=<your_spreadsheet_id>
GOOGLE_SHEETS_CREDENTIALS_JSON=/path/to/service-account-key.json
```

Or set `GOOGLE_SHEETS_CREDENTIALS_JSON` as the JSON content directly (if using env var injection).

### Step 6: Verify Sheets Integration

1. Create a test lead via WhatsApp
2. Complete qualification
3. Check the Google Sheet - a new row should appear
4. Verify columns are populated correctly

---

## Google Calendar Setup

### Step 1: Create Service Account

1. Follow same steps as Sheets (or reuse same service account)
2. Enable **Google Calendar API** (not just Sheets)

### Step 2: Generate JSON Key

1. Use the same service account or create a new one
2. Download JSON key file
3. Store securely

### Step 3: Create or Use Existing Calendar

1. Go to [Google Calendar](https://calendar.google.com/)
2. Create a new calendar (or use existing)
3. Name it (e.g., "Tattoo Bookings")
4. Copy the **Calendar ID**:
   - Go to calendar settings
   - Find **Calendar ID** (format: `xxxxx@group.calendar.google.com`)

### Step 4: Share Calendar with Service Account

1. In calendar settings, go to **Share with specific people**
2. Add service account email
3. Grant **Make changes to events** permission
4. Click **Send**

### Step 5: Configure Environment

```bash
GOOGLE_CALENDAR_ENABLED=true
GOOGLE_CALENDAR_ID=<your_calendar_id>
GOOGLE_CALENDAR_CREDENTIALS_JSON=/path/to/service-account-key.json
```

### Step 6: Configure Calendar Rules

Edit `app/config/calendar_rules.yml`:

```yaml
timezone: "Europe/London"
working_hours:
  monday:    { start: "10:00", end: "18:00" }
  tuesday:   { start: "10:00", end: "18:00" }
  # ... etc
session_durations_minutes:
  default: 180
  SMALL: 120
  MEDIUM: 180
  LARGE: 240
  XL: 360
buffer_minutes: 30
lookahead_days: 60
minimum_advance_hours: 24
```

### Step 7: Verify Calendar Integration

1. Approve a test lead
2. System should send slot suggestions
3. Check calendar for events (if manual booking detection enabled)

---

## Staging Verification

### Pre-Deployment Checklist

- [ ] All environment variables set
- [ ] WhatsApp templates approved and configured
- [ ] Google Sheets service account has access
- [ ] Google Calendar service account has access
- [ ] Stripe webhook endpoint configured
- [ ] Database migrations applied
- [ ] `/health` endpoint returns `ok: true`
- [ ] Feature flags set correctly

### Test Flow (Staging)

1. **WhatsApp Integration**
   - Send test message to bot
   - Verify bot responds and starts consultation
   - Complete all questions
   - Verify lead appears in Sheets

2. **Approval Flow**
   - Approve lead via admin API
   - Verify slot suggestions sent (if calendar enabled)
   - Verify artist notification sent (if enabled)

3. **Stripe Integration**
   - Send deposit link
   - Complete test payment (Stripe test mode)
   - Verify webhook received and processed
   - Verify lead status updated to `BOOKING_PENDING`

4. **Template Messages**
   - Wait 25+ hours after last message
   - Trigger reminder or approval
   - Verify template message sent (not free-form)

5. **Idempotency**
   - Send duplicate WhatsApp message
   - Verify processed only once
   - Send duplicate Stripe webhook
   - Verify processed only once

6. **State Machine**
   - Try invalid transitions (e.g., approve from wrong status)
   - Verify 400 error returned
   - Verify clear error message

### Production Readiness

- [ ] All staging tests pass
- [ ] Stripe webhook secret updated to live key
- [ ] `WHATSAPP_DRY_RUN=false`
- [ ] `APP_ENV=production`
- [ ] `ADMIN_API_KEY` set (strong random key)
- [ ] Database backups configured
- [ ] Monitoring/logging configured
- [ ] Panic mode procedure documented

---

## Troubleshooting

### Common Errors

#### 1. "Template not found" / Template messages failing

**Symptoms:**
- Template messages not sending
- `/health` shows templates missing

**Solutions:**
- Verify template names match exactly (case-sensitive)
- Check template approval status in WhatsApp Manager
- Verify `WHATSAPP_ACCESS_TOKEN` is valid
- Check logs for specific error messages

**Logs to check:**
```bash
# Look for template-related errors
grep -i "template" /var/log/app.log
```

---

#### 2. Google Sheets not updating

**Symptoms:**
- Leads not appearing in Sheets
- Rows not updating on status changes

**Solutions:**
- Verify `FEATURE_SHEETS_ENABLED=true`
- Check service account has Editor access to spreadsheet
- Verify `GOOGLE_SHEETS_SPREADSHEET_ID` is correct
- Check JSON credentials file path/permissions
- Verify Sheets API is enabled in Google Cloud Console

**Logs to check:**
```bash
grep -i "sheets" /var/log/app.log
```

---

#### 3. Calendar slot suggestions not working

**Symptoms:**
- No slots sent after approval
- Empty slot list errors

**Solutions:**
- Verify `FEATURE_CALENDAR_ENABLED=true`
- Check `GOOGLE_CALENDAR_ID` is correct
- Verify service account has calendar access
- Check `calendar_rules.yml` configuration
- Verify Calendar API is enabled

**Logs to check:**
```bash
grep -i "calendar" /var/log/app.log
```

---

#### 4. Stripe webhook not processing

**Symptoms:**
- Payments complete but lead status not updating
- Webhook errors in Stripe dashboard

**Solutions:**
- Verify webhook endpoint URL is correct
- Check `STRIPE_WEBHOOK_SECRET` matches Stripe dashboard
- Verify webhook signature validation
- Check webhook event types configured in Stripe
- Verify `client_reference_id` contains lead_id

**Logs to check:**
```bash
grep -i "stripe\|webhook" /var/log/app.log
```

---

#### 5. Duplicate messages/events

**Symptoms:**
- Same message processed multiple times
- Duplicate Stripe payments processed

**Solutions:**
- Check `ProcessedMessage` table for duplicates
- Verify idempotency checks are working
- Check for race conditions in status updates
- Review `message_id` / `event_id` uniqueness

**Logs to check:**
```bash
grep -i "duplicate\|idempotent" /var/log/app.log
```

---

#### 6. State machine errors

**Symptoms:**
- "Cannot approve lead in status X" errors
- Invalid transition attempts

**Solutions:**
- Verify lead is in correct status before action
- Check status-locked operations are atomic
- Review state machine flow diagram
- Check for concurrent updates

**Logs to check:**
```bash
grep -i "status\|transition" /var/log/app.log
```

---

### Health Check Endpoint

Always check `/health` first:

```bash
curl https://yourdomain.com/health
```

Expected response:
```json
{
  "ok": true,
  "templates_configured": [...],
  "templates_missing": [],
  "whatsapp_enabled": true,
  "features": {
    "sheets_enabled": true,
    "calendar_enabled": true,
    "reminders_enabled": true,
    "notifications_enabled": true,
    "panic_mode_enabled": false
  },
  "calendar_enabled": true,
  "sheets_enabled": true
}
```

---

## Panic Mode Procedure

Panic mode pauses all automation while preserving logging and artist notifications.

### When to Enable Panic Mode

- Unexpected behavior in production
- High error rate
- Security concern
- Need to pause for manual review

### How to Enable

1. Set environment variable:
   ```bash
   FEATURE_PANIC_MODE_ENABLED=true
   ```

2. Restart application (or reload config if supported)

3. Verify panic mode active:
   ```bash
   curl https://yourdomain.com/health
   # Should show: "panic_mode_enabled": true
   ```

### What Happens in Panic Mode

- **Inbound messages:** Stored and logged, but bot replies with safe message (if within 24h window)
- **Reminders:** Disabled
- **Automated actions:** Paused
- **Artist notifications:** Still sent (if `FEATURE_NOTIFICATIONS_ENABLED=true`)
- **Sheets logging:** Still active (if enabled)
- **Manual admin actions:** Still work (approve, reject, etc.)

### Safe Message Sent to Clients

```
Thanks — Jonah will reply shortly.
```

### How to Disable

1. Set environment variable:
   ```bash
   FEATURE_PANIC_MODE_ENABLED=false
   ```

2. Restart application

3. Verify normal operation:
   ```bash
   curl https://yourdomain.com/health
   # Should show: "panic_mode_enabled": false
   ```

### After Panic Mode

1. Review logs for issues during panic period
2. Check for stuck leads (`NEEDS_FOLLOW_UP`, `NEEDS_ARTIST_REPLY`)
3. Manually process any leads that were paused
4. Re-enable automation once issues resolved

---

## Log Locations

### Application Logs

- **Docker:** `docker logs <container_name>`
- **Systemd:** `/var/log/app/app.log`
- **Cloud:** Check your cloud provider's logging service

### Key Log Patterns

```bash
# WhatsApp errors
grep -i "whatsapp\|messaging" /var/log/app.log

# Stripe webhook errors
grep -i "stripe\|webhook\|payment" /var/log/app.log

# Database errors
grep -i "database\|sql\|integrity" /var/log/app.log

# State machine errors
grep -i "status\|transition\|atomic" /var/log/app.log

# Idempotency issues
grep -i "duplicate\|processed" /var/log/app.log
```

---

## Support Contacts

- **Technical Issues:** [Your support email]
- **WhatsApp API:** [Meta Business Support]
- **Stripe Support:** [Stripe Support]
- **Google APIs:** [Google Cloud Support]

---

## Quick Reference

### Test Commands

```bash
# Health check
curl https://yourdomain.com/health

# Test WhatsApp webhook (verification)
curl "https://yourdomain.com/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=<TOKEN>&hub.challenge=test"

# List leads (requires ADMIN_API_KEY)
curl -H "X-Admin-API-Key: <KEY>" https://yourdomain.com/admin/leads

# Get funnel metrics
curl -H "X-Admin-API-Key: <KEY>" https://yourdomain.com/admin/funnel?days=7

# Get slot parse stats (matched_by / reject reason counts)
curl -H "X-Admin-API-Key: <KEY>" https://yourdomain.com/admin/slot-parse-stats?days=7
```

### Scheduled Jobs (SystemEvent Retention)

To prevent `system_events` from growing unbounded (e.g. from slot parsing observability), run retention cleanup regularly.

**Recommended schedule:** Daily (e.g. `0 3 * * *` at 3am UTC)

**Option A – Admin endpoint (Render Cron or external cron):**
```bash
curl -X POST "https://yourdomain.com/admin/events/retention-cleanup?retention_days=90" \
  -H "X-Admin-API-Key: ${ADMIN_API_KEY}"
```

**Option B – CLI job (cron or Render Cron):**
```bash
python -m app.jobs.cleanup_system_events --retention-days 90
```

**Endpoints:**
- `POST /admin/events/retention-cleanup?retention_days=90` – Delete events older than N days (default 90)

---

### Database Queries

```sql
-- Check recent leads
SELECT id, wa_from, status, created_at FROM leads ORDER BY created_at DESC LIMIT 10;

-- Check for stuck leads
SELECT id, status, last_client_message_at FROM leads 
WHERE status IN ('NEEDS_FOLLOW_UP', 'NEEDS_ARTIST_REPLY') 
AND last_client_message_at < NOW() - INTERVAL '24 hours';

-- Check duplicate events
SELECT message_id, COUNT(*) FROM processed_messages 
GROUP BY message_id HAVING COUNT(*) > 1;
```

---

**Last Updated:** [Current Date]
**Version:** Phase 1
