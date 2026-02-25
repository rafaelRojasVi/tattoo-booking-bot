# DB Commit Policy Audit

**Generated:** 2026-02-17

This document lists every `db.commit()` call in `app/services` (and key `app/api` paths) with context. Use it to evaluate a future policy of "only top-level request handlers commit" or to plan refactors.

---

## app/services

### state_machine.py

| Location | Function | Why it commits | Could use flush + caller commit? |
|----------|----------|----------------|----------------------------------|
| L290 | `transition()` | Atomic status change; side effects (WhatsApp, Sheets) happen *after* commit per design | No – transition is the atomic boundary; callers depend on committed state before sending |
| L347 | `advance_step_if_at()` | Conditional UPDATE; commit makes step advance visible before caller sends next prompt | No – atomic step advance; caller sends only after success |

### conversation.py

| Location | Function | Why it commits | Could use flush + caller commit? |
|----------|----------|----------------|----------------------------------|
| L99 | `handle_inbound_message` | Log last_client_message_at for opted-out lead | Possibly – single request handler path |
| L124 | `handle_inbound_message` | After sending holding reply | Possibly – part of request flow |
| L271, L287 | `handle_inbound_message` | Slot selection confirmation | Possibly |
| L374, L391, L402, L419 | `handle_inbound_message` | Tour offer accept/decline | Possibly |
| L475, L486 | `handle_inbound_message` | Resume from handover, reset step | Possibly |
| L510 | `handle_inbound_message` | Holding reply cooldown | Possibly |
| L538, L557, L565 | `handle_inbound_message` | Restart from OPTOUT/ABANDONED/STALE | Possibly |
| L579 | `_handle_new_lead` | Start qualification flow | Possibly |
| L605 | `_handle_new_lead` | After first question sent | Possibly |
| L678, L723, L762, L795 | `handle_inbound_message` | After various prompts sent | Possibly |
| L952, L961 | `handle_inbound_message` | After confirmation summary; before next question | Possibly |
| L1003, L1044 | `handle_inbound_message` | After next question sent | Possibly |
| L1071, L1087, L1103 | `_handle_human_request`, `_handle_refund_request`, `_handle_delete_data_request` | After handover message sent | Possibly |
| L1127 | `handle_inbound_message` | After slot unavailable message | Possibly |
| L1228, L1263 | `handle_inbound_message` | Handover/cover-up flows | Possibly |
| L1319, L1343 | `_complete_qualification` | Cover-up handover | Possibly |
| L1405, L1437 | `_complete_qualification` | Below-min-budget handover | Possibly |
| L1460, L1471 | `_complete_qualification` | Tour offer flows | Possibly |
| L1482, L1496 | `_complete_qualification` | Waitlist flow | Possibly |
| L1506, L1539 | `_complete_qualification` | Qualification complete, PENDING_APPROVAL | Possibly |

**Note:** conversation.py has ~35 commits. All are in request-scoped `handle_inbound_message` or helpers it calls. A refactor could centralize: `handle_inbound_message` does all DB work, then a single commit at the end. Risk: partial failure mid-flow would roll back more.

### reminders.py

| Location | Function | Why it commits | Could use flush + caller commit? |
|----------|----------|----------------|----------------------------------|
| L163 | `check_and_send_qualifying_reminder` | Mark reminder sent (reminder_qualifying_sent_at) | Possibly – called from sweep/job |
| L217 | `_mark_abandoned` | Status → ABANDONED | Possibly |
| L265 | `_mark_stale` | Status → STALE | Possibly |
| L379 | `check_and_send_booking_reminder` | Mark 24h/72h reminder sent | Possibly |
| L440 | `_mark_deposit_expired` | Status → DEPOSIT_EXPIRED | Possibly |
| L491 | `check_and_send_follow_up_reminder` | Status → NEEDS_FOLLOW_UP | Possibly |

### safety.py

| Location | Function | Why it commits | Could use flush + caller commit? |
|----------|----------|----------------|----------------------------------|
| L49 | `update_lead_status_if_matches` | Atomic status update (Core UPDATE) | No – atomic operation; commit is the success boundary |
| L161 | `record_processed_event` | Persist ProcessedMessage for idempotency | Possibly – but callers expect it committed before proceeding |
| L241 | `validate_and_mark_token_used_atomic` | Mark token used | No – atomic; single-use enforcement |

### system_event_service.py

| Location | Function | Why it commits | Could use flush + caller commit? |
|----------|----------|----------------|----------------------------------|
| L56 | `log_event` | Persist SystemEvent | Possibly – but many callers rely on event being committed (e.g. admin views events) |

### calendar_service.py

| Location | Function | Why it commits | Could use flush + caller commit? |
|----------|----------|----------------|----------------------------------|
| L89 | (inline) | Mark lead booked from calendar event | Possibly |
| L410, L428, L453 | `send_slot_suggestions_to_client` | Update lead with slots, last_bot_message_at | Possibly |

### time_window_collection.py

| Location | Function | Why it commits | Could use flush + caller commit? |
|----------|----------|----------------|----------------------------------|
| L87 | `collect_time_window` | Save LeadAnswer, last_client_message_at | Possibly |
| L129, L161 | `collect_time_window` | After artist notification, last_bot_message_at | Possibly |

### parse_repair.py

| Location | Function | Why it commits | Could use flush + caller commit? |
|----------|----------|----------------|----------------------------------|
| L44 | `increment_parse_failure` | Update parse_failure_counts JSON | Possibly |
| L69 | `reset_parse_failures` | Reset parse_failure_counts | Possibly |
| L140 | `_send_repair_prompt` | last_bot_message_at | Possibly |

### artist_notifications.py

| Location | Function | Why it commits | Could use flush + caller commit? |
|----------|----------|----------------|----------------------------------|
| L422 | `notify_artist_needs_reply` | Mark needs_artist_reply_notified_at (idempotency) | Possibly – caller could commit |
| L507 | `notify_artist_needs_follow_up` | Mark needs_follow_up_notified_at (idempotency) | Possibly |

### action_tokens.py

| Location | Function | Why it commits | Could use flush + caller commit? |
|----------|----------|----------------|----------------------------------|
| L57 | `generate_action_token` | Persist new token | Possibly – but token must exist before returning URL |
| L144 | `mark_token_used` (in validate) | Mark used, used_at | No – atomic single-use enforcement |

### media_upload.py

| Location | Function | Why it commits | Could use flush + caller commit? |
|----------|----------|----------------|----------------------------------|
| L48 | `attempt_upload_attachment` | Increment attempts, last_attempt_at | Possibly – sweep job context |
| L69 | `attempt_upload_attachment` | Success: update status, size, clear error | Possibly |
| L86 | `attempt_upload_attachment` | Failure: update status, failed_at | Possibly |

### leads.py

| Location | Function | Why it commits | Could use flush + caller commit? |
|----------|----------|----------------|----------------------------------|
| L89 | `get_or_create_lead` | Persist new lead | Possibly – but callers expect lead.id to exist |

---

## app/api (for context)

| Module | Why it commits |
|--------|----------------|
| webhooks.py | WhatsApp/Stripe request handlers – commit after processing |
| admin.py | Admin actions (approve, reject, send_deposit, etc.) |
| actions.py | Action token execution (approve, reject, etc.) |
| demo.py | Demo mode flows |

---

## Summary

- **Atomic operations** (transition, advance_step_if_at, update_lead_status_if_matches, validate_and_mark_token): commit is the success boundary; changing to flush would require caller coordination.
- **Conversation flow**: Many commits; could be consolidated to one per request at the top level.
- **Reminders, calendar, time_window, parse_repair, artist_notifications**: All could theoretically use flush + caller commit if callers are refactored.
- **system_event_service.log_event**: Commits to persist event; used widely. Could accept a "no_commit" flag for batch scenarios.
