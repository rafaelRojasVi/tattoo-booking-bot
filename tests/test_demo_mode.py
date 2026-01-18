"""
Tests for DEMO_MODE feature flag.

Ensures demo endpoints are blocked when DEMO_MODE=false.
"""

import pytest
from unittest.mock import patch

from app.core.config import settings


def test_demo_endpoints_blocked_when_demo_mode_false(client):
    """Test that demo endpoints return 404 when DEMO_MODE is False."""
    # Ensure demo_mode is False (default)
    with patch.object(settings, "demo_mode", False):
        # All demo endpoints should return 404
        response = client.get("/demo/client")
        assert response.status_code == 404
        assert "Not found" in response.json()["detail"]

        response = client.post("/demo/client/send", json={"from_number": "+441234567890", "text": "test"})
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
            json={"from_number": "+449999888777", "text": "Hi, I want a tattoo"}
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
            json={"from_number": "+449999888777", "text": "A dragon on my back"}
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
    """Test that demo_mode defaults to False in settings."""
    # When no env var is set, should default to False
    from app.core.config import Settings
    from unittest.mock import patch
    
    # Simulate no DEMO_MODE env var
    with patch.dict("os.environ", {}, clear=False):
        # Remove DEMO_MODE if it exists
        import os
        demo_mode_val = os.environ.pop("DEMO_MODE", None)
        try:
            # Force reload settings (in practice, this would be on import)
            # For test, just check the default
            settings_obj = Settings()
            assert settings_obj.demo_mode is False
        finally:
            # Restore if it existed
            if demo_mode_val:
                os.environ["DEMO_MODE"] = demo_mode_val
