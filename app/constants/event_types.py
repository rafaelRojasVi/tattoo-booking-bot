"""
Event type constants for SystemEvent and ProcessedMessage.

Use these instead of string literals to ensure consistency.
Dynamic event types use prefixes; use the helpers or format strings.
"""

# ---- State machine ----
EVENT_ADVANCE_STEP_PENDING_CHANGES = "advance_step.pending_changes"
EVENT_ATOMIC_UPDATE_CONFLICT = "atomic_update.conflict"

# ---- WhatsApp ----
EVENT_WHATSAPP_SIGNATURE_VERIFICATION_FAILURE = "whatsapp.signature_verification_failure"
EVENT_WHATSAPP_MESSAGE = "whatsapp.message"
EVENT_WHATSAPP_WEBHOOK_FAILURE = "whatsapp.webhook_failure"
EVENT_WHATSAPP_SEND_FAILURE = "whatsapp.send_failure"
EVENT_WHATSAPP_TEMPLATE_NOT_CONFIGURED_PREFIX = "whatsapp.template_not_configured"

# ---- Stripe ----
EVENT_STRIPE_SIGNATURE_VERIFICATION_FAILURE = "stripe.signature_verification_failure"
EVENT_STRIPE_SESSION_ID_MISMATCH = "stripe.session_id_mismatch"
EVENT_STRIPE_WEBHOOK_FAILURE = "stripe.webhook_failure"
EVENT_STRIPE_CHECKOUT_SESSION_COMPLETED = "stripe.checkout.session.completed"

# ---- Pilot / mode ----
EVENT_PILOT_MODE_BLOCKED = "pilot_mode.blocked"

# ---- Deposit / payment ----
EVENT_DEPOSIT_PAID = "deposit_paid"

# ---- Sheets ----
EVENT_SHEETS_BACKGROUND_LOG_FAILURE = "sheets.background_log_failure"
EVENT_SHEETS_BACKGROUND_DB_ERROR = "sheets.background_db_error"

# ---- Conversation / slots ----
EVENT_NEEDS_ARTIST_REPLY = "needs_artist_reply"
EVENT_SLOT_UNAVAILABLE_AFTER_SELECTION = "slot.unavailable_after_selection"

# ---- Reminders (prefixes for dynamic types) ----
EVENT_REMINDER_QUALIFYING_PREFIX = "reminder.qualifying"
EVENT_REMINDER_BOOKING_PREFIX = "reminder.booking"

# ---- Admin / notifications ----
EVENT_PENDING_APPROVAL = "pending_approval"
EVENT_DEPOSIT_EXPIRED_SWEEP = "deposit_expired_sweep"

# ---- Calendar ----
EVENT_CALENDAR_NO_SLOTS_FALLBACK = "calendar.no_slots_fallback"

# ---- Media ----
EVENT_MEDIA_UPLOAD_FAILURE = "media_upload.failure"

# ---- Template fallback ----
EVENT_TEMPLATE_FALLBACK_USED = "template.fallback_used"


def reminder_qualifying_event_type(reminder_number: int) -> str:
    """e.g. reminder.qualifying.1, reminder.qualifying.2"""
    return f"{EVENT_REMINDER_QUALIFYING_PREFIX}.{reminder_number}"


def reminder_booking_event_type(reminder_type: str) -> str:
    """e.g. reminder.booking.deposit_pending"""
    return f"{EVENT_REMINDER_BOOKING_PREFIX}.{reminder_type}"


def whatsapp_template_not_configured_event_type(template_name: str) -> str:
    """e.g. whatsapp.template_not_configured.consultation_reminder_2"""
    return f"{EVENT_WHATSAPP_TEMPLATE_NOT_CONFIGURED_PREFIX}.{template_name}"
