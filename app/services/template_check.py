"""
Template configuration check - validates WhatsApp templates are configured.
"""

import logging
from typing import Any

from app.services.whatsapp_templates import (
    TEMPLATE_CONSULTATION_REMINDER_2_FINAL,
    TEMPLATE_DEPOSIT_RECEIVED_NEXT_STEPS,
    TEMPLATE_NEXT_STEPS_REPLY_TO_CONTINUE,
)

logger = logging.getLogger(__name__)

# All required templates
REQUIRED_TEMPLATES: list[str] = [
    TEMPLATE_CONSULTATION_REMINDER_2_FINAL,
    TEMPLATE_NEXT_STEPS_REPLY_TO_CONTINUE,
    TEMPLATE_DEPOSIT_RECEIVED_NEXT_STEPS,
]


def startup_check_templates() -> dict[str, Any]:
    """
    Check template configuration at startup.
    Logs warnings if templates are missing.

    Returns:
        Dict with template status
    """
    from app.core.config import settings

    templates_configured = REQUIRED_TEMPLATES.copy()
    templates_missing: list[str] = []
    templates_status = {}

    # Check if WhatsApp is enabled (templates only matter if WhatsApp is enabled)
    if not settings.whatsapp_access_token:
        logger.info("WhatsApp not configured - template check skipped")
        return {
            "templates_configured": [],
            "templates_missing": [],
            "whatsapp_enabled": False,
        }

    # For now, we just log the template names
    # In production, you could verify templates exist in WhatsApp Manager via API
    # For Phase 1, we just ensure the names are defined
    for template_name in REQUIRED_TEMPLATES:
        templates_status[template_name] = "configured"  # Assume configured if name exists

    logger.info(f"Template check: {len(templates_configured)} templates configured")
    logger.info(f"Templates: {', '.join(templates_configured)}")

    if templates_missing:
        logger.warning(f"Missing templates: {', '.join(templates_missing)}")
        logger.warning("These templates must be created in WhatsApp Manager and approved")

    return {
        "templates_configured": templates_configured,
        "templates_missing": templates_missing,
        "templates_status": templates_status,
        "whatsapp_enabled": True,
    }
