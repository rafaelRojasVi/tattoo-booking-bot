# Implementation Status - Proposal v1.4 Alignment

**Date:** 2026-01-19  
**Status:** Core infrastructure updates complete, ready for admin actions and integrations

---

## ✅ Completed Tasks

### 1. Database Schema Updates
- ✅ Added all missing Lead fields per proposal:
  - Location: `location_city`, `location_country`, `region_bucket`
  - Size: `size_category`, `size_measurement`
  - Budget: `budget_range_text`
  - Summary: `summary_text` (cached)
  - Deposit: `deposit_amount_pence`, `stripe_checkout_session_id`, `stripe_payment_intent_id`, `stripe_payment_status`, `deposit_paid_at`
  - Booking: `booking_link`, `booking_tool`, `booking_link_sent_at`, `booked_at`
  - Timestamps: `last_client_message_at`, `last_bot_message_at`, reminder fields, `stale_marked_at`, `abandoned_marked_at`
  - Admin: `approved_at`, `rejected_at`, `last_admin_action`, `last_admin_action_at`, `admin_notes`
- ✅ Added media fields to `lead_answers`: `message_id`, `media_id`, `media_url`
- ✅ Created `processed_messages` table for webhook idempotency
- ✅ Migration file created: `a1b2c3d4e5f6_add_proposal_v1_4_fields.py`

### 2. Status Model Alignment
- ✅ Expanded status constants to match proposal:
  - Core: `NEW`, `QUALIFYING`, `PENDING_APPROVAL`, `AWAITING_DEPOSIT`, `DEPOSIT_PAID`, `BOOKING_LINK_SENT`, `BOOKED`
  - Operational: `NEEDS_ARTIST_REPLY`, `NEEDS_FOLLOW_UP`, `REJECTED`
  - Housekeeping: `ABANDONED`, `STALE`
- ✅ Updated conversation flow to transition to `PENDING_APPROVAL` (not `AWAITING_DEPOSIT`) after qualification
- ✅ Added handlers for all new statuses

### 3. Conversation Flow Updates
- ✅ Implemented ARTIST handover (`_handle_artist_handover`)
  - Client types "ARTIST" → status → `NEEDS_ARTIST_REPLY`
  - Bot pauses and asks for handover preference
- ✅ Implemented CONTINUE resume
  - Client types "CONTINUE" → resumes qualification flow
- ✅ Updated completion flow to send appropriate message and set `PENDING_APPROVAL`
- ✅ Added timestamp tracking (`last_client_message_at`, `last_bot_message_at`)

### 4. Webhook Idempotency
- ✅ Added `ProcessedMessage` model
- ✅ Implemented duplicate message detection in webhook handler
- ✅ Stores message IDs to prevent reprocessing

### 5. WhatsApp Dry-Run Feature Flag
- ✅ Added `whatsapp_dry_run` config setting (defaults to `True`)
- ✅ Updated webhook to use `settings.whatsapp_dry_run` instead of hardcoded `True`
- ✅ Can be controlled via environment variable `WHATSAPP_DRY_RUN=false`

### 6. Question Updates
- ✅ Updated questions to match proposal:
  - Added `size_category` question (Small/Medium/Large selection - Option A)
  - Added optional `size_measurement` question
  - Made `style` optional
  - Added `location_city` and `location_country` questions
  - Renamed `preferred_days` to `preferred_timing`
- ✅ Questions now align with proposal requirements

---

## 🚧 Next Steps (Can Start Immediately)

### 7. Admin Action Endpoints (No-Ops First)
**Priority: High**

Create endpoints that perform status transitions without full implementation:
- `POST /admin/leads/{id}/approve` → `PENDING_APPROVAL` → `AWAITING_DEPOSIT`
- `POST /admin/leads/{id}/reject` → `PENDING_APPROVAL` → `REJECTED`
- `POST /admin/leads/{id}/send-deposit` → `AWAITING_DEPOSIT` → (creates Stripe link, sends WhatsApp)
- `POST /admin/leads/{id}/send-booking-link` → `DEPOSIT_PAID` → `BOOKING_LINK_SENT`
- `POST /admin/leads/{id}/mark-booked` → `BOOKING_LINK_SENT` → `BOOKED`

**Implementation:**
- Add to `app/api/admin.py`
- Status-locked (can only execute in correct state)
- Update `last_admin_action` and `last_admin_action_at`
- For now, just log actions (no-op for Stripe/WhatsApp sending)

### 8. Action Token System
**Priority: Medium**

For Mode B (WhatsApp action links):
- Create `action_tokens` table:
  - `token_hash` (unique), `lead_id`, `action`, `expires_at`, `used_at`, `created_at`
- Generate secure tokens for each action
- `GET /a/{token}` - Show confirm page
- `POST /a/{token}` - Execute action (status-locked, single-use, expiry check)

### 9. Basic Admin Authentication
**Priority: High**

- Add `ADMIN_API_KEY` to config
- Create dependency `get_admin_auth()` that checks `X-Admin-API-Key` header
- Apply to all `/admin/*` endpoints

### 10. Stripe Integration (Test Mode)
**Priority: High**

- Create `app/services/stripe_service.py`:
  - `create_deposit_checkout_session(lead_id, amount_pence)` → returns Stripe session URL
  - Hardcode amount for now (e.g., 5000 pence = £50)
- Create `POST /webhooks/stripe`:
  - Verify webhook signature
  - Handle `checkout.session.completed`
  - Update lead: `DEPOSIT_PAID`, `deposit_paid_at`, `stripe_payment_status`
- Add idempotency (check if payment_intent already processed)

### 11. Region Bucket Derivation
**Priority: Medium**

Create helper function to derive `region_bucket` from `location_country`:
- UK → "UK"
- EU countries → "EUROPE"
- Else → "ROW"

Call this in `_complete_qualification()` after saving answers.

### 12. Size Category Validation
**Priority: Low**

Add validation in conversation flow to ensure `size_category` is one of: "SMALL", "MEDIUM", "LARGE" (case-insensitive).

### 13. Google Sheets Stub
**Priority: Medium**

Create `app/services/sheets_service.py`:
- `log_lead_to_sheets(lead)` - Append/update row
- `update_lead_status_in_sheets(lead_id, status)` - Update status column
- For now, just log what would be sent (no actual API calls)

---

## 📋 Implementation Order Recommendation

1. **Admin Authentication** (Task 9) - Security first
2. **Admin Action Endpoints** (Task 7) - Core workflow
3. **Stripe Integration** (Task 10) - Payment flow
4. **Action Token System** (Task 8) - Mode B support
5. **Region Bucket Derivation** (Task 11) - Data completeness
6. **Google Sheets Stub** (Task 13) - Logging structure

---

## 🔍 Code Locations

### Files Modified
- `app/db/models.py` - Added fields and `ProcessedMessage` model
- `app/services/conversation.py` - Status updates, ARTIST/CONTINUE handlers
- `app/api/webhooks.py` - Idempotency, dry-run flag
- `app/core/config.py` - Added `whatsapp_dry_run`
- `app/services/questions.py` - Updated question set
- `migrations/versions/a1b2c3d4e5f6_add_proposal_v1_4_fields.py` - New migration

### Files to Create
- `app/services/stripe_service.py` - Stripe integration
- `app/services/sheets_service.py` - Google Sheets logging
- `app/api/actions.py` - Action token endpoints (Mode B)
- `app/db/models.py` - Add `ActionToken` model (for Task 8)

---

## ⚠️ Known Issues / TODOs

1. **Region bucket derivation** - Not yet implemented (needs country → region mapping)
2. **Deposit tier calculation** - Hardcoded for now, needs tier table/config
3. **Artist notifications** - Not implemented (WhatsApp summary + action links)
4. **Reminder scheduler** - Not implemented (needs background job/cron)
5. **Media handling** - Fields added but not used in webhook yet
6. **Summary formatting** - May need updates for new question keys

---

## 🧪 Testing Status

- ✅ Existing tests should still pass (status constants updated)
- ⚠️ May need to update tests for new status transitions
- ⚠️ Need tests for:
  - ARTIST/CONTINUE handlers
  - Idempotency (duplicate message detection)
  - Admin action endpoints (status-locked behavior)
  - Stripe webhook handler

---

## 📝 Notes

- All changes are backward compatible (new fields are nullable)
- Migration can be run when database is available
- Dry-run mode is default (safe for development)
- Status model now matches proposal exactly
- Ready to implement admin actions and Stripe integration
