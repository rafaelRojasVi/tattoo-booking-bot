"""
Message composer service - loads copy from YAML and selects variants deterministically.

Uses lead_id to deterministically select a variant (same lead always gets same variant).
Supports intent-based compose_message(intent, ctx) with optional apply_voice and retry_count.
"""

import hashlib
import logging
from pathlib import Path
from typing import Any, cast

import yaml

logger = logging.getLogger(__name__)

# Intent -> YAML key mapping (single place to apply artist style)
INTENT_TO_KEY = {
    "ASK_QUESTION": "ask_question",
    "WELCOME": "welcome",
    "OPT_OUT": "opt_out_confirmation",
    "REPAIR_SIZE": "repair_size",
    "REPAIR_BUDGET": "repair_budget",
    "REPAIR_LOCATION": "repair_location",
    "REPAIR_SLOT": "repair_slot",
    "ATTACHMENT_ACK_REPROMPT": "attachment_ack_reprompt",
    "ONE_AT_A_TIME_REPROMPT": "one_at_a_time_reprompt",
    "REFUND_ACK": "refund_ack",
    "DELETE_DATA_ACK": "delete_data_ack",
    "HUMAN_HANDOVER": "handover_client_question",  # reuse handover copy
}

# Path to copy files
COPY_DIR = Path(__file__).resolve().parent.parent.parent / "copy"
DEFAULT_LOCALE = "en_GB"


class MessageComposer:
    """Composes messages from YAML copy files with deterministic variant selection."""

    def __init__(self, locale: str = DEFAULT_LOCALE):
        """
        Initialize message composer.

        Args:
            locale: Locale code (e.g., "en_GB")
        """
        self.locale = locale
        self.copy_file = COPY_DIR / f"{locale}.yml"
        self._copy_data: dict[str, Any] = {}
        self._load_copy()

    def _load_copy(self) -> None:
        """Load copy from YAML file."""
        if not self.copy_file.exists():
            logger.warning(f"Copy file not found: {self.copy_file}, using empty copy")
            self._copy_data = {}
            return

        try:
            with open(self.copy_file, encoding="utf-8") as f:
                self._copy_data = yaml.safe_load(f) or {}
            logger.info(f"Loaded copy from {self.copy_file}")
        except Exception as e:
            logger.error(f"Failed to load copy from {self.copy_file}: {e}")
            self._copy_data = {}

    def _select_variant(self, key: str, lead_id: int | None = None) -> str:
        """
        Select a variant deterministically based on lead_id.

        Args:
            key: Message key
            lead_id: Lead ID for deterministic selection (None = random)

        Returns:
            Selected variant text
        """
        if key not in self._copy_data:
            logger.warning(f"Message key not found: {key}")
            return f"[MISSING: {key}]"

        variants = self._copy_data[key]
        if not isinstance(variants, list):
            # Single variant (not a list) - could be string or dict
            if isinstance(variants, str):
                return variants
            return str(variants)

        if not variants:
            logger.warning(f"No variants found for key: {key}")
            return ""

        # Deterministic selection based on lead_id
        if lead_id is not None:
            # Hash lead_id to get consistent variant index
            hash_value = int(hashlib.md5(f"{key}:{lead_id}".encode()).hexdigest(), 16)
            variant_index = hash_value % len(variants)
        else:
            # No lead_id - use first variant as default
            variant_index = 0

        return cast(str, variants[variant_index])

    def render(
        self,
        key: str,
        lead_id: int | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Render a message from copy.

        Args:
            key: Message key in YAML
            lead_id: Lead ID for deterministic variant selection
            **kwargs: Template variables to substitute

        Returns:
            Rendered message string

        Example:
            composer.render("welcome", lead_id=123, question_text="What tattoo do you want?")
        """
        template = self._select_variant(key, lead_id)

        # Simple template substitution: {variable_name}
        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.warning(f"Missing template variable {e} for key {key}")
            return template
        except Exception as e:
            logger.error(f"Failed to render message {key}: {e}")
            return template


# Global instance (reset in tests so temp COPY_DIR doesn't leak)
_composer: MessageComposer | None = None


def reset_cache() -> None:
    """Clear the global composer cache. Use in tests so real app copy is loaded after patching COPY_DIR."""
    global _composer
    _composer = None


def get_composer(locale: str = DEFAULT_LOCALE) -> MessageComposer:
    """
    Get global message composer instance.

    Args:
        locale: Locale code

    Returns:
        MessageComposer instance
    """
    global _composer
    if _composer is None or _composer.locale != locale:
        _composer = MessageComposer(locale=locale)
    return _composer


def render_message(
    key: str,
    lead_id: int | None = None,
    locale: str = DEFAULT_LOCALE,
    **kwargs: Any,
) -> str:
    """
    Convenience function to render a message.

    Args:
        key: Message key in YAML
        lead_id: Lead ID for deterministic variant selection
        locale: Locale code
        **kwargs: Template variables

    Returns:
        Rendered message string
    """
    composer = get_composer(locale)
    return composer.render(key, lead_id=lead_id, **kwargs)


def compose_message(
    intent: str,
    ctx: dict[str, Any],
    *,
    locale: str = DEFAULT_LOCALE,
    apply_voice_to_result: bool = True,
) -> str:
    """
    Compose a message by intent with context. Maps intent to YAML key, optionally
    selects retry-aware variant (for REPAIR_*), renders, and applies voice pack.

    Args:
        intent: One of INTENT_TO_KEY keys (e.g. ASK_QUESTION, OPT_OUT, REPAIR_BUDGET).
        ctx: Context dict; must include lead_id for variant selection and any
             template variables (e.g. question_text, retry_count, min_gbp).
        locale: Locale code.
        apply_voice_to_result: If True, run result through tone.apply_voice (for free-form only).

    Returns:
        Rendered message string (voice pack applied when apply_voice_to_result=True).
    """
    key = INTENT_TO_KEY.get(intent)
    if not key:
        logger.warning(f"Unknown intent {intent}, falling back to render with key={intent}")
        key = intent

    composer = get_composer(locale)
    lead_id = ctx.get("lead_id")

    # Retry-aware variant: retry 1 = gentle (index 0), retry 2 = short+example+boundary (index 1), retry 3 = handover
    retry_count = ctx.get("retry_count", 0)
    ctx_render = {k: v for k, v in ctx.items() if k not in ("lead_id", "retry_count")}
    if intent.startswith("REPAIR_") and retry_count >= 1 and key in composer._copy_data:
        variants = composer._copy_data.get(key)
        if isinstance(variants, list) and len(variants) > 1:
            idx = min(max(0, retry_count - 1), len(variants) - 1)
            template = variants[idx]
            try:
                result = template.format(**ctx_render) if ctx_render else template
            except KeyError:
                result = composer.render(key, lead_id=lead_id, **ctx_render)
        else:
            result = composer.render(key, lead_id=lead_id, **ctx_render)
    else:
        result = composer.render(key, lead_id=lead_id, **ctx_render)

    if apply_voice_to_result and result:
        try:
            from app.services.tone import apply_voice

            result = apply_voice(result, is_template=False)
        except Exception as e:
            logger.debug(f"Voice pack not applied: {e}")

    return cast(str, result)
