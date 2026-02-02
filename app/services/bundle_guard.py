"""
Bundle guard - detects when user sends multiple answers in one message.

Used to reprompt "one at a time" and avoid advancing the step.
"""

import re

# Style keywords (from consultation questions; include UK/US spellings)
_STYLE_KEYWORDS = [
    "realism",
    "fine line",
    "traditional",
    "watercolour",
    "watercolor",
    "geometric",
]


def looks_like_multi_answer_bundle(text: str) -> bool:
    """
    Heuristic: return True if 2+ of these signals exist:
    (a) dimension pattern r"\\d+\\s*[x×]\\s*\\d+" OR contains "cm" OR "inch"
    (b) parse_budget_from_text(text) returns not None
    (c) style keyword present (realism, fine line, traditional, watercolour, geometric, etc.)
    (d) instagram handle "@"

    Args:
        text: User message text

    Returns:
        True if message looks like a multi-answer bundle (2+ signals)
    """
    if not text or not text.strip():
        return False

    t = text.strip().lower()
    signals = 0

    # (a) dimension pattern or cm/inch
    if re.search(r"\d+\s*[x×]\s*\d+", t, re.IGNORECASE) or "cm" in t or "inch" in t:
        signals += 1

    # (b) budget parse
    from app.services.estimation_service import parse_budget_from_text

    if parse_budget_from_text(text) is not None:
        signals += 1

    # (c) style keyword
    if any(kw in t for kw in _STYLE_KEYWORDS):
        signals += 1

    # (d) instagram handle
    if "@" in text:
        signals += 1

    return signals >= 2
