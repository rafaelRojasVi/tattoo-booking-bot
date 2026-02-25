# Phase Summary & Cost Tracking

Summary of what’s implemented for each phase and a structure for tracking costs. Fill in the cost columns with your own numbers (dev, APIs, hosting, etc.).

---

## Phase 1 — “Secretary + Safety Gate”

**Purpose:** Qualify leads, collect info, let artist decide.  
**Ends when:** Phase 1 acceptance criteria met + Go-Live.

| Feature | Status | Notes |
|--------|--------|--------|
| Guided WhatsApp consultation (structured questions) | ✅ Implemented | `conversation.py`, state machine, questions flow |
| Parse/repair + two-strikes → handover | ✅ Implemented | `parse_repair.py`, `handover_service`, per-field failure count → handover |
| Budget minimum spend + tour conversion / waitlist | ✅ Implemented | Budget check in conversation; `tour_service` conversion offer; waitlist when declined/no tour |
| Lead summary to artist | ✅ Implemented | `summary.py`, `artist_notifications`, `handover_packet` |
| Google Sheets logging | ✅ Implemented | `sheets.py` — `log_lead_to_sheets`, upsert by lead_id; feature flag + stub when disabled |
| Secure action links (approve/reject/send_deposit/mark_booked) | ✅ Implemented | `action_tokens.py`, `api/actions.py` — single-use, expiry, status-locked; confirm page then execute |
| Calendar read-only slot suggestions | ✅ Implemented | `calendar_service.py` — slot suggestions, format and send; no calendar write |
| Stripe deposit link only after approval + webhook | ✅ Implemented | Deposit link sent after approve; `webhooks.py` handles `checkout.session.completed`, updates lead, idempotency |

**Phase 1 overall:** Implemented and covered by tests (e2e, go-live guardrails, phase1 services).

| Cost type | Estimated / actual | Notes |
|-----------|--------------------|--------|
| Development (Phase 1) | _fill in_ | |
| WhatsApp / Meta (conversation, templates) | _fill in_ | Per conversation / template |
| Stripe (deposits) | _fill in_ | Per transaction |
| Google (Sheets, Calendar read) | _fill in_ | If using APIs |
| Hosting / infra | _fill in_ | |

---

## Phase 2 — “Secretary Fully Books”

**Purpose:** Operational automation — less manual work, safer booking.  
**Ends when:** Client can go slot selection → deposit → confirmed booking + calendar event created.

| Feature | Status | Notes |
|--------|--------|--------|
| Client selects slot inside chat | ✅ Implemented | `slot_parsing.py`, conversation: by number, “option N”, day/time; `selected_slot_start_at` / `end_at` |
| Holds / anti-double-booking (TTL holds) | ❌ Not implemented | No calendar hold with TTL; selection stored on lead but no temporary “hold” with expiry |
| Deposit tied to selected slot/hold | ✅ Implemented | Deposit flow uses lead; `selected_slot_*` stored; no separate hold entity |
| Google Calendar write: create confirmed event | ❌ Not implemented | `calendar_service`: read-only slot suggestions; `find_event_by_lead_tag` is stub; no `events.insert` / create event |
| Post-payment confirmation flow (client + artist) | ✅ Implemented | Stripe webhook updates lead; notifications/messaging for client and artist |
| Retry/recovery for calendar/payment failures | ⚠️ Partial | Stripe webhook: logging, SystemEvent, idempotency; calendar write N/A (not built) |
| Sheets updated with booking status | ✅ Implemented | `log_lead_to_sheets`, `update_lead_status_in_sheets` on status changes |
| Slot selection → deposit → confirmed booking + calendar event | ⚠️ Partial | Slot → deposit → “booked” state exists; **calendar event creation missing** for “confirmed booking” |

**Phase 2 overall:** Slot selection and deposit flow are in place; missing pieces are calendar holds (TTL) and **creating the confirmed event in Google Calendar**.

| Cost type | Estimated / actual | Notes |
|-----------|--------------------|--------|
| Development (Phase 2 – remaining) | _fill in_ | Calendar write + optional holds |
| WhatsApp / Meta | _fill in_ | |
| Stripe | _fill in_ | |
| Google (Calendar write scope) | _fill in_ | |
| Hosting / infra | _fill in_ | |

---

## Phase 3 — “Marketing / Re-engagement inside WhatsApp”

**Purpose:** More revenue from past leads, reduce drop-off.  
**Ends when:** You can run a campaign safely (compliance + templates) and see results in logging/metrics.

| Feature | Status | Notes |
|--------|--------|--------|
| Broadcast campaigns (e.g. healed work, tour dates, last-minute slots) | ❌ Not implemented | No broadcast/campaign sender |
| Segmentation (waitlisted, abandoned, past booked, deposit expired, city, etc.) | ❌ Not implemented | Lead flags exist (e.g. `waitlisted`) but no segmentation service for campaigns |
| Automated follow-ups (nurture, “still interested?”, tour city update) | ⚠️ Partial | `reminders.py`: deposit reminder, abandonment, stale; not full “nurture sequences” or campaign-driven |
| Opt-in / opt-out compliance (stop keywords, consent) | ✅ Implemented | `conversation.py`: STOP/UNSUBSCRIBE → `_handle_opt_out`, confirmation message |
| Message templates strategy (approved templates for outreach) | ✅ Implemented | `whatsapp_templates`, `template_check`, `template_registry` |
| Tracking: campaign tags + conversion metrics in Sheets | ❌ Not implemented | Funnel/metrics exist; no campaign tags or campaign-level conversion logging |

**Phase 3 overall:** Opt-out and template tooling are in place; broadcast, segmentation, and campaign tracking are not.

| Cost type | Estimated / actual | Notes |
|-----------|--------------------|--------|
| Development (Phase 3) | _fill in_ | Broadcast, segmentation, campaign tracking |
| WhatsApp / Meta (business, template approval) | _fill in_ | |
| Hosting / infra | _fill in_ | |

---

## Summary Table

| Phase | Purpose | Implemented | Missing / partial |
|-------|---------|-------------|-------------------|
| **1** | Secretary + safety gate | Full | — |
| **2** | Secretary fully books | Slot selection, deposit, post-payment, Sheets | Calendar event creation; optional TTL holds |
| **3** | Marketing / re-engagement | Opt-out, templates | Broadcast, segmentation, campaign tracking |

---

## Cost Notes (fill in your own figures)

- **Development:** Use your internal rate or contractor rate × effort (e.g. Phase 2: calendar write + holds; Phase 3: campaigns + segmentation).
- **WhatsApp / Meta:** Conversation-based pricing, template messages; check Meta Business pricing for your region.
- **Stripe:** Per successful charge (e.g. deposit); no extra for webhooks.
- **Google:** Sheets API, Calendar API (read already used; write when Phase 2 calendar create is added).
- **Hosting:** Render/VM/containers, DB, any workers (e.g. sweepers).

*This doc does not provide financial or pricing advice. Use your own rates and vendor pricing for “Estimated / actual” and for what your services should cost.*
