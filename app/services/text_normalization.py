"""
Text normalization for parsing — strip, collapse spaces, normalize unicode.

Use before parsing user input (budget, dimensions, slot, etc.) to handle
WhatsApp copy/paste: non-breaking spaces, zero-width chars, smart quotes.
"""

import re
import unicodedata

# Common unicode replacements
NBSP = "\u00A0"
ZWSP = "\u200B"
ZWNBSP = "\uFEFF"
# Multiplication sign (× U+00D7) → ASCII x for dimension parsing
MULT_SIGN = "\u00D7"


def normalize_text(text: str | None) -> str:
    """
    Normalize user input for parsing: strip, collapse spaces, fix common unicode.

    Args:
        text: Raw user message (or None)

    Returns:
        Normalized string (empty string if input is None/empty)
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        return ""
    s = text.strip()
    # Replace non-breaking space and other common space-like chars with normal space
    s = s.replace(NBSP, " ")
    s = s.replace(ZWSP, "")
    s = s.replace(ZWNBSP, "")
    # Normalize unicode (NFC) so composed chars are consistent
    s = unicodedata.normalize("NFC", s)
    # Collapse multiple spaces
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def normalize_for_dimensions(text: str | None) -> str:
    """
    Normalize for dimension parsing: normalize_text + replace × with x.

    Args:
        text: Raw dimensions input

    Returns:
        Normalized string (× and × U+00D7 become ASCII x)
    """
    s = normalize_text(text)
    s = s.replace(MULT_SIGN, "x")
    s = s.replace("×", "x")  # same char, different way to write
    return s


def normalize_for_budget(text: str | None) -> str:
    """
    Normalize for budget parsing: normalize_text (commas handled in parser).

    Args:
        text: Raw budget input

    Returns:
        Normalized string
    """
    return normalize_text(text)
