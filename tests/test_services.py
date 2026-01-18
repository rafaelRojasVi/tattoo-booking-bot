import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import Lead
from app.services.leads import get_or_create_lead


def test_get_or_create_lead_creates_new(db):
    """Test creating a new lead."""
    lead = get_or_create_lead(db, wa_from="1234567890")

    assert lead.id is not None
    assert lead.wa_from == "1234567890"
    assert lead.status == "NEW"
    assert lead.channel == "whatsapp"


def test_get_or_create_lead_returns_existing(db):
    """Test returning existing lead."""
    # Create existing lead
    existing = Lead(wa_from="1234567890", status="CONTACTED")
    db.add(existing)
    db.commit()
    db.refresh(existing)

    # Get or create should return existing
    lead = get_or_create_lead(db, wa_from="1234567890")

    assert lead.id == existing.id
    assert lead.status == "CONTACTED"  # Should keep existing status


def test_get_or_create_lead_invalid_input(db):
    """Test validation of input parameters."""
    with pytest.raises(ValueError, match="wa_from must be a non-empty string"):
        get_or_create_lead(db, wa_from="")

    with pytest.raises(ValueError, match="wa_from must be a non-empty string"):
        get_or_create_lead(db, wa_from=None)

    with pytest.raises(ValueError, match="wa_from must be a non-empty string"):
        get_or_create_lead(db, wa_from=123)  # Not a string


def test_get_or_create_lead_database_rollback_on_error(db):
    """Test that database errors are properly handled with rollback."""
    from unittest.mock import MagicMock

    # Create a mock session that raises error on commit
    mock_db = MagicMock()
    # Mock the execute chain: execute() -> scalars() -> all()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []  # No existing leads
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_result
    mock_db.commit.side_effect = SQLAlchemyError("Connection lost")

    # Test that error is raised
    with pytest.raises(SQLAlchemyError):
        get_or_create_lead(mock_db, wa_from="1234567890")

    # Verify rollback was attempted
    mock_db.rollback.assert_called_once()


def test_get_or_create_lead_concurrent_creation(db):
    """Test handling when lead might be created concurrently."""
    # This tests the idempotency - even if called twice, should work
    lead1 = get_or_create_lead(db, wa_from="1234567890")
    lead2 = get_or_create_lead(db, wa_from="1234567890")

    assert lead1.id == lead2.id
    assert lead1.wa_from == lead2.wa_from


def test_get_or_create_lead_special_characters_in_phone(db):
    """Test handling of phone numbers with special characters."""
    # WhatsApp numbers can have + prefix
    lead = get_or_create_lead(db, wa_from="+441234567890")

    assert lead.wa_from == "+441234567890"

    # Should be able to retrieve it
    lead2 = get_or_create_lead(db, wa_from="+441234567890")
    assert lead.id == lead2.id
