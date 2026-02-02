"""
Tests for pricing service - price range calculations.

Tests all region/category combinations to ensure correct price calculations.
"""

from app.services.estimation_service import Category
from app.services.pricing_service import (
    PriceRange,
    calculate_price_range,
    get_category_time_range,
)
from app.services.region_service import RegionBucket


def test_get_category_time_range_small():
    """Test time range for SMALL category."""
    min_hours, max_hours = get_category_time_range("SMALL")
    assert min_hours == 4.0
    assert max_hours == 5.0


def test_get_category_time_range_medium():
    """Test time range for MEDIUM category."""
    min_hours, max_hours = get_category_time_range("MEDIUM")
    assert min_hours == 5.0
    assert max_hours == 7.0


def test_get_category_time_range_large():
    """Test time range for LARGE category."""
    min_hours, max_hours = get_category_time_range("LARGE")
    assert min_hours == 7.5
    assert max_hours == 10.0


def test_get_category_time_range_xl():
    """Test time range for XL category."""
    min_hours, max_hours = get_category_time_range("XL")
    assert min_hours == 9.5
    assert max_hours == 11.0


def test_get_category_time_range_unknown_defaults_to_medium():
    """Test that unknown category defaults to MEDIUM time range."""
    min_hours, max_hours = get_category_time_range("UNKNOWN")  # type: ignore
    assert min_hours == 5.0
    assert max_hours == 7.0


# UK Tests
def test_calculate_price_range_uk_small():
    """Test price range calculation for UK + SMALL."""
    result = calculate_price_range(region="UK", category="SMALL")

    assert result.region == "UK"
    assert result.category == "SMALL"
    assert result.hourly_rate_pence == 13000  # £130/h
    assert result.min_hours == 4.0
    assert result.max_hours == 5.0
    assert result.min_pence == 52000  # 4h × £130 = £520
    assert result.max_pence == 65000  # 5h × £130 = £650
    assert result.trace is not None
    assert len(result.trace) > 0
    assert result.trace["region"] == "UK"
    assert result.trace["category"] == "SMALL"


def test_calculate_price_range_uk_medium():
    """Test price range calculation for UK + MEDIUM."""
    result = calculate_price_range(region="UK", category="MEDIUM")

    assert result.region == "UK"
    assert result.category == "MEDIUM"
    assert result.hourly_rate_pence == 13000
    assert result.min_hours == 5.0
    assert result.max_hours == 7.0
    assert result.min_pence == 65000  # 5h × £130 = £650
    assert result.max_pence == 91000  # 7h × £130 = £910


def test_calculate_price_range_uk_large():
    """Test price range calculation for UK + LARGE."""
    result = calculate_price_range(region="UK", category="LARGE")

    assert result.region == "UK"
    assert result.category == "LARGE"
    assert result.hourly_rate_pence == 13000
    assert result.min_hours == 7.5
    assert result.max_hours == 10.0
    assert result.min_pence == 97500  # 7.5h × £130 = £975
    assert result.max_pence == 130000  # 10h × £130 = £1300


def test_calculate_price_range_uk_xl():
    """Test price range calculation for UK + XL."""
    result = calculate_price_range(region="UK", category="XL")

    assert result.region == "UK"
    assert result.category == "XL"
    assert result.hourly_rate_pence == 13000
    assert result.min_hours == 9.5
    assert result.max_hours == 11.0
    assert result.min_pence == 123500  # 9.5h × £130 = £1235
    assert result.max_pence == 143000  # 11h × £130 = £1430


# EUROPE Tests
def test_calculate_price_range_europe_small():
    """Test price range calculation for EUROPE + SMALL."""
    result = calculate_price_range(region="EUROPE", category="SMALL")

    assert result.region == "EUROPE"
    assert result.category == "SMALL"
    assert result.hourly_rate_pence == 14000  # £140/h
    assert result.min_hours == 4.0
    assert result.max_hours == 5.0
    assert result.min_pence == 56000  # 4h × £140 = £560
    assert result.max_pence == 70000  # 5h × £140 = £700


def test_calculate_price_range_europe_medium():
    """Test price range calculation for EUROPE + MEDIUM."""
    result = calculate_price_range(region="EUROPE", category="MEDIUM")

    assert result.region == "EUROPE"
    assert result.category == "MEDIUM"
    assert result.hourly_rate_pence == 14000
    assert result.min_hours == 5.0
    assert result.max_hours == 7.0
    assert result.min_pence == 70000  # 5h × £140 = £700
    assert result.max_pence == 98000  # 7h × £140 = £980


def test_calculate_price_range_europe_large():
    """Test price range calculation for EUROPE + LARGE."""
    result = calculate_price_range(region="EUROPE", category="LARGE")

    assert result.region == "EUROPE"
    assert result.category == "LARGE"
    assert result.hourly_rate_pence == 14000
    assert result.min_hours == 7.5
    assert result.max_hours == 10.0
    assert result.min_pence == 105000  # 7.5h × £140 = £1050
    assert result.max_pence == 140000  # 10h × £140 = £1400


def test_calculate_price_range_europe_xl():
    """Test price range calculation for EUROPE + XL."""
    result = calculate_price_range(region="EUROPE", category="XL")

    assert result.region == "EUROPE"
    assert result.category == "XL"
    assert result.hourly_rate_pence == 14000
    assert result.min_hours == 9.5
    assert result.max_hours == 11.0
    assert result.min_pence == 133000  # 9.5h × £140 = £1330
    assert result.max_pence == 154000  # 11h × £140 = £1540


# ROW Tests
def test_calculate_price_range_row_small():
    """Test price range calculation for ROW + SMALL."""
    result = calculate_price_range(region="ROW", category="SMALL")

    assert result.region == "ROW"
    assert result.category == "SMALL"
    assert result.hourly_rate_pence == 15000  # £150/h
    assert result.min_hours == 4.0
    assert result.max_hours == 5.0
    assert result.min_pence == 60000  # 4h × £150 = £600
    assert result.max_pence == 75000  # 5h × £150 = £750


def test_calculate_price_range_row_medium():
    """Test price range calculation for ROW + MEDIUM."""
    result = calculate_price_range(region="ROW", category="MEDIUM")

    assert result.region == "ROW"
    assert result.category == "MEDIUM"
    assert result.hourly_rate_pence == 15000
    assert result.min_hours == 5.0
    assert result.max_hours == 7.0
    assert result.min_pence == 75000  # 5h × £150 = £750
    assert result.max_pence == 105000  # 7h × £150 = £1050


def test_calculate_price_range_row_large():
    """Test price range calculation for ROW + LARGE."""
    result = calculate_price_range(region="ROW", category="LARGE")

    assert result.region == "ROW"
    assert result.category == "LARGE"
    assert result.hourly_rate_pence == 15000
    assert result.min_hours == 7.5
    assert result.max_hours == 10.0
    assert result.min_pence == 112500  # 7.5h × £150 = £1125
    assert result.max_pence == 150000  # 10h × £150 = £1500


def test_calculate_price_range_row_xl():
    """Test price range calculation for ROW + XL."""
    result = calculate_price_range(region="ROW", category="XL")

    assert result.region == "ROW"
    assert result.category == "XL"
    assert result.hourly_rate_pence == 15000
    assert result.min_hours == 9.5
    assert result.max_hours == 11.0
    assert result.min_pence == 142500  # 9.5h × £150 = £1425
    assert result.max_pence == 165000  # 11h × £150 = £1650


# Trace tests
def test_calculate_price_range_includes_trace():
    """Test that price range calculation includes trace information."""
    result = calculate_price_range(region="UK", category="SMALL", include_trace=True)

    assert result.trace is not None
    assert result.trace["category"] == "SMALL"
    assert result.trace["region"] == "UK"
    assert result.trace["hourly_rate_pence"] == 13000
    assert result.trace["hourly_rate_gbp"] == 130.0
    assert result.trace["min_hours"] == 4.0
    assert result.trace["max_hours"] == 5.0
    assert "calculation" in result.trace
    assert "min_price" in result.trace["calculation"]
    assert "max_price" in result.trace["calculation"]


def test_calculate_price_range_no_trace():
    """Test that trace can be disabled."""
    result = calculate_price_range(region="UK", category="SMALL", include_trace=False)

    assert result.trace == {}


# Edge cases
def test_calculate_price_range_all_combinations():
    """Test all region/category combinations produce valid results."""
    regions: list[RegionBucket] = ["UK", "EUROPE", "ROW"]
    categories: list[Category] = ["SMALL", "MEDIUM", "LARGE", "XL"]

    for region in regions:
        for category in categories:
            result = calculate_price_range(region=region, category=category)

            # Verify basic structure
            assert isinstance(result, PriceRange)
            assert result.min_pence > 0
            assert result.max_pence > 0
            assert result.max_pence >= result.min_pence
            assert result.min_hours > 0
            assert result.max_hours > 0
            assert result.max_hours >= result.min_hours
            assert result.hourly_rate_pence > 0
            assert result.region == region
            assert result.category == category


def test_price_range_trace_calculation_format():
    """Test that trace calculation strings are properly formatted."""
    result = calculate_price_range(region="UK", category="SMALL", include_trace=True)

    calc = result.trace["calculation"]
    assert "4.0h" in calc["min_price"]
    assert "£130.00" in calc["min_price"] or "£130" in calc["min_price"]
    assert "£520" in calc["min_price"] or "520.00" in calc["min_price"]

    assert "5.0h" in calc["max_price"]
    assert "£130.00" in calc["max_price"] or "£130" in calc["max_price"]
    assert "£650" in calc["max_price"] or "650.00" in calc["max_price"]
