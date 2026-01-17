"""
End-to-end test covering the complete client-artist interaction flow from start to finish.
Tests the full proposal flow including ARTIST handover and CONTINUE resume functionality.
"""
import pytest
import json
from unittest.mock import patch, AsyncMock
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.models import Lead, LeadAnswer, ProcessedMessage
from app.core.config import settings
from app.services.conversation import (
    STATUS_NEW,
    STATUS_QUALIFYING,
    STATUS_PENDING_APPROVAL,
    STATUS_AWAITING_DEPOSIT,
    STATUS_DEPOSIT_PAID,
    STATUS_BOOKING_LINK_SENT,
    STATUS_BOOKED,
    STATUS_NEEDS_ARTIST_REPLY,
    handle_inbound_message,
    get_lead_summary,
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
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": wa_from,
                            "id": "msg_001",
                            "text": {"body": "Hi, I want a tattoo"}
                        }]
                    }
                }]
            }]
        }
    )
    assert response.status_code == 200
    
    # Verify lead was created
    lead = db.execute(select(Lead).where(Lead.wa_from == wa_from)).scalar_one()
    assert lead.status == STATUS_QUALIFYING  # Should immediately transition to QUALIFYING
    assert lead.current_step == 0
    assert lead.wa_from == wa_from
    
    # Verify message was marked as processed
    processed = db.execute(
        select(ProcessedMessage).where(ProcessedMessage.message_id == "msg_001")
    ).scalar_one_or_none()
    assert processed is not None
    
    # Step 2: Client answers first question (idea)
    total_questions = get_total_questions()
    answers = {
        "idea": "A dragon on my back",
        "placement": "Upper back",
        "size_category": "Large",
        "size_measurement": "30cm x 20cm",
        "style": "Realism",
        "location_city": "London",
        "location_country": "United Kingdom",
        "budget_range": "£500-£1000",
        "reference_images": "no",
        "preferred_timing": "Next month",
    }
    
    # Answer questions one by one
    for i, (key, answer) in enumerate(answers.items()):
        message_id = f"msg_{i+2:03d}"
        
        result = await handle_inbound_message(
            db=db,
            lead=lead,
            message_text=answer,
            dry_run=True,
        )
        
        db.refresh(lead)
        
        # Verify answer was saved
        saved_answer = db.execute(
            select(LeadAnswer).where(
                LeadAnswer.lead_id == lead.id,
                LeadAnswer.question_key == key
            )
        ).scalar_one_or_none()
        assert saved_answer is not None
        assert saved_answer.answer_text == answer
        
        # Verify step progression (except for last question)
        if i < total_questions - 1:
            assert lead.current_step == i + 1
            assert lead.status == STATUS_QUALIFYING
            assert "question_sent" in result.get("status", "")
        else:
            # Last question - should complete qualification
            assert lead.status == STATUS_PENDING_APPROVAL
            assert "completed" in result.get("status", "")
    
    # Step 3: Verify all answers are stored
    all_answers = db.execute(
        select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)
    ).scalars().all()
    assert len(all_answers) == len(answers)
    
    # Verify summary was generated
    summary = get_lead_summary(db, lead.id)
    assert summary["status"] == STATUS_PENDING_APPROVAL
    assert len(summary["answers"]) == len(answers)
    assert summary["summary_text"] is not None
    
    # Step 4: Artist approves lead
    response = client.post(
        f"/admin/leads/{lead.id}/approve",
        headers={"X-Admin-API-Key": "test-key"} if settings.admin_api_key else {}
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
        headers={"X-Admin-API-Key": "test-key"} if settings.admin_api_key else {}
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
        }
    }
    
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    assert response.status_code == 200
    
    db.refresh(lead)
    assert lead.status == STATUS_DEPOSIT_PAID
    assert lead.stripe_payment_status == "paid"
    assert lead.deposit_paid_at is not None
    
    # Step 7: Artist sends booking link
    response = client.post(
        f"/admin/leads/{lead.id}/send-booking-link",
        json={"booking_url": "https://fresha.com/book/abc123", "booking_tool": "FRESHA"},
        headers={"X-Admin-API-Key": "test-key"} if settings.admin_api_key else {}
    )
    assert response.status_code == 200
    
    db.refresh(lead)
    assert lead.status == STATUS_BOOKING_LINK_SENT
    assert lead.booking_link == "https://fresha.com/book/abc123"
    
    # Step 8: Artist marks as booked
    response = client.post(
        f"/admin/leads/{lead.id}/mark-booked",
        headers={"X-Admin-API-Key": "test-key"} if settings.admin_api_key else {}
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
    assert final_lead.booking_link is not None
    
    # Verify all answers are still there
    final_answers = db.execute(
        select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)
    ).scalars().all()
    assert len(final_answers) == len(answers)


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
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": wa_from,
                            "id": "msg_handover_001",
                            "text": {"body": "Hello"}
                        }]
                    }
                }]
            }]
        }
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
        select(LeadAnswer).where(
            LeadAnswer.lead_id == lead.id,
            LeadAnswer.question_key == "idea"
        )
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
            LeadAnswer.lead_id == lead.id,
            LeadAnswer.question_key == "placement"
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
    assert "artist_handover" in result.get("status", "")
    
    # Verify previous answers are still there
    answers_before_handover = db.execute(
        select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)
    ).scalars().all()
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
    assert lead.current_step == 2  # Should resume at step 2 (size_category question)
    assert "resumed" in result.get("status", "")
    
    # Verify previous answers are still intact
    answers_after_resume = db.execute(
        select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)
    ).scalars().all()
    assert len(answers_after_resume) == 2  # Still have idea and placement
    
    # Step 7: Continue answering questions from where we left off
    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="Small",
        dry_run=True,
    )
    db.refresh(lead)
    assert lead.current_step == 3  # Moved to next question
    assert lead.status == STATUS_QUALIFYING
    
    # Verify new answer was saved
    answer3 = db.execute(
        select(LeadAnswer).where(
            LeadAnswer.lead_id == lead.id,
            LeadAnswer.question_key == "size_category"
        )
    ).scalar_one_or_none()
    assert answer3 is not None
    assert answer3.answer_text == "Small"
    
    # Step 8: Complete the rest of the consultation
    remaining_answers = {
        "size_measurement": "5cm",
        "style": "Fine line",
        "location_city": "Manchester",
        "location_country": "United Kingdom",
        "budget_range": "£200-£400",
        "reference_images": "no",
        "preferred_timing": "In 2 months",
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
    all_final_answers = db.execute(
        select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)
    ).scalars().all()
    assert len(all_final_answers) == 2 + 1 + len(remaining_answers)  # 2 before handover + 1 after resume + remaining
    
    # Verify summary includes all answers
    summary = get_lead_summary(db, lead.id)
    assert len(summary["answers"]) == len(all_final_answers)
    assert "A rose tattoo" in summary["answers"].get("idea", "")
    assert "On my wrist" in summary["answers"].get("placement", "")
    assert "Small" in summary["answers"].get("size_category", "")


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
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": wa_from,
                            "id": "msg_persist_001",
                            "text": {"body": "Start"}
                        }]
                    }
                }]
            }]
        }
    )
    assert response.status_code == 200
    
    lead = db.execute(select(Lead).where(Lead.wa_from == wa_from)).scalar_one()
    initial_created_at = lead.created_at
    assert initial_created_at is not None
    
    # Complete consultation - answer all questions
    answers = {
        "idea": "Test idea",
        "placement": "Test placement",
        "size_category": "Medium",
        "size_measurement": "skip",
        "style": "not sure",
        "location_city": "Test City",
        "location_country": "Test Country",
        "budget_range": "£300-£600",
        "reference_images": "no",
        "preferred_timing": "flexible",
    }
    
    for key, answer in answers.items():
        await handle_inbound_message(db=db, lead=lead, message_text=answer, dry_run=True)
        db.refresh(lead)
        # Verify timestamps are updated after first answer
        if key == "idea":
            assert lead.last_client_message_at is not None
            assert lead.last_bot_message_at is not None
            assert lead.last_client_message_at >= initial_created_at
            assert lead.last_bot_message_at >= initial_created_at
    
    # Verify all answers stored
    stored_answers = db.execute(
        select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)
    ).scalars().all()
    assert len(stored_answers) == len(answers)
    
    # Verify each answer has correct data
    answers_dict = {ans.question_key: ans.answer_text for ans in stored_answers}
    for key, expected_answer in answers.items():
        assert key in answers_dict
        assert answers_dict[key] == expected_answer
    for stored in stored_answers:
        assert stored.lead_id == lead.id
        assert stored.created_at is not None
    
    # Artist approves
    response = client.post(
        f"/admin/leads/{lead.id}/approve",
        headers={"X-Admin-API-Key": "test-key"} if settings.admin_api_key else {}
    )
    db.refresh(lead)
    assert lead.approved_at is not None
    assert lead.last_admin_action_at is not None
    assert lead.last_admin_action == "approve"
    
    # Send deposit
    response = client.post(
        f"/admin/leads/{lead.id}/send-deposit",
        json={"amount_pence": 5000},
        headers={"X-Admin-API-Key": "test-key"} if settings.admin_api_key else {}
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
        }
    }
    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(webhook_payload).encode("utf-8"),
        headers={"stripe-signature": "test_signature"},
    )
    db.refresh(lead)
    assert lead.deposit_paid_at is not None
    assert lead.stripe_payment_status == "paid"
    
    # Send booking link
    response = client.post(
        f"/admin/leads/{lead.id}/send-booking-link",
        json={"booking_url": "https://test.com/book", "booking_tool": "FRESHA"},
        headers={"X-Admin-API-Key": "test-key"} if settings.admin_api_key else {}
    )
    db.refresh(lead)
    assert lead.booking_link == "https://test.com/book"
    
    # Mark booked
    response = client.post(
        f"/admin/leads/{lead.id}/mark-booked",
        headers={"X-Admin-API-Key": "test-key"} if settings.admin_api_key else {}
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
    assert final_lead.booking_link is not None
    
    # All answers still there
    final_answers = db.execute(
        select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)
    ).scalars().all()
    assert len(final_answers) == len(answers)
    
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
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": wa_from,
                            "id": "msg_multi_001",
                            "text": {"body": "Hi"}
                        }]
                    }
                }]
            }]
        }
    )
    lead = db.execute(select(Lead).where(Lead.wa_from == wa_from)).scalar_one()
    
    # Answer first question
    await handle_inbound_message(db=db, lead=lead, message_text="First answer", dry_run=True)
    db.refresh(lead)
    assert lead.current_step == 1
    
    # First handover
    await handle_inbound_message(db=db, lead=lead, message_text="ARTIST", dry_run=True)
    db.refresh(lead)
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
    
    # Second handover
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
    all_answers = db.execute(
        select(LeadAnswer).where(LeadAnswer.lead_id == lead.id)
    ).scalars().all()
    assert len(all_answers) == 2  # First answer and second answer
