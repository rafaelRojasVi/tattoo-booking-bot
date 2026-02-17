# Deployment Guide: Render.com

This guide covers deploying the Tattoo Booking Bot to Render.com with a Web Service and Managed PostgreSQL database.

## Prerequisites

- Render.com account
- WhatsApp Business API credentials (Meta)
- Stripe account with webhook secret
- Admin API key (generate a strong random key)

## Render Resources

### 1. Web Service

**Service Type:** Web Service  
**Environment:** Docker  
**Region:** Choose closest to your users  
**Branch:** `master` (or your production branch)

**Build Command:**
```bash
# Render will use Dockerfile automatically
```

**Start Command:**
```bash
# Uses WEB_CONCURRENCY env var (default: 2 workers)
# Command is in Dockerfile CMD
```

**Health Check Path:** `/health`  
**Auto-Deploy:** Yes (recommended for production)

### 2. Managed PostgreSQL

**Service Type:** PostgreSQL  
**Database Name:** `tattoo_booking_bot` (or your preference)  
**PostgreSQL Version:** 15+ (recommended)

**Important:** After creating the database, Render will provide a `DATABASE_URL` connection string. Copy this for your Web Service environment variables.

## Required Environment Variables

Set these in your Render Web Service environment variables:

### Database
- `DATABASE_URL` - PostgreSQL connection string (from Managed PostgreSQL service)
  - Format: `postgresql://user:password@host:port/dbname`

### WhatsApp Configuration
- `WHATSAPP_VERIFY_TOKEN` - Meta webhook verification token (create in Meta App Dashboard)
- `WHATSAPP_ACCESS_TOKEN` - Meta WhatsApp API access token
- `WHATSAPP_PHONE_NUMBER_ID` - Meta phone number ID
- `WHATSAPP_APP_SECRET` - Meta App Secret (required for webhook signature verification)
- `WHATSAPP_DRY_RUN` - Set to `false` in production

### Stripe Configuration
- `STRIPE_SECRET_KEY` - Stripe secret key (use `sk_live_...` for production)
- `STRIPE_WEBHOOK_SECRET` - Stripe webhook signing secret (from Stripe Dashboard)
- `STRIPE_DEPOSIT_AMOUNT_PENCE` - Default deposit amount in pence (e.g., `5000` for £50)

### Admin & Security
- `ADMIN_API_KEY` - Strong random key for admin API authentication
  - Generate: `openssl rand -hex 32` or use a password manager
  - **Required in production** (service will refuse to start if missing)

### Application Settings
- `APP_ENV` - Set to `production`
- `DEMO_MODE` - Set to `false` (required in production)
- `WEB_CONCURRENCY` - Number of uvicorn workers (default: `2`)
  - Small instances: `1-2`
  - Medium instances: `2-4`
  - Large instances: `4-8`

### URLs & Callbacks
- `ACTION_TOKEN_BASE_URL` - Your Render service URL (e.g., `https://your-service.onrender.com`)
- `STRIPE_SUCCESS_URL` - Success redirect after payment (e.g., `https://your-service.onrender.com/payment/success`)
- `STRIPE_CANCEL_URL` - Cancel redirect (e.g., `https://your-service.onrender.com/payment/cancel`)
- `FRESHA_BOOKING_URL` - Your booking platform URL

### Optional Integrations
- `GOOGLE_SHEETS_ENABLED` - Set to `true` if using Google Sheets
- `GOOGLE_SHEETS_SPREADSHEET_ID` - Google Sheets spreadsheet ID
- `GOOGLE_SHEETS_CREDENTIALS_JSON` - Service account JSON (or path to file)
- `GOOGLE_CALENDAR_ENABLED` - Set to `true` if using Google Calendar
- `GOOGLE_CALENDAR_ID` - Calendar ID (email address)
- `GOOGLE_CALENDAR_CREDENTIALS_JSON` - Service account JSON (or path to file)

### Rate Limiting (Optional)
- `RATE_LIMIT_ENABLED` - Set to `true` to enable rate limiting (default: `true`)
- `RATE_LIMIT_REQUESTS` - Requests per window (default: `10`)
- `RATE_LIMIT_WINDOW_SECONDS` - Time window in seconds (default: `60`)

## Webhook URLs

After deploying, configure these webhook URLs:

### Meta WhatsApp Webhook
1. Go to Meta App Dashboard → WhatsApp → Configuration
2. Set **Webhook URL:** `https://your-service.onrender.com/webhooks/whatsapp`
3. Set **Verify Token:** (use your `WHATSAPP_VERIFY_TOKEN` value)
4. Subscribe to: `messages` events

### Stripe Webhook
1. Go to Stripe Dashboard → Developers → Webhooks
2. Click "Add endpoint"
3. Set **Endpoint URL:** `https://your-service.onrender.com/webhooks/stripe`
4. Select events:
   - `checkout.session.completed`
   - `checkout.session.expired`
   - `payment_intent.succeeded` (if needed)
5. Copy the **Signing secret** and set as `STRIPE_WEBHOOK_SECRET`

## Health Checks

Render will use these endpoints for health monitoring:

- **Health Check:** `GET /health` - Returns 200 immediately
- **Readiness Check:** `GET /ready` - Checks database connection, returns 200/503

Configure in Render Dashboard:
- **Health Check Path:** `/health`
- **Auto-Deploy:** Enabled

## Keeping Service Always-On

**Important:** Render free tier services sleep after 15 minutes of inactivity. For webhooks to work reliably:

1. **Use a paid plan** (Starter or higher) - Services stay always-on
2. **Or use a cron job** to ping `/health` every 5-10 minutes (external service like cron-job.org)
3. **Or upgrade to a paid tier** - Recommended for production

## Database Migrations

After first deployment, run migrations:

```bash
# Via Render Shell (Dashboard → Shell)
alembic upgrade head

# Or via local connection (if DATABASE_URL is accessible)
DATABASE_URL="your-render-db-url" alembic upgrade head
```

## Worker Service (Optional)

For background tasks (reminders, sweeps), create a separate Worker Service:

**Service Type:** Background Worker  
**Start Command:**
```bash
python -m app.services.worker
```

**Note:** Worker service implementation is a placeholder. For now, use cron jobs or scheduled tasks.

## Cron Jobs (Optional)

For periodic tasks, use Render Cron Jobs or external cron services.

### Expired deposit sweeper

**Schedule:** `0 */6 * * *` (every 6 hours)  
**Command:**
```bash
curl -X POST https://your-service.onrender.com/admin/sweep-expired-deposits \
  -H "X-Admin-API-Key: ${ADMIN_API_KEY}"
```

### SystemEvent retention cleanup

Prevents `system_events` from growing unbounded (slot parsing, WhatsApp events, etc.).

**Schedule:** `0 3 * * *` (daily at 3am UTC)  
**Command:**
```bash
curl -X POST "https://your-service.onrender.com/admin/events/retention-cleanup?retention_days=90" \
  -H "X-Admin-API-Key: ${ADMIN_API_KEY}"
```

Or run the CLI job: `python -m app.jobs.cleanup_system_events --retention-days 90`

## Monitoring

- **Logs:** View in Render Dashboard → Logs
- **Metrics:** Use `/admin/metrics` endpoint (requires `X-Admin-API-Key` header)
- **Health:** Monitor `/health` and `/ready` endpoints

## Troubleshooting

### Service won't start
- Check environment variables (especially `ADMIN_API_KEY` in production)
- Verify `DATABASE_URL` is correct
- Check logs in Render Dashboard

### Webhooks not working
- Verify webhook URLs are correct
- Check `WHATSAPP_APP_SECRET` is set (required for signature verification)
- Ensure service is always-on (not sleeping)

### Database connection errors
- Verify `DATABASE_URL` format
- Check PostgreSQL service is running
- Ensure database exists and migrations are applied

## Security Checklist

- [ ] `APP_ENV=production` is set
- [ ] `ADMIN_API_KEY` is set (strong random key)
- [ ] `DEMO_MODE=false` is set
- [ ] `WHATSAPP_DRY_RUN=false` is set (for production)
- [ ] `WHATSAPP_APP_SECRET` is set (for webhook verification)
- [ ] All secrets are in environment variables (not in code)
- [ ] HTTPS is enabled (Render provides this automatically)
- [ ] Rate limiting is enabled for admin/action endpoints

## Next Steps

1. Deploy Web Service and PostgreSQL
2. Set all environment variables
3. Run database migrations
4. Configure webhook URLs in Meta and Stripe
5. Test health endpoints
6. Monitor logs for first few hours
7. Set up external monitoring (optional)

For production issues, see [Operations Runbook](ops_runbook.md).
