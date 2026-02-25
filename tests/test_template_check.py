"""
Test template configuration check.
"""

from app.services.messaging.template_check import (
    REQUIRED_TEMPLATES,
    startup_check_templates,
)


def test_required_templates_list():
    """Test that required templates list is defined."""
    assert len(REQUIRED_TEMPLATES) > 0
    assert "consultation_reminder_2_final" in REQUIRED_TEMPLATES
    assert "next_steps_reply_to_continue" in REQUIRED_TEMPLATES
    assert "deposit_received_next_steps" in REQUIRED_TEMPLATES


def test_startup_check_templates():
    """Test that startup check returns template status."""
    result = startup_check_templates()

    assert "templates_configured" in result
    assert "templates_missing" in result
    assert "whatsapp_enabled" in result

    assert isinstance(result["templates_configured"], list)
    assert isinstance(result["templates_missing"], list)
    assert isinstance(result["whatsapp_enabled"], bool)


def test_health_endpoint_includes_templates(client):
    """Test that /health endpoint includes template names."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()

    assert "ok" in data
    assert "templates_configured" in data
    assert "features" in data
    assert "integrations" in data

    # Check feature flags
    assert "sheets_enabled" in data["features"]
    assert "calendar_enabled" in data["features"]
    assert "reminders_enabled" in data["features"]
    assert "notifications_enabled" in data["features"]
    assert "panic_mode_enabled" in data["features"]

    # Check integrations
    assert "google_sheets_enabled" in data["integrations"]
    assert "google_calendar_enabled" in data["integrations"]
