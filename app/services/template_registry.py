"""
Template Registry - maps out-of-24h message types to WhatsApp template keys.

This registry ensures every outbound message that might be sent outside the
24-hour window has a corresponding template configured.
"""

import logging
from enum import Enum

from app.services.whatsapp_templates import (
    TEMPLATE_CONSULTATION_REMINDER_2_FINAL,
    TEMPLATE_DEPOSIT_RECEIVED_NEXT_STEPS,
    TEMPLATE_NEXT_STEPS_REPLY_TO_CONTINUE,
)

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
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
    # Note: BOOKING_REMINDER_24H and BOOKING_REMINDER_72H don't have templates yet
    # They use a hardcoded "reminder_booking" string - this needs to be added
}


def get_template_for_message_type(message_type: MessageType) -> str | None:
    """
    Get template key for a message type.

    Args:
        message_type: Message type enum

    Returns:
        Template key string, or None if no template is configured
    """
    return TEMPLATE_REGISTRY.get(message_type)


def get_all_required_templates() -> list[str]:
    """
    Get all unique template keys required by the registry.

    Returns:
        List of template key strings
    """
    templates = set(TEMPLATE_REGISTRY.values())
    return sorted(list(templates))


def validate_template_registry() -> dict[str, any]:
    """
    Validate that all templates in registry are configured.

    Returns:
        Dict with validation results:
        - valid: bool
        - missing_templates: list[str]
        - message_types_without_templates: list[str]
    """
    from app.services.template_check import REQUIRED_TEMPLATES

    required_templates = get_all_required_templates()
    missing_templates = []
    message_types_without_templates = []

    # Check which templates are missing
    for template_key in required_templates:
        if template_key not in REQUIRED_TEMPLATES:
            missing_templates.append(template_key)

    # Check which message types don't have templates
    for message_type in MessageType:
        if message_type not in TEMPLATE_REGISTRY:
            message_types_without_templates.append(message_type.value)

    is_valid = len(missing_templates) == 0 and len(message_types_without_templates) == 0

    return {
        "valid": is_valid,
        "missing_templates": missing_templates,
        "message_types_without_templates": message_types_without_templates,
        "required_templates": required_templates,
        "configured_templates": REQUIRED_TEMPLATES,
    }
