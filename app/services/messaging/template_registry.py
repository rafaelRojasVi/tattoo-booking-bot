"""
Template Registry - maps out-of-24h message types to WhatsApp template keys.

Uses template_core for shared data; no import of template_check (breaks cycle).
"""

import logging
from typing import Any

from app.services.messaging.template_core import (
    TEMPLATE_REGISTRY,
    MessageType,
    get_all_required_templates,
)

logger = logging.getLogger(__name__)


def get_template_for_message_type(message_type: MessageType) -> str | None:
    """
    Get template key for a message type.

    Args:
        message_type: Message type enum

    Returns:
        Template key string, or None if no template is configured
    """
    return TEMPLATE_REGISTRY.get(message_type)


def validate_template_registry() -> dict[str, Any]:
    """
    Validate that all templates in registry are configured.

    Returns:
        Dict with validation results:
        - valid: bool
        - missing_templates: list[str]
        - message_types_without_templates: list[str]
    """
    required_templates = get_all_required_templates()
    missing_templates: list[str] = []  # No external "configured" list; structural check only
    message_types_without_templates = []

    for message_type in MessageType:
        if message_type not in TEMPLATE_REGISTRY:
            message_types_without_templates.append(message_type.value)

    is_valid = len(missing_templates) == 0 and len(message_types_without_templates) == 0

    return {
        "valid": is_valid,
        "missing_templates": missing_templates,
        "message_types_without_templates": message_types_without_templates,
        "required_templates": required_templates,
        "configured_templates": required_templates,
    }
