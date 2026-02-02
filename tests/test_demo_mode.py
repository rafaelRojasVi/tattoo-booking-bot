"""
Tests for DEMO_MODE feature flag.

Ensures demo endpoints are blocked when DEMO_MODE=false.
"""

from unittest.mock import patch

import pytest

from app.core.config import settings


def test_demo_endpoints_blocked_when_demo_mode_false(client):
    """Test that demo endpoints return 404 when DEMO_MODE is False."""
    # Ensure demo_mode is False (default)
    with patch.object(settings, "demo_mode", False):
        # All demo endpoints should return 404
        response = client.get("/demo/client")
        assert response.status_code == 404
        assert "Not found" in response.json()["detail"]

        response = client.post(
            "/demo/client/send", json={"from_number": "+441234567890", "text": "test"}
        )
        assert response.status_code == 404

        response = client.get("/demo/artist/inbox")
        assert response.status_code == 404

        response = client.get("/demo/artist")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_demo_client_send_creates_lead_and_progresses(client, db):
    """Test that demo client send creates lead and progresses to QUALIFYING/PENDING_APPROVAL correctly."""
    with patch.object(settings, "demo_mode", True):
        # Send first message
        response = client.post(
            "/demo/client/send",
            json={"from_number": "+449999888777", "text": "Hi, I want a tattoo"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["received"] is True
        assert "lead_id" in data
        assert data["lead_status"] == "QUALIFYING"  # Should transition to QUALIFYING

        lead_id = data["lead_id"]

        # Send answer to first question
        response = client.post(
            "/demo/client/send",
            json={"from_number": "+449999888777", "text": "A dragon on my back"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["lead_id"] == lead_id  # Same lead reused
        assert data["lead_status"] == "QUALIFYING"  # Still qualifying


def test_demo_artist_inbox_returns_leads(client, db):
    """Test that demo artist inbox returns leads with summaries and action links."""
    with patch.object(settings, "demo_mode", True):
        response = client.get("/demo/artist/inbox")
        assert response.status_code == 200
        data = response.json()
        assert "leads" in data
        assert "count" in data
        assert isinstance(data["leads"], list)

        # If leads exist, check structure
        if data["leads"]:
            lead = data["leads"][0]
            assert "lead_id" in lead
            assert "status" in lead
            assert "summary" in lead
            assert "action_links" in lead


def test_demo_mode_defaults_to_false():
    """Test that demo_mode defaults to False in settings class definition."""
    # Check the default value in the Settings class definition
    # This tests the actual default, not the instantiated settings (which may have env overrides)

    from app.core.config import Settings

    # Get the default value from the class field definition
    # Pydantic models store defaults in model_fields
    demo_mode_field = Settings.model_fields.get("demo_mode")
    assert demo_mode_field is not None, "demo_mode field should exist"

    # Check the default value
    default_value = demo_mode_field.default
    assert default_value is False, (
        f"demo_mode should default to False in Settings class, but default is {default_value}"
    )
