"""
WhatsApp template message definitions and helpers.

Phase 1 templates (all Utility category):
1. consultation_reminder_2_final - 36h final reminder
2. next_steps_reply_to_continue - Re-open window after approval/deposit
3. deposit_received_next_steps - Deposit confirmation outside window
"""

import logging

logger = logging.getLogger(__name__)

# Template definitions (must match WhatsApp Manager template names)
TEMPLATE_CONSULTATION_REMINDER_2_FINAL = "consultation_reminder_2_final"
TEMPLATE_NEXT_STEPS_REPLY_TO_CONTINUE = "next_steps_reply_to_continue"
TEMPLATE_DEPOSIT_RECEIVED_NEXT_STEPS = "deposit_received_next_steps"

# Template language code (default to en_GB, can be configured)
TEMPLATE_LANGUAGE_CODE = "en_GB"


def get_template_params_consultation_reminder_2_final(client_name: str | None = None) -> dict:
    """
    Get template parameters for consultation_reminder_2_final.

    Template body: "Hey {{1}} — just checking in. If you'd like to continue your tattoo enquiry, reply to this message and we'll pick up where we left off."

    Args:
        client_name: Optional client name (if available)

    Returns:
        Dict with template parameters
    """
    return {
        "1": client_name or "there",  # Fallback to "there" if name not available
    }


def get_template_params_next_steps_reply_to_continue() -> dict:
    """
    Get template parameters for next_steps_reply_to_continue.

    Template body: "Your enquiry has been reviewed ✅ Reply to this message to see the next available times and continue."

    Returns:
        Dict with template parameters (empty - no placeholders in this template)
    """
    return {}


def get_template_params_deposit_received_next_steps(client_name: str | None = None) -> dict:
    """
    Get template parameters for deposit_received_next_steps.

    Template body: "Deposit received ✅ Thanks {{1}}. Jonah will confirm your booking in Google Calendar and message you with the details shortly."

    Args:
        client_name: Optional client name (if available)

    Returns:
        Dict with template parameters
    """
    return {
        "1": client_name or "there",  # Fallback to "there" if name not available
    }


def get_template_for_reminder_2() -> str:
    """Get template name for 36h final consultation reminder."""
    return TEMPLATE_CONSULTATION_REMINDER_2_FINAL


def get_template_for_next_steps() -> str:
    """Get template name for re-opening window after approval."""
    return TEMPLATE_NEXT_STEPS_REPLY_TO_CONTINUE


def get_template_for_deposit_confirmation() -> str:
    """Get template name for deposit confirmation outside window."""
    return TEMPLATE_DEPOSIT_RECEIVED_NEXT_STEPS
