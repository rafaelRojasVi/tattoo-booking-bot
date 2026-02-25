"""
Shared template constants and helpers.

Breaks the import cycle between template_check and template_registry.
Both depend on template_core only.
"""

from enum import StrEnum

from app.services.whatsapp_templates import (
    TEMPLATE_CONSULTATION_REMINDER_2_FINAL,
    TEMPLATE_DEPOSIT_RECEIVED_NEXT_STEPS,
    TEMPLATE_NEXT_STEPS_REPLY_TO_CONTINUE,
)


class MessageType(StrEnum):
    """Enumeration of all outbound message types that may require templates."""

    # Reminders
    CONSULTATION_REMINDER_2 = "consultation_reminder_2"  # 36h final reminder
    BOOKING_REMINDER_24H = "booking_reminder_24h"  # 24h booking reminder
    BOOKING_REMINDER_72H = "booking_reminder_72h"  # 72h booking reminder

    # Deposit & Payment
    DEPOSIT_CONFIRMATION = "deposit_confirmation"  # After deposit paid
    DEPOSIT_LINK_SENT = "deposit_link_sent"  # When sending deposit link

    # Booking & Scheduling
    SLOT_SUGGESTIONS = "slot_suggestions"  # Calendar slot suggestions
    NO_SLOTS_FALLBACK = "no_slots_fallback"  # When no slots available
    APPROVAL_NOTIFICATION = "approval_notification"  # After lead approval

    # General
    NEXT_STEPS = "next_steps"  # Generic next steps message


# Template Registry: Maps message types to template keys
TEMPLATE_REGISTRY: dict[MessageType, str] = {
    MessageType.CONSULTATION_REMINDER_2: TEMPLATE_CONSULTATION_REMINDER_2_FINAL,
    MessageType.DEPOSIT_CONFIRMATION: TEMPLATE_DEPOSIT_RECEIVED_NEXT_STEPS,
    MessageType.DEPOSIT_LINK_SENT: TEMPLATE_NEXT_STEPS_REPLY_TO_CONTINUE,
    MessageType.SLOT_SUGGESTIONS: TEMPLATE_NEXT_STEPS_REPLY_TO_CONTINUE,
    MessageType.NO_SLOTS_FALLBACK: TEMPLATE_NEXT_STEPS_REPLY_TO_CONTINUE,
    MessageType.APPROVAL_NOTIFICATION: TEMPLATE_NEXT_STEPS_REPLY_TO_CONTINUE,
    MessageType.NEXT_STEPS: TEMPLATE_NEXT_STEPS_REPLY_TO_CONTINUE,
}


def get_all_required_templates() -> list[str]:
    """All unique template keys required by the registry (sorted)."""
    templates = set(TEMPLATE_REGISTRY.values())
    return sorted(list(templates))


def get_required_templates_app() -> list[str]:
    """Required templates for the app (registry + test_template for tests)."""
    base = get_all_required_templates()
    if "test_template" not in base:
        return base + ["test_template"]
    return base
