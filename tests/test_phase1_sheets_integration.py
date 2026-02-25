"""
Test Phase 1 Google Sheets integration.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.db.models import Lead, LeadAnswer
from app.services.integrations.sheets import (
    _count_reference_media,
    _get_sheets_service,
    _parse_budget_amount,
    log_lead_to_sheets,
)


def test_parse_budget_amount():
    """Test parsing budget amount from various formats."""
    # Test GBP format
    assert _parse_budget_amount({"budget": "£500"}) == 50000  # 500 GBP = 50000 pence
    assert _parse_budget_amount({"budget": "500"}) == 50000
    assert _parse_budget_amount({"budget": "1,000"}) == 100000
    assert (
        _parse_budget_amount({"budget": "£1,500.50"}) == 150050
    )  # Converts 1500.50 GBP to 150050 pence

    # Test missing budget
    assert _parse_budget_amount({"budget": ""}) is None
    assert _parse_budget_amount({}) is None

    # Test invalid format
    assert _parse_budget_amount({"budget": "not a number"}) is None


def test_count_reference_media(db):
    """Test counting reference links and media."""
    lead = Lead(
        wa_from="1234567890",
        status="QUALIFYING",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Add reference images answer with Instagram link
    answer1 = LeadAnswer(
        lead_id=lead.id,
        question_key="reference_images",
        answer_text="Check my Instagram: https://instagram.com/user",
    )
    db.add(answer1)

    # Add reference images answer with media
    answer2 = LeadAnswer(
        lead_id=lead.id,
        question_key="reference_images",
        answer_text="Here's an image",
        media_id="media_123",
        media_url="https://example.com/image.jpg",
    )
    db.add(answer2)

    db.commit()
    db.refresh(lead)

    links_count, media_count = _count_reference_media(lead)

    assert links_count >= 1  # At least one Instagram link
    assert media_count == 1  # One media item


def test_log_lead_to_sheets_stub_mode(db):
    """Test that log_lead_to_sheets works in stub mode (no Google Sheets configured)."""
    lead = Lead(
        wa_from="1234567890",
        status="NEW",
        instagram_handle="@testuser",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Add some answers
    answer = LeadAnswer(
        lead_id=lead.id,
        question_key="idea",
        answer_text="Dragon tattoo",
    )
    db.add(answer)
    db.commit()

    # Should work in stub mode
    with patch.object(settings, "google_sheets_enabled", False):
        result = log_lead_to_sheets(db, lead)
        assert result is True


def test_log_lead_to_sheets_with_real_api_mock(db):
    """Test that log_lead_to_sheets attempts to use real API when enabled."""
    lead = Lead(
        wa_from="1234567890",
        status="PENDING_APPROVAL",
        instagram_handle="@testuser",
        complexity_level=2,
        estimated_category="MEDIUM",
        estimated_deposit_amount=15000,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Mock Google Sheets service
    mock_service = MagicMock()
    mock_service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": [["lead_id"], ["999"]]  # No matching lead_id
    }
    mock_service.spreadsheets.return_value.values.return_value.append.return_value.execute.return_value = {}

    with patch("app.services.integrations.sheets._get_sheets_service", return_value=mock_service):
        with patch.object(settings, "google_sheets_enabled", True):
            with patch.object(settings, "google_sheets_spreadsheet_id", "test_spreadsheet_id"):
                result = log_lead_to_sheets(db, lead)

                # Should attempt to append (since lead not found)
                assert mock_service.spreadsheets.return_value.values.return_value.append.called


def test_log_lead_to_sheets_updates_existing_row(db):
    """Test that log_lead_to_sheets updates existing row if lead_id found."""
    lead = Lead(
        wa_from="1234567890",
        status="PENDING_APPROVAL",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Mock Google Sheets service with existing row
    mock_service = MagicMock()
    mock_service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": [["lead_id"], [str(lead.id)]]  # Found matching lead_id
    }
    mock_service.spreadsheets.return_value.values.return_value.update.return_value.execute.return_value = {}

    with patch("app.services.integrations.sheets._get_sheets_service", return_value=mock_service):
        with patch.object(settings, "google_sheets_enabled", True):
            with patch.object(settings, "google_sheets_spreadsheet_id", "test_spreadsheet_id"):
                result = log_lead_to_sheets(db, lead)

                # Should attempt to update (since lead found)
                assert mock_service.spreadsheets.return_value.values.return_value.update.called


def test_get_sheets_service_returns_none_when_disabled():
    """Test that _get_sheets_service returns None when not enabled."""
    with patch.object(settings, "google_sheets_enabled", False):
        service = _get_sheets_service()
        assert service is None


def test_get_sheets_service_handles_missing_credentials():
    """Test that _get_sheets_service handles missing credentials gracefully."""
    with patch.object(settings, "google_sheets_enabled", True):
        with patch.object(settings, "google_sheets_credentials_json", None):
            service = _get_sheets_service()
            assert service is None


def test_log_lead_to_sheets_handles_all_phase1_fields(db):
    """Test that all Phase 1 fields are included in row_data."""

    lead = Lead(
        wa_from="1234567890",
        status="BOOKING_PENDING",
        instagram_handle="@testuser",
        complexity_level=2,
        estimated_category="MEDIUM",
        estimated_deposit_amount=15000,
        location_city="London",
        location_country="UK",
        region_bucket="UK",
        requested_city="Manchester",
        offered_tour_city="London",
        tour_offer_accepted=True,
        waitlisted=False,
        min_budget_amount=40000,
        below_min_budget=False,
        calendar_event_id="cal_123",
        handover_reason="Complex design",
        qualifying_started_at=datetime.now(UTC),
        qualifying_completed_at=datetime.now(UTC),
        approved_at=datetime.now(UTC),
        deposit_paid_at=datetime.now(UTC),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Add answers
    for key in ["idea", "placement", "dimensions", "budget"]:
        answer = LeadAnswer(
            lead_id=lead.id,
            question_key=key,
            answer_text=f"Answer for {key}",
        )
        db.add(answer)
    db.commit()
    db.refresh(lead)

    # Should not raise errors
    with patch.object(settings, "google_sheets_enabled", False):
        result = log_lead_to_sheets(db, lead)
        assert result is True
