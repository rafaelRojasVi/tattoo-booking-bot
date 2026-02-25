"""
Pricing service - computes internal estimated price ranges.

This service calculates price estimates based on:
- Category time ranges (Small 4-5h, Medium 5-7h, Large 7.5-10h, XL 9.5-11h per day)
- Regional hourly rates (UK £130/h, EU £140/h, ROW £150/h)

IMPORTANT: These estimates are for INTERNAL USE ONLY and should NOT be shown to clients.
Price ranges are stored in the Lead model for admin/artist visibility only.
"""

import logging
from dataclasses import dataclass

from app.services.parsing.estimation_service import Category
from app.services.parsing.region_service import RegionBucket, region_hourly_rate

logger = logging.getLogger(__name__)


@dataclass
class PriceRange:
    """Price range estimate with trace information."""

    min_pence: int  # Minimum price in pence
    max_pence: int  # Maximum price in pence
    min_hours: float  # Minimum billable hours
    max_hours: float  # Maximum billable hours
    hourly_rate_pence: int  # Hourly rate used (in pence)
    region: RegionBucket  # Region bucket
    category: Category  # Project category
    trace: dict  # Calculation trace for debugging


def get_category_time_range(category: Category) -> tuple[float, float]:
    """
    Get billable time range (min, max hours) for a category.

    Args:
        category: Project category (SMALL, MEDIUM, LARGE, XL)

    Returns:
        Tuple of (min_hours, max_hours)
    """
    # Spec: Billable time ranges per category (tattoo + design time)
    time_ranges = {
        "SMALL": (4.0, 5.0),  # 4-5 hours
        "MEDIUM": (5.0, 7.0),  # 5-7 hours
        "LARGE": (7.5, 10.0),  # 7.5-10 hours
        "XL": (9.5, 11.0),  # 9.5-11 hours per day
    }
    return time_ranges.get(category, (5.0, 7.0))  # Default to MEDIUM if unknown


def calculate_price_range(
    region: RegionBucket,
    category: Category,
    include_trace: bool = True,
) -> PriceRange:
    """
    Calculate estimated price range for a project.

    Formula: price = billable_time × hourly_rate
    Returns min and max prices based on time range × hourly rate.

    Args:
        region: Region bucket (UK, EUROPE, ROW)
        category: Project category (SMALL, MEDIUM, LARGE, XL)
        include_trace: Whether to include calculation trace

    Returns:
        PriceRange object with min/max prices in pence and trace info
    """
    # Get hourly rate for region
    hourly_rate_pence = region_hourly_rate(region)

    # Get time range for category
    min_hours, max_hours = get_category_time_range(category)

    # Calculate price range: time × hourly_rate
    min_price_pence = int(min_hours * hourly_rate_pence)
    max_price_pence = int(max_hours * hourly_rate_pence)

    # Build trace information
    trace = {}
    if include_trace:
        trace = {
            "category": category,
            "region": region,
            "hourly_rate_pence": hourly_rate_pence,
            "hourly_rate_gbp": hourly_rate_pence / 100,
            "min_hours": min_hours,
            "max_hours": max_hours,
            "calculation": {
                "min_price": f"{min_hours}h × £{hourly_rate_pence / 100:.2f}/h = £{min_price_pence / 100:.2f}",
                "max_price": f"{max_hours}h × £{hourly_rate_pence / 100:.2f}/h = £{max_price_pence / 100:.2f}",
            },
        }

    return PriceRange(
        min_pence=min_price_pence,
        max_pence=max_price_pence,
        min_hours=min_hours,
        max_hours=max_hours,
        hourly_rate_pence=hourly_rate_pence,
        region=region,
        category=category,
        trace=trace,
    )


def estimate_price_range_for_lead(
    region: RegionBucket | None,
    category: Category | None,
    include_trace: bool = True,
) -> PriceRange | None:
    """
    Estimate price range for a lead (convenience function).

    Args:
        region: Region bucket (from lead.region_bucket)
        category: Project category (from lead.estimated_category)
        include_trace: Whether to include calculation trace

    Returns:
        PriceRange object, or None if region or category is missing
    """
    if not region or not category:
        logger.debug(f"Cannot calculate price range: region={region}, category={category}")
        return None

    return calculate_price_range(region=region, category=category, include_trace=include_trace)
