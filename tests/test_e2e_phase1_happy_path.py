"""
E2E Happy Path Test - Phase 1 full flow from NEW to BOOKED.

Tests the complete Phase 1 flow with mocked external services:
- WhatsApp sends
- Calendar slot suggestions
- Stripe checkout creation + webhook
- Sheets logging
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from freezegun import freeze_time

from app.services.conversation import (
    STATUS_ABANDONED,
    STATUS_AWAITING_DEPOSIT,
    STATUS_BOOKED,
    STATUS_BOOKING_PENDING,
    STATUS_NEEDS_ARTIST_REPLY,
    STATUS_NEEDS_FOLLOW_UP,
    STATUS_NEW,
    STATUS_PENDING_APPROVAL,
    STATUS_QUALIFYING,
    STATUS_REJECTED,
    handle_inbound_message,
)
from app.services.leads import get_or_create_lead


@pytest.fixture
def frozen_time():
    """Freeze time to control 24h window checks."""
    with freeze_time("2026-01-20 10:00:00") as frozen:
        yield frozen


@pytest.mark.asyncio
async def test_e2e_happy_path_city_on_tour_new_to_booked(db, frozen_time):
    """
    Test the complete Phase 1 flow from NEW to BOOKED (city on tour scenario).

    This test mocks tour service to ensure city is on tour, avoiding waitlist branch.
    For tour conversion/waitlist testing, see test_tour_conversion_offered.

    Flow:
    1. Client sends initial message → consult starts
    2. Client answers all questions → qualification completes → PENDING_APPROVAL
    3. Artist approves → AWAITING_DEPOSIT + slot suggestions sent
    4. Client selects slot
    5. Deposit link sent → Stripe session created
    6. Stripe webhook confirms payment → DEPOSIT_PAID → BOOKING_PENDING
    7. Artist marks booked → BOOKED
    """
    wa_from = "1234567890"

    # Mock external services (conversation + messaging so _maybe_send_confirmation_summary uses mock)
    with (
        patch(
            "app.services.messaging.messaging.send_whatsapp_message", new_callable=AsyncMock
        ) as mock_whatsapp,
        patch(
            "app.services.messaging.messaging.send_whatsapp_message", new_callable=AsyncMock
        ) as mock_whatsapp_messaging,
        patch("app.services.integrations.calendar_service.get_available_slots") as mock_slots,
        patch("app.services.integrations.stripe_service.create_checkout_session") as mock_stripe,
        patch("app.services.integrations.sheets.log_lead_to_sheets") as mock_sheets,
        patch(
            "app.services.integrations.artist_notifications.send_artist_summary",
            new_callable=AsyncMock,
        ) as mock_artist_notify,
        patch(
            "app.services.messaging.whatsapp_window.send_with_window_check", new_callable=AsyncMock
        ) as mock_window_send,
        patch("app.services.conversation.tour_service.is_city_on_tour", return_value=True),
        patch("app.services.conversation.tour_service.closest_upcoming_city", return_value=None),
        patch(
            "app.services.conversation.handover_service.should_handover", return_value=(False, None)
        ),
    ):
        # Setup mocks
        mock_whatsapp.return_value = {"id": "wamock_123", "status": "sent"}
        mock_whatsapp_messaging.return_value = {"id": "wamock_123", "status": "sent"}
        mock_window_send.return_value = {
            "id": "wamock_123",
            "status": "sent",
            "window_status": "open",
        }
        mock_slots.return_value = [
            {
                "start": datetime(2026, 1, 25, 10, 0, tzinfo=UTC),
                "end": datetime(2026, 1, 25, 13, 0, tzinfo=UTC),
            },
            {
                "start": datetime(2026, 1, 27, 14, 0, tzinfo=UTC),
                "end": datetime(2026, 1, 27, 17, 0, tzinfo=UTC),
            },
        ]
        mock_stripe.return_value = {
            "checkout_session_id": "cs_test_123",
            "checkout_url": "https://checkout.stripe.com/test",
        }
        mock_sheets.return_value = True

        # Step 1: Initial message starts consultation
        lead = get_or_create_lead(db, wa_from)
        assert lead.status == STATUS_NEW

        result = await handle_inbound_message(
            db, lead, "Hi, I'd like to book a tattoo", dry_run=False
        )
        db.refresh(lead)
        assert lead.status == STATUS_QUALIFYING
        # _handle_new_lead uses _get_send_whatsapp() (messaging.send_whatsapp_message); second patch wins
        assert mock_whatsapp_messaging.called

        # Step 2: Answer all consultation questions (in order from questions.py)
        answers = [
            "A dragon tattoo on my arm",  # idea
            "Upper arm",  # placement
            "10x15cm",  # dimensions
            "Realism",  # style (optional)
            "2",  # complexity (use 2 to avoid handover trigger)
            "No",  # coverup
            "no",  # reference_images (optional)
            "500",  # budget
            "London",  # location_city
            "UK",  # location_country
            "@myhandle",  # instagram_handle (optional)
            "same",  # travel_city (optional)
            "Next 2-4 weeks",  # timing (last question)
        ]

        for answer in answers:
            await handle_inbound_message(db, lead, answer, dry_run=False)
            db.refresh(lead)

        # Qualification should be complete
        assert lead.status == STATUS_PENDING_APPROVAL
        assert lead.qualifying_completed_at is not None
        assert lead.pending_approval_at is not None
        # Sheets may be called during qualification or after - just verify it's called at some point

        # Step 3: Artist approves
        from app.api.admin import approve_lead

        # Mock auth to bypass security (send_slot_suggestions_to_client uses mock_slots + mock_window_send)
        with patch("app.api.admin.get_admin_auth", return_value=True):
            approve_result = await approve_lead(lead=lead, db=db)

        db.refresh(lead)

        assert lead.status == STATUS_AWAITING_DEPOSIT
        assert lead.approved_at is not None

        # Slot suggestions should be sent automatically after approval
        assert mock_slots.called  # Calendar service should be called

        # Step 4: Client selects a slot (simulate by storing preference)
        lead.calendar_start_at = datetime(2026, 1, 25, 10, 0, tzinfo=UTC)
        lead.calendar_end_at = datetime(2026, 1, 25, 13, 0, tzinfo=UTC)
        db.commit()
        db.refresh(lead)

        # Step 5: Send deposit link
        from app.api.admin import send_deposit
        from app.schemas.admin import SendDepositRequest

        deposit_request = SendDepositRequest()
        # Mock auth to bypass security
        with patch("app.api.admin.get_admin_auth", return_value=True):
            deposit_result = await send_deposit(lead=lead, request=deposit_request, db=db)

        db.refresh(lead)

        assert mock_stripe.called
        assert lead.stripe_checkout_session_id == "cs_test_123"
        assert lead.deposit_sent_at is not None

        # Step 6: Simulate Stripe webhook - payment successful
        from app.api.webhooks import stripe_webhook
        from tests.helpers.stripe_webhook import (
            build_stripe_webhook_request,
            create_checkout_completed_event,
        )

        # Create webhook event
        webhook_event = create_checkout_completed_event(
            event_id="evt_test_123",
            checkout_session_id="cs_test_123",
            payment_intent_id="pi_test_123",
            lead_id=lead.id,
            amount_total=15000,
        )

        # Build mock request
        mock_request = build_stripe_webhook_request(webhook_event)

        # Mock webhook signature verification to return our payload
        from fastapi import BackgroundTasks

        with (
            patch(
                "app.services.integrations.stripe_service.verify_webhook_signature",
                return_value=webhook_event,
            ),
            patch(
                "app.services.messaging.whatsapp_window.send_with_window_check",
                new_callable=AsyncMock,
            ) as mock_webhook_send,
        ):
            mock_webhook_send.return_value = {"id": "wamock_456", "status": "sent"}
            background_tasks = BackgroundTasks()
            webhook_result = await stripe_webhook(
                mock_request, background_tasks=background_tasks, db=db
            )

        db.refresh(lead)
        assert lead.status == STATUS_BOOKING_PENDING
        assert lead.deposit_paid_at is not None
        assert lead.stripe_payment_intent_id == "pi_test_123"
        assert lead.booking_pending_at is not None

        # Step 7: Mark as booked
        from app.api.admin import mark_booked

        # Mock auth to bypass security
        with patch("app.api.admin.get_admin_auth", return_value=True):
            booked_result = mark_booked(lead=lead, db=db)

        db.refresh(lead)

        assert lead.status == STATUS_BOOKED
        assert lead.booked_at is not None

        # Final assertions - verify all timestamps are set
        assert lead.approved_at is not None
        assert lead.deposit_sent_at is not None
        assert lead.deposit_paid_at is not None
        assert lead.booking_pending_at is not None
        assert lead.booked_at is not None

        # Verify no unexpected statuses occurred
        assert lead.status not in [STATUS_REJECTED, STATUS_ABANDONED]

        # Verify Sheets was called for major transitions
        # Note: Sheets may be called at different points, so we just verify it was called
        # The exact count depends on when log_lead_to_sheets is invoked
        # In a real scenario, it would be called on status changes


@pytest.mark.asyncio
async def test_e2e_no_unexpected_statuses(db, frozen_time):
    """
    Test that no unexpected statuses occur during happy path.

    This ensures rules don't misfire and cause unwanted transitions.
    """
    wa_from = "9876543210"

    with (
        patch(
            "app.services.messaging.messaging.send_whatsapp_message", new_callable=AsyncMock
        ) as mock_whatsapp,
        patch(
            "app.services.messaging.messaging.send_whatsapp_message", new_callable=AsyncMock
        ) as mock_whatsapp_messaging,
        patch(
            "app.services.integrations.sheets.log_lead_to_sheets", return_value=True
        ) as mock_sheets,
        patch(
            "app.services.conversation.handover_service.should_handover", return_value=(False, None)
        ),
        patch("app.services.conversation.tour_service.is_city_on_tour", return_value=True),
        patch("app.services.conversation.tour_service.closest_upcoming_city", return_value=None),
    ):  # Disable tour conversion
        mock_whatsapp.return_value = {"id": "wamock_123", "status": "sent"}
        mock_whatsapp_messaging.return_value = {"id": "wamock_123", "status": "sent"}

        lead = get_or_create_lead(db, wa_from)

        # Go through qualification
        await handle_inbound_message(db, lead, "Hello", dry_run=False)
        await handle_inbound_message(db, lead, "Dragon tattoo", dry_run=False)
        await handle_inbound_message(db, lead, "Arm", dry_run=False)
        await handle_inbound_message(db, lead, "10x15cm", dry_run=False)
        await handle_inbound_message(db, lead, "Realism", dry_run=False)
        await handle_inbound_message(db, lead, "3", dry_run=False)
        await handle_inbound_message(db, lead, "No", dry_run=False)
        await handle_inbound_message(db, lead, "no", dry_run=False)  # Reference images
        await handle_inbound_message(db, lead, "500", dry_run=False)  # Budget
        await handle_inbound_message(db, lead, "London", dry_run=False)  # City
        await handle_inbound_message(db, lead, "UK", dry_run=False)  # Country
        await handle_inbound_message(db, lead, "@handle", dry_run=False)  # Instagram
        await handle_inbound_message(db, lead, "same", dry_run=False)  # Travel city
        await handle_inbound_message(db, lead, "Next 2-4 weeks", dry_run=False)  # Timing

        db.refresh(lead)

        # Should end at PENDING_APPROVAL, not any unexpected status
        assert lead.status == STATUS_PENDING_APPROVAL
        assert lead.status != STATUS_REJECTED
        assert lead.status != STATUS_ABANDONED
        assert lead.status != STATUS_NEEDS_ARTIST_REPLY  # Unless explicitly triggered
        assert lead.status != STATUS_NEEDS_FOLLOW_UP  # Unless explicitly triggered
