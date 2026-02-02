"""
Handover packet service - builds comprehensive context packet for artist handover.

The handover packet includes:
- Last 5 inbound messages
- Parse failures
- Size/budget/location
- Category + deposit + price range
- Tour conversion context
- Status + current question key
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Lead, LeadAnswer
from app.services.questions import get_question_by_index

logger = logging.getLogger(__name__)


def build_handover_packet(db: Session, lead: Lead) -> dict:
    """
    Build a comprehensive handover packet for artist review.

    Args:
        db: Database session
        lead: Lead object

    Returns:
        dict with all handover context
    """
    # Get last 5 inbound messages (most recent first; use id when created_at ties)
    stmt = (
        select(LeadAnswer)
        .where(LeadAnswer.lead_id == lead.id)
        .order_by(LeadAnswer.created_at.desc(), LeadAnswer.id.desc())
        .limit(5)
    )
    recent_answers = db.execute(stmt).scalars().all()

    last_messages = []
    for answer in reversed(recent_answers):  # Oldest first
        last_messages.append(
            {
                "question_key": answer.question_key,
                "answer_text": answer.answer_text,
                "created_at": answer.created_at.isoformat() if answer.created_at else None,
            }
        )

    # Get parse failures
    parse_failures = {}
    if lead.parse_failure_counts:
        parse_failures = {k: v for k, v in lead.parse_failure_counts.items() if v > 0}

    # Get size/budget/location from answers (ordered so latest-wins per key)
    stmt_answers = (
        select(LeadAnswer)
        .where(LeadAnswer.lead_id == lead.id)
        .order_by(LeadAnswer.created_at, LeadAnswer.id)
    )
    answers_list = db.execute(stmt_answers).scalars().all()
    answers_dict = {a.question_key: a.answer_text for a in answers_list}

    # Get current question key
    current_question_key = None
    if lead.current_step is not None:
        try:
            current_question = get_question_by_index(lead.current_step)
            if current_question:
                current_question_key = current_question.key
        except (IndexError, AttributeError):
            pass

    # Build tour conversion context
    tour_context = {
        "requested_city": lead.requested_city,
        "requested_country": lead.requested_country,
        "offered_tour_city": lead.offered_tour_city,
        "offered_tour_dates_text": lead.offered_tour_dates_text,
        "tour_offer_accepted": lead.tour_offer_accepted,
        "waitlisted": lead.waitlisted or False,
    }

    # Client name from answers (for artist context)
    client_name = answers_dict.get("name") or answers_dict.get("client_name")
    if client_name:
        client_name = str(client_name).strip() or None

    # Build packet
    packet = {
        "lead_id": lead.id,
        "wa_from": lead.wa_from,
        "client_name": client_name,
        "status": lead.status,
        "current_step": lead.current_step,
        "current_question_key": current_question_key,
        "handover_reason": lead.handover_reason,
        "last_messages": last_messages,
        "parse_failures": parse_failures,
        "size": {
            "dimensions": answers_dict.get("dimensions", ""),
            "size_category": lead.size_category,
            "size_measurement": lead.size_measurement,
        },
        "budget": {
            "budget_text": answers_dict.get("budget", ""),
            "budget_amount_pence": None,  # Will be parsed if available
            "min_budget_amount_pence": lead.min_budget_amount,
            "below_min_budget": lead.below_min_budget or False,
        },
        "location": {
            "location_city": lead.location_city,
            "location_country": lead.location_country,
            "region_bucket": lead.region_bucket,
        },
        "category": lead.estimated_category,
        "deposit_amount_pence": lead.estimated_deposit_amount,
        "deposit_locked_amount_pence": lead.deposit_amount_pence,
        "deposit_amount_locked_at": lead.deposit_amount_locked_at.isoformat()
        if lead.deposit_amount_locked_at
        else None,
        "price_range_min_pence": lead.estimated_price_min_pence,
        "price_range_max_pence": lead.estimated_price_max_pence,
        "tour_context": tour_context,
        "complexity_level": lead.complexity_level,
        "coverup": answers_dict.get("coverup", "").upper() in ["YES", "Y", "TRUE", "1"],
        "instagram_handle": lead.instagram_handle,
        "preferred_handover_channel": lead.preferred_handover_channel,
        "call_availability_notes": lead.call_availability_notes,
        "admin_notes": lead.admin_notes,
        "timestamps": {
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
            "qualifying_started_at": lead.qualifying_started_at.isoformat()
            if lead.qualifying_started_at
            else None,
            "qualifying_completed_at": lead.qualifying_completed_at.isoformat()
            if lead.qualifying_completed_at
            else None,
            "needs_artist_reply_at": lead.needs_artist_reply_at.isoformat()
            if lead.needs_artist_reply_at
            else None,
        },
    }

    # Parse budget amount if available
    budget_text = answers_dict.get("budget", "")
    if budget_text:
        try:
            import re

            budget_clean = budget_text.replace("£", "").replace("$", "").replace(",", "").strip()
            match = re.search(r"\d+\.?\d*", budget_clean)
            if match:
                budget_gbp = float(match.group())
                packet["budget"]["budget_amount_pence"] = int(budget_gbp * 100)
        except (ValueError, AttributeError):
            pass

    return packet
