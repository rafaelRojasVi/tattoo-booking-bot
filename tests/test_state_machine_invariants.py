"""
State Machine Invariant Tests.

Tests that invalid status transitions are rejected with clear errors.
Prevents "ops accidents" in production.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.admin import (
    approve_lead,
    mark_booked,
    reject_lead,
    send_deposit,
)
from app.db.models import Lead
from app.schemas.admin import RejectRequest, SendDepositRequest
from app.services.conversation import (
    STATUS_AWAITING_DEPOSIT,
    STATUS_BOOKED,
    STATUS_BOOKING_PENDING,
    STATUS_DEPOSIT_PAID,
    STATUS_NEW,
    STATUS_PENDING_APPROVAL,
    STATUS_QUALIFYING,
    STATUS_REJECTED,
)


@pytest.fixture
def lead_in_status(db, status: str):
    """Helper to create a lead in a specific status."""
    lead = Lead(
        wa_from="1234567890",
        status=status,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


@pytest.mark.parametrize(
    "invalid_status",
    [
        STATUS_NEW,
        STATUS_QUALIFYING,
        STATUS_AWAITING_DEPOSIT,
        STATUS_DEPOSIT_PAID,
        STATUS_BOOKING_PENDING,
        STATUS_BOOKED,
        STATUS_REJECTED,
    ],
)
@pytest.mark.asyncio
async def test_approve_only_from_pending_approval(db, invalid_status):
    """
    Test that approve only works from PENDING_APPROVAL.

    Invalid transitions:
    - NEW → AWAITING_DEPOSIT (via approve)
    - QUALIFYING → AWAITING_DEPOSIT (via approve)
    - AWAITING_DEPOSIT → AWAITING_DEPOSIT (via approve) - already approved
    - DEPOSIT_PAID → AWAITING_DEPOSIT (via approve) - already past approval
    - BOOKING_PENDING → AWAITING_DEPOSIT (via approve) - already past approval
    - BOOKED → AWAITING_DEPOSIT (via approve) - already booked
    - REJECTED → AWAITING_DEPOSIT (via approve) - already rejected
    """
    lead = Lead(wa_from="1111111111", status=invalid_status)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch("app.api.admin.get_admin_auth", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            await approve_lead(lead.id, db=db)

        assert exc_info.value.status_code == 400
        assert "PENDING_APPROVAL" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_approve_from_pending_approval_succeeds(db):
    """Test that approve works correctly from PENDING_APPROVAL."""
    lead = Lead(wa_from="2222222222", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with (
        patch("app.api.admin.get_admin_auth", return_value=True),
        patch(
            "app.services.calendar_service.send_slot_suggestions_to_client",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.services.artist_notifications.notify_artist", new_callable=AsyncMock
        ) as mock_notify,
    ):
        mock_notify.return_value = True

        result = await approve_lead(lead.id, db=db)
        db.refresh(lead)

        assert lead.status == STATUS_AWAITING_DEPOSIT
        assert lead.approved_at is not None


@pytest.mark.parametrize(
    "invalid_status",
    [
        STATUS_BOOKED,
    ],
)
def test_reject_blocks_booked(db, invalid_status):
    """
    Test that reject cannot be called on BOOKED leads.

    Note: Reject can be called from most statuses, but not BOOKED.
    """
    lead = Lead(wa_from="3333333333", status=invalid_status)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch("app.api.admin.get_admin_auth", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            reject_lead(lead.id, request=RejectRequest(reason="Test"), db=db)

        assert exc_info.value.status_code == 400
        assert "booked" in str(exc_info.value.detail).lower()


def test_reject_from_pending_approval_succeeds(db):
    """Test that reject works correctly from PENDING_APPROVAL."""
    lead = Lead(wa_from="4444444444", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch("app.api.admin.get_admin_auth", return_value=True):
        result = reject_lead(lead.id, request=RejectRequest(reason="Not suitable"), db=db)
        db.refresh(lead)

        assert lead.status == STATUS_REJECTED
        assert lead.rejected_at is not None


@pytest.mark.parametrize(
    "invalid_status",
    [
        STATUS_NEW,
        STATUS_QUALIFYING,
        STATUS_PENDING_APPROVAL,
        STATUS_DEPOSIT_PAID,
        STATUS_BOOKING_PENDING,
        STATUS_BOOKED,
        STATUS_REJECTED,
    ],
)
@pytest.mark.asyncio
async def test_send_deposit_only_from_awaiting_deposit(db, invalid_status):
    """
    Test that send_deposit only works from AWAITING_DEPOSIT.

    Invalid transitions:
    - NEW → (send deposit) - not approved yet
    - QUALIFYING → (send deposit) - not approved yet
    - PENDING_APPROVAL → (send deposit) - not approved yet
    - DEPOSIT_PAID → (send deposit) - already paid
    - BOOKING_PENDING → (send deposit) - already paid
    - BOOKED → (send deposit) - already booked
    - REJECTED → (send deposit) - rejected
    """
    lead = Lead(wa_from="5555555555", status=invalid_status)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch("app.api.admin.get_admin_auth", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            await send_deposit(lead.id, request=SendDepositRequest(), db=db)

        assert exc_info.value.status_code == 400
        assert "AWAITING_DEPOSIT" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_send_deposit_from_awaiting_deposit_succeeds(db):
    """Test that send_deposit works correctly from AWAITING_DEPOSIT."""
    lead = Lead(wa_from="6666666666", status=STATUS_AWAITING_DEPOSIT)
    lead.estimated_category = "MEDIUM"
    lead.estimated_deposit_amount = 15000
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with (
        patch("app.api.admin.get_admin_auth", return_value=True),
        patch("app.services.stripe_service.create_checkout_session") as mock_stripe,
        patch(
            "app.services.whatsapp_window.send_with_window_check", new_callable=AsyncMock
        ) as mock_whatsapp,
    ):
        mock_stripe.return_value = {
            "checkout_session_id": "cs_test_123",
            "checkout_url": "https://checkout.stripe.com/test",
        }
        mock_whatsapp.return_value = {"id": "wamock_123", "status": "sent"}

        result = await send_deposit(lead.id, request=SendDepositRequest(), db=db)
        db.refresh(lead)

        assert lead.stripe_checkout_session_id == "cs_test_123"
        assert lead.deposit_sent_at is not None
        assert mock_stripe.called


@pytest.mark.parametrize(
    "invalid_status",
    [
        STATUS_NEW,
        STATUS_QUALIFYING,
        STATUS_PENDING_APPROVAL,
        STATUS_AWAITING_DEPOSIT,
        STATUS_DEPOSIT_PAID,
        STATUS_BOOKED,
        STATUS_REJECTED,
    ],
)
def test_mark_booked_only_from_booking_pending(db, invalid_status):
    """
    Test that mark_booked only works from BOOKING_PENDING.

    Invalid transitions:
    - NEW → BOOKED (via mark_booked) - not ready
    - QUALIFYING → BOOKED (via mark_booked) - not ready
    - PENDING_APPROVAL → BOOKED (via mark_booked) - not approved
    - AWAITING_DEPOSIT → BOOKED (via mark_booked) - deposit not paid
    - DEPOSIT_PAID → BOOKED (via mark_booked) - should be BOOKING_PENDING first
    - BOOKED → BOOKED (via mark_booked) - already booked
    - REJECTED → BOOKED (via mark_booked) - rejected
    """
    lead = Lead(wa_from="7777777777", status=invalid_status)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch("app.api.admin.get_admin_auth", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            mark_booked(lead.id, db=db)

        assert exc_info.value.status_code == 400
        assert "BOOKING_PENDING" in str(exc_info.value.detail)


def test_mark_booked_from_booking_pending_succeeds(db):
    """Test that mark_booked works correctly from BOOKING_PENDING."""
    lead = Lead(wa_from="8888888888", status=STATUS_BOOKING_PENDING)
    lead.deposit_paid_at = datetime.now(UTC)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch("app.api.admin.get_admin_auth", return_value=True):
        result = mark_booked(lead.id, db=db)
        db.refresh(lead)

        assert lead.status == STATUS_BOOKED
        assert lead.booked_at is not None


@pytest.mark.asyncio
async def test_approve_after_rejected_fails(db):
    """Test that approve cannot be called after lead is rejected."""
    lead = Lead(wa_from="9999999999", status=STATUS_REJECTED)
    lead.rejected_at = datetime.now(UTC)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch("app.api.admin.get_admin_auth", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            await approve_lead(lead.id, db=db)

        assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_send_deposit_before_approval_fails(db):
    """Test that send_deposit cannot be called before approval."""
    lead = Lead(wa_from="1010101010", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch("app.api.admin.get_admin_auth", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            await send_deposit(lead.id, request=SendDepositRequest(), db=db)

        assert exc_info.value.status_code == 400
        assert "AWAITING_DEPOSIT" in str(exc_info.value.detail)


def test_mark_booked_before_deposit_paid_fails(db):
    """Test that mark_booked cannot be called before deposit is paid."""
    lead = Lead(wa_from="1212121212", status=STATUS_AWAITING_DEPOSIT)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch("app.api.admin.get_admin_auth", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            mark_booked(lead.id, db=db)

        assert exc_info.value.status_code == 400
        assert "BOOKING_PENDING" in str(exc_info.value.detail)


def test_reject_after_booked_fails(db):
    """Test that reject cannot be called after lead is booked."""
    lead = Lead(wa_from="1313131313", status=STATUS_BOOKED)
    lead.booked_at = datetime.now(UTC)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch("app.api.admin.get_admin_auth", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            reject_lead(lead.id, request=RejectRequest(reason="Test"), db=db)

        assert exc_info.value.status_code == 400
        assert "booked" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_send_deposit_after_booked_fails(db):
    """Test that send_deposit cannot be called after lead is booked."""
    lead = Lead(wa_from="1414141414", status=STATUS_BOOKED)
    lead.booked_at = datetime.now(UTC)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch("app.api.admin.get_admin_auth", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            await send_deposit(lead.id, request=SendDepositRequest(), db=db)

        assert exc_info.value.status_code == 400
        assert "AWAITING_DEPOSIT" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_approve_after_booked_fails(db):
    """Test that approve cannot be called after lead is booked."""
    lead = Lead(wa_from="1515151515", status=STATUS_BOOKED)
    lead.booked_at = datetime.now(UTC)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    with patch("app.api.admin.get_admin_auth", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            await approve_lead(lead.id, db=db)

        assert exc_info.value.status_code == 400
