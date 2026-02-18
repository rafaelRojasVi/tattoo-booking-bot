"""
Voice pack service - applies tone, phrasing, and boundaries to outgoing messages.

Only applies to free-form messages (not templates).
"""

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import yaml

logger = logging.getLogger(__name__)

# Default voice pack path
VOICE_PACK_PATH = Path(__file__).parent.parent / "config" / "voice_pack.yml"

# In-memory cache for voice pack
_voice_pack_cache: dict[str, Any] | None = None


@lru_cache(maxsize=1)
def load_voice_pack() -> dict[str, Any]:
    """
    Load voice pack configuration from YAML file.
    Cached for performance.

    Returns:
        Dict with voice pack configuration
    """
    global _voice_pack_cache

    if _voice_pack_cache is not None:
        return _voice_pack_cache

    try:
        if VOICE_PACK_PATH.exists():
            with open(VOICE_PACK_PATH, encoding="utf-8") as f:
                _voice_pack_cache = yaml.safe_load(f) or {}
                logger.info(f"Loaded voice pack from {VOICE_PACK_PATH}")
        else:
            logger.warning(f"Voice pack file not found at {VOICE_PACK_PATH}, using defaults")
            _voice_pack_cache = {}
    except Exception as e:
        logger.error(f"Failed to load voice pack: {e}, using defaults")
        _voice_pack_cache = {}

    return _voice_pack_cache


def apply_voice(text: str, is_template: bool = False) -> str:
    """
    Apply voice pack rules to a message.

    Only applies to free-form messages (not templates).

    Args:
        text: Message text to transform
        is_template: Whether this is a template message (skip transformation)

    Returns:
        Transformed message text
    """
    if is_template:
        # Don't modify templates
        return text

    if not text:
        return text

    pack = load_voice_pack()
    if not pack:
        # No voice pack configured, return as-is
        return text

    result = text

    # Apply spelling replacements (UK English)
    if "spelling" in pack and "replacements" in pack["spelling"]:
        for us_spelling, uk_spelling in pack["spelling"]["replacements"].items():
            # Case-insensitive replacement
            result = re.sub(re.escape(us_spelling), uk_spelling, result, flags=re.IGNORECASE)

    # Replace banned phrases
    if "banned_phrases" in pack and "phrase_replacements" in pack:
        replacements = pack.get("phrase_replacements", {})
        for banned, replacement in replacements.items():
            # Case-insensitive replacement
            result = re.sub(re.escape(banned), replacement, result, flags=re.IGNORECASE)

    # Apply preferred terms
    if "preferred_terms" in pack:
        for old_term, new_term in pack["preferred_terms"].items():
            # Case-insensitive replacement
            result = re.sub(re.escape(old_term), new_term, result, flags=re.IGNORECASE)

    # Limit emojis (if enabled)
    if "emoji" in pack and pack["emoji"].get("enabled", True):
        max_emojis = pack["emoji"].get("max_per_message", 3)
        # Count emojis (simple Unicode emoji detection)
        emoji_pattern = re.compile(
            r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U000024C2-\U0001F251]+",
            flags=re.UNICODE,
        )
        emojis = emoji_pattern.findall(result)
        if len(emojis) > max_emojis:
            # Remove excess emojis (keep first max_emojis)
            emoji_count = 0
            new_result = ""
            for char in result:
                if emoji_pattern.match(char):
                    if emoji_count < max_emojis:
                        new_result += char
                        emoji_count += 1
                    # Skip excess emojis
                else:
                    new_result += char
            result = new_result

    # Remove banned emojis
    if "emoji" in pack and "banned" in pack["emoji"]:
        banned_emojis = pack["emoji"]["banned"]
        for emoji in banned_emojis:
            result = result.replace(emoji, "")

    return result.strip()


def get_call_preference_text() -> str:
    """
    Get the preferred call preference text from voice pack.

    Returns:
        Call preference text (e.g., "quick call")
    """
    pack = load_voice_pack()
    if "call_preference" in pack and "preferred" in pack["call_preference"]:
        return cast(str, pack["call_preference"]["preferred"])
    return "quick call"


def should_apply_voice() -> bool:
    """
    Check if voice pack should be applied (i.e., if it's configured).

    Returns:
        True if voice pack is configured and should be used
    """
    pack = load_voice_pack()
    return bool(pack)
