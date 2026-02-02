# Side-Effect Ordering and Last-Mile Production Tests

## Last-Mile Tests Added

| Test | What it verifies |
|------|-------------------|
| **test_send_failure_does_not_advance_step** | If `send_whatsapp_message` raises, `current_step` is unchanged (send-before-advance in qualifying flow). |
| **test_out_of_order_message_does_not_advance_or_reprompt** | Message with timestamp older than `last_client_message_at` returns `type: "out_of_order"`, no outbound send, no step advance. |
| **test_optout_restart_resets_step_and_handover_timestamps** | OPTOUT → NEW policy: sending START resets status to QUALIFYING and `current_step` to 0. |
| **test_duplicate_message_id_different_text_is_ignored** | Same `message_id` with different text: second request is duplicate; only first message creates a LeadAnswer; one ProcessedMessage. |
| **test_stripe_duplicate_events_do_not_double_transition** | Same Stripe `event_id` delivered twice: one ProcessedMessage, one status transition (BOOKING_PENDING), no double notification. |

All in **tests/test_production_last_mile.py**.

---

## Ordering Change Implemented: Send Before Advance

**Goal:** If sending the “next question” fails, we must not advance `current_step`, so retries can send the same question again.

**Change in conversation.py:**

- **Confirmation-sent branch:** Compose next message, `await send_whatsapp_message(next_msg)`, then `advance_step_if_at(db, lead_id, current_step)`, then update `last_bot_message_at` and commit.
- **Main “next question” branch:** Same: compose, send, then `advance_step_if_at`, then `last_bot_message_at` and commit.

So we **send first, then advance**. If send raises, we never call `advance_step_if_at`, so step stays unchanged and `test_send_failure_does_not_advance_step` passes.

---

## Review: Outbound Messages vs State Commits in conversation.py

**Safe pattern (prefer):** Send outbound message, then commit state (and any `last_bot_message_at`). If send fails, we don’t persist the transition.

**Risky pattern:** Commit state (or transition), then send. If send fails, state is already persisted and the user may not get the message.

### Current patterns

1. **Qualifying “next question” (fixed)**  
   - Now: send next question → advance step → commit.  
   - Safe: send failure does not advance step.

2. **Repair message (parse failure)**  
   - ~851: `send_whatsapp_message(repair_message)` then `db.commit()`.  
   - Safe: no state transition before send; only `last_bot_message_at` after send.

3. **Handover (should_handover)**  
   - ~682: `transition(db, lead, STATUS_NEEDS_ARTIST_REPLY)` (commits), then `notify_artist_needs_reply`, then `send_whatsapp_message(handover_msg)`, then commit.  
   - **Risky:** Status is committed before client handover message is sent. If send fails, lead is already NEEDS_ARTIST_REPLY but client didn’t get the handover text.  
   - **Recommendation:** Send handover message to client first, then `transition(...)`, then notify artist. Optionally: move artist notify after transition (as now) but send client message before transition.

4. **Tour accept**  
   - ~374: commit location/tour_offer_accepted, then `transition(db, lead, STATUS_PENDING_APPROVAL)` (commits), then send accept_msg, then commit.  
   - **Risky:** Transition committed before send. If send fails, lead is PENDING_APPROVAL but user didn’t get the accept message.  
   - **Recommendation (minimal):** Compose accept_msg, `await send_whatsapp_message(accept_msg)`, then `transition(db, lead, STATUS_PENDING_APPROVAL)`, then set `last_bot_message_at` and commit.

5. **Tour decline (waitlist)**  
   - Same idea: commit + transition, then send decline_msg.  
   - **Recommendation:** Send decline message first, then transition and commit.

6. **Coverup handover**  
   - ~1224: commit `qualifying_completed_at`, then `transition(db, lead, STATUS_NEEDS_ARTIST_REPLY)`, then send handover_msg, then commit.  
   - **Recommendation:** Send handover_msg to client first, then transition, then commit.

7. **Budget below minimum (NEEDS_FOLLOW_UP)**  
   - ~1310: commit, then transition, then send budget_msg.  
   - **Recommendation:** Send budget_msg first, then transition and commit.

8. **Tour conversion offered**  
   - ~1365: commit tour fields, then transition, then send tour_msg.  
   - **Recommendation:** Send tour_msg first, then transition and commit.

9. **Waitlisted (no tour)**  
   - ~1387: commit, then transition, then send waitlist_msg.  
   - **Recommendation:** Send waitlist_msg first, then transition and commit.

10. **Complete qualification (PENDING_APPROVAL)**  
    - ~1411: commit, then `transition(db, lead, STATUS_PENDING_APPROVAL)`, then send completion_msg, then commit.  
    - **Risky:** Transition committed before user sees completion message.  
    - **Recommendation (minimal):** Compose completion_msg, `await send_whatsapp_message(completion_msg)`, then `transition(db, lead, STATUS_PENDING_APPROVAL)`, then set `last_bot_message_at` and commit.

11. **Slot selection confirmation**  
    - ~271: commit slot fields, then send confirmation_msg, then commit.  
    - State is “slot selected”; if send fails, we’ve still committed slot. Acceptable if we can retry send; otherwise consider sending first then committing slot.

12. **Human/refund/delete handover, opt-out, CONTINUE resume, holding message, welcome, etc.**  
    - Most do send then commit (or transition then send where the “state” is already decided and the message is a side effect).  
    - Opt-out: `transition(db, lead, STATUS_OPTOUT)` then send optout_msg — same idea: transition first. Minimal improvement: send optout_msg first, then transition, so user always sees confirmation even if transition fails (unlikely).

### Minimal safe ordering (summary)

- **Already done:** Qualifying next-question: send → advance → commit.
- **Recommended next (same pattern):**  
  - Completion message: send completion_msg → transition(PENDING_APPROVAL) → commit.  
  - Tour accept: send accept_msg → transition(PENDING_APPROVAL) → commit.  
  - Tour decline: send decline_msg → transition(WAITLISTED) → commit.  
  - Coverup handover: send handover_msg → transition(NEEDS_ARTIST_REPLY) → commit.  
  - Budget below min: send budget_msg → transition(NEEDS_FOLLOW_UP) → commit.  
  - Tour conversion offered: send tour_msg → transition(TOUR_CONVERSION_OFFERED) → commit.  
  - Waitlisted: send waitlist_msg → transition(WAITLISTED) → commit.  
  - Dynamic handover (should_handover): send handover_msg to client → transition(NEEDS_ARTIST_REPLY) → then notify artist and commit.

For each of these, the minimal change is: **compose message, await send_whatsapp_message(...), then transition(...) and commit.** No need to change how artist notifications or Sheets are ordered unless we want them strictly after “client saw the message.”

---

## Policy Notes

- **Restart (OPTOUT → NEW):** Step is reset to 0 and status goes to QUALIFYING via _handle_new_lead. Handover-related timestamps (`handover_last_hold_reply_at`, `needs_artist_reply_notified_at`) are **not** cleared on restart; only step and status are. Clearing them on restart would avoid stale “already notified” state if the user hands over again later.
- **Out-of-order:** Handled in the webhook by comparing message timestamp to `last_client_message_at`; no ProcessedMessage is written for out-of-order messages, so a later delivery with the same message_id could still be processed (acceptable; duplicate message_id check would then apply).
