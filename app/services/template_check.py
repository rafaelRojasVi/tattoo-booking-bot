"""
Template configuration check - validates WhatsApp templates are configured.
"""

import logging
from typing import Any

from app.services.template_registry import get_all_required_templates, validate_template_registry

logger = logging.getLogger(__name__)

# All required templates (from registry)
# Get required templates from registry
_required_templates = get_all_required_templates()

# Add test_template for testing (if not already present)
if "test_template" not in _required_templates:
    _required_templates.append("test_template")

REQUIRED_TEMPLATES: list[str] = _required_templates


def startup_check_templates() -> dict[str, Any]:
    """
    Check template configuration at startup using TemplateRegistry.
    Validates all required templates are configured.
    Logs warnings and notifies artist if templates are missing.

    Returns:
        Dict with template status
    """
    from app.core.config import settings

    # Check if WhatsApp is enabled (templates only matter if WhatsApp is enabled)
    if not settings.whatsapp_access_token:
        logger.info("WhatsApp not configured - template check skipped")
        return {
            "templates_configured": [],
            "templates_missing": [],
            "whatsapp_enabled": False,
            "registry_valid": True,
        }

    # Validate template registry
    validation = validate_template_registry()
    templates_configured = validation["required_templates"]
    templates_missing = validation["missing_templates"]
    message_types_without_templates = validation["message_types_without_templates"]

    # Build status dict
    templates_status = {}
    for template_name in templates_configured:
        if template_name in templates_missing:
            templates_status[template_name] = "missing"
        else:
            templates_status[template_name] = "configured"

    logger.info(f"Template registry check: {len(templates_configured)} templates required")
    logger.info(f"Templates: {', '.join(templates_configured)}")

    if templates_missing:
        logger.error(
            f"CRITICAL: Missing {len(templates_missing)} required templates: "
            f"{', '.join(templates_missing)}"
        )
        logger.error(
            "These templates must be created in WhatsApp Manager and approved. "
            "Messages outside 24h window will be blocked until templates are configured."
        )

        # Notify artist if notifications enabled and artist number configured
        if settings.feature_notifications_enabled and settings.artist_whatsapp_number:
            try:
                import asyncio

                from app.services.artist_notifications import send_system_alert

                try:
                    asyncio.run(
                        send_system_alert(
                            message=(
                                f"⚠️ System Alert: {len(templates_missing)} WhatsApp templates are missing. "
                                f"Missing: {', '.join(templates_missing)}. "
                                "Messages outside 24h window will be blocked. "
                                "Please configure templates in WhatsApp Manager."
                            ),
                            dry_run=settings.whatsapp_dry_run,
                        )
                    )
                except Exception as e:
                    logger.error(f"Failed to send system alert about missing templates: {e}")
            except Exception as e:
                logger.error(f"Failed to send system alert about missing templates: {e}")

    if message_types_without_templates:
        logger.warning(
            f"Message types without templates: {', '.join(message_types_without_templates)}"
        )

    return {
        "templates_configured": [t for t in templates_configured if t not in templates_missing],
        "templates_missing": templates_missing,
        "templates_status": templates_status,
        "whatsapp_enabled": True,
        "registry_valid": validation["valid"],
        "message_types_without_templates": message_types_without_templates,
    }
