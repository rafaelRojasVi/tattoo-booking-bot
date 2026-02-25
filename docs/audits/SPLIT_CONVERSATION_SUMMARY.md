# Conversation.py Split Implementation Summary

## Overview
Successfully split `app/services/conversation.py` (~1800 lines) into three focused modules to improve maintainability:
- `conversation.py` - Main orchestrator (~330 lines)
- `conversation_qualifying.py` - Qualification flow handlers (~1062 lines)
- `conversation_booking.py` - Booking flow handlers (~374 lines)

## Branch
- **Current branch**: `refactor/split-conversation`
- **Latest commit**: `ac58a4b` - "refactor: split conversation.py into qualifying and booking modules"

## Files Created/Modified

### New Files
1. **`app/services/conversation_qualifying.py`** (new, ~1062 lines)
   - Handles qualification flow: new leads, qualifying leads, human/refund/delete/opt-out requests
   - Functions:
     - `_handle_new_lead()` - Starts qualification flow (Phase 1)
     - `_handle_qualifying_lead()` - Processes qualification questions/answers
     - `_handle_human_request()` - Handles requests for human assistance
     - `_handle_refund_request()` - Processes refund requests
     - `_handle_delete_data_request()` - Handles data deletion requests
     - `_handle_opt_out()` - Processes opt-out requests
     - `_maybe_send_confirmation_summary()` - Sends confirmation summary after qualification
     - `_handle_artist_handover()` - Handles transition to artist
     - `_complete_qualification()` - Completes qualification process

2. **`app/services/conversation_booking.py`** (new, ~374 lines)
   - Handles booking flow: slot selection, tour conversion, artist replies
   - Functions:
     - `_handle_booking_pending()` - Slot selection logic (deposit paid, waiting for slot)
     - `_handle_tour_conversion_offered()` - Handles tour conversion offers
     - `_handle_needs_artist_reply()` - Handles CONTINUE/holding during artist handover
   - Constants:
     - `HANDOVER_HOLD_REPLY_COOLDOWN_HOURS = 6` - Rate-limit holding messages during handover

3. **`app/constants/statuses.py`** (new, ~40 lines)
   - Centralized STATUS_* constants (previously scattered)
   - All status constants: STATUS_NEW, STATUS_QUALIFYING, STATUS_BOOKING_PENDING, etc.

### Modified Files
1. **`app/services/conversation.py`** (reduced from ~1800 to ~330 lines)
   - Now acts as orchestrator, delegates to new modules
   - Re-exports functions for backward compatibility with tests
   - Imports from `conversation_qualifying` and `conversation_booking`
   - Still contains main `handle_message()` entry point

2. **`app/services/state_machine.py`**
   - Updated to import STATUS_* constants from `app.constants.statuses`

3. **`pyproject.toml`**
   - Added mypy overrides for `conversation_qualifying` and `conversation_booking` modules
   - Matches existing override pattern for `conversation` module (assignment errors)

## Test Status
- **All tests passing**: 953 passed, 2 skipped
- **Ruff**: Format and check passed (3 issues auto-fixed)
- **Mypy**: Passes with new overrides in place
- Tests import from `app.services.conversation` (backward compatibility maintained)

## Key Implementation Details

### Import Pattern
- Both new modules use late-binding pattern for `send_whatsapp_message`:
  ```python
  def _get_send_whatsapp():
      """Late-binding so tests patching conversation.send_whatsapp_message take effect."""
      from app.services.conversation import send_whatsapp_message
      return send_whatsapp_message
  ```
- This allows tests to patch `conversation.send_whatsapp_message` and have it affect the new modules

### Status Constants Migration
- All STATUS_* constants moved to `app/constants/statuses.py`
- Previously imported from various places, now centralized
- `state_machine.py` updated to import from new location

### Backward Compatibility
- `conversation.py` re-exports functions for tests:
  - `_handle_qualifying_lead`, `_complete_qualification`, `_maybe_send_confirmation_summary`
- Tests continue to work without modification

## Git Status
**Committed files** (split-related only):
- `app/constants/statuses.py` (new)
- `app/services/conversation.py` (modified)
- `app/services/conversation_booking.py` (new)
- `app/services/conversation_qualifying.py` (new)
- `app/services/state_machine.py` (modified)
- `pyproject.toml` (modified)

**Uncommitted files** (not part of split, left for other branches):
- `.github/workflows/quality.yml`
- `.gitignore`
- `tests/test_bundle_guard.py`
- `tests/test_golden_transcript_phase1.py`
- `tests/test_parse_repair.py`
- `tests/test_production_hardening.py`
- `docs/MYPY_TRIAGE_PLAN.md`
- `docs/OPS_QUICKSTART.md`

## Code Quality
- ✅ Ruff format: 2 files reformatted, 162 unchanged
- ✅ Ruff check: 3 errors fixed, 0 remaining
- ✅ Mypy: Passes (with module-specific overrides)
- ✅ Pytest: 953 passed, 2 skipped

## Next Steps (if needed)
1. Review split structure for any additional improvements
2. Consider further modularization if needed
3. Update any documentation that references conversation.py structure
4. Merge `refactor/split-conversation` branch when ready

## Architecture Notes
- **Separation of concerns**: Qualification logic separate from booking logic
- **Maintainability**: Each module has clear responsibility
- **Testability**: Functions remain testable via re-exports
- **Extensibility**: Easy to add new handlers to appropriate module
