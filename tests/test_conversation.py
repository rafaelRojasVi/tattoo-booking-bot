import pytest
from app.db.models import Lead, LeadAnswer
from app.services.conversation import (
    handle_inbound_message,
    get_lead_summary,
    STATUS_NEW,
    STATUS_QUALIFYING,
    STATUS_PENDING_APPROVAL,
    STATUS_AWAITING_DEPOSIT,
    STATUS_DEPOSIT_PAID,
    STATUS_BOOKING_LINK_SENT,
    STATUS_BOOKED,
    STATUS_NEEDS_ARTIST_REPLY,
    STATUS_REJECTED,
    STATUS_ABANDONED,
    STATUS_STALE,
)
from app.services.questions import get_total_questions


@pytest.mark.asyncio
async def test_new_lead_starts_qualification(client, db):
    """Test that a new lead starts the qualification flow."""
    # Create a new lead
    lead = Lead(wa_from="1234567890", status=STATUS_NEW, current_step=0)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    # Handle first message
    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="Hello, I want a tattoo",
        dry_run=True,
    )
    
    # Should transition to QUALIFYING
    db.refresh(lead)
    assert lead.status == STATUS_QUALIFYING
    assert lead.current_step == 0
    assert result["status"] == "question_sent"
    assert "question_key" in result
    assert result["question_key"] == "idea"  # First question


@pytest.mark.asyncio
async def test_qualifying_lead_saves_answer_and_asks_next(client, db):
    """Test that qualifying lead saves answer and asks next question."""
    # Create lead in QUALIFYING state
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=0)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    # Answer first question
    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="I want a dragon tattoo",
        dry_run=True,
    )
    
    # Should save answer and move to next question
    db.refresh(lead)
    assert lead.status == STATUS_QUALIFYING
    assert lead.current_step == 1
    assert result["status"] == "question_sent"
    assert result["saved_answer"]["question"] == "idea"
    assert result["saved_answer"]["answer"] == "I want a dragon tattoo"
    
    # Check answer was saved
    answers = db.query(LeadAnswer).filter(LeadAnswer.lead_id == lead.id).all()
    assert len(answers) == 1
    assert answers[0].question_key == "idea"
    assert answers[0].answer_text == "I want a dragon tattoo"


@pytest.mark.asyncio
async def test_complete_qualification_flow(client, db):
    """Test completing the full qualification flow."""
    # Create lead in QUALIFYING state at last question
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_QUALIFYING,
        current_step=get_total_questions() - 1,  # Last question
    )
    db.add(lead)
    db.commit()
    
    # Add previous answers
    previous_questions = ["idea", "placement", "size", "style", "budget_range", "reference_images"]
    for i, q_key in enumerate(previous_questions):
        answer = LeadAnswer(
            lead_id=lead.id,
            question_key=q_key,
            answer_text=f"Answer for {q_key}",
        )
        db.add(answer)
    db.commit()
    db.refresh(lead)
    
    # Answer last question
    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="Monday and Wednesday afternoons",
        dry_run=True,
    )
    
    # Should complete and move to PENDING_APPROVAL (not AWAITING_DEPOSIT)
    db.refresh(lead)
    assert lead.status == STATUS_PENDING_APPROVAL
    assert result["status"] == "completed"
    assert "summary" in result
    # Note: Updated question count due to new questions (location, size_category, etc.)


@pytest.mark.asyncio
async def test_awaiting_deposit_acknowledges_message(client, db):
    """Test that leads in AWAITING_DEPOSIT state are acknowledged."""
    lead = Lead(
        wa_from="1234567890",
        status=STATUS_AWAITING_DEPOSIT,
        current_step=get_total_questions(),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    result = await handle_inbound_message(
        db=db,
        lead=lead,
        message_text="When can I pay?",
        dry_run=True,
    )
    
    assert result["status"] == "awaiting_deposit"
    assert "deposit" in result["message"].lower()


def test_get_lead_summary_with_answers(client, db):
    """Test getting lead summary with answers."""
    # Create lead with answers
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=2)
    db.add(lead)
    db.commit()
    
    # Add some answers
    answers_data = [
        ("idea", "Dragon tattoo"),
        ("placement", "Left arm"),
    ]
    for q_key, answer_text in answers_data:
        answer = LeadAnswer(
            lead_id=lead.id,
            question_key=q_key,
            answer_text=answer_text,
        )
        db.add(answer)
    db.commit()
    
    # Get summary
    summary = get_lead_summary(db, lead.id)
    
    assert summary["lead_id"] == lead.id
    assert summary["status"] == STATUS_QUALIFYING
    assert summary["current_step"] == 2
    assert len(summary["answers"]) == 2
    assert summary["answers"]["idea"] == "Dragon tattoo"
    assert summary["answers"]["placement"] == "Left arm"


def test_get_lead_summary_not_found(client, db):
    """Test getting summary for non-existent lead."""
    summary = get_lead_summary(db, 99999)
    assert "error" in summary
    assert summary["error"] == "Lead not found"


@pytest.mark.asyncio
async def test_webhook_integration_new_lead(client, db):
    """Test webhook integration with new lead."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "text": {"body": "Hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    data = response.json()
    
    assert data["received"] is True
    assert "conversation" in data
    assert data["conversation"]["status"] == "question_sent"
    
    # Check lead was created and updated
    lead = db.query(Lead).filter(Lead.wa_from == "1234567890").first()
    assert lead is not None
    assert lead.status == STATUS_QUALIFYING


@pytest.mark.asyncio
async def test_webhook_integration_qualifying_lead(client, db):
    """Test webhook integration with qualifying lead."""
    # Create existing lead in QUALIFYING
    lead = Lead(wa_from="1234567890", status=STATUS_QUALIFYING, current_step=0)
    db.add(lead)
    db.commit()
    
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "text": {"body": "I want a rose tattoo"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    
    response = client.post("/webhooks/whatsapp", json=payload)
    assert response.status_code == 200
    data = response.json()
    
    assert data["received"] is True
    assert "conversation" in data
    assert data["conversation"]["status"] == "question_sent"
    
    # Check answer was saved
    db.refresh(lead)
    answers = db.query(LeadAnswer).filter(LeadAnswer.lead_id == lead.id).all()
    assert len(answers) == 1
    assert answers[0].question_key == "idea"
