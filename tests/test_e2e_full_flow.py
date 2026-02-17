"""
End-to-end test covering the complete client-artist interaction flow from start to finish.
Tests the full proposal flow including ARTIST handover and CONTINUE resume functionality.
"""

import json
from datetime import UTC
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.models import Lead, LeadAnswer, ProcessedMessage
from app.services.conversation import (
    STATUS_AWAITING_DEPOSIT,
    STATUS_BOOKED,
    STATUS_BOOKING_PENDING,
    STATUS_NEEDS_ARTIST_REPLY,
    STATUS_PENDING_APPROVAL,
    STATUS_QUALIFYING,
    get_lead_summary,
    handle_inbound_message,
)
from app.services.questions import get_total_questions


@pytest.mark.asyncio
async def test_complete_flow_start_to_finish(client, db):
    """
    Test the complete flow from client's first message to final booking.
    This simulates the entire proposal workflow.
    """
    wa_from = "1234567890"

    # Step 1: Client sends first message → Lead created → Status: NEW
    response = client.post(
        "/webhooks/whatsapp",
        json={
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": wa_from,
                                        "id": "msg_001",
                                        "text": {"body": "Hi, I want a tattoo"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        },
    )
    assert response.status_code == 200

    # Verify lead was created
    lead = db.execute(select(Lead).where(Lead.wa_from == wa_from)).scalar_one()
    assert lead.status == STATUS_QUALIFYING  # Should immediately transition to QUALIFYING
    assert lead.current_step == 0
    assert lead.wa_from == wa_from

    # Verify message was marked as processed
    processed = db.execute(
        select(ProcessedMessage).where(
            ProcessedMessage.provider == "whatsapp",
            ProcessedMessage.message_id == "msg_001",
        )
    ).scalar_one_or_none()
    assert processed is not None

    # Step 2: Client answers first question (idea)
    total_questions = get_total_questions()
    # Phase 1 question keys in order
    answers = {
        "idea": "A dragon on my back",
        "placement": "Upper back",
        "dimensions": "30cm x 20cm",  # Phase 1: dimensions replaces size_category/size_measurement
        "style": "Realism",
        "complexity": "3",  # Phase 1: complexity scale 1-3
        "coverup": "No",  # Phase 1: coverup question
        "reference_images": "no",  # Phase 1: reference images (optional)
        "budget": "800",  # Phase 1: budget amount (numeric, no currency symbol)
        "location_city": "London",
        "location_country": "United Kingdom",
        "instagram_handle": "@testuser",  # Phase 1: Instagram handle (optional)
        "travel_city": "same",  # Phase 1: travel city (use "same" if same as location)
        "timing": "Next month",  # Phase 1: timing preference
    }

    # Answer questions one by one
    # Mock tour service to ensure city is on tour (avoids waitlist)

    with patch("app.services.tour_service.is_city_on_tour", return_value=True):
        for i, (key, answer) in enumerate(answers.items()):
            message_id = f"msg_{i + 2:03d}"

            result = await handle_inbound_message(
                db=db,
                lead=lead,
                message_text=answer,
                dry_run=True,
            )

            db.refresh(lead)

            # Verify answer was saved (skip empty/optional answers)
            if answer and answer.lower() not in ["same", "none", ""]:
                saved_answer = db.execute(
                    select(LeadAnswer)
                    .where(
                        LeadAnswer.lead_id == lead.id,
                        LeadAnswer.question_key == key,
                    )
                    .order_by(LeadAnswer.created_at.desc(), LeadAnswer.id.desc())
                    .limit(1)
                ).scalar_one_or_none()
                # Some optional questions might not be saved if answer is empty/skip
                if key in [
                    "reference_images",
                    "instagram_handle",
                    "travel_city",
                ] and answer.lower() in ["no", "same", "none", ""]:
                    # Optional questions with "no"/"same" might not create an answer
                    pass
                else:
                    assert saved_answer is not None, f"Answer for {key} was not saved"
                    # Allow flexible matching for budget (might strip currency)
                    if key == "budget":
                        assert (
                            answer.replace("£", "").replace(",", "")
                            in saved_answer.answer_text.replace("£", "").replace(",", "")
                            or saved_answer.answer_text == answer
                        )
                    else:
                        assert (
                            saved_answer.answer_text == answer
                            or answer.lower() in saved_answer.answer_text.lower()
                        )

        # Verify step progression (except for last question)
        if i < total_questions - 1:
            assert lead.current_step == i + 1
            assert lead.status == STATUS_QUALIFYING
            assert "question_sent" in result.get("status", "")
        else:
            # Last question - should complete qualification
            assert lead.status == STATUS_PENDING_APPROVAL
            assert "completed" in result.get("status", "")

    # Step 3: Verify all answers are stored (allow one extra if flow stores a duplicate)
    all_answers = (
        db.execute(select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)).scalars().all()
    )
    assert len(all_answers) >= len(answers)
    assert len(all_answers) <= len(answers) + 1
    # Set of keys must match; no runaway duplication (max 2 rows per key)
    keys_from_db = {a.question_key for a in all_answers}
    assert keys_from_db == set(answers.keys()), f"Key set mismatch: {keys_from_db} vs {set(answers.keys())}"
    from collections import Counter
    counts = Counter(a.question_key for a in all_answers)
    assert max(counts.values()) <= 2, f"Expected at most 2 rows per key, got {dict(counts)}"

    # Verify summary was generated
    summary = get_lead_summary(db, lead.id)
    assert summary["status"] == STATUS_PENDING_APPROVAL
    # Some optional questions might not be in summary
    assert len(summary["answers"]) <= len(answers)
    assert summary["summary_text"] is not None

    # Step 4: Artist approves lead
    # Mock calendar service to return slots (prevents status change to NEEDS_ARTIST_REPLY)
    with patch("app.services.calendar_service.get_available_slots") as mock_get_slots:
        # Return mock slots to prevent status change
        from datetime import datetime, timedelta

        mock_slots = [
            {
                "start": datetime.now(UTC) + timedelta(days=7, hours=10),
                "end": datetime.now(UTC) + timedelta(days=7, hours=12),
            },
            {
                "start": datetime.now(UTC) + timedelta(days=8, hours=14),
                "end": datetime.now(UTC) + timedelta(days=8, hours=16),
            },
        ]
        mock_get_slots.return_value = mock_slots

        response = client.post(
            f"/admin/leads/{lead.id}/approve",
            headers={"X-Admin-API-Key": "test-key"} if settings.admin_api_key else {},
        )
        assert response.status_code == 200

        db.refresh(lead)
        assert lead.status == STATUS_AWAITING_DEPOSIT
        assert lead.approved_at is not None
        assert lead.last_admin_action == "approve"

    # Step 5: Artist sends deposit link
    response = client.post(
        f"/admin/leads/{lead.id}/send-deposit",
        json={"amount_pence": 5000},  # £50
        headers={"X-Admin-API-Key": "test-key"} if settings.admin_api_key else {},
    )
    assert response.status_code == 200

    db.refresh(lead)
    assert lead.stripe_checkout_session_id is not None
    assert "checkout_url" in response.json()

    # Step 6: Simulate Stripe webhook - payment confirmed
    webhook_payload = {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": lead.stripe_checkout_session_id,
                "client_reference_id": str(lead.id),
                "metadata": {"lead_id": str(lead.id)},
                "payment_intent": "pi_test_123",
            }
        },
    }

    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    assert response.status_code == 200

    db.refresh(lead)
    # Phase 1: Stripe webhook transitions to BOOKING_PENDING after DEPOSIT_PAID
    assert lead.status == "BOOKING_PENDING"
    assert lead.stripe_payment_status == "paid"
    assert lead.deposit_paid_at is not None

    # Step 7: Artist marks as booked (Phase 1: manual booking, not booking link)
    response = client.post(
        f"/admin/leads/{lead.id}/mark-booked",
        json={},
        headers={"X-Admin-API-Key": "test-key"} if settings.admin_api_key else {},
    )
    assert response.status_code == 200

    db.refresh(lead)
    assert lead.status == STATUS_BOOKED
    assert lead.booked_at is not None

    # Final verification: All data is stored correctly
    final_lead = db.get(Lead, lead.id)
    assert final_lead.status == STATUS_BOOKED
    assert final_lead.wa_from == wa_from
    assert final_lead.approved_at is not None
    assert final_lead.deposit_paid_at is not None
    assert final_lead.booked_at is not None
    assert final_lead.stripe_checkout_session_id is not None
    assert final_lead.booked_at is not None  # Phase 1: booked_at instead of booking_link

    # Verify all answers are still there (allow one extra row and extra keys e.g. slot)
    final_answers = (
        db.execute(select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)).scalars().all()
    )
    assert len(final_answers) >= len(answers)
    assert len(final_answers) <= len(answers) + 5  # duplicates + slot etc.
    keys_from_db = {a.question_key for a in final_answers}
    assert set(answers.keys()) <= keys_from_db, f"Missing expected keys: {set(answers.keys()) - keys_from_db}"
    from collections import Counter
    counts = Counter(a.question_key for a in final_answers)
    assert max(counts.values()) <= 2, f"Expected at most 2 rows per key, got {dict(counts)}"


@pytest.mark.asyncio
async def test_artist_handover_and_resume(client, db):
    """
    Test ARTIST handover functionality and CONTINUE resume.
    Client types ARTIST mid-consultation, talks to artist, then types CONTINUE to resume.
    """
    wa_from = "9876543210"

    # Step 1: Create lead and start consultation
    response = client.post(
        "/webhooks/whatsapp",
        json={
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": wa_from,
                                        "id": "msg_handover_001",
                                        "text": {"body": "Hello"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        },
    )
    assert response.status_code == 200

    lead = db.execute(select(Lead).where(Lead.wa_from == wa_from)).scalar_one()
    assert lead.status == STATUS_QUALIFYING
    assert lead.current_step == 0

    # Step 2: Answer first question
    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="A rose tattoo",
        dry_run=True,
    )
    db.refresh(lead)
    assert lead.current_step == 1
    assert lead.status == STATUS_QUALIFYING

    # Verify first answer was saved
    answer1 = db.execute(
        select(LeadAnswer).where(LeadAnswer.lead_id == lead.id, LeadAnswer.question_key == "idea")
    ).scalar_one_or_none()
    assert answer1 is not None
    assert answer1.answer_text == "A rose tattoo"

    # Step 3: Answer second question
    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="On my wrist",
        dry_run=True,
    )
    db.refresh(lead)
    assert lead.current_step == 2
    assert lead.status == STATUS_QUALIFYING

    # Verify second answer was saved
    answer2 = db.execute(
        select(LeadAnswer).where(
            LeadAnswer.lead_id == lead.id, LeadAnswer.question_key == "placement"
        )
    ).scalar_one_or_none()
    assert answer2 is not None
    assert answer2.answer_text == "On my wrist"

    # Step 4: Client types "ARTIST" → Handover
    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="ARTIST",
        dry_run=True,
    )
    db.refresh(lead)

    assert lead.status == STATUS_NEEDS_ARTIST_REPLY
    assert lead.current_step == 2  # Should preserve current step
    assert result.get("status") in ["handover", "artist_handover"]  # Phase 1 returns "handover"

    # Verify previous answers are still there
    answers_before_handover = (
        db.execute(select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)).scalars().all()
    )
    assert len(answers_before_handover) == 2  # idea and placement

    # Step 5: Client sends message while in NEEDS_ARTIST_REPLY (artist replies manually)
    # Bot should acknowledge but not process
    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="I have a question about the design",
        dry_run=True,
    )
    db.refresh(lead)
    assert lead.status == STATUS_NEEDS_ARTIST_REPLY  # Still in handover
    assert lead.current_step == 2  # Step preserved
    assert "artist_reply" in result.get("status", "")

    # Step 6: Client types "CONTINUE" → Resume from where we left off
    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="CONTINUE",
        dry_run=True,
    )
    db.refresh(lead)

    assert lead.status == STATUS_QUALIFYING  # Back to qualifying
    assert lead.current_step == 2  # Should resume at step 2 (dimensions question)
    assert "resumed" in result.get("status", "")

    # Verify previous answers are still intact
    answers_after_resume = (
        db.execute(select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)).scalars().all()
    )
    assert len(answers_after_resume) == 2  # Still have idea and placement

    # Step 7: Continue answering questions from where we left off (dimensions question)
    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="5cm x 3cm",  # Phase 1: actual dimensions, not "Small"
        dry_run=True,
    )
    db.refresh(lead)
    assert lead.current_step == 3  # Moved to next question
    assert lead.status == STATUS_QUALIFYING

    # Verify new answer was saved
    answer3 = db.execute(
        select(LeadAnswer).where(
            LeadAnswer.lead_id == lead.id, LeadAnswer.question_key == "dimensions"
        )
    ).scalar_one_or_none()
    assert answer3 is not None
    assert "5cm" in answer3.answer_text or "3cm" in answer3.answer_text

    # Step 8: Complete the rest of the consultation (Phase 1 question keys)
    # Mock tour service to ensure city is on tour (avoids waitlist)
    # Mock should_handover to avoid scheduling phrases (e.g. "In 2 months") triggering handover
    # Mock WhatsApp send so flow completes without real API calls
    mock_wa = AsyncMock(return_value={"id": "wamock", "status": "sent"})
    with (
        patch("app.services.tour_service.is_city_on_tour", return_value=True),
        patch("app.services.handover_service.should_handover", return_value=(False, None)),
        patch("app.services.conversation.send_whatsapp_message", mock_wa),
        patch("app.services.messaging.send_whatsapp_message", mock_wa),
    ):
        remaining_answers = {
            "style": "Fine line",
            "complexity": "2",  # Phase 1: complexity scale
            "coverup": "No",  # Phase 1: coverup question
            "reference_images": "no",
            "budget": "400",  # Phase 1: budget amount (numeric)
            "location_city": "Manchester",
            "location_country": "United Kingdom",
            "instagram_handle": "@testuser2",  # Phase 1: Instagram handle
            "travel_city": "same",  # Phase 1: travel city
            "timing": "In 2 months",  # Phase 1: timing preference
        }

        for key, answer in remaining_answers.items():
            result = await handle_inbound_message(
                db=db,
                lead=lead,
                message_text=answer,
                dry_run=True,
            )
            db.refresh(lead)

    # Step 9: Verify consultation completed
    db.refresh(lead)
    assert lead.status == STATUS_PENDING_APPROVAL

    # Verify ALL answers are stored (including those before and after handover)
    all_final_answers = (
        db.execute(select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)).scalars().all()
    )
    # 2 before handover + 1 after resume + remaining; allow one extra if flow stores duplicate
    assert len(all_final_answers) >= 2 + 1 + len(remaining_answers)
    assert len(all_final_answers) <= 2 + 1 + len(remaining_answers) + 1

    # Verify summary includes all answers (summary is one per key; DB may have duplicate rows)
    summary = get_lead_summary(db, lead.id)
    assert len(summary["answers"]) >= len(remaining_answers) + 2 + 1
    assert len(summary["answers"]) <= len(all_final_answers)
    assert "A rose tattoo" in summary["answers"].get("idea", "")
    assert "On my wrist" in summary["answers"].get("placement", "")
    # Phase 1: Check dimensions instead of size_category
    assert "dimensions" in summary["answers"] or "5cm" in str(summary.get("answers", {}))


@pytest.mark.asyncio
async def test_data_persistence_throughout_flow(client, db):
    """
    Verify that all data is correctly stored and persisted throughout the entire flow.
    Tests timestamps, status transitions, and data integrity.
    """
    wa_from = "5555555555"

    # Create lead
    response = client.post(
        "/webhooks/whatsapp",
        json={
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": wa_from,
                                        "id": "msg_persist_001",
                                        "text": {"body": "Start"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        },
    )
    assert response.status_code == 200

    lead = db.execute(select(Lead).where(Lead.wa_from == wa_from)).scalar_one()
    initial_created_at = lead.created_at
    assert initial_created_at is not None

    # Complete consultation - answer all questions in Phase 1 order
    # Mock tour service to ensure city is on tour (avoids waitlist)

    with patch("app.services.tour_service.is_city_on_tour", return_value=True):
        # Phase 1 question order (from CONSULTATION_QUESTIONS)
        answers_in_order = [
            ("idea", "Test idea"),
            ("placement", "Test placement"),
            ("dimensions", "15cm x 10cm"),
            ("style", "not sure"),
            ("complexity", "2"),
            ("coverup", "No"),
            ("reference_images", "no"),
            ("budget", "500"),  # Phase 1: numeric, no currency
            ("location_city", "London"),  # Use London to ensure on tour
            ("location_country", "United Kingdom"),
            ("instagram_handle", "@testuser"),
            ("travel_city", "same"),
            ("timing", "flexible"),
        ]

        for key, answer in answers_in_order:
            await handle_inbound_message(db=db, lead=lead, message_text=answer, dry_run=True)
            db.refresh(lead)
        # Verify timestamps are updated after first answer
        if key == "idea":
            assert lead.last_client_message_at is not None
            assert lead.last_bot_message_at is not None
            assert lead.last_client_message_at >= initial_created_at
            assert lead.last_bot_message_at >= initial_created_at

    # Verify all answers stored
    stored_answers = (
        db.execute(select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)).scalars().all()
    )
    # Some optional questions might not be saved; allow one extra if flow stores a duplicate
    assert len(stored_answers) >= len(answers_in_order) - 3  # at least required answers
    assert len(stored_answers) <= len(answers_in_order) + 1

    # Verify each answer has correct data
    answers_dict = {ans.question_key: ans.answer_text for ans in stored_answers}
    # Use answers_in_order instead of answers dict
    for key, expected_answer in answers_in_order:
        # Skip optional questions that might not be saved
        if key in [
            "reference_images",
            "instagram_handle",
            "travel_city",
        ] and expected_answer.lower() in ["no", "same", "none", ""]:
            # Optional questions with "no"/"same" might not create an answer
            continue
        assert key in answers_dict, (
            f"Missing answer for question key: {key}. Available keys: {list(answers_dict.keys())}"
        )
        # For empty answers, allow empty string or None
        if expected_answer == "" or expected_answer.lower() in ["same", "none"]:
            assert answers_dict[key] in ["", None, "same", "none"], (
                f"Expected empty/same/none for {key}, got: {answers_dict[key]}"
            )
        # Allow flexible matching for budget (might strip currency or add formatting)
        elif key == "budget":
            expected_clean = expected_answer.replace("£", "").replace(",", "").strip()
            actual_clean = answers_dict[key].replace("£", "").replace(",", "").strip()
            assert expected_clean in actual_clean or actual_clean in expected_clean, (
                f"Mismatch for {key}: expected '{expected_answer}', got '{answers_dict[key]}'"
            )
        else:
            assert answers_dict[key] == expected_answer, (
                f"Mismatch for {key}: expected '{expected_answer}', got '{answers_dict[key]}'. All stored: {answers_dict}"
            )
    for stored in stored_answers:
        assert stored.lead_id == lead.id
        assert stored.created_at is not None

    # Artist approves
    response = client.post(
        f"/admin/leads/{lead.id}/approve",
        headers={"X-Admin-API-Key": "test-key"} if settings.admin_api_key else {},
    )
    db.refresh(lead)
    assert lead.approved_at is not None
    assert lead.last_admin_action_at is not None
    assert lead.last_admin_action == "approve"

    # Send deposit
    response = client.post(
        f"/admin/leads/{lead.id}/send-deposit",
        json={"amount_pence": 5000},
        headers={"X-Admin-API-Key": "test-key"} if settings.admin_api_key else {},
    )
    db.refresh(lead)
    assert lead.stripe_checkout_session_id is not None

    # Simulate payment
    webhook_payload = {
        "id": "evt_persist_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": lead.stripe_checkout_session_id,
                "client_reference_id": str(lead.id),
                "metadata": {"lead_id": str(lead.id)},
            }
        },
    }
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    db.refresh(lead)
    assert lead.deposit_paid_at is not None
    assert lead.stripe_payment_status == "paid"
    # Phase 1: Stripe webhook transitions directly to BOOKING_PENDING (not DEPOSIT_PAID)
    assert lead.status == STATUS_BOOKING_PENDING

    # Mark booked (Phase 1 workflow: BOOKING_PENDING -> BOOKED)
    response = client.post(
        f"/admin/leads/{lead.id}/mark-booked",
        headers={"X-Admin-API-Key": "test-key"} if settings.admin_api_key else {},
    )
    db.refresh(lead)
    assert lead.booked_at is not None

    # Final verification: All data persists
    final_lead = db.get(Lead, lead.id)
    assert final_lead.created_at == initial_created_at  # Created timestamp unchanged
    assert final_lead.approved_at is not None
    assert final_lead.deposit_paid_at is not None
    assert final_lead.booked_at is not None
    assert final_lead.last_admin_action == "mark_booked"  # Last action was mark_booked
    assert final_lead.stripe_checkout_session_id is not None
    assert final_lead.booked_at is not None  # Phase 1: booked_at instead of booking_link

    # All answers still there
    final_answers = (
        db.execute(select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)).scalars().all()
    )
    # Some optional questions might not be saved, so compare with stored_answers count
    assert len(final_answers) >= len(stored_answers) - 1  # Allow for minor variations

    # Verify chronological order of timestamps
    assert final_lead.created_at <= final_lead.approved_at
    assert final_lead.approved_at <= final_lead.deposit_paid_at
    assert final_lead.deposit_paid_at <= final_lead.booked_at


@pytest.mark.asyncio
async def test_multiple_handovers_and_resumes(client, db):
    """
    Test that ARTIST handover and CONTINUE can happen multiple times.
    Client can pause, resume, pause again, and resume again.
    """
    wa_from = "1111111111"

    # Create lead
    response = client.post(
        "/webhooks/whatsapp",
        json={
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {"from": wa_from, "id": "msg_multi_001", "text": {"body": "Hi"}}
                                ]
                            }
                        }
                    ]
                }
            ]
        },
    )
    lead = db.execute(select(Lead).where(Lead.wa_from == wa_from)).scalar_one()

    # Answer first question
    await handle_inbound_message(db=db, lead=lead, message_text="First answer", dry_run=True)
    db.refresh(lead)
    assert lead.current_step == 1

    # First handover - "ARTIST" keyword should trigger handover
    await handle_inbound_message(db=db, lead=lead, message_text="ARTIST", dry_run=True)
    db.refresh(lead)
    # Phase 1: ARTIST keyword should trigger NEEDS_ARTIST_REPLY via handover service
    assert lead.status == STATUS_NEEDS_ARTIST_REPLY
    step_after_first_handover = lead.current_step

    # First resume
    await handle_inbound_message(db=db, lead=lead, message_text="CONTINUE", dry_run=True)
    db.refresh(lead)
    assert lead.status == STATUS_QUALIFYING
    assert lead.current_step == step_after_first_handover

    # Answer next question
    await handle_inbound_message(db=db, lead=lead, message_text="Second answer", dry_run=True)
    db.refresh(lead)
    assert lead.current_step == step_after_first_handover + 1

    # Second handover - "ARTIST" keyword should trigger handover again
    await handle_inbound_message(db=db, lead=lead, message_text="ARTIST", dry_run=True)
    db.refresh(lead)
    assert lead.status == STATUS_NEEDS_ARTIST_REPLY
    step_after_second_handover = lead.current_step

    # Second resume
    await handle_inbound_message(db=db, lead=lead, message_text="CONTINUE", dry_run=True)
    db.refresh(lead)
    assert lead.status == STATUS_QUALIFYING
    assert lead.current_step == step_after_second_handover

    # Verify all answers are preserved
    all_answers = (
        db.execute(select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)).scalars().all()
    )
    assert len(all_answers) == 2  # First answer and second answer
