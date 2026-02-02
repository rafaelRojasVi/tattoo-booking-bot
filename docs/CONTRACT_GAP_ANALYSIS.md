# Contract vs Implementation — Gap Analysis

**Reference:** Freelance Services Agreement v1.0 (29 Jan 2026) — Schedule A (Phase 1) + Schedule B (Phase 2)  
**Purpose:** What is **already implemented** vs **not implemented yet** against the contract.

---

## Summary (at a glance)

| Phase | Contract scope | Already implemented | Not implemented yet |
|-------|----------------|---------------------|----------------------|
| **Phase 1** | A1–A10 + Acceptance Criteria | **All of Phase 1** | — |
| **Phase 2** | B1–B4 + Acceptance Criteria | B1 (partial), B4; slot selection, deposit binding, post-payment flow, Sheets | **B2 (holds + TTL), B3 (Calendar event creation)**; retry/recovery for calendar |

**Phase 1:** Fully implemented and test-covered.  
**Phase 2:** Slot selection and post-payment flow are done; **missing: slot holds with TTL (B2) and Google Calendar event creation (B3)**.

---

## Phase 1 — Schedule A: Already Implemented

All Schedule A deliverables and Phase 1 Acceptance Criteria are implemented.

| Contract item | Status | Implementation notes |
|---------------|--------|------------------------|
| **A1** Guided WhatsApp consultation (structured) | ✅ Done | `conversation.py`, `questions.py` — 13 questions (idea, placement, dimensions, style, complexity, coverup, references, budget, city, country, Instagram, travel city, timing). Answers stored in `lead_answers`; parsing for dimensions, budget, location. |
| **A2** Budget filtering (UK £400 / EU £500 / ROW £600) → NEEDS_FOLLOW_UP | ✅ Done | Region detection (`region_service`, `location_parsing`); min thresholds in conversation; below min → NEEDS_FOLLOW_UP (no auto-decline). |
| **A3** Tour conversion + waitlist | ✅ Done | `tour_service` — offer closest tour city; decline → WAITLISTED. |
| **A4** Deposit rules (Small £150, Medium £150, Large £200, XL £200/day) | ✅ Done | `estimation_service` (category: SMALL/MEDIUM/LARGE/XL), `pricing_service`; deposit amount per tier; XL uses `estimated_days`. |
| **A5** Stripe deposit (Checkout + webhook) after approval | ✅ Done | Deposit link only after approve; `stripe_service` (Checkout session); `webhooks.py` handles `checkout.session.completed` with signature verification, idempotency, status update. |
| **A6** Calendar slot suggestions (read-only) + client selects; manual safety gate | ✅ Done | `calendar_service.py` — read-only free/busy; slot suggestions; `slot_parsing.py` (e.g. "option 2", "Tuesday pm"); `selected_slot_start_at`/`end_at` on lead. Artist confirms manually (no calendar write). |
| **A7** Google Sheets log + secure action links | ✅ Done | `sheets.py` — `log_lead_to_sheets`, `update_lead_status_in_sheets`; `action_tokens.py` + `api/actions.py` — Approve, Reject, Send deposit, Send booking link, Mark booked; single-use, expiring, status-locked; confirm page then execute. |
| **A8** Dynamic artist handover (NEEDS_ARTIST_REPLY) | ✅ Done | `parse_repair.py` (two-strikes per field); `handover_service`; `handover_packet` (last messages, parse failures, context); status NEEDS_ARTIST_REPLY. |
| **A9** Reminders/expiry (12h / 36h / ~48h; stale rules) | ✅ Done | `reminders.py` — qualifying reminders (12h/36h), booking reminders (24h/72h); PENDING_APPROVAL stale handling; idempotent via `processed_messages`. |
| **A10** Voice pack (non-AI) | ✅ Done | `app/copy/en_GB.yml`, `tone.py`, template library; message formatting from config. |

### Phase 1 Acceptance Criteria — status

- Consultation works end-to-end — ✅  
- Sheet logging correct — ✅  
- Approval gate works — ✅  
- Deposit link sent only after approval; Stripe webhook updates status correctly — ✅  
- Calendar suggestions generated correctly — ✅  
- Status machine enforced — ✅  

**Phase 1 is ready for Go-Live** once staging/production env and third-party access (WhatsApp, Stripe, Google) are in place.

---

## Phase 2 — Schedule B: Implemented vs Not Implemented

| Contract item | Status | Implementation notes |
|---------------|--------|------------------------|
| **B1** Slot selection → hold → deposit → confirmation in chat | ⚠️ Partial | **Done:** Slot selection in chat, deposit link tied to selected slot, confirmation flow (client + artist messages, status BOOKED/BOOKING_PENDING). **Missing:** No “hold” entity — slot is chosen and stored on lead but not temporarily held with TTL (see B2). |
| **B2** Holds with TTL (15–20 mins) + concurrency protection + safe conflict fallback | ❌ Not implemented | No slot hold table/record; no TTL (e.g. 15–20 min) after which the slot is released; no explicit concurrency guard to prevent two clients booking the same slot. Selection is stored on lead only. **To build:** Hold entity, TTL expiry job, locking/conflict detection, fallback when hold expires or conflict. |
| **B3** Google Calendar event creation on successful deposit (retry/recovery; timezone/DST safe) | ❌ Not implemented | `calendar_service` is **read-only** (slot suggestions only). No `events.insert` / create event. No retry or reconciliation for “paid but no event”. **To build:** Calendar write scope; create event on successful deposit; retries; timezone/DST handling per rules; reconciliation for failures. |
| **B4** Post-payment confirmation flow (client + artist notifications, logging, Sheets update) | ✅ Done | Stripe webhook updates lead; confirmation message to client; artist notification; `log_lead_to_sheets` / `update_lead_status_in_sheets` on status change. |

### Phase 2 Acceptance Criteria — status

- Client can select slot → pay deposit → receive confirmation — ✅ (without holds; slot selection + deposit + confirmation exist)  
- **Calendar event created automatically and matches slot** — ❌ Not implemented  
- **Concurrency protection prevents double booking** — ❌ Not implemented (no holds/TTL)  
- **Failure states are safe (no ghost bookings)** — ⚠️ Partial (Stripe side is safe; calendar write N/A)  
- Logging + Sheets updates reflect confirmed booking — ✅  

**Phase 2 is not complete** until B2 (holds + TTL + concurrency) and B3 (Calendar event creation) are implemented and acceptance criteria are met.

---

## What Is Not Implemented Yet (checklist)

Use this list for planning and for Change Request / milestone discussions.

### Phase 2 — Required by contract

1. **B2 — Slot holds with TTL (15–20 minutes)**  
   - Introduce a hold (e.g. table or record) for the chosen slot.  
   - TTL: hold expires after 15–20 minutes if deposit not paid; slot becomes available again.  
   - Concurrency protection: two clients cannot confirm the same slot (e.g. lock or conflict check when creating hold / confirming).  
   - Safe conflict fallback: clear behaviour when hold expires or when a conflict is detected (e.g. release hold, notify, offer another slot).

2. **B3 — Google Calendar event creation on successful deposit**  
   - When deposit is paid, create a **Google Calendar event** for the chosen slot (title, start/end, timezone).  
   - Use Calendar **write** scope (not just read).  
   - Retry/recovery for transient failures (e.g. API timeout) so “paid but no event” is reconciled.  
   - Timezone/DST handling consistent with your rules (e.g. artist timezone, session blocks).

3. **Phase 2 Acceptance Criteria**  
   - Ensure: calendar event created automatically and matches slot; concurrency protection prevents double booking; failure states do not create ghost bookings; logging + Sheets reflect confirmed booking (including calendar event ID if desired).

### Not in Phase 1/2 contract (out of scope unless CR)

- Phase 3 (broadcast campaigns, segmentation, campaign tracking).  
- Payment entirely inside WhatsApp (no external Stripe page).  
- External scheduling platforms (Fresha/Calendly) for availability or confirmation.  
- Optional internal improvements (e.g. retry queue for side effects, version column for optimistic concurrency) — only if you add them as scope.

---

## Already Implemented — Quick reference

**Phase 1 (all):**  
A1–A10 and all Phase 1 Acceptance Criteria — consultation, budget/tour/deposit rules, approval gate, Stripe Checkout + webhook, read-only calendar suggestions, Sheets, secure action links, handover, reminders, voice pack.

**Phase 2 (partial):**  
- B1 (partial): Slot selection in chat, deposit tied to selected slot, confirmation flow.  
- B4: Post-payment confirmation (client + artist, logging, Sheets).  
- **Not yet:** B2 (holds + TTL + concurrency), B3 (Calendar event creation).

---

*This document is a gap analysis against the Agreement’s Schedules A and B. It does not amend the Agreement; for scope and acceptance, the signed contract and its Schedules apply.*
