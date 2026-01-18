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
    Parse dimensions from text (e.g., "8x12cm", "3x5 inches", "10cm").

    Args:
        dimensions_text: Text containing dimensions

    Returns:
        Tuple of (width, height) in cm, or None if can't parse
    """
    if not dimensions_text:
        return None

    text = dimensions_text.lower().strip()

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

            return (w, h)

    return None


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


def get_deposit_amount(category: Category) -> int:
    """
    Get deposit amount in pence for a category (universal deposits).

    Args:
        category: Project category

    Returns:
        Deposit amount in pence
    """
    # Universal deposits (Phase 1)
    # Small: £150 = 15000 pence
    # Medium: £150 = 15000 pence
    # Large: £200 = 20000 pence
    # XL: £200 per full day (Phase 1: use £200, booking is manual)
    deposits = {
        "SMALL": 15000,
        "MEDIUM": 15000,
        "LARGE": 20000,
        "XL": 20000,  # Phase 1: simplified
    }
    return deposits.get(category, 15000)


def estimate_project(
    dimensions_text: str | None,
    complexity_level: int | None,
    is_coverup: bool = False,
    placement: str | None = None,
) -> tuple[Category, int]:
    """
    Full estimation: category + deposit amount.

    Args:
        dimensions_text: Dimensions as text (e.g., "8x12cm")
        complexity_level: 1-3 scale
        is_coverup: Whether cover-up/rework
        placement: Body placement

    Returns:
        Tuple of (category, deposit_amount_pence)
    """
    dimensions = parse_dimensions(dimensions_text) if dimensions_text else None
    category = estimate_category(dimensions, complexity_level, is_coverup, placement)
    deposit = get_deposit_amount(category)

    return category, deposit
