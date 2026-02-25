# WhatsApp Cloud API Setup Guide

This guide walks you through setting up WhatsApp Cloud API integration for testing and production.

## Prerequisites

1. **Meta Business Account** with WhatsApp Business API access
2. **Meta App** created in [Meta for Developers](https://developers.facebook.com/)
3. **Test Phone Number** (provided by Meta for development)
4. **ngrok** or **cloudflared** for exposing localhost (development)

## Step 1: Get WhatsApp Cloud API Credentials

### In Meta App Dashboard (WhatsApp product):

1. **Temporary Access Token** (for quick tests)
   - Go to: [Meta App Dashboard](https://developers.facebook.com/apps/)
   - Select your app → WhatsApp → API Setup
   - Copy the **Temporary access token** (expires quickly, good for testing)
   - For production, create a **System User** with permanent token

2. **Phone Number ID**
   - Same page: copy the **Phone number ID** (looks like: `123456789012345`)

3. **App Secret** (for webhook signature verification)
   - Go to: Settings → Basic
   - Copy the **App Secret** (click "Show" to reveal)

4. **Add Test Recipient**
   - In WhatsApp → API Setup
   - Add your personal phone number to "To" field
   - This allows you to receive messages from the test number

## Step 2: Configure Environment Variables

Add to your `.env` file:

```bash
# WhatsApp API Configuration
WHATSAPP_VERIFY_TOKEN=your_random_verify_token_here  # Choose any random string
WHATSAPP_ACCESS_TOKEN=your_access_token_from_meta
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id_from_meta
WHATSAPP_APP_SECRET=your_app_secret_from_meta  # Optional in dev, required in prod
WHATSAPP_DRY_RUN=true  # Set to false when ready to send real messages
```

**Important:**
- `WHATSAPP_VERIFY_TOKEN`: Choose a random string (e.g., `my_secure_token_12345`)
- Store this token securely - you'll need it for webhook verification
- `WHATSAPP_APP_SECRET`: Required for production webhook signature verification

## Step 3: Expose Local Webhook to Internet (Development)

WhatsApp webhooks require a **public HTTPS URL**. Use one of these:

### Option A: ngrok (Recommended)

1. **Install ngrok**: [ngrok.com/download](https://ngrok.com/download)

2. **Start ngrok tunnel**:
   ```powershell
   ngrok http 8000
   ```

3. **Copy the HTTPS URL** (e.g., `https://abc123.ngrok-free.app`)

### Option B: cloudflared (Alternative)

1. **Install cloudflared**: [cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation)

2. **Start tunnel**:
   ```powershell
   cloudflared tunnel --url http://localhost:8000
   ```

3. **Copy the HTTPS URL**

## Step 4: Configure Webhook in Meta Dashboard

1. **Go to**: [Meta App Dashboard](https://developers.facebook.com/apps/) → Your App → WhatsApp → Configuration

2. **Set Webhook**:
   - **Callback URL**: `https://your-ngrok-url.ngrok-free.app/webhooks/whatsapp`
   - **Verify token**: The same value as `WHATSAPP_VERIFY_TOKEN` in your `.env`
   - **Webhook fields**: Subscribe to `messages` (and optionally `message_status`)

3. **Click "Verify and Save"**
   - Meta will send a GET request to verify your webhook
   - Your endpoint should return the `hub.challenge` value
   - If verification fails, check:
     - URL is accessible (not localhost)
     - Verify token matches exactly
     - Endpoint returns plain text (not JSON)

## Step 5: Test Webhook Verification

Test that webhook verification works:

```powershell
# From your local machine (not Docker)
curl "https://your-ngrok-url.ngrok-free.app/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=your_verify_token&hub.challenge=test123"
```

Should return: `test123` (the challenge value)

## Step 6: Test Sending Messages

### Using the smoke test script:

```powershell
# In Docker
docker compose exec api python scripts/whatsapp_smoke.py --to YOUR_PHONE_NUMBER
```

Replace `YOUR_PHONE_NUMBER` with your phone number (country code, no +, e.g., `14155551234`)

### Using Postman:

1. Import the [WhatsApp Cloud API Postman Collection](https://www.postman.com/meta/whatsapp-business-platform/collection/wlk6lh4/whatsapp-cloud-api)
2. Set variables:
   - `access_token`: Your WhatsApp access token
   - `phone_number_id`: Your phone number ID
3. Send a message using "Send Text Message" request

## Step 7: Test Receiving Messages (Webhook)

### Option A: Send from your phone

1. Message the **test business number** from your personal WhatsApp
2. Check your API logs to see the webhook being received
3. Check database for new Lead record

### Option B: Replay webhook payload

```powershell
# In Docker
docker compose exec api python scripts/webhook_replay.py --text "Hello, I want a tattoo" --from YOUR_PHONE_NUMBER
```

## Step 8: Test Media (Images/Documents)

### Send an image from your phone:

1. Message an image to the test business number
2. Check logs for:
   - Attachment record created (status: PENDING)
   - Background task scheduled
3. Run sweeper to process upload:
   ```powershell
   docker compose exec api python -m app.jobs.sweep_pending_uploads --limit 10 --verbose
   ```
4. Check Attachment status changed to UPLOADED

### Replay image webhook:

```powershell
docker compose exec api python scripts/webhook_replay.py --image --from YOUR_PHONE_NUMBER
```

## Verification Checklist

- [ ] Webhook GET verification returns challenge
- [ ] Webhook POST receives messages (check logs)
- [ ] Lead records created in database
- [ ] ProcessedMessage records created (idempotency)
- [ ] Bot responds to messages (if conversation flow is active)
- [ ] Image messages create Attachment records
- [ ] Media uploads to Supabase successfully

## Troubleshooting

### Webhook verification fails

- **Check**: Verify token matches exactly (case-sensitive)
- **Check**: URL is HTTPS (not HTTP)
- **Check**: Endpoint returns plain text, not JSON
- **Check**: Endpoint is accessible from internet (not localhost)

### Messages not sending

- **Check**: `WHATSAPP_DRY_RUN=false` in `.env`
- **Check**: Access token is valid (not expired)
- **Check**: Phone number ID is correct
- **Check**: Recipient is in test number's allowed list
- **Check**: API logs for error messages

### Webhook not receiving messages

- **Check**: Webhook URL is correct in Meta dashboard
- **Check**: Webhook is verified (green checkmark)
- **Check**: Webhook fields include "messages"
- **Check**: ngrok/cloudflared tunnel is still running
- **Check**: API is running and accessible

### Signature verification fails

- **Check**: `WHATSAPP_APP_SECRET` is set correctly
- **Check**: Signature header `X-Hub-Signature-256` is present
- **Check**: Raw request body is used (not re-serialized JSON)
- **Note**: In dev mode, signature verification is skipped if secret is not set

## Production Checklist

Before going live:

- [ ] Create **System User** with permanent access token (not temporary)
- [ ] Set `WHATSAPP_DRY_RUN=false`
- [ ] Set `WHATSAPP_APP_SECRET` (required for signature verification)
- [ ] Use production webhook URL (not ngrok)
- [ ] Test webhook signature verification
- [ ] Set up monitoring/alerts for webhook failures
- [ ] Configure rate limiting if needed
- [ ] Review and approve message templates (if using templates)

## Next Steps

1. **Test full conversation flow**: Send messages and verify bot responses
2. **Test media uploads**: Send images and verify Supabase upload
3. **Test error handling**: Send invalid messages, expired media, etc.
4. **Set up monitoring**: Log webhook events, track failures
5. **Production deployment**: Move from test number to production number

## Resources

- [WhatsApp Cloud API Documentation](https://developers.facebook.com/docs/whatsapp/cloud-api)
- [Postman Collection](https://www.postman.com/meta/whatsapp-business-platform/collection/wlk6lh4/whatsapp-cloud-api)
- [Meta for Developers Dashboard](https://developers.facebook.com/apps/)
