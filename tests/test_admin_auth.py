"""
Tests for admin authentication.
"""

from unittest.mock import patch


def test_admin_endpoint_without_api_key_works_in_dev_mode(client):
    """Test that admin endpoints work without API key when admin_api_key is not set (dev mode)."""
    # In dev mode (no admin_api_key set), endpoints should work
    # This is the default behavior - no ADMIN_API_KEY env var set
    response = client.get("/admin/leads")
    assert response.status_code == 200


def test_admin_endpoint_with_correct_api_key(client):
    """Test that admin endpoints work with correct API key."""
    # Mock settings to require API key
    with patch("app.api.auth.settings.admin_api_key", "test-secret-key-123"):
        # Request without API key should fail
        response = client.get("/admin/leads")
        assert response.status_code == 401
        assert (
            "missing" in response.json()["detail"].lower()
            or "api key" in response.json()["detail"].lower()
        )

        # Request with correct API key should work
        response = client.get("/admin/leads", headers={"X-Admin-API-Key": "test-secret-key-123"})
        assert response.status_code == 200


def test_admin_endpoint_with_wrong_api_key(client):
    """Test that admin endpoints reject wrong API key."""
    # Mock settings to require API key
    with patch("app.api.auth.settings.admin_api_key", "test-secret-key-123"):
        # Request with wrong API key should fail
        response = client.get("/admin/leads", headers={"X-Admin-API-Key": "wrong-key"})
        assert response.status_code == 403
        assert "Invalid" in response.json()["detail"]


def test_admin_endpoint_missing_api_key_when_required(client):
    """Test that admin endpoints require API key when configured."""
    # Mock settings to require API key
    with patch("app.api.auth.settings.admin_api_key", "required-key"):
        # Request without API key should fail
        response = client.get("/admin/leads")
        assert response.status_code == 401
        assert "Missing" in response.json()["detail"]


def test_all_admin_endpoints_protected(client, db):
    """Test that all admin endpoints require authentication."""
    # Mock settings to require API key
    with patch("app.api.auth.settings.admin_api_key", "test-key"):
        # Create a test lead
        from app.db.models import Lead

        lead = Lead(wa_from="1234567890", status="NEW")
        db.add(lead)
        db.commit()
        db.refresh(lead)

        # Test list_leads without auth
        response = client.get("/admin/leads")
        assert response.status_code == 401

        # Test get_lead_detail without auth
        response = client.get(f"/admin/leads/{lead.id}")
        assert response.status_code == 401

        # Test with auth
        headers = {"X-Admin-API-Key": "test-key"}
        response = client.get("/admin/leads", headers=headers)
        assert response.status_code == 200

        response = client.get(f"/admin/leads/{lead.id}", headers=headers)
        assert response.status_code == 200
