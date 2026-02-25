# Step-by-Step: Render + WhatsApp Setup

Follow these steps in order. Check off each one before moving on.

---

## Part 1: Push to GitHub

- [ ] **1.1** If not already on GitHub, create a repo and push:
  ```powershell
  git remote add origin https://github.com/YOUR_USERNAME/tattoo-booking-bot.git
  git push -u origin master
  ```

---

## Part 2: Deploy to Render

- [ ] **2.1** Go to [Render Dashboard](https://dashboard.render.com) and sign in.

- [ ] **2.2** Click **New +** → **Blueprint**.

- [ ] **2.3** Connect your GitHub account (if needed) and select the `tattoo-booking-bot` repo.

- [ ] **2.4** Render will detect `render.yaml` and show:
  - **Web Service**: tattoo-booking-bot
  - **PostgreSQL**: tattoo-booking-bot-db

- [ ] **2.5** Before creating, you must add **Environment Variables** (secrets).  
  For each variable below, add it in the Render UI for the **tattoo-booking-bot** web service:

  | Variable | Value | Where to get it |
  |----------|-------|-----------------|
  | `WHATSAPP_VERIFY_TOKEN` | Any random string (e.g. `my_secure_token_123`) | You choose it; you’ll use it in Meta |
  | `WHATSAPP_ACCESS_TOKEN` | From Meta (see Part 3) | Meta → WhatsApp → API Setup |
  | `WHATSAPP_PHONE_NUMBER_ID` | From Meta | Meta → WhatsApp → API Setup |
  | `WHATSAPP_APP_SECRET` | From Meta | Meta → Settings → Basic |
  | `WHATSAPP_DRY_RUN` | `false` | Enables real sending |
  | `STRIPE_SECRET_KEY` | `sk_test_...` | Stripe Dashboard (test mode) |
  | `STRIPE_WEBHOOK_SECRET` | `whsec_...` | Stripe → Webhooks (create endpoint first) |
  | `FRESHA_BOOKING_URL` | `https://placeholder.com` | Placeholder OK for pilot |
  | `ADMIN_API_KEY` | Random hex (e.g. `openssl rand -hex 32`) | You generate it |
  | `ACTION_TOKEN_BASE_URL` | `https://YOUR-SERVICE.onrender.com` | Your Render URL after deploy |

  For pilot mode (optional but recommended):
  | Variable | Value |
  |----------|-------|
  | `PILOT_MODE_ENABLED` | `true` |
  | `PILOT_ALLOWLIST_NUMBERS` | `447123456789` (client number, no +) |

- [ ] **2.6** Click **Apply** to create the Blueprint. Render will:
  - Create the PostgreSQL database
  - Build and deploy the web service
  - Run `alembic upgrade head` before each deploy (via releaseCommand)

- [ ] **2.7** Wait for the first deploy to finish. Note your service URL, e.g.:
  ```
  https://tattoo-booking-bot-xxxx.onrender.com
  ```

- [ ] **2.8** Update `ACTION_TOKEN_BASE_URL` in Render to your actual URL if you used a placeholder.

---

## Part 3: Meta WhatsApp Setup

- [ ] **3.1** Go to [Meta for Developers](https://developers.facebook.com/apps/).

- [ ] **3.2** Create an app (or use existing) → Add product → **WhatsApp**.

- [ ] **3.3** In **WhatsApp → API Setup**:
  - Copy **Temporary access token**
  - Copy **Phone number ID**
  - Add your (or client’s) number under **To** as a test recipient

- [ ] **3.4** In **Settings → Basic**:
  - Copy **App Secret**

- [ ] **3.5** In **WhatsApp → Configuration**:
  - **Callback URL**: `https://YOUR-RENDER-URL.onrender.com/webhooks/whatsapp`
  - **Verify token**: Same as `WHATSAPP_VERIFY_TOKEN` in Render
  - Subscribe to **messages**
  - Click **Verify and Save**

---

## Part 4: Verify Everything Works

- [ ] **4.1** Health check:
  ```powershell
  curl https://YOUR-SERVICE.onrender.com/health
  ```
  Expected: `{"ok":true,...}`

- [ ] **4.2** Readiness check:
  ```powershell
  curl https://YOUR-SERVICE.onrender.com/ready
  ```
  Expected: `{"ok":true,"database":"connected"}`

- [ ] **4.3** Webhook verification (replace YOUR_TOKEN and YOUR_SERVICE):
  ```powershell
  curl "https://YOUR-SERVICE.onrender.com/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=test123"
  ```
  Expected: `test123` (plain text)

- [ ] **4.4** Send "Hi" from your WhatsApp to the bot number.  
  Expected: Bot replies with the first question.

---

## Part 5: Stripe Webhook (for deposit flow)

- [ ] **5.1** In [Stripe Dashboard → Webhooks](https://dashboard.stripe.com/webhooks):
  - Add endpoint: `https://YOUR-SERVICE.onrender.com/webhooks/stripe`
  - Events: `checkout.session.completed`, `checkout.session.expired`
  - Copy the **Signing secret** (whsec_...)

- [ ] **5.2** In Render, set `STRIPE_WEBHOOK_SECRET` to that value.

---

## Troubleshooting

| Problem | Check |
|---------|-------|
| Deploy fails | Render logs; often missing env var |
| Health returns 503 | DB not connected; verify `DATABASE_URL` |
| Webhook verify fails | `WHATSAPP_VERIFY_TOKEN` must match exactly |
| No reply to "Hi" | `WHATSAPP_DRY_RUN=false`; client number in test recipients |
| Pilot blocks client | Add client number to `PILOT_ALLOWLIST_NUMBERS` (no +) |

---

## Quick Reference: Env Vars

**Required for startup:**
- `DATABASE_URL` (from Render when DB is linked)
- `WHATSAPP_VERIFY_TOKEN`
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `FRESHA_BOOKING_URL`

**Required in production (APP_ENV=production):**
- `ADMIN_API_KEY`
- `WHATSAPP_APP_SECRET`

**For real WhatsApp replies:**
- `WHATSAPP_DRY_RUN=false`
