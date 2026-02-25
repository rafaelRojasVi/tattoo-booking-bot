# Critical Architecture Fixes - Summary

## Issues Identified & Fixed

### ✅ 1. Race Conditions (FIXED)

**Problem**: Three actors (WhatsApp webhook, admin API, Stripe webhook) mutating same lead simultaneously.

**Fix Applied**:
- Added `SELECT FOR UPDATE` row locking in `state_machine.transition()`
- Reloads lead with lock before transition
- Re-validates status after locking (double-check)
- All transitions in single transaction

**Code**: `app/services/state_machine.py::transition(lock_row=True)`

**Test**: `tests/test_state_machine.py` - All passing

---

### ✅ 2. Idempotency Timing (FIXED)

**Problem**: Marking events as processed BEFORE completing side effects → dropped events if crash.

**Fix Applied**:
- Split into `check_processed_event()` (read-only) and `record_processed_event()` (write)
- Updated WhatsApp webhook to record AFTER `handle_inbound_message()` succeeds
- Updated Stripe webhook to record AFTER all processing (DB + Sheets + WhatsApp)

**Code**: 
- `app/services/safety.py` - New functions
- `app/api/webhooks.py` - Updated pattern

**Pattern**:
```python
# 1. Check (read-only)
is_duplicate, existing = check_processed_event(db, event_id)
if is_duplicate:
    return

# 2. Process (DB updates, external calls)
process_event(...)

# 3. Record (after success)
record_processed_event(db, event_id, event_type, lead_id)
```

---

### ✅ 3. Side Effects After Commit (FIXED)

**Problem**: External calls (WhatsApp, Sheets) inside transaction → rollback on failure.

**Fix Applied**:
- Commit DB transaction FIRST
- Then external calls (wrapped in try/except)
- Log failures but don't rollback DB
- Record processed event AFTER all side effects

**Code**: `app/api/webhooks.py` (Stripe webhook)

**Pattern**:
```python
# 1. DB update + commit
lead.status = new_status
db.commit()

# 2. External calls (after commit)
try:
    log_lead_to_sheets(db, lead)
except Exception as e:
    logger.error(f"Sheets failed: {e}")  # Log, don't fail

try:
    await send_whatsapp_message(...)
except Exception as e:
    logger.error(f"WhatsApp failed: {e}")  # Log, don't fail

# 3. Record processed (last)
record_processed_event(db, event_id, event_type, lead_id)
```

---

## State Machine Improvements

### Terminal State Semantics

Added clear definitions:
- **ABANDONED**: User stopped responding mid-flow (time-based)
- **STALE**: System-level timeout / no longer actionable
- **OPTOUT**: User explicitly STOP / unsubscribed (highest priority)
- **WAITLISTED**: User wants it, but you can't serve now
- **BOOKED**: Successfully booked - terminal success
- **REJECTED**: Artist rejected - terminal rejection

**Code**: `app/services/state_machine.py::STATE_SEMANTICS`

---

## Migration Notes

### For Status Transitions

**Old**:
```python
lead.status = new_status
db.commit()
```

**New**:
```python
from app.services.state_machine import transition

transition(
    db=db,
    lead=lead,
    to_status=new_status,
    lock_row=True,  # Use in production
)
```

### For Idempotency

**Old** (deprecated):
```python
is_duplicate, processed = check_and_record_processed_event(
    db, event_id, event_type, lead_id
)
```

**New**:
```python
# Check first
is_duplicate, existing = check_processed_event(db, event_id)
if is_duplicate:
    return

# Process...
process_event(...)

# Record after success
record_processed_event(db, event_id, event_type, lead_id)
```

---

## Testing Status

✅ All state machine tests passing
✅ Idempotency pattern updated
✅ Side effects moved after commit
⚠️ Need to add integration tests for:
   - Concurrent status updates (race condition test)
   - Idempotency timing (crash before record)
   - Side effect failure handling

---

## Performance Impact

- **Row Locking**: Minimal (microseconds). Locks held only during transition.
- **Idempotency Split**: No performance change (same queries, just reordered).
- **Side Effects After Commit**: Slightly better (external calls don't block transaction).

---

## Monitoring

Watch for these events:
- `atomic_update.conflict` - Status changed during transition (should be rare)
- `stripe.webhook_failure` with `status_mismatch` - Expected status changed
- Failed side effects logged as SystemEvents (Sheets, WhatsApp failures)

---

## Next Steps (Future)

1. **Optimistic Concurrency**: Add `version` column as alternative to SELECT FOR UPDATE
2. **Retry Queue**: For failed side effects (WhatsApp, Sheets)
3. **Job Queue**: Move side effects to background jobs
4. **Integration Tests**: Add tests for concurrent updates
