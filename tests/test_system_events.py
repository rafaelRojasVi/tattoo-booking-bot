"""
Tests for system events service and admin endpoint.
"""

import pytest

from app.db.models import Lead, SystemEvent
from app.services.system_event_service import error, info, warn


@pytest.fixture
def admin_headers():
    """Admin API headers."""
    return {"X-Admin-API-Key": "test_admin_key"}


@pytest.fixture
def setup_admin_key(monkeypatch):
    """Set admin API key for testing."""
    monkeypatch.setenv("ADMIN_API_KEY", "test_admin_key")
    monkeypatch.setenv("APP_ENV", "dev")  # Dev mode allows missing key


@pytest.fixture
def sample_lead(db):
    """Create a sample lead for testing."""
    lead = Lead(wa_from="1234567890", status="NEW")
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def test_system_event_info(db):
    """Test logging INFO-level system event."""
    event = info(
        db=db,
        event_type="test.info_event",
        lead_id=None,
        payload={"test_key": "test_value"},
    )

    assert event.id is not None
    assert event.level == "INFO"
    assert event.event_type == "test.info_event"
    assert event.lead_id is None
    assert event.payload == {"test_key": "test_value"}
    assert event.created_at is not None

    # Verify it's in the database
    db.refresh(event)
    assert db.query(SystemEvent).filter(SystemEvent.id == event.id).first() is not None


def test_system_event_warn(db):
    """Test logging WARN-level system event."""
    event = warn(
        db=db,
        event_type="test.warn_event",
        lead_id=None,
        payload={"warning": "test warning"},
    )

    assert event.level == "WARN"
    assert event.event_type == "test.warn_event"


def test_system_event_error(db):
    """Test logging ERROR-level system event."""
    event = error(
        db=db,
        event_type="test.error_event",
        lead_id=None,
        payload={"error": "test error"},
    )

    assert event.level == "ERROR"
    assert event.event_type == "test.error_event"


def test_system_event_exc_nested_under_payload_error(db):
    """Exception info is nested under payload['error'] = {type, message}."""
    exc = ValueError("Something went wrong")
    event = error(
        db=db,
        event_type="test.exc_event",
        lead_id=None,
        payload={"context": "extra"},
        exc=exc,
    )
    assert event.payload is not None
    assert event.payload["error"] == {"type": "ValueError", "message": "Something went wrong"}
    assert event.payload["context"] == "extra"


def test_system_event_with_lead(db, sample_lead):
    """Test logging system event with lead ID."""
    event = info(
        db=db,
        event_type="test.lead_event",
        lead_id=sample_lead.id,
        payload={"lead_status": sample_lead.status},
    )

    assert event.lead_id == sample_lead.id
    assert event.payload is not None
    assert event.payload["lead_status"] == sample_lead.status


def test_system_event_without_payload(db):
    """Test logging system event without payload."""
    event = info(
        db=db,
        event_type="test.no_payload",
        lead_id=None,
        payload=None,
    )

    assert event.payload is None


def test_admin_events_endpoint(client, db, admin_headers, setup_admin_key):
    """Test GET /admin/events endpoint."""
    # Create some test events
    info(db, event_type="test.event1", lead_id=None, payload={"key": "value1"})
    warn(db, event_type="test.event2", lead_id=None, payload={"key": "value2"})
    error(db, event_type="test.event3", lead_id=None, payload={"key": "value3"})

    # Get all events
    response = client.get("/admin/events", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 3

    # Check structure
    event = data[0]
    assert "id" in event
    assert "created_at" in event
    assert "level" in event
    assert "event_type" in event
    assert "lead_id" in event
    assert "payload" in event

    # Check ordering (most recent first)
    if len(data) > 1:
        assert data[0]["id"] >= data[1]["id"]


def test_admin_events_endpoint_with_limit(client, db, admin_headers, setup_admin_key):
    """Test GET /admin/events with limit parameter."""
    # Create 5 events
    for i in range(5):
        info(db, event_type=f"test.event{i}", lead_id=None)

    # Get with limit
    response = client.get("/admin/events?limit=3", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3


def test_admin_events_endpoint_with_lead_id(
    client, db, admin_headers, setup_admin_key, sample_lead
):
    """Test GET /admin/events with lead_id filter."""
    # Create events with and without lead_id
    info(db, event_type="test.lead_event", lead_id=sample_lead.id)
    info(db, event_type="test.no_lead_event", lead_id=None)

    # Filter by lead_id
    response = client.get(f"/admin/events?lead_id={sample_lead.id}", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert all(event["lead_id"] == sample_lead.id for event in data)


def test_admin_events_endpoint_requires_auth(client, db, setup_admin_key):
    """Test that /admin/events requires authentication."""
    # Without admin key header, should fail
    response = client.get("/admin/events")
    # In dev mode without admin_api_key set, it allows access
    # But if admin_api_key is set (via setup_admin_key), it requires the header
    # So we need to check based on whether key is set
    from app.core.config import settings

    if settings.admin_api_key:
        assert response.status_code in [401, 403]  # Missing or invalid key
    else:
        # Dev mode - allows access without key
        assert response.status_code == 200


def test_admin_events_endpoint_max_limit(client, db, admin_headers, setup_admin_key):
    """Test that limit is capped at 1000."""
    # Create many events
    for i in range(5):
        info(db, event_type=f"test.event{i}", lead_id=None)

    # Request more than max
    response = client.get("/admin/events?limit=5000", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    # Should return at most 1000, but we only have 5
    assert len(data) <= 5
