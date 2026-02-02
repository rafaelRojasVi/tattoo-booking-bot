# Demo Script for Tattoo Booking Bot

This script outlines the step-by-step demo flow for presenting the booking bot to stakeholders.

## Prerequisites

1. **Start the application** with `DEMO_MODE=true`:
   ```bash
   export DEMO_MODE=true
   docker compose up
   # OR
   python -m uvicorn app.main:app --reload
   ```

2. **Open two browser windows:**
   - Client window: `http://localhost:8000/demo/client`
   - Artist window: `http://localhost:8000/demo/artist`

3. **Verify startup log** shows:
   ```
   WARNING: DEMO MODE ENABLED - DO NOT USE IN PROD
   ```

---

## Phase 1 demo — what’s included

The demo gives you a **full Phase 1 flow** you can show your client in the browser:

- **Client chat** (`/demo/client`): Structured consultation (all 13 questions), chat-style UI, full conversation history after each message, optional **reference image URL** (paste a link to simulate sending an image).
- **Artist inbox** (`/demo/artist`): Leads list with summary and **secure action links** (Approve, Reject, Send deposit, Mark booked). Clicking a link opens the real confirmation page and runs the real action.
- **Simulate payment** (`POST /demo/stripe/pay` with `lead_id`): Moves lead to BOOKING_PENDING so you can show “Mark booked” in the artist inbox.
- **Load conversation**: After a refresh, enter the Lead ID and click “Load” to restore the chat view.

**Images:** In the client demo you can type `no` for reference images, or paste an IG/image URL in the message or in “Reference image URL”. Real file upload (like WhatsApp) is only in production; the demo accepts URLs so the flow works.

---

## Going live / testing

- **Demo mode (browser):** Use `DEMO_MODE=true` and open `/demo/client` and `/demo/artist`. No WhatsApp or Stripe needed; everything is simulated. Good for showing the client and rehearsing.
- **Staging / real WhatsApp:** When you’re ready to test with real WhatsApp, set `DEMO_MODE=false` and `WHATSAPP_DRY_RUN=false`, configure webhooks and templates, and use the real WhatsApp number. The same conversation and approval flow run; only the channel (webhook vs demo page) changes.
- **Production:** After Phase 1 acceptance, deploy with `DEMO_MODE=false`, set production env vars (see runbook), and run migrations. Demo endpoints return 404 in production.

---

## Demo 1: Happy Path (5 minutes)

**Goal:** Show complete flow from initial message to booking confirmation.

### Step 1: Client Sends First Message

**Client Window:**
- Phone number: `+441234567890`
- Message: `Hi, I want a tattoo`
- Click "Send Message"

**Expected:**
- Bot responds with first question (about idea/concept)
- Status in conversation shows: `QUALIFYING`

### Step 2: Answer Qualification Questions

**Client Window:**
Answer each question as prompted:

1. **Idea:** `A dragon on my back`
2. **Placement:** `Upper back`
3. **Dimensions:** `30cm x 20cm`
4. **Style:** `Realism`
5. **Complexity:** `3` (high complexity)
6. **Coverup:** `No`
7. **Reference images:** `no`
8. **Budget:** `800` (numeric, no currency symbol)
9. **Location City:** `London`
10. **Location Country:** `United Kingdom`
11. **Instagram:** `@testuser`
12. **Travel City:** `same` (if same as location)
13. **Timing:** `Next month`

**Expected:**
- Bot asks next question after each answer
- After last question: Status changes to `PENDING_APPROVAL`
- Bot message: "Thanks! I'm reviewing your request..."

### Step 3: Artist Reviews Lead

**Artist Window:**
- Click "Refresh Inbox"
- Find lead with phone `+441234567890`
- Verify status: `PENDING_APPROVAL`
- Check summary shows all answers
- See action buttons: "Approve" and "Reject"

### Step 4: Artist Approves Lead

**Artist Window:**
- Click "Approve" button (or use admin endpoint)
- Status changes to: `AWAITING_DEPOSIT`
- Action buttons update: "Send Deposit" available

**Expected:** Client receives message about deposit link (if within 24h window)

### Step 5: Artist Sends Deposit Link

**Artist Window:**
- Click "Send Deposit" button (or use admin endpoint)
- Status remains: `AWAITING_DEPOSIT`
- Deposit link generated (fake URL in demo mode)

### Step 6: Simulate Payment

**Optional - Using Demo Endpoint:**
- `POST /demo/stripe/pay` with `lead_id: <lead_id>`
- Status changes to: `BOOKING_PENDING`

**OR manually via admin:**
- Update lead status to `BOOKING_PENDING`

### Step 7: Artist Marks as Booked

**Artist Window:**
- Click "Mark Booked" button (or use admin endpoint)
- Status changes to: `BOOKED`

**Expected:**
- Complete! Lead is now booked
- Timestamps show chronological progression

---

## Demo 2: Below Minimum Budget

**Goal:** Show budget validation and NEEDS_FOLLOW_UP path.

### Steps:

1. **Client starts new conversation:**
   - Phone: `+449876543210`
   - Message: `Hi, I want a tattoo`

2. **Answer questions normally, but use low budget:**
   - Budget: `200` (below minimum for region)

3. **Complete qualification:**
   - After last question, status: `NEEDS_FOLLOW_UP`
   - Bot message mentions budget constraint

4. **Artist Window:**
   - Find lead in inbox
   - Status: `NEEDS_FOLLOW_UP`
   - Summary shows budget flag: `below_min_budget: true`
   - No "Approve" button (different flow)

**Key Points:**
- System automatically detects below-minimum budget
- Lead is flagged for artist follow-up
- No automatic approval (requires manual review)

---

## Demo 3: Tour Conversion (City Not on Tour)

**Goal:** Show tour offer flow when city isn't on current schedule.

### Steps:

1. **Client starts conversation:**
   - Phone: `+441112223344`
   - Message: `Hi, I want a tattoo`

2. **Answer questions with city not on tour:**
   - Location City: `Manchester` (or any city not in tour schedule)
   - Other answers: normal

3. **After last question:**
   - Bot offers tour: "I'm planning to visit London soon. Would you like to book for that?"
   - Status: `TOUR_CONVERSION_OFFERED`

4. **Client responds:**
   - Option A: `yes` → Status: `PENDING_APPROVAL`, `location_city` updated to tour city
   - Option B: `no` → Status: `WAITLISTED`

**Artist Window:**
- View lead status (either `PENDING_APPROVAL` or `WAITLISTED`)
- Summary shows `tour_offer_accepted: true/false`

---

## Demo 4: Needs Artist Reply (Off-Script)

**Goal:** Show handover trigger when client goes off-script.

### Steps:

1. **Client in QUALIFYING state:**
   - Phone: `+445556667777`
   - Complete first 2-3 questions normally

2. **Client goes off-script:**
   - Message: `Can you do it cheaper?` or `How painful is it?`
   - System detects handover trigger

3. **Status changes:**
   - Status: `NEEDS_ARTIST_REPLY`
   - Bot: "Thanks — Jonah will reply shortly."

**Artist Window:**
- Find lead in inbox
- Status: `NEEDS_ARTIST_REPLY`
- Summary shows reason for handover
- Action available: "Mark Handled" or "Continue Flow"

**Resume Flow (Optional):**
- Client types: `CONTINUE`
- Status: `QUALIFYING` (resumes from where they left off)

---

## Quick Reference: Expected Statuses

| Stage | Status | Next Action |
|-------|--------|-------------|
| First message | `QUALIFYING` | Answer questions |
| All questions answered | `PENDING_APPROVAL` | Artist approves |
| Approved | `AWAITING_DEPOSIT` | Send deposit link |
| Deposit paid | `BOOKING_PENDING` | Mark as booked |
| Booked | `BOOKED` | Complete ✓ |

### Edge Case Statuses

| Scenario | Status | Notes |
|----------|--------|-------|
| Below min budget | `NEEDS_FOLLOW_UP` | Manual review needed |
| City not on tour | `TOUR_CONVERSION_OFFERED` | Client chooses tour city |
| Client declines tour | `WAITLISTED` | Added to waitlist |
| Off-script question | `NEEDS_ARTIST_REPLY` | Manual handover |
| Artist rejects | `REJECTED` | End of flow |

---

## Troubleshooting During Demo

**Issue: Lead stuck in QUALIFYING**
- Check: All questions answered?
- Fix: Continue answering questions

**Issue: Status doesn't change after payment**
- Check: Using `/demo/stripe/pay` endpoint?
- Fix: Verify `lead_id` is correct

**Issue: No action buttons in artist inbox**
- Check: Lead status matches available actions?
- Fix: `PENDING_APPROVAL` → Approve/Reject
       `AWAITING_DEPOSIT` → Send Deposit

**Issue: HTML pages not loading**
- Check: `DEMO_MODE=true` in environment?
- Fix: Restart application with demo mode enabled

---

## Demo Tips

1. **Use consistent phone numbers** for each demo scenario
2. **Refresh artist inbox** between major actions to see updates
3. **Keep both windows visible** side-by-side for best effect
4. **Explain status transitions** as they happen
5. **Pause after each major step** to let audience see the state change

---

## Sample Demo Script (Narration)

*"I'm going to show you how the booking bot handles a complete client journey from first message to booking confirmation."*

*"Here in the client window, someone messages 'Hi, I want a tattoo'..."*

*"The bot immediately starts the qualification flow, asking about their idea. The lead is now in QUALIFYING status."*

*"As the client answers each question, we progress through the flow. Notice how the bot responds naturally and guides them through the process."*

*"Once all questions are answered, the lead moves to PENDING_APPROVAL status, waiting for you - the artist - to review."*

*"In the artist inbox, you can see the complete summary with all their answers. The system provides action links for approve, reject, etc."*

*"After approval, we send the deposit link, and once payment is confirmed, we mark it as booked. The entire flow is tracked with timestamps for full auditability."*

---

**Duration:** ~5 minutes for happy path, ~2 minutes per edge case demo.
