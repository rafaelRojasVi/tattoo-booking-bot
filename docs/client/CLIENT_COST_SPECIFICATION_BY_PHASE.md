# Cost Specification by Phase — What You're Paying For

**Tattoo Booking Assistant System (WhatsApp + Stripe + Google Calendar + Google Sheets)**  
**Document Date:** 20 January 2026  
**Version:** v3.0 (Phase 1 + Phase 2)  
**Reference:** Freelance Services Agreement, Schedules A & B

This document explains **what is being built** and **what each payment milestone covers**. It aligns with the Agreement’s Schedule A (Phase 1) and Schedule B (Phase 2).

---

## Payment overview

| Milestone | Amount | When due | What it covers |
|-----------|--------|----------|----------------|
| **Upfront** | £1,000 | To begin work | Phase 1 build (Weeks 1–2): consultation flow, budget/tour rules, deposit rules, approval gate, calendar suggestions, Sheets, action links, handover, reminders, voice pack. |
| **Phase 1 Go-Live** | £1,000 | When Phase 1 passes acceptance & goes live | Phase 1 completion: staging + Go-Live, acceptance criteria met, consultation end-to-end, sheet logging, approval gate, deposit link after approval, calendar suggestions, status machine enforced. |
| **Phase 2 Start** | £2,500 | When Phase 2 work begins | Phase 2 build (Weeks 3–4): end-to-end booking in chat (slot selection → hold → deposit → confirm), holds + TTL (anti-double-book), Google Calendar event creation on confirmed booking, post-payment confirmation flow. |
| **Phase 2 Go-Live** | £2,000 | When Phase 2 passes acceptance & goes live | Phase 2 completion: client can select slot → pay deposit → receive confirmation; calendar event created automatically; concurrency protection; safe failure states; logging + sheet updates. |
| **Total** | **£6,500** | | Phase 1 + Phase 2 as per Schedules A & B. |

---

## Schedule A — Phase 1 (£2,000 total: £1,000 upfront + £1,000 at Go-Live)

**What Phase 1 delivers:** A “secretary + safety gate” — the bot collects enquiry details, applies budget and tour rules, suggests slots from your calendar, and sends deposit links **only after you approve**. You keep final say on every booking.

### A1) Guided WhatsApp consultation (structured) — *included in Phase 1 fee*

**What you get:**

- A fixed sequence of questions in WhatsApp (idea, placement, size, complexity, budget, city/country, timing, Instagram, references).
- Answers stored per lead; the bot moves to the next question based on the last answer.
- Parsing of dimensions, budget, and location so the system can apply rules (e.g. minimum spend, tour city).
- If the client’s answer can’t be parsed after two attempts, the lead is handed over to you (NEEDS_ARTIST_REPLY) with context.

**You’re paying for:** Design and implementation of the question set, flow logic, parsing, and handover triggers.

---

### A2) Budget filtering (minimum spend) — *included in Phase 1 fee*

**What you get:**

- Minimum spend rules: **UK £400 / Europe £500 / Rest of World £600** (configurable).
- If the client’s stated budget is below the minimum, the lead is **not** auto-declined; it goes to **NEEDS_FOLLOW_UP** so you can decide (e.g. offer a smaller scope or tour).

**You’re paying for:** Region detection (UK/EU/ROW), minimum thresholds, and status handling so no one is auto-rejected on budget alone.

---

### A3) Tour conversion + waitlist — *included in Phase 1 fee*

**What you get:**

- If the client’s city is not on your tour list, the bot offers the **closest upcoming tour city** (using your tour schedule as source of truth).
- If they decline or don’t confirm, the lead is marked **WAITLISTED** so you can re-engage later.

**You’re paying for:** Tour-city matching, offer message, and waitlist status so you keep those leads in the pipeline.

---

### A4) Deposit rules — *included in Phase 1 fee*

**What you get:**

- Deposit amounts by project type:
  - **Small:** £150  
  - **Medium:** £150  
  - **Large:** £200  
  - **XL:** £200 per full day booked  
- The system estimates project size (Small/Medium/Large/XL) from dimensions, complexity, and cover-up so the correct deposit is applied when the deposit link is sent.

**You’re paying for:** Estimation logic, category rules, and correct deposit amount per lead (client-facing wording stays neutral if you prefer).

---

### A5) Stripe deposit payment (external Stripe Checkout page) — *included in Phase 1 fee*

**What you get:**

- Deposit link is **only sent after you approve** the lead.
- The link opens Stripe’s secure Checkout page (Stripe-hosted; not a third-party booking platform).
- When the client pays, Stripe sends a webhook; the system marks the lead as deposit paid and can trigger the next step (e.g. confirmation message, artist notification).

**You’re paying for:** Integration with Stripe (Checkout + webhook), security (signature verification, idempotency), and correct status updates so no double-counting or wrong lead assignment.

---

### A6) Calendar-aware slot suggestions (read-only) — *included in Phase 1 fee*

**What you get:**

- The system **reads** your Google Calendar availability (hours, buffers, timezone from your rules).
- It suggests a small set of slot options (e.g. 5–8) to the client in the chat.
- The client picks a preferred option (e.g. “Option 2” or “Tuesday afternoon”).
- **Safety gate:** You still confirm the booking manually; the system does not write to the calendar in Phase 1.

**You’re paying for:** Calendar read integration, slot suggestion logic, and client-facing slot selection (parsing “option 3”, “Tuesday morning”, etc.).

---

### A7) Ops: Google Sheets + secure action links — *included in Phase 1 fee*

**What you get:**

- Every qualified lead is logged to a **Google Sheet** (queue/log) with key fields (status, contact, summary, etc.).
- **Secure action links** (e.g. in WhatsApp or email) let you: **Approve**, **Reject**, **Send deposit**, **Mark booked**.
- Each link is **single-use**, **expiring** (e.g. 7 days), and **status-locked** (e.g. “Send deposit” only when the lead is in “Approved”). A confirmation page is shown before the action runs.

**You’re paying for:** Sheets integration (log + status updates), token generation, and the secure action endpoints so you can operate from your phone without using an admin dashboard.

---

### A8) Dynamic artist handover — *included in Phase 1 fee*

**What you get:**

- When the bot can’t safely continue (e.g. complex/off-script/cover-up, or two parse failures on the same field), the lead is moved to **NEEDS_ARTIST_REPLY**.
- You receive a **handover packet**: last few messages, parse failures, size/budget/location, category/deposit, tour context, and preferred handover channel (e.g. “Quick call scheduled manually”).

**You’re paying for:** Handover triggers, handover packet content, and notifications so you know when to step in.

---

### A9) Reminders / expiry — *included in Phase 1 fee*

**What you get:**

- **12h reminder** → **36h final** → ~**48h abandoned** for leads who don’t complete the consultation.
- **PENDING_APPROVAL** leads marked **stale** after 3 days if no action.
- Reminders are idempotent (no duplicate reminders if the webhook is retried).

**You’re paying for:** Reminder logic, timing rules, and template-based messages (including 24-hour window handling where required by WhatsApp).

---

### A10) Voice pack (non-AI) — *included in Phase 1 fee*

**What you get:**

- A **phrase bank** (e.g. 30–50 lines) and boundaries so bot messages match your tone (polite, clear, on-brand).
- No AI generation; fixed or template-driven wording.

**You’re paying for:** Copy structure, voice pack configuration, and wiring into the consultation and notification messages.

---

### Phase 1 acceptance criteria (what “Go-Live” means)

- Consultation works end-to-end.
- Sheet logging is correct.
- Approval gate works (deposit link only after approval).
- Deposit link and Stripe webhook work correctly.
- Calendar suggestions are generated correctly.
- Status machine is enforced (no invalid status jumps).

When these are met and Phase 1 is live, the **Phase 1 Go-Live** payment (£1,000) is due.

---

## Schedule B — Phase 2 (£4,500 total: £2,500 at Phase 2 Start + £2,000 at Go-Live)

**What Phase 2 delivers:** The “secretary fully books” — the client selects a slot in chat, the system holds it (with TTL), they pay the deposit, and the booking is confirmed with **automatic creation of a Google Calendar event**. Concurrency protection prevents double booking.

### B1) End-to-end booking inside the chat (date selection + deposit + confirm) — *included in Phase 2 fee*

**What you get:**

- The client chooses a slot from the suggested options **in the chat** (e.g. “2” or “Tuesday 2pm”).
- That choice is tied to the lead; the deposit link is for that slot.
- After payment, the client receives a **confirmation** (e.g. date, time, next steps) and the system moves the lead to a “confirmed” state (e.g. BOOKED or equivalent).

**You’re paying for:** Slot selection in chat, binding the chosen slot to the lead and to the deposit, and the confirmation flow (messages + status updates).

---

### B2) Holds + expiry (anti-double-book) — *included in Phase 2 fee*

**What you get:**

- **Slot holds with TTL** (e.g. 15–20 minutes): when a client is shown slots and is “in flow” toward paying, that slot is temporarily held so another client can’t book it.
- When the TTL expires without payment, the hold is released and the slot can be suggested again.
- **Concurrency protection** so two people can’t confirm the same slot (e.g. locking or conflict detection).

**You’re paying for:** Hold creation, expiry logic, and safe behaviour on conflicts (no ghost bookings, clear fallback paths).

---

### B3) System-owned Google Calendar event creation — *included in Phase 2 fee*

**What you get:**

- On **successful deposit**, the system **creates a Google Calendar event** for the chosen slot (title, time, duration, optional description/link).
- **Retry and recovery** for transient failures (e.g. Calendar API timeout) so we don’t leave the lead “paid but no event”.
- **Timezone/DST** handling based on your rules pack so events land on the correct local time.

**You’re paying for:** Calendar write integration (events.insert or equivalent), retry logic, and timezone-safe behaviour.

---

### B4) Post-payment confirmation flow — *included in Phase 2 fee*

**What you get:**

- **Confirmation message** to the client (e.g. “You’re booked for [date] at [time]. Here’s what happens next…”).
- **Internal logging** (e.g. status, timestamps, calendar event ID) and **artist notification** (e.g. “Lead X paid deposit and is booked for [slot]”).
- **Sheet updates** so the queue/log shows the confirmed booking and, if applicable, the calendar event ID.

**You’re paying for:** Message content, logging, and notifications so you and the client both see the confirmed booking.

---

### Phase 2 acceptance criteria (what “Go-Live” means)

- A client can: **select a slot → pay deposit → receive confirmation**.
- A **calendar event is created automatically** and matches the chosen slot.
- **Concurrency protection** prevents double booking.
- **Failure states are safe** (no ghost bookings, no paid-but-no-event without recovery path).
- **Logging + sheet updates** reflect the confirmed booking.

When these are met and Phase 2 is live, the **Phase 2 Go-Live** payment (£2,000) is due.

---

## What is not included (out of scope unless changed)

- **Phase 3 (marketing/re-engagement):** Broadcast campaigns, segmentation, campaign tags, or full nurture sequences. Opt-out (STOP/UNSUBSCRIBE) and template strategy are in scope where needed for Phase 1/2.
- **Payment inside WhatsApp:** The Agreement allows Stripe Checkout (external page). Paying entirely inside WhatsApp with no external page would be a Change Request.
- **External booking platforms:** No Fresha/Calendly/etc. for scheduling or confirmation; calendar is the source of truth for Phase 2.
- **Ongoing maintenance:** Post–Phase 2 support is the 14-day defect-fix period; any ongoing maintenance is per Clause 9.2 (optional, separate fee).
- **Third-party fees:** WhatsApp/Meta, Stripe, Google, hosting, and domain costs are the Client’s responsibility (Clause 13).

---

## Summary table — cost per deliverable

| Schedule item | What you get | Phase fee |
|---------------|--------------|-----------|
| **A1** Guided consultation | Structured questions, parsing, handover on repeated parse failure | Phase 1 |
| **A2** Budget filtering | Min spend UK/EU/ROW, NEEDS_FOLLOW_UP (no auto-decline) | Phase 1 |
| **A3** Tour + waitlist | Tour city offer, WAITLISTED on decline | Phase 1 |
| **A4** Deposit rules | Small/Medium/Large/XL deposit amounts, estimation | Phase 1 |
| **A5** Stripe deposit | Link after approval, Checkout + webhook, status update | Phase 1 |
| **A6** Calendar suggestions | Read-only slots, client picks option | Phase 1 |
| **A7** Sheets + action links | Lead log, Approve/Reject/Send deposit/Mark booked (secure links) | Phase 1 |
| **A8** Artist handover | NEEDS_ARTIST_REPLY + handover packet | Phase 1 |
| **A9** Reminders/expiry | 12h/36h/48h + PENDING_APPROVAL stale at 3 days | Phase 1 |
| **A10** Voice pack | Phrase bank, tone boundaries, non-AI | Phase 1 |
| **B1** Booking in chat | Slot selection → deposit → confirm in chat | Phase 2 |
| **B2** Holds + TTL | Slot hold, expiry, anti-double-book | Phase 2 |
| **B3** Calendar event creation | Create event on successful deposit, retry, timezone-safe | Phase 2 |
| **B4** Post-payment confirmation | Client + artist messages, logging, sheet update | Phase 2 |

**Phase 1 total:** £2,000 (A1–A10).  
**Phase 2 total:** £4,500 (B1–B4).  
**Project total:** £6,500.

---

*This document is a specification of scope and cost by phase. It does not replace the Freelance Services Agreement; in case of conflict, the Agreement prevails.*
