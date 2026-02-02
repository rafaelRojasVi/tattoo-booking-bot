# Architecture Improvements - Production Hardening

This document outlines the critical fixes applied to address race conditions, idempotency timing, and side-effect ordering.

## Issues Fixed

### 1. Race Conditions in Status Transitions

**Problem**: Multiple actors (WhatsApp webhook, admin API, Stripe webhook) could simultaneously mutate the same lead, causing:
- Lost updates
- Invalid state transitions
- Data corruption

**Solution**: 
- Added `SELECT FOR UPDATE` row locking in `state_machine.transition()`
- Reloads lead with lock before transition
- Re-validates status after locking (double-check pattern)
- All transitions happen in single transaction

**Code Location**: `app/services/state_machine.py::transition()`

```python
# Before: No locking
lead.status = to_status
db.commit()

# After: Row-level locking
stmt = select(Lead).where(Lead.id == lead_id).with_for_update()
locked_lead = db.execute(stmt).scalar_one_or_none()
# Re-check status after lock
if locked_lead.status != from_status:
    raise ValueError("Status changed during transition")
```

### 2. Idempotency Timing: Don't Mark Processed Too Early

**Problem**: If we mark an event as processed BEFORE completing side effects, and then crash:
- Event is marked "processed"
- Side effects never happened
- Event will never be retried (dropped)

**Solution**:
- Split `check_and_record_processed_event()` into two functions:
  - `check_processed_event()` - Read-only check (call first)
  - `record_processed_event()` - Record after success (call last)
- Updated webhooks to record AFTER all processing completes

**Code Location**: 
- `app/services/safety.py` - New functions
- `app/api/webhooks.py` - Updated to use new pattern

**Pattern**:
```python
# Check first (read-only)
is_duplicate, existing = check_processed_event(db, event_id)
if is_duplicate:
    return {"type": "duplicate"}

# Process event (DB updates, external calls)
process_event(...)

# Record AFTER success
record_processed_event(db, event_id, event_type, lead_id)
```

### 3. Side Effects After Commit

**Problem**: External calls (WhatsApp, Sheets, Calendar) happening inside DB transaction:
- If external call fails, transaction rolls back
- DB state becomes inconsistent
- Hard to retry failed side effects

**Solution**:
- Commit DB transaction FIRST
- Then perform external calls (WhatsApp, Sheets)
- If external call fails, log error but don't rollback DB
- Record processed event AFTER all side effects succeed

**Code Location**: `app/api/webhooks.py` (Stripe webhook)

**Pattern**:
```python
# 1. Update DB
lead.status = new_status
db.commit()  # Commit FIRST

# 2. External calls (after commit)
try:
    log_lead_to_sheets(db, lead)  # External API
except Exception as e:
    logger.error(f"Sheets failed: {e}")  # Log but don't fail

try:
    await send_whatsapp_message(...)  # External API
except Exception as e:
    logger.error(f"WhatsApp failed: {e}")  # Log but don't fail

# 3. Record processed (after all side effects)
record_processed_event(db, event_id, event_type, lead_id)
```

## State Machine Improvements

### Terminal State Semantics

Added clear definitions for terminal states:

- **ABANDONED**: User stopped responding mid-flow (time-based)
- **STALE**: System-level timeout / no longer actionable (e.g., too old to revive)
- **OPTOUT**: User explicitly STOP / unsubscribed (highest priority - blocks all outbound)
- **WAITLISTED**: User wants it, but you can't serve now (tour declined, waitlisted)
- **BOOKED**: Successfully booked - terminal success state
- **REJECTED**: Artist rejected the lead - terminal rejection state

**Code Location**: `app/services/state_machine.py::STATE_SEMANTICS`

## Migration Guide

### For Existing Code Using `check_and_record_processed_event()`

**Old Pattern** (deprecated):
```python
is_duplicate, processed = check_and_record_processed_event(
    db, event_id, event_type, lead_id
)
if is_duplicate:
    return
# Process...
```

**New Pattern** (recommended):
```python
# Check first
is_duplicate, existing = check_processed_event(db, event_id)
if is_duplicate:
    return

# Process event (DB updates, external calls)
process_event(...)

# Record after success
record_processed_event(db, event_id, event_type, lead_id)
```

### For Status Transitions

**Old Pattern** (no locking):
```python
lead.status = new_status
db.commit()
```

**New Pattern** (with locking):
```python
from app.services.state_machine import transition

transition(
    db=db,
    lead=lead,
    to_status=new_status,
    reason="Optional reason",
    lock_row=True,  # Use locking in production
)
```

## Testing

All fixes are covered by tests:
- `tests/test_state_machine.py` - Tests row locking and re-validation
- `tests/test_go_live_guardrails.py` - Tests idempotency timing
- `tests/test_safety.py` - Tests new idempotency functions

## Performance Considerations

### Row Locking

- `SELECT FOR UPDATE` locks the row until transaction commits
- Lock duration is minimal (microseconds for simple updates)
- If multiple requests try to update same lead, one waits (correct behavior)
- Consider adding indexes on `status` column if you see lock contention

### Idempotency Check

- `check_processed_event()` is a simple SELECT (fast)
- Index on `ProcessedMessage.message_id` ensures O(log n) lookup
- No performance impact for normal flow

## Monitoring

Watch for these metrics:
- `atomic_update.conflict` events (status changed during transition)
- `stripe.webhook_failure` with `status_mismatch` reason
- `whatsapp.webhook_failure` events
- Failed side effects (Sheets, WhatsApp) logged as SystemEvents

## Future Improvements

1. **Optimistic Concurrency**: Add `version` column to Lead for optimistic locking (alternative to SELECT FOR UPDATE)
2. **Retry Queue**: For failed side effects (WhatsApp, Sheets), implement retry queue
3. **Job Queue**: Move side effects to background jobs (Celery, RQ, etc.)
4. **Event Sourcing**: Consider event sourcing for audit trail of all state changes
