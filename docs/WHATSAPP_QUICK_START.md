# WhatsApp Integration Quick Start

## 🚀 5-Minute Setup

### 1. Get Credentials from Meta Dashboard

1. Go to [Meta for Developers](https://developers.facebook.com/apps/)
2. Select your app → **WhatsApp** → **API Setup**
3. Copy:
   - **Temporary access token**
   - **Phone number ID**
4. Go to **Settings** → **Basic** → Copy **App Secret**

### 2. Update `.env`

```bash
WHATSAPP_VERIFY_TOKEN=my_random_token_12345  # Choose any string
WHATSAPP_ACCESS_TOKEN=<paste_from_meta>
WHATSAPP_PHONE_NUMBER_ID=<paste_from_meta>
WHATSAPP_APP_SECRET=<paste_from_meta>
WHATSAPP_DRY_RUN=true  # Keep true for testing
```

### 3. Start ngrok (in separate terminal)

```powershell
ngrok http 8000
```

Copy the HTTPS URL (e.g., `https://abc123.ngrok-free.app`)

### 4. Configure Webhook in Meta

1. Go to: **WhatsApp** → **Configuration** → **Webhook**
2. **Callback URL**: `https://your-ngrok-url.ngrok-free.app/webhooks/whatsapp`
3. **Verify token**: Same as `WHATSAPP_VERIFY_TOKEN` in `.env`
4. Click **Verify and Save**

### 5. Test It!

```powershell
# Test sending a message
docker compose exec api python scripts/whatsapp_smoke.py --to YOUR_PHONE_NUMBER

# Test receiving a webhook
docker compose exec api python scripts/webhook_replay.py --text "Hello"
```

## ✅ Verification Checklist

- [ ] Webhook GET returns challenge: `curl "https://your-url/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=test"`
- [ ] Smoke test script runs without errors
- [ ] Webhook replay creates Lead in database
- [ ] Send message from your phone → see webhook in logs

## 🐛 Common Issues

| Issue | Solution |
|-------|----------|
| Webhook verification fails | Check verify token matches exactly |
| Messages not sending | Set `WHATSAPP_DRY_RUN=false` |
| Webhook not receiving | Check ngrok is running, webhook URL is correct |
| Signature verification fails | Check `WHATSAPP_APP_SECRET` is set correctly |

## 📚 Full Documentation

See [WHATSAPP_SETUP.md](./WHATSAPP_SETUP.md) for detailed setup instructions.
