# WhatsApp Testing Guide

Complete guide for testing WhatsApp integration end-to-end.

## Quick Test Commands

### 1. Test Sending a Message

```powershell
# In Docker
docker compose exec api python scripts/whatsapp_smoke.py --to YOUR_PHONE_NUMBER

# Example (US number):
docker compose exec api python scripts/whatsapp_smoke.py --to 14155551234
```

**What it does**:
- Sends a test message via WhatsApp Cloud API
- Respects `WHATSAPP_DRY_RUN` setting
- Shows status and message ID (if sent)

**Expected output**:
```
📤 Sending WhatsApp message...
   To: 14155551234
   Message: Hello! This is a test message...
   Dry Run: true

✅ Result:
   Status: dry_run
   
💡 This was a dry run. To send real messages:
   1. Set WHATSAPP_DRY_RUN=false in .env
   2. Ensure WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID are set
   3. Run this script again
```

---

### 2. Test Receiving a Webhook (Text Message)

```powershell
# In Docker
docker compose exec api python scripts/webhook_replay.py --text "Hello, I want a tattoo" --from YOUR_PHONE_NUMBER
```

**What it does**:
- Replays a sample WhatsApp webhook payload
- Tests webhook endpoint without needing real WhatsApp
- Creates Lead record in database

**Expected output**:
```
📤 Sending webhook payload to: http://localhost:8000/webhooks/whatsapp
   Payload: {...}

📥 Response:
   Status: 200
   Body: {"received": true, "lead_id": 1, ...}

✅ Webhook processed successfully!
   Lead ID: 1
   Type: message
```

**Check database**:
```powershell
docker compose exec api python -c "from app.db.session import SessionLocal; from app.db.models import Lead; db=SessionLocal(); leads=db.query(Lead).order_by(Lead.id.desc()).limit(1).all(); print(f'Lead: {leads[0].id}, Status: {leads[0].status}, From: {leads[0].wa_from}') if leads else print('No leads')"
```

---

### 3. Test Receiving a Webhook (Image Message)

```powershell
# In Docker
docker compose exec api python scripts/webhook_replay.py --image --from YOUR_PHONE_NUMBER
```

**What it does**:
- Replays an image message webhook
- Creates Attachment record with PENDING status
- Schedules background upload task

**Check attachments**:
```powershell
docker compose exec api python scripts/test_attachment_pipeline.py
```

**Process pending uploads**:
```powershell
docker compose exec api python -m app.jobs.sweep_pending_uploads --limit 10 --verbose
```

---

## End-to-End Testing Flow

### Step 1: Setup ngrok

```powershell
# In a separate terminal
ngrok http 8000
```

Copy the HTTPS URL (e.g., `https://abc123.ngrok-free.app`)

### Step 2: Configure Webhook in Meta

1. Go to [Meta App Dashboard](https://developers.facebook.com/apps/)
2. Your App → WhatsApp → Configuration → Webhook
3. **Callback URL**: `https://your-ngrok-url.ngrok-free.app/webhooks/whatsapp`
4. **Verify token**: Same as `WHATSAPP_VERIFY_TOKEN` in `.env`
5. Click **Verify and Save**

### Step 3: Test Webhook Verification

```powershell
# Replace YOUR_TOKEN with your actual verify token
curl "https://your-ngrok-url.ngrok-free.app/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=test123"
```

Should return: `test123`

### Step 4: Test Sending (Dry Run)

```powershell
docker compose exec api python scripts/whatsapp_smoke.py --to YOUR_PHONE_NUMBER
```

Verify it shows "dry_run" status.

### Step 5: Test Sending (Real)

1. Update `.env`: `WHATSAPP_DRY_RUN=false`
2. Restart API: `docker compose restart api`
3. Run again:
   ```powershell
   docker compose exec api python scripts/whatsapp_smoke.py --to YOUR_PHONE_NUMBER
   ```
4. Check your phone for the message

### Step 6: Test Receiving (From Phone)

1. Message the **test business number** from your personal WhatsApp
2. Check API logs:
   ```powershell
   docker compose logs api --tail 50
   ```
3. Check database for new Lead:
   ```powershell
   docker compose exec api python -c "from app.db.session import SessionLocal; from app.db.models import Lead; db=SessionLocal(); print(f'Total leads: {db.query(Lead).count()}')"
   ```

### Step 7: Test Image Upload

1. Send an image to the test business number
2. Check Attachment was created:
   ```powershell
   docker compose exec api python scripts/test_attachment_pipeline.py
   ```
3. Process upload:
   ```powershell
   docker compose exec api python -m app.jobs.sweep_pending_uploads --limit 10 --verbose
   ```
4. Verify upload status changed to UPLOADED

---

## Testing Checklist

### Basic Functionality
- [ ] Webhook GET verification returns challenge
- [ ] Webhook POST receives text messages
- [ ] Webhook POST receives image messages
- [ ] Lead records created in database
- [ ] ProcessedMessage records created (idempotency)
- [ ] Attachment records created for images

### Message Sending
- [ ] Dry-run mode works (logs but doesn't send)
- [ ] Real sending works (with `WHATSAPP_DRY_RUN=false`)
- [ ] Error handling works (invalid token, etc.)

### Media Handling
- [ ] Image webhook creates Attachment (PENDING)
- [ ] Sweeper processes pending uploads
- [ ] Media uploads to Supabase successfully
- [ ] Attachment status updates to UPLOADED

### Error Scenarios
- [ ] Invalid webhook signature rejected
- [ ] Missing credentials handled gracefully
- [ ] Expired media handled (retry logic)
- [ ] Network errors handled (timeouts, etc.)

---

## Troubleshooting Commands

### Check Webhook is Receiving

```powershell
# Watch logs in real-time
docker compose logs api -f | Select-String "whatsapp"
```

### Check Database State

```powershell
# Count leads
docker compose exec api python -c "from app.db.session import SessionLocal; from app.db.models import Lead; db=SessionLocal(); print(f'Leads: {db.query(Lead).count()}')"

# Check recent attachments
docker compose exec api python scripts/test_attachment_pipeline.py

# Check processed messages (idempotency)
docker compose exec api python -c "from app.db.session import SessionLocal; from app.db.models import ProcessedMessage; db=SessionLocal(); print(f'Processed: {db.query(ProcessedMessage).count()}')"
```

### Test Webhook Endpoint Directly

```powershell
# Test GET verification
curl "http://localhost:8000/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=test"

# Test POST (using webhook_replay script)
docker compose exec api python scripts/webhook_replay.py --text "Test"
```

### Check Configuration

```powershell
# Verify environment variables are loaded
docker compose exec api python -c "from app.core.config import settings; print(f'Verify Token: {settings.whatsapp_verify_token[:10]}...'); print(f'Phone Number ID: {settings.whatsapp_phone_number_id}'); print(f'Dry Run: {settings.whatsapp_dry_run}')"
```

---

## Next Steps After Testing

1. **Test full conversation flow**: Send messages and verify bot responses
2. **Test error handling**: Send invalid messages, test edge cases
3. **Monitor logs**: Watch for any errors or warnings
4. **Production setup**: Move from test number to production number
5. **Set up monitoring**: Track webhook events, failures, etc.
