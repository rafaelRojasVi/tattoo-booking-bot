"""
Tests for admin action endpoints (approve, reject, send-deposit, send-booking-link, mark-booked).
"""

from app.db.models import Lead
from app.services.conversation import (
    STATUS_AWAITING_DEPOSIT,
    STATUS_BOOKED,
    STATUS_BOOKING_LINK_SENT,
    STATUS_DEPOSIT_PAID,
    STATUS_PENDING_APPROVAL,
    STATUS_QUALIFYING,
    STATUS_REJECTED,
)


def test_approve_lead_success(client, db):
    """Test approving a lead transitions from PENDING_APPROVAL to AWAITING_DEPOSIT."""
    # Create lead in PENDING_APPROVAL
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    response = client.post(f"/admin/leads/{lead.id}/approve")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == STATUS_AWAITING_DEPOSIT

    # Verify database changes
    db.refresh(lead)
    assert lead.status == STATUS_AWAITING_DEPOSIT
    assert lead.approved_at is not None
    assert lead.last_admin_action == "approve"
    assert lead.last_admin_action_at is not None


def test_approve_lead_wrong_status(client, db):
    """Test that approve fails if lead is not in PENDING_APPROVAL."""
    # Create lead in QUALIFYING
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    response = client.post(f"/admin/leads/{lead.id}/approve")
    assert response.status_code == 400
    assert STATUS_PENDING_APPROVAL in response.json()["detail"]


def test_approve_lead_not_found(client, db):
    """Test that approve returns 404 for non-existent lead."""
    response = client.post("/admin/leads/99999/approve")
    assert response.status_code == 404


def test_reject_lead_success(client, db):
    """Test rejecting a lead transitions to REJECTED."""
    # Create lead in PENDING_APPROVAL
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    response = client.post(f"/admin/leads/{lead.id}/reject", json={"reason": "Budget too low"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == STATUS_REJECTED

    # Verify database changes
    db.refresh(lead)
    assert lead.status == STATUS_REJECTED
    assert lead.rejected_at is not None
    assert lead.last_admin_action == "reject"
    assert lead.last_admin_action_at is not None
    assert "Budget too low" in lead.admin_notes


def test_reject_lead_without_reason(client, db):
    """Test rejecting a lead without providing a reason."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    response = client.post(f"/admin/leads/{lead.id}/reject", json={})
    assert response.status_code == 200
    db.refresh(lead)
    assert lead.status == STATUS_REJECTED


def test_reject_lead_already_rejected(client, db):
    """Test that rejecting an already rejected lead fails."""
    lead = Lead(wa_from="1234567890", status=STATUS_REJECTED)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    response = client.post(f"/admin/leads/{lead.id}/reject", json={})
    assert response.status_code == 400
    assert "already rejected" in response.json()["detail"].lower()


def test_reject_lead_booked_fails(client, db):
    """Test that rejecting a booked lead fails."""
    lead = Lead(wa_from="1234567890", status=STATUS_BOOKED)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    response = client.post(f"/admin/leads/{lead.id}/reject", json={})
    assert response.status_code == 400
    assert "booked" in response.json()["detail"].lower()


def test_send_deposit_success(client, db):
    """Test sending deposit link transitions status and sets amount."""
    from unittest.mock import MagicMock, patch

    # Create lead in AWAITING_DEPOSIT
    lead = Lead(wa_from="1234567890", status=STATUS_AWAITING_DEPOSIT)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Mock Stripe checkout session creation
    mock_session = MagicMock()
    mock_session.id = "cs_test_123"
    mock_session.url = "https://checkout.stripe.com/test/cs_test_123"

    with patch("app.services.stripe_service.stripe.checkout.Session.create") as mock_stripe_create:
        mock_stripe_create.return_value = mock_session

        response = client.post(f"/admin/leads/{lead.id}/send-deposit", json={"amount_pence": 5000})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["deposit_amount_pence"] == 5000

        # Verify database changes
        db.refresh(lead)
        assert lead.deposit_amount_pence == 5000
        assert lead.last_admin_action == "send_deposit"
        assert lead.last_admin_action_at is not None
        # Status should remain AWAITING_DEPOSIT until payment confirmed
        assert lead.status == STATUS_AWAITING_DEPOSIT


def test_send_deposit_wrong_status(client, db):
    """Test that send-deposit fails if lead is not in AWAITING_DEPOSIT."""
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    response = client.post(f"/admin/leads/{lead.id}/send-deposit", json={})
    assert response.status_code == 400
    assert STATUS_AWAITING_DEPOSIT in response.json()["detail"]


def test_send_booking_link_success(client, db):
    """Test sending booking link transitions from DEPOSIT_PAID to BOOKING_LINK_SENT."""
    # Create lead in DEPOSIT_PAID
    lead = Lead(wa_from="1234567890", status=STATUS_DEPOSIT_PAID)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    booking_url = "https://fresha.com/book/123"
    response = client.post(
        f"/admin/leads/{lead.id}/send-booking-link",
        json={"booking_url": booking_url, "booking_tool": "FRESHA"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == STATUS_BOOKING_LINK_SENT
    assert data["booking_link"] == booking_url

    # Verify database changes
    db.refresh(lead)
    assert lead.status == STATUS_BOOKING_LINK_SENT
    assert lead.booking_link == booking_url
    assert lead.booking_tool == "FRESHA"
    assert lead.booking_link_sent_at is not None
    assert lead.last_admin_action == "send_booking_link"


def test_send_booking_link_wrong_status(client, db):
    """Test that send-booking-link fails if lead is not in DEPOSIT_PAID."""
    lead = Lead(wa_from="1234567890", status=STATUS_AWAITING_DEPOSIT)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    response = client.post(
        f"/admin/leads/{lead.id}/send-booking-link",
        json={"booking_url": "https://test.com", "booking_tool": "FRESHA"},
    )
    assert response.status_code == 400
    assert STATUS_DEPOSIT_PAID in response.json()["detail"]


def test_mark_booked_success(client, db):
    """Test marking lead as booked transitions from BOOKING_LINK_SENT to BOOKED."""
    # Create lead in BOOKING_LINK_SENT
    lead = Lead(wa_from="1234567890", status=STATUS_BOOKING_LINK_SENT)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    response = client.post(f"/admin/leads/{lead.id}/mark-booked")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == STATUS_BOOKED

    # Verify database changes
    db.refresh(lead)
    assert lead.status == STATUS_BOOKED
    assert lead.booked_at is not None
    assert lead.last_admin_action == "mark_booked"
    assert lead.last_admin_action_at is not None


def test_mark_booked_wrong_status(client, db):
    """Test that mark-booked fails if lead is not in BOOKING_PENDING (Phase 1)."""
    lead = Lead(wa_from="1234567890", status=STATUS_DEPOSIT_PAID)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    response = client.post(f"/admin/leads/{lead.id}/mark-booked")
    assert response.status_code == 400
    assert "BOOKING_PENDING" in response.json()["detail"]


def test_all_admin_actions_require_auth(client, db, monkeypatch):
    """Test that all admin action endpoints require authentication when API key is set."""
    from unittest.mock import patch

    # Create test lead
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Mock settings to require API key
    with patch("app.api.auth.settings.admin_api_key", "test-key"):
        # Test all endpoints without auth
        endpoints = [
            ("POST", f"/admin/leads/{lead.id}/approve", {}),
            ("POST", f"/admin/leads/{lead.id}/reject", {}),
            ("POST", f"/admin/leads/{lead.id}/send-deposit", {}),
            (
                "POST",
                f"/admin/leads/{lead.id}/send-booking-link",
                {"booking_url": "https://test.com", "booking_tool": "FRESHA"},
            ),
            ("POST", f"/admin/leads/{lead.id}/mark-booked", {}),
        ]

        for method, endpoint, json_data in endpoints:
            if method == "POST":
                response = client.post(endpoint, json=json_data)
            assert response.status_code == 401, f"{endpoint} should require auth"

        # Test with auth
        headers = {"X-Admin-API-Key": "test-key"}
        response = client.post(f"/admin/leads/{lead.id}/approve", headers=headers)
        assert response.status_code == 200


def test_complete_workflow(client, db):
    """Test a complete workflow: approve -> send-deposit -> (webhook would set DEPOSIT_PAID) -> send-booking-link -> mark-booked."""
    # Start with PENDING_APPROVAL
    lead = Lead(wa_from="1234567890", status=STATUS_PENDING_APPROVAL)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # 1. Approve
    response = client.post(f"/admin/leads/{lead.id}/approve")
    assert response.status_code == 200
    db.refresh(lead)
    assert lead.status == STATUS_AWAITING_DEPOSIT

    # 2. Send deposit (simulate - in real flow, Stripe webhook would set DEPOSIT_PAID)
    response = client.post(f"/admin/leads/{lead.id}/send-deposit", json={"amount_pence": 5000})
    assert response.status_code == 200
    db.refresh(lead)
    assert lead.deposit_amount_pence == 5000

    # 3. Simulate deposit paid (manually set status - in real flow, Stripe webhook does this)
    from sqlalchemy import func

    lead.status = STATUS_DEPOSIT_PAID
    lead.deposit_paid_at = func.now()
    db.commit()
    db.refresh(lead)

    # 4. Send booking link
    response = client.post(
        f"/admin/leads/{lead.id}/send-booking-link",
        json={"booking_url": "https://fresha.com/book/123", "booking_tool": "FRESHA"},
    )
    assert response.status_code == 200
    db.refresh(lead)
    assert lead.status == STATUS_BOOKING_LINK_SENT

    # 5. Mark booked
    response = client.post(f"/admin/leads/{lead.id}/mark-booked")
    assert response.status_code == 200
    db.refresh(lead)
    assert lead.status == STATUS_BOOKED
    assert lead.booked_at is not None
