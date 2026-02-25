"""
Region service - handles country to region mapping and region-based pricing rules.
"""

from typing import Literal

RegionBucket = Literal["UK", "EUROPE", "ROW"]


def country_to_region(country: str) -> RegionBucket:
    """
    Map country name to region bucket.

    Args:
        country: Country name (case-insensitive)

    Returns:
        RegionBucket: UK, EUROPE, or ROW
    """
    country_upper = country.upper().strip()

    # UK countries
    uk_countries = {
        "UK",
        "UNITED KINGDOM",
        "ENGLAND",
        "SCOTLAND",
        "WALES",
        "NORTHERN IRELAND",
        "GB",
        "GBR",
        "GREAT BRITAIN",
    }
    if country_upper in uk_countries:
        return "UK"

    # Europe (EU + EEA + Switzerland)
    europe_countries = {
        "AUSTRIA",
        "BELGIUM",
        "BULGARIA",
        "CROATIA",
        "CYPRUS",
        "CZECH REPUBLIC",
        "DENMARK",
        "ESTONIA",
        "FINLAND",
        "FRANCE",
        "GERMANY",
        "GREECE",
        "HUNGARY",
        "IRELAND",
        "ITALY",
        "LATVIA",
        "LITHUANIA",
        "LUXEMBOURG",
        "MALTA",
        "NETHERLANDS",
        "POLAND",
        "PORTUGAL",
        "ROMANIA",
        "SLOVAKIA",
        "SLOVENIA",
        "SPAIN",
        "SWEDEN",
        "SWITZERLAND",
        "NORWAY",
        "ICELAND",
        "LIECHTENSTEIN",
        "EU",
        "EUROPE",
    }
    if country_upper in europe_countries:
        return "EUROPE"

    # Default to Rest of World
    return "ROW"


def region_min_budget(region: RegionBucket) -> int:
    """
    Get minimum budget amount in pence for a region.

    Args:
        region: Region bucket (UK, EUROPE, ROW)

    Returns:
        Minimum budget in pence
    """
    # UK: £400 = 40000 pence
    # Europe: £500 = 50000 pence
    # ROW: £600 = 60000 pence
    min_budgets = {
        "UK": 40000,
        "EUROPE": 50000,
        "ROW": 60000,
    }
    return min_budgets.get(region, 60000)


def region_hourly_rate(region: RegionBucket) -> int:
    """
    Get hourly rate in pence for a region (internal use only).

    Args:
        region: Region bucket (UK, EUROPE, ROW)

    Returns:
        Hourly rate in pence
    """
    # UK: £130/h = 13000 pence
    # Europe: £140/h = 14000 pence
    # ROW: £150/h = 15000 pence
    hourly_rates = {
        "UK": 13000,
        "EUROPE": 14000,
        "ROW": 15000,
    }
    return hourly_rates.get(region, 15000)
