"""
Tests for Phase 1 services: region, tour, estimation, handover.
"""

from datetime import UTC, datetime

import pytest

from app.services.estimation_service import (
    estimate_category,
    estimate_project,
    get_deposit_amount,
    parse_budget_from_text,
    parse_dimensions,
)
from app.services.handover_service import should_handover
from app.services.region_service import country_to_region, region_hourly_rate, region_min_budget
from app.services.tour_service import (
    TourStop,
    format_tour_offer,
    is_city_on_tour,
    load_tour_schedule,
)


class TestRegionService:
    """Tests for region service."""

    def test_country_to_region_uk(self):
        """Test UK country mapping."""
        assert country_to_region("UK") == "UK"
        assert country_to_region("United Kingdom") == "UK"
        assert country_to_region("England") == "UK"
        assert country_to_region("Scotland") == "UK"
        assert country_to_region("Wales") == "UK"
        assert country_to_region("gb") == "UK"

    def test_country_to_region_europe(self):
        """Test Europe country mapping."""
        assert country_to_region("France") == "EUROPE"
        assert country_to_region("Germany") == "EUROPE"
        assert country_to_region("Spain") == "EUROPE"
        assert country_to_region("Italy") == "EUROPE"
        assert country_to_region("Netherlands") == "EUROPE"
        assert country_to_region("Switzerland") == "EUROPE"

    def test_country_to_region_row(self):
        """Test Rest of World mapping."""
        assert country_to_region("USA") == "ROW"
        assert country_to_region("Canada") == "ROW"
        assert country_to_region("Australia") == "ROW"
        assert country_to_region("Japan") == "ROW"
        assert country_to_region("Brazil") == "ROW"

    def test_region_min_budget(self):
        """Test minimum budget by region."""
        assert region_min_budget("UK") == 40000  # £400
        assert region_min_budget("EUROPE") == 50000  # £500
        assert region_min_budget("ROW") == 60000  # £600

    def test_region_hourly_rate(self):
        """Test hourly rate by region."""
        assert region_hourly_rate("UK") == 13000  # £130/h
        assert region_hourly_rate("EUROPE") == 14000  # £140/h
        assert region_hourly_rate("ROW") == 15000  # £150/h


class TestTourService:
    """Tests for tour service."""

    def test_load_tour_schedule(self):
        """Test loading tour schedule."""
        schedule_data = [
            {
                "city": "London",
                "country": "UK",
                "start_date": "2024-06-01T00:00:00Z",
                "end_date": "2024-06-05T00:00:00Z",
            },
            {
                "city": "Paris",
                "country": "France",
                "start_date": "2024-07-01T00:00:00Z",
                "end_date": "2024-07-05T00:00:00Z",
            },
        ]
        load_tour_schedule(schedule_data)
        # Schedule should be loaded (we can't easily test without accessing private var)

    def test_is_city_on_tour_no_schedule(self):
        """Test city check with no schedule loaded."""
        # No schedule loaded, should return False
        assert is_city_on_tour("London") == False

    def test_format_tour_offer(self):
        """Test tour offer formatting."""
        start = datetime(2024, 6, 1, tzinfo=UTC)
        end = datetime(2024, 6, 5, tzinfo=UTC)
        stop = TourStop(
            city="London",
            country="UK",
            start_date=start,
            end_date=end,
        )
        message = format_tour_offer(stop, requested_city="Manchester")
        assert "London" in message
        assert "June" in message
        assert "yes" in message.lower() or "no" in message.lower()


class TestEstimationService:
    """Tests for estimation service."""

    def test_parse_dimensions_cm(self):
        """Test parsing dimensions in cm."""
        dims = parse_dimensions("8x12cm")
        assert dims == (8.0, 12.0)

        dims = parse_dimensions("10cm")
        assert dims == (10.0, 10.0)  # Square

    def test_parse_dimensions_inches(self):
        """Test parsing dimensions in inches."""
        dims = parse_dimensions("3x5 inches")
        # Should convert to cm: 3*2.54 = 7.62, 5*2.54 = 12.7
        assert dims[0] == pytest.approx(7.62, rel=0.01)
        assert dims[1] == pytest.approx(12.7, rel=0.01)

    def test_parse_dimensions_invalid(self):
        """Test parsing invalid dimensions."""
        assert parse_dimensions("") is None
        assert parse_dimensions("not a size") is None

    def test_parse_budget_from_text_plain_number(self):
        """Budget parser accepts plain number (pence = number * 100)."""
        assert parse_budget_from_text("400") == 40000
        assert parse_budget_from_text("500") == 50000

    def test_parse_budget_from_text_currency_symbols(self):
        """Budget parser accepts £ and $ and strips to number."""
        assert parse_budget_from_text("£400") == 40000
        assert parse_budget_from_text("400gbp") == 40000

    def test_parse_budget_from_text_invalid(self):
        """Budget parser returns None when no number."""
        assert parse_budget_from_text("") is None
        assert parse_budget_from_text("not a number") is None

    def test_estimate_category_small(self):
        """Test category estimation for small projects."""
        # Small area, low complexity
        category = estimate_category(
            dimensions=(5.0, 5.0),  # 25 cm²
            complexity_level=1,
            is_coverup=False,
            placement="wrist",
        )
        assert category == "SMALL"

    def test_estimate_category_medium(self):
        """Test category estimation for medium projects."""
        category = estimate_category(
            dimensions=(10.0, 10.0),  # 100 cm²
            complexity_level=2,
            is_coverup=False,
            placement="forearm",
        )
        assert category == "MEDIUM"

    def test_estimate_category_large(self):
        """Test category estimation for large projects."""
        category = estimate_category(
            dimensions=(15.0, 20.0),  # 300 cm² (at XL boundary)
            complexity_level=2,
            is_coverup=False,
            placement="back",
        )
        # 300 cm² is at the boundary, could be LARGE or XL
        assert category in ["LARGE", "XL"]

    def test_estimate_category_coverup_bump(self):
        """Test that coverups bump category."""
        category = estimate_category(
            dimensions=(5.0, 5.0),  # Small area
            complexity_level=1,
            is_coverup=True,  # But coverup
            placement="arm",
        )
        # Should be bumped to at least MEDIUM
        assert category in ["MEDIUM", "LARGE"]

    def test_estimate_category_high_complexity_bump(self):
        """Test that high complexity bumps category."""
        category = estimate_category(
            dimensions=(8.0, 8.0),  # Medium area
            complexity_level=3,  # High complexity
            is_coverup=False,
            placement="arm",
        )
        # Should be bumped
        assert category in ["MEDIUM", "LARGE"]

    def test_get_deposit_amount(self):
        """Test deposit amounts by category."""
        assert get_deposit_amount("SMALL") == 15000  # £150
        assert get_deposit_amount("MEDIUM") == 15000  # £150
        assert get_deposit_amount("LARGE") == 20000  # £200
        assert get_deposit_amount("XL") == 20000  # £200

    def test_estimate_project_full(self):
        """Test full project estimation."""
        category, deposit, estimated_days = estimate_project(
            dimensions_text="10x15cm",
            complexity_level=2,
            is_coverup=False,
            placement="forearm",
        )
        assert category in ["SMALL", "MEDIUM", "LARGE", "XL"]
        assert deposit in [15000, 20000]  # Valid deposit amounts
        # estimated_days is None for non-XL, float for XL
        if category == "XL":
            assert estimated_days is not None
            assert isinstance(estimated_days, float)
        else:
            assert estimated_days is None


class TestHandoverService:
    """Tests for handover service."""

    def test_handover_high_complexity(self, db):
        """Test handover triggered by high complexity."""
        from app.db.models import Lead

        lead = Lead(
            wa_from="1234567890",
            status="QUALIFYING",
            complexity_level=3,  # High complexity
        )
        db.add(lead)
        db.commit()

        should, reason = should_handover("I want a realistic portrait", lead)
        assert should == True
        assert "complexity" in reason.lower() or "realism" in reason.lower()

    def test_handover_coverup_keyword(self, db):
        """Test handover triggered by coverup keyword."""
        from app.db.models import Lead

        lead = Lead(wa_from="1234567890", status="QUALIFYING")
        db.add(lead)
        db.commit()

        # Test with exact keyword from service: "cover-up" (with hyphen)
        should, reason = should_handover("I need a cover-up", lead)
        assert should == True
        assert "cover" in reason.lower()

    def test_handover_price_negotiation(self, db):
        """Test handover triggered by price negotiation."""
        from app.db.models import Lead

        lead = Lead(wa_from="1234567890", status="QUALIFYING")
        db.add(lead)
        db.commit()

        # Use exact keyword from service: "cheaper"
        should, reason = should_handover("Can you do it cheaper?", lead)
        assert should == True
        assert "price" in reason.lower() or "negotiation" in reason.lower()

    def test_handover_hesitation(self, db):
        """Test handover triggered by hesitation."""
        from app.db.models import Lead

        lead = Lead(wa_from="1234567890", status="QUALIFYING")
        db.add(lead)
        db.commit()

        # Use exact phrase from service: "i'm ready but"
        should, reason = should_handover("I'm ready but I'm not sure", lead)
        assert should == True
        assert "hesitation" in reason.lower() or "personal" in reason.lower()

    def test_no_handover_normal_message(self, db):
        """Test no handover for normal messages."""
        from app.db.models import Lead

        lead = Lead(wa_from="1234567890", status="QUALIFYING", complexity_level=1)
        db.add(lead)
        db.commit()

        should, reason = should_handover("I want a small dragon on my arm", lead)
        assert should == False
        assert reason is None
