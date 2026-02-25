"""
Estimation service - calculates project category and deposit amount based on dimensions, complexity, coverup, and placement.
"""

import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)

Category = Literal["SMALL", "MEDIUM", "LARGE", "XL"]


def parse_dimensions(dimensions_text: str) -> tuple[float, float] | None:
    """
    Parse dimensions from text (e.g., "8x12cm", "3x5 inches", "10×12cm").

    Normalizes unicode × to x before parsing.

    Args:
        dimensions_text: Text containing dimensions

    Returns:
        Tuple of (width, height) in cm, or None if can't parse
    """
    if not dimensions_text:
        return None

    from app.services.text_normalization import normalize_for_dimensions

    text = normalize_for_dimensions(dimensions_text).lower()

    # Try to find dimensions pattern: "WxH" or "W x H" with units
    # Patterns: "8x12cm", "3x5 inches", "10cm" (assume square)
    patterns = [
        r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*(cm|inch|inches|in)",
        r"(\d+(?:\.\d+)?)\s*(cm|inch|inches|in)",  # Single dimension (assume square)
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            if len(match.groups()) == 3:  # W x H with unit
                w = float(match.group(1))
                h = float(match.group(2))
                unit = match.group(3)
            else:  # Single dimension
                w = float(match.group(1))
                h = w  # Assume square
                unit = match.group(2)

            # Convert to cm
            if "inch" in unit or "in" in unit:
                w *= 2.54
                h *= 2.54

            # Sanity bounds: reject likely typos or wrong units (> 100 cm)
            if w > 100 or h > 100:
                return None

            return (w, h)

    return None


def parse_budget_from_text(text: str) -> int | None:
    """
    Parse budget amount from text. Accepts "400", "£400", "400gbp", "400k", etc.
    Returns amount in pence (GBP). Rejects negative, zero, and ambiguous ranges.

    Args:
        text: User message (e.g. "£400", "400", "400k", "500 dollars")

    Returns:
        Amount in pence, or None if no number / negative / zero / invalid.
    """
    if not text or not isinstance(text, str):
        return None
    from app.services.text_normalization import normalize_for_budget

    cleaned = normalize_for_budget(text).lower().replace(",", "")
    for sym in ["£", "$", "€"]:
        cleaned = cleaned.replace(sym, "")
    for word in ["gbp", "pounds", "pound", "usd", "dollars", "dollar", "eur", "euros", "euro"]:
        cleaned = cleaned.replace(word, "")
    cleaned = cleaned.strip()
    numbers = re.findall(r"\d+(?:\.\d+)?", cleaned)
    if not numbers:
        return None
    first_num = numbers[0]
    # Reject if the first number is preceded by minus (e.g. -400, £-400), not "400-500"
    first_pos = cleaned.find(first_num)
    if first_pos > 0:
        prefix = cleaned[:first_pos].strip()
        if prefix.endswith("-"):
            return None
    if cleaned.startswith("-"):
        return None
    value = float(first_num)
    if value <= 0:
        return None
    # k suffix: 400k → 400_000 GBP → 40_000_000 pence
    first_num_str = numbers[0]
    idx = cleaned.find(first_num_str)
    after = cleaned[idx + len(first_num_str) :].strip() if idx >= 0 else ""
    if after.startswith("k") or re.match(r"^\s*k\b", after):
        value *= 1000
    # Assume GBP (pence). If they said $/usd we still store as pence for UK client (1:1 for simplicity).
    return int(round(value * 100))


def calculate_area_cm2(dimensions: tuple[float, float] | None) -> float | None:
    """Calculate area in cm² from dimensions."""
    if not dimensions:
        return None
    return dimensions[0] * dimensions[1]


def estimate_category(
    dimensions: tuple[float, float] | None,
    complexity_level: int | None,
    is_coverup: bool = False,
    placement: str | None = None,
) -> Category:
    """
    Estimate project category based on dimensions, complexity, coverup, and placement.

    Args:
        dimensions: Tuple of (width, height) in cm
        complexity_level: 1-3 scale (1=simple, 2=medium, 3=high detail/realism)
        is_coverup: Whether this is a cover-up/rework
        placement: Body placement (hard placements can bump time)

    Returns:
        Estimated category: SMALL, MEDIUM, LARGE, or XL
    """
    area = calculate_area_cm2(dimensions) if dimensions else None

    # Hard placements that typically take longer
    hard_placements = {
        "ribs",
        "rib",
        "stomach",
        "stomach area",
        "side",
        "spine",
        "back",
        "full back",
        "full sleeve",
        "sleeve",
        "thigh",
        "thighs",
    }
    is_hard_placement = placement and any(hard in placement.lower() for hard in hard_placements)

    # Base category from area
    if area:
        if area < 50:  # < 50 cm²
            base_category = "SMALL"
        elif area < 150:  # 50-150 cm²
            base_category = "MEDIUM"
        elif area < 300:  # 150-300 cm²
            base_category = "LARGE"
        else:  # > 300 cm²
            base_category = "XL"
    # No dimensions - use complexity and other factors
    elif complexity_level == 3 or is_coverup:
        base_category = "LARGE"
    elif complexity_level == 2:
        base_category = "MEDIUM"
    else:
        base_category = "SMALL"

    # Bump category based on complexity, coverup, or hard placement
    if is_coverup:
        # Coverups are always at least MEDIUM
        if base_category == "SMALL":
            base_category = "MEDIUM"
        elif base_category == "MEDIUM":
            base_category = "LARGE"

    if complexity_level == 3:
        # High detail/realism can bump category
        if base_category == "SMALL":
            base_category = "MEDIUM"
        elif base_category == "MEDIUM":
            base_category = "LARGE"

    if is_hard_placement:
        # Hard placements can add time
        if base_category == "SMALL":
            base_category = "MEDIUM"
        elif base_category == "MEDIUM":
            base_category = "LARGE"

    # Ensure valid category
    if base_category not in ["SMALL", "MEDIUM", "LARGE", "XL"]:
        base_category = "MEDIUM"

    # Type assertion for mypy (runtime check ensures validity)
    category_upper = base_category.upper()
    if category_upper in ("SMALL", "MEDIUM", "LARGE", "XL"):
        return category_upper  # type: ignore[return-value]  # mypy doesn't understand runtime check
    return "MEDIUM"  # Default fallback


def estimate_days_for_xl(
    dimensions: tuple[float, float] | None,
    complexity_level: int | None,
    is_coverup: bool = False,
    placement: str | None = None,
) -> float:
    """
    Estimate number of days for XL projects based on area, complexity, coverup, and placement.

    Uses heuristic: base days from area, then adjusts for complexity/coverup/placement.
    Returns days in 0.5-day increments (e.g., 1.5, 2.0, 2.5).

    Args:
        dimensions: Tuple of (width, height) in cm
        complexity_level: 1-3 scale (1=simple, 2=medium, 3=high detail/realism)
        is_coverup: Whether this is a cover-up/rework
        placement: Body placement (hard placements can add time)

    Returns:
        Estimated days (in 0.5-day increments)
    """
    area = calculate_area_cm2(dimensions) if dimensions else None

    # Base days from area (for XL projects, typically > 300 cm²)
    if area:
        if area < 350:  # Small XL
            base_days = 1.5
        elif area < 500:  # Medium XL
            base_days = 2.0
        elif area < 700:  # Large XL
            base_days = 2.5
        else:  # Very large XL
            base_days = 3.0
    # No dimensions - use complexity/coverup as proxy
    elif complexity_level == 3 or is_coverup:
        base_days = 2.5
    elif complexity_level == 2:
        base_days = 2.0
    else:
        base_days = 1.5

    # Adjustments
    if is_coverup:
        base_days += 0.5  # Coverups typically take longer

    if complexity_level == 3:
        base_days += 0.5  # High detail/realism adds time

    # Hard placements can add time
    hard_placements = {
        "ribs",
        "rib",
        "stomach",
        "stomach area",
        "side",
        "spine",
        "back",
        "full back",
        "full sleeve",
        "sleeve",
        "thigh",
        "thighs",
    }
    is_hard_placement = placement and any(hard in placement.lower() for hard in hard_placements)
    if is_hard_placement:
        base_days += 0.5

    # Round to nearest 0.5-day increment
    # Multiply by 2, round, divide by 2
    rounded_days = round(base_days * 2) / 2.0

    # Ensure minimum 1.0 day and maximum 4.0 days (reasonable bounds)
    rounded_days = max(1.0, min(4.0, rounded_days))

    return rounded_days


def get_deposit_amount(category: Category, estimated_days: float | None = None) -> int:
    """
    Get deposit amount in pence for a category.

    For XL projects, deposit = £200 × estimated_days (with 0.5-day increments).
    For other categories, uses fixed amounts.

    Args:
        category: Project category
        estimated_days: Estimated days for XL projects (required if category is XL)

    Returns:
        Deposit amount in pence
    """
    # Fixed deposits for non-XL categories
    if category != "XL":
        deposits = {
            "SMALL": 15000,  # £150
            "MEDIUM": 15000,  # £150
            "LARGE": 20000,  # £200
        }
        return deposits.get(category, 15000)

    # XL: £200 per day (with 0.5-day increments)
    # Example: 1.5 days = £300, 2.0 days = £400
    if estimated_days is None:
        logger.warning(
            "XL category requires estimated_days for deposit calculation. "
            "Defaulting to 1.0 day (£200)."
        )
        estimated_days = 1.0

    # Calculate: £200 × days (in pence)
    # 20000 pence = £200
    deposit_pence = int(20000 * estimated_days)

    return deposit_pence


def estimate_project(
    dimensions_text: str | None,
    complexity_level: int | None,
    is_coverup: bool = False,
    placement: str | None = None,
) -> tuple[Category, int, float | None]:
    """
    Full estimation: category + deposit amount + estimated days.

    Args:
        dimensions_text: Dimensions as text (e.g., "8x12cm")
        complexity_level: 1-3 scale
        is_coverup: Whether cover-up/rework
        placement: Body placement

    Returns:
        Tuple of (category, deposit_amount_pence, estimated_days)
        estimated_days is None for non-XL categories, float for XL (e.g., 1.5, 2.0)
    """
    dimensions = parse_dimensions(dimensions_text) if dimensions_text else None
    category = estimate_category(dimensions, complexity_level, is_coverup, placement)

    # Calculate estimated days for XL projects
    estimated_days = None
    if category == "XL":
        estimated_days = estimate_days_for_xl(
            dimensions=dimensions,
            complexity_level=complexity_level,
            is_coverup=is_coverup,
            placement=placement,
        )

    # Calculate deposit (uses estimated_days for XL)
    deposit = get_deposit_amount(category, estimated_days=estimated_days)

    return category, deposit, estimated_days
