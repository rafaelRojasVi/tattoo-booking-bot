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

# Budget intent: currency symbols or budget keywords (avoid false positive on "2" or "10" from dimensions)
_BUDGET_KEYWORDS = ("budget", "gbp", "pound", "dollar", "€", "$", "£")
_MIN_BUDGET_PENCE = 5000  # £50 — numbers below are likely quantity/complexity, not budget


def looks_like_multi_answer_bundle(
    text: str,
    *,
    current_question_key: str | None = None,
) -> bool:
    """
    Heuristic: return True if 2+ of these signals exist:
    (a) dimension pattern r"\\d+\\s*[x×]\\s*\\d+" OR word-boundary cm/inch
    (b) budget intent: parse_budget returns not None AND (currency/budget keyword OR >= £50)
    (c) style keyword present (realism, fine line, traditional, watercolour, geometric, etc.)
    (d) instagram handle "@" — at reference_images/instagram_handle, @+style counts as 1 signal

    Budget is NOT counted when text parses as dimensions (avoids "10x15" double-count).
    Small numbers (< £50) require currency/budget keywords to avoid "2 dragons" false positive.

    Args:
        text: User message text
        current_question_key: Optional question key for step-aware logic (reference_images, instagram_handle)

    Returns:
        True if message looks like a multi-answer bundle (2+ signals)
    """
    if not text or not text.strip():
        return False

    t = text.strip().lower()
    signals = 0

    # (a) dimension: use parse_dimensions when possible; else dimension pattern with word-boundary cm/inch
    from app.services.estimation_service import parse_dimensions, parse_budget_from_text

    has_dimension = parse_dimensions(text) is not None
    if not has_dimension:
        has_dimension = bool(
            re.search(r"\d+\s*[x×]\s*\d+", t, re.IGNORECASE)
            or re.search(r"\bcm\b", t)
            or re.search(r"\binch(?:es)?\b", t)
        )
    if has_dimension:
        signals += 1

    # (b) budget: only count when budget intent exists (not dimension spillover, not small quantity)
    budget_pence = parse_budget_from_text(text)
    has_budget_keyword = any(kw in t for kw in _BUDGET_KEYWORDS)
    if budget_pence is None:
        pass
    elif has_dimension and not has_budget_keyword:
        # Dimension string without explicit budget — don't count (e.g. "10x15" parses 10)
        pass
    elif has_budget_keyword or budget_pence >= _MIN_BUDGET_PENCE:
        signals += 1

    # (c) style keyword
    has_style = any(kw in t for kw in _STYLE_KEYWORDS)
    has_at = "@" in text

    # (d) instagram handle — at reference_images/instagram_handle, @+style is one coherent answer
    if current_question_key in ("reference_images", "instagram_handle"):
        if has_at or has_style:
            signals += 1  # Combined: "@handle realism" or "Realism like @artist" = 1 signal
    else:
        if has_style:
            signals += 1
        if has_at:
            signals += 1

    return signals >= 2


def looks_like_wrong_field_single_answer(
    text: str,
    current_question_key: str,
) -> bool:
    """
    At idea/placement steps: detect budget-only or dimensions-only (wrong field).

    If message is mostly numeric/currency/dimensions with very low alphabetic content,
    reprompt the current question and do not advance.

    Returns True when at idea or placement and message clearly answers a different question.
    """
    if current_question_key not in ("idea", "placement"):
        return False
    if not text or not text.strip():
        return False

    from app.services.estimation_service import parse_budget_from_text, parse_dimensions

    t = text.strip()
    alpha_chars = sum(1 for c in t if c.isalpha())
    total_non_space = sum(1 for c in t if not c.isspace())
    if total_non_space == 0:
        return False
    alpha_ratio = alpha_chars / total_non_space

    # Budget-only: parses as budget, very low alphabetic (< 30%)
    budget_parsed = parse_budget_from_text(text) is not None
    if budget_parsed and alpha_ratio < 0.3:
        return True

    # Dimensions-only: parses as dimensions or dimension pattern, very low alphabetic
    dim_parsed = parse_dimensions(text) is not None
    if not dim_parsed:
        dim_parsed = bool(
            re.search(r"\d+\s*[x×]\s*\d+", t.lower(), re.IGNORECASE)
            or re.search(r"\bcm\b", t.lower())
            or re.search(r"\binch(?:es)?\b", t.lower())
        )
    if dim_parsed and alpha_ratio < 0.5:  # "10x15cm" has x,cm — allow slightly higher
        return True

    return False
