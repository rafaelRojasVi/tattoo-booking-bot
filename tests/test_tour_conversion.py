"""
Focused tests for tour conversion and waitlist logic.

Tests the tour branch without full E2E flow to keep E2E stable.
"""

from datetime import UTC
from unittest.mock import AsyncMock, patch

import pytest

from app.services.conversation import (
    STATUS_PENDING_APPROVAL,
    STATUS_QUALIFYING,
    STATUS_TOUR_CONVERSION_OFFERED,
    STATUS_WAITLISTED,
    handle_inbound_message,
)
from app.services.leads import get_or_create_lead


@pytest.mark.asyncio
async def test_city_not_on_tour_offers_conversion(db):
    """
    Test that city not on tour triggers tour conversion offer.

    Scenario:
    - Client requests city not on tour
    - System offers closest upcoming tour city
    - Lead transitions to TOUR_CONVERSION_OFFERED
    """
    wa_from = "9999999999"

    # Patch both: conversation uses module-level import; _maybe_send_confirmation_summary imports from messaging
    mock_whatsapp_fn = AsyncMock(return_value={"id": "wamock_123", "status": "sent"})
    with (
        patch("app.services.messaging.messaging.send_whatsapp_message", mock_whatsapp_fn),
        patch("app.services.messaging.messaging.send_whatsapp_message", mock_whatsapp_fn),
        patch("app.services.conversation.tour_service.is_city_on_tour", return_value=False),
        patch("app.services.conversation.tour_service.closest_upcoming_city") as mock_closest,
        patch(
            "app.services.conversation.handover_service.should_handover", return_value=(False, None)
        ),
    ):
        mock_whatsapp = mock_whatsapp_fn

        # Mock closest city to return a tour stop
        from datetime import datetime, timedelta

        from app.services.conversation.tour_service import TourStop

        mock_tour_stop = TourStop(
            city="Manchester",
            country="UK",
            start_date=datetime.now(UTC) + timedelta(days=30),
            end_date=datetime.now(UTC) + timedelta(days=35),
        )
        mock_closest.return_value = mock_tour_stop

        # Create lead and go through qualification
        lead = get_or_create_lead(db, wa_from)
        await handle_inbound_message(db, lead, "Hi", dry_run=False)

        # Answer questions up to travel_city
        answers = [
            "Dragon tattoo",  # idea
            "Arm",  # placement
            "10x15cm",  # dimensions
            "Realism",  # style
            "2",  # complexity
            "No",  # coverup
            "no",  # reference_images
            "500",  # budget
            "Birmingham",  # location_city (not on tour)
            "UK",  # location_country
            "@handle",  # instagram_handle
            "Birmingham",  # travel_city (not on tour - will trigger conversion)
            "Next 2-4 weeks",  # timing
        ]

        for answer in answers:
            await handle_inbound_message(db, lead, answer, dry_run=False)
            db.refresh(lead)

        # Should be in TOUR_CONVERSION_OFFERED status
        assert lead.status == STATUS_TOUR_CONVERSION_OFFERED
        assert lead.offered_tour_city == "Manchester"
        assert mock_whatsapp_fn.called


@pytest.mark.asyncio
async def test_tour_offer_declined_waitlisted(db):
    """
    Test that declining tour offer results in WAITLISTED status.

    Scenario:
    - Lead is in TOUR_CONVERSION_OFFERED
    - Client declines offer
    - Lead transitions to WAITLISTED
    """
    wa_from = "8888888888"

    with patch(
        "app.services.messaging.messaging.send_whatsapp_message", new_callable=AsyncMock
    ) as mock_whatsapp:
        mock_whatsapp.return_value = {"id": "wamock_123", "status": "sent"}

        # Create lead in TOUR_CONVERSION_OFFERED status
        lead = get_or_create_lead(db, wa_from)
        lead.status = STATUS_TOUR_CONVERSION_OFFERED
        lead.requested_city = "Birmingham"
        lead.offered_tour_city = "Manchester"
        db.commit()
        db.refresh(lead)

        # Client declines offer
        result = await handle_inbound_message(db, lead, "no", dry_run=False)
        db.refresh(lead)

        assert lead.status == STATUS_WAITLISTED
        assert lead.waitlisted is True
        assert lead.requested_city == "Birmingham"  # Original city preserved


@pytest.mark.asyncio
async def test_tour_offer_accepted_continues(db):
    """
    Test that accepting tour offer continues qualification.

    Scenario:
    - Lead is in TOUR_CONVERSION_OFFERED
    - Client accepts offer
    - Qualification continues and completes
    """
    wa_from = "7777777777"

    with (
        patch(
            "app.services.messaging.messaging.send_whatsapp_message", new_callable=AsyncMock
        ) as mock_whatsapp,
        patch("app.services.conversation.tour_service.is_city_on_tour", return_value=True),
        patch(
            "app.services.conversation.handover_service.should_handover", return_value=(False, None)
        ),
    ):
        mock_whatsapp.return_value = {"id": "wamock_123", "status": "sent"}

        # Create lead in TOUR_CONVERSION_OFFERED status
        lead = get_or_create_lead(db, wa_from)
        lead.status = STATUS_TOUR_CONVERSION_OFFERED
        lead.requested_city = "Birmingham"
        lead.offered_tour_city = "Manchester"
        lead.tour_offer_accepted = None
        db.commit()
        db.refresh(lead)

        # Client accepts offer
        result = await handle_inbound_message(db, lead, "yes", dry_run=False)
        db.refresh(lead)

        # Should continue to PENDING_APPROVAL (if all questions answered)
        # Or remain in QUALIFYING if more questions needed
        assert lead.status in [STATUS_QUALIFYING, STATUS_PENDING_APPROVAL]
        assert lead.tour_offer_accepted is True
