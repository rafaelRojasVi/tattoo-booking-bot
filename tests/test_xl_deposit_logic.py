"""
Tests for XL deposit logic - per-day calculation with 0.5-day increments.

Tests that XL deposits are calculated as £200 × estimated_days.
"""

from app.services.estimation_service import (
    estimate_days_for_xl,
    estimate_project,
    get_deposit_amount,
)


def test_xl_deposit_1_5_days_equals_300():
    """Test that 1.5 days = £300 deposit (20000 pence × 1.5 = 30000 pence)."""
    deposit = get_deposit_amount(category="XL", estimated_days=1.5)
    assert deposit == 30000  # £300 in pence
    assert deposit / 100 == 300.0  # Verify in GBP


def test_xl_deposit_2_0_days_equals_400():
    """Test that 2.0 days = £400 deposit (20000 pence × 2.0 = 40000 pence)."""
    deposit = get_deposit_amount(category="XL", estimated_days=2.0)
    assert deposit == 40000  # £400 in pence
    assert deposit / 100 == 400.0  # Verify in GBP


def test_xl_deposit_2_5_days_equals_500():
    """Test that 2.5 days = £500 deposit (20000 pence × 2.5 = 50000 pence)."""
    deposit = get_deposit_amount(category="XL", estimated_days=2.5)
    assert deposit == 50000  # £500 in pence
    assert deposit / 100 == 500.0  # Verify in GBP


def test_xl_deposit_1_0_day_equals_200():
    """Test that 1.0 day = £200 deposit (minimum)."""
    deposit = get_deposit_amount(category="XL", estimated_days=1.0)
    assert deposit == 20000  # £200 in pence


def test_xl_deposit_without_days_defaults_to_200():
    """Test that XL without estimated_days defaults to 1.0 day (£200)."""
    deposit = get_deposit_amount(category="XL", estimated_days=None)
    assert deposit == 20000  # Defaults to £200 (1.0 day)


def test_non_xl_deposits_unchanged():
    """Test that Small/Medium/Large deposits remain unchanged."""
    assert get_deposit_amount("SMALL") == 15000  # £150
    assert get_deposit_amount("MEDIUM") == 15000  # £150
    assert get_deposit_amount("LARGE") == 20000  # £200
    assert get_deposit_amount("LARGE", estimated_days=2.0) == 20000  # Days ignored for non-XL


def test_estimate_days_for_xl_small_area():
    """Test estimated days for small XL project (< 350 cm²)."""
    dimensions = (18, 18)  # 324 cm² (just under 350)
    days = estimate_days_for_xl(
        dimensions=dimensions,
        complexity_level=2,
        is_coverup=False,
        placement=None,
    )
    assert days == 1.5  # Small XL = 1.5 days


def test_estimate_days_for_xl_medium_area():
    """Test estimated days for medium XL project (350-500 cm²)."""
    dimensions = (20, 20)  # 400 cm²
    days = estimate_days_for_xl(
        dimensions=dimensions,
        complexity_level=2,
        is_coverup=False,
        placement=None,
    )
    assert days == 2.0  # Medium XL = 2.0 days


def test_estimate_days_for_xl_large_area():
    """Test estimated days for large XL project (500-700 cm²)."""
    dimensions = (25, 25)  # 625 cm²
    days = estimate_days_for_xl(
        dimensions=dimensions,
        complexity_level=2,
        is_coverup=False,
        placement=None,
    )
    assert days == 2.5  # Large XL = 2.5 days


def test_estimate_days_for_xl_very_large_area():
    """Test estimated days for very large XL project (> 700 cm²)."""
    dimensions = (30, 30)  # 900 cm²
    days = estimate_days_for_xl(
        dimensions=dimensions,
        complexity_level=2,
        is_coverup=False,
        placement=None,
    )
    assert days == 3.0  # Very large XL = 3.0 days


def test_estimate_days_for_xl_with_coverup_adds_half_day():
    """Test that coverup adds 0.5 days."""
    dimensions = (20, 20)  # 400 cm² = 2.0 days base
    days = estimate_days_for_xl(
        dimensions=dimensions,
        complexity_level=2,
        is_coverup=True,  # Adds 0.5 days
        placement=None,
    )
    assert days == 2.5  # 2.0 + 0.5 = 2.5 days


def test_estimate_days_for_xl_with_complexity_3_adds_half_day():
    """Test that complexity level 3 adds 0.5 days."""
    dimensions = (20, 20)  # 400 cm² = 2.0 days base
    days = estimate_days_for_xl(
        dimensions=dimensions,
        complexity_level=3,  # Adds 0.5 days
        is_coverup=False,
        placement=None,
    )
    assert days == 2.5  # 2.0 + 0.5 = 2.5 days


def test_estimate_days_for_xl_with_hard_placement_adds_half_day():
    """Test that hard placement adds 0.5 days."""
    dimensions = (20, 20)  # 400 cm² = 2.0 days base
    days = estimate_days_for_xl(
        dimensions=dimensions,
        complexity_level=2,
        is_coverup=False,
        placement="ribs",  # Hard placement adds 0.5 days
    )
    assert days == 2.5  # 2.0 + 0.5 = 2.5 days


def test_estimate_days_for_xl_rounds_to_half_day_increments():
    """Test that days are rounded to 0.5-day increments."""
    # Test various scenarios that should round correctly
    dimensions = (19, 19)  # 361 cm² (between thresholds)
    days = estimate_days_for_xl(
        dimensions=dimensions,
        complexity_level=2,
        is_coverup=False,
        placement=None,
    )
    # Should be rounded to nearest 0.5
    assert days in [1.5, 2.0, 2.5]  # Valid 0.5-day increments
    assert days % 0.5 == 0  # Must be multiple of 0.5


def test_estimate_days_for_xl_minimum_1_0_day():
    """Test that minimum days is 1.0."""
    # Very small XL with no complexity
    dimensions = (18, 18)  # 324 cm² = 1.5 days base
    days = estimate_days_for_xl(
        dimensions=dimensions,
        complexity_level=1,  # Low complexity
        is_coverup=False,
        placement=None,
    )
    assert days >= 1.0  # Minimum 1.0 day


def test_estimate_days_for_xl_maximum_4_0_days():
    """Test that maximum days is 4.0."""
    # Very large XL with all complexity factors
    dimensions = (30, 30)  # 900 cm² = 3.0 days base
    days = estimate_days_for_xl(
        dimensions=dimensions,
        complexity_level=3,  # High complexity (+0.5)
        is_coverup=True,  # Coverup (+0.5)
        placement="full back",  # Hard placement (+0.5)
    )
    # Total would be 3.0 + 0.5 + 0.5 + 0.5 = 4.5, but capped at 4.0
    assert days <= 4.0  # Maximum 4.0 days


def test_estimate_project_xl_returns_days():
    """Test that estimate_project returns estimated_days for XL projects."""
    # Large area that should be XL
    category, deposit, estimated_days = estimate_project(
        dimensions_text="25x25cm",  # 625 cm² = XL
        complexity_level=2,
        is_coverup=False,
        placement=None,
    )

    assert category == "XL"
    assert estimated_days is not None
    assert isinstance(estimated_days, float)
    assert estimated_days >= 1.0
    # Deposit should be £200 × estimated_days
    expected_deposit = int(20000 * estimated_days)
    assert deposit == expected_deposit


def test_estimate_project_non_xl_returns_none_days():
    """Test that estimate_project returns None for estimated_days for non-XL projects."""
    category, deposit, estimated_days = estimate_project(
        dimensions_text="8x12cm",  # 96 cm² = MEDIUM
        complexity_level=2,
        is_coverup=False,
        placement=None,
    )

    assert category == "MEDIUM"
    assert estimated_days is None
    assert deposit == 15000  # Fixed £150 for MEDIUM


def test_xl_deposit_calculation_examples():
    """Test specific deposit calculation examples."""
    test_cases = [
        (1.0, 20000),  # 1.0 day = £200
        (1.5, 30000),  # 1.5 days = £300
        (2.0, 40000),  # 2.0 days = £400
        (2.5, 50000),  # 2.5 days = £500
        (3.0, 60000),  # 3.0 days = £600
        (3.5, 70000),  # 3.5 days = £700
        (4.0, 80000),  # 4.0 days = £800
    ]

    for days, expected_pence in test_cases:
        deposit = get_deposit_amount(category="XL", estimated_days=days)
        assert deposit == expected_pence, (
            f"Failed for {days} days: expected {expected_pence}, got {deposit}"
        )


def test_estimate_days_for_xl_no_dimensions_uses_complexity():
    """Test that XL estimation without dimensions uses complexity/coverup."""
    # No dimensions, but complexity level 3 should give reasonable estimate
    days = estimate_days_for_xl(
        dimensions=None,
        complexity_level=3,
        is_coverup=False,
        placement=None,
    )
    assert days >= 1.5  # Should estimate at least 1.5 days for high complexity
    assert days <= 4.0  # Should not exceed maximum


def test_estimate_days_for_xl_no_dimensions_coverup():
    """Test that XL estimation without dimensions but with coverup works."""
    days = estimate_days_for_xl(
        dimensions=None,
        complexity_level=2,
        is_coverup=True,  # Coverup should give reasonable estimate
        placement=None,
    )
    assert days >= 2.0  # Coverup should estimate at least 2.0 days
    assert days <= 4.0  # Should not exceed maximum
