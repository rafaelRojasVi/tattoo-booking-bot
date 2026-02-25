# Messaging: WhatsApp send, templates, window, composer, outbox, reminders
# Re-export so "from app.services.messaging import ..." works (CI and callers).

from app.services.messaging.messaging import (
    format_deposit_link_message,
    format_payment_confirmation_message,
    format_summary_message,
    send_whatsapp_message,
)

__all__ = [
    "format_deposit_link_message",
    "format_payment_confirmation_message",
    "format_summary_message",
    "send_whatsapp_message",
]
