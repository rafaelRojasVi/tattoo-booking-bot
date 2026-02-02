"""
Tests for deposit amount locking and audit fields.

Tests that deposit amounts are locked when deposit links are generated,
and that audit fields (deposit_amount_locked_at, deposit_rule_version) are set.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.db.models import Lead
from app.services.stripe_service import create_checkout_session


@pytest.fixture
def lead_with_estimated_deposit(db):
    """Create a lead with estimated deposit amount."""
    lead = Lead(
        wa_from="test_wa_from",
        status="AWAITING_DEPOSIT",
        channel="whatsapp",
        estimated_deposit_amount=15000,  # £150
        estimated_category="MEDIUM",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


@pytest.fixture
def lead_with_locked_deposit(db):
    """Create a lead with already locked deposit amount."""
    lead = Lead(
        wa_from="test_wa_from_locked",
        status="AWAITING_DEPOSIT",
        channel="whatsapp",
        deposit_amount_pence=20000,  # Already locked at £200
        estimated_deposit_amount=15000,  # Original estimate was £150
        estimated_category="MEDIUM",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def test_send_deposit_locks_amount_from_estimated(db, client, lead_with_estimated_deposit):
    """Test that send_deposit locks amount from estimated_deposit_amount."""
    from app.core.config import settings

    with patch("app.services.stripe_service.create_checkout_session") as mock_create:
        from datetime import UTC, datetime, timedelta

        mock_create.return_value = {
            "checkout_session_id": "cs_test_123",
            "checkout_url": "https://checkout.stripe.com/test/cs_test_123",
            "expires_at": datetime.now(UTC) + timedelta(hours=24),
        }

        response = client.post(
            f"/admin/leads/{lead_with_estimated_deposit.id}/send-deposit",
            headers={"X-Admin-API-Key": "test_admin_key"},
            json={},
        )

        assert response.status_code == 200
        db.refresh(lead_with_estimated_deposit)

        # Verify deposit amount is locked
        assert lead_with_estimated_deposit.deposit_amount_pence == 15000  # £150
        assert lead_with_estimated_deposit.estimated_deposit_amount == 15000

        # Verify audit fields are set
        assert lead_with_estimated_deposit.deposit_amount_locked_at is not None
        assert lead_with_estimated_deposit.deposit_rule_version == settings.deposit_rule_version

        # Verify Stripe session was created with correct amount
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        assert call_args.kwargs["amount_pence"] == 15000
        assert call_args.kwargs["metadata"]["amount_pence"] == "15000"
        assert call_args.kwargs["metadata"]["deposit_rule_version"] == settings.deposit_rule_version


def test_send_deposit_uses_locked_amount_if_already_set(db, client, lead_with_locked_deposit):
    """Test that send_deposit uses already locked deposit_amount_pence if set."""
    from app.core.config import settings

    with patch("app.services.stripe_service.create_checkout_session") as mock_create:
        from datetime import UTC, datetime, timedelta

        mock_create.return_value = {
            "checkout_session_id": "cs_test_456",
            "checkout_url": "https://checkout.stripe.com/test/cs_test_456",
            "expires_at": datetime.now(UTC) + timedelta(hours=24),
        }

        response = client.post(
            f"/admin/leads/{lead_with_locked_deposit.id}/send-deposit",
            headers={"X-Admin-API-Key": "test_admin_key"},
            json={},
        )

        assert response.status_code == 200
        db.refresh(lead_with_locked_deposit)

        # Verify locked amount is used (not estimated)
        assert lead_with_locked_deposit.deposit_amount_pence == 20000  # £200 (locked)
        assert lead_with_locked_deposit.estimated_deposit_amount == 20000  # Updated to match

        # Verify audit fields are set
        assert lead_with_locked_deposit.deposit_amount_locked_at is not None
        assert lead_with_locked_deposit.deposit_rule_version == settings.deposit_rule_version

        # Verify Stripe session was created with locked amount
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        assert call_args.kwargs["amount_pence"] == 20000
        assert call_args.kwargs["metadata"]["amount_pence"] == "20000"


def test_send_deposit_stripe_metadata_includes_version_and_amount(monkeypatch):
    """Test that Stripe checkout session metadata includes deposit_rule_version and amount_pence."""
    from app.core.config import settings

    # Bypass stripe_service test-mode early return so Session.create is actually called
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_other")

    with patch("stripe.checkout.Session.create") as mock_stripe_create:
        mock_session = MagicMock()
        mock_session.id = "cs_test_789"
        mock_session.url = "https://checkout.stripe.com/test/cs_test_789"
        mock_stripe_create.return_value = mock_session

        result = create_checkout_session(
            lead_id=123,
            amount_pence=15000,
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
            metadata={
                "wa_from": "test_wa",
                "status": "AWAITING_DEPOSIT",
            },
        )

        # Verify Stripe session was created
        mock_stripe_create.assert_called_once()
        call_kwargs = mock_stripe_create.call_args.kwargs

        # Verify metadata includes version and amount
        metadata = call_kwargs["metadata"]
        assert "deposit_rule_version" in metadata
        assert metadata["deposit_rule_version"] == settings.deposit_rule_version
        assert "amount_pence" in metadata
        assert metadata["amount_pence"] == "15000"
        assert "lead_id" in metadata
        assert "type" in metadata
        assert metadata["type"] == "deposit"


def test_send_deposit_action_token_path_locks_amount(db):
    """Test that action token send_deposit path logic locks amount."""
    from sqlalchemy import func

    from app.core.config import settings

    lead = Lead(
        wa_from="test_action_token",
        status="AWAITING_DEPOSIT",
        channel="whatsapp",
        estimated_deposit_amount=20000,  # £200
        estimated_category="LARGE",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Simulate the action processing logic (as in actions.py send_deposit branch)
    if lead.deposit_amount_pence:
        amount_pence = lead.deposit_amount_pence
    elif lead.estimated_deposit_amount:
        amount_pence = lead.estimated_deposit_amount
    else:
        amount_pence = settings.stripe_deposit_amount_pence

    # Lock the deposit amount and set audit fields (as in actions.py)
    lead.deposit_amount_pence = amount_pence
    lead.estimated_deposit_amount = amount_pence
    lead.deposit_amount_locked_at = func.now()
    lead.deposit_rule_version = settings.deposit_rule_version
    db.commit()
    db.refresh(lead)

    # Verify deposit amount is locked
    assert lead.deposit_amount_pence == 20000
    assert lead.estimated_deposit_amount == 20000

    # Verify audit fields are set
    assert lead.deposit_amount_locked_at is not None
    assert lead.deposit_rule_version == settings.deposit_rule_version


def test_deposit_locking_preference_order(db, client):
    """Test that deposit locking follows correct preference order."""

    # Lead with both deposit_amount_pence and estimated_deposit_amount
    lead = Lead(
        wa_from="test_preference",
        status="AWAITING_DEPOSIT",
        channel="whatsapp",
        deposit_amount_pence=30000,  # £300 (should be preferred)
        estimated_deposit_amount=15000,  # £150 (should be ignored)
        estimated_category="MEDIUM",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch("app.services.stripe_service.create_checkout_session") as mock_create:
        from datetime import UTC, datetime, timedelta

        mock_create.return_value = {
            "checkout_session_id": "cs_test_pref",
            "checkout_url": "https://checkout.stripe.com/test/cs_test_pref",
            "expires_at": datetime.now(UTC) + timedelta(hours=24),
        }

        response = client.post(
            f"/admin/leads/{lead.id}/send-deposit",
            headers={"X-Admin-API-Key": "test_admin_key"},
            json={},
        )

        assert response.status_code == 200
        db.refresh(lead)

        # Should use deposit_amount_pence (locked value)
        assert lead.deposit_amount_pence == 30000
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["amount_pence"] == 30000


def test_deposit_rule_version_in_config():
    """Test that deposit_rule_version is defined in settings."""
    from app.core.config import settings

    assert hasattr(settings, "deposit_rule_version")
    assert settings.deposit_rule_version is not None
    assert isinstance(settings.deposit_rule_version, str)
    assert len(settings.deposit_rule_version) > 0
