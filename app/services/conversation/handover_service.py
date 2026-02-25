"""
Handover service - determines when to hand over to artist (dynamic triggers).
"""

import logging

from app.db.models import Lead

logger = logging.getLogger(__name__)


def should_handover(
    message: str,
    lead: Lead,
    lead_context: dict | None = None,
) -> tuple[bool, str | None]:
    """
    Determine if message/context should trigger artist handover.

    Args:
        message: Current message text
        lead: Lead object with context
        lead_context: Optional additional context dict

    Returns:
        Tuple of (should_handover: bool, reason: str | None)
    """
    message_upper = message.upper().strip()

    # Trigger 0: Explicit ARTIST keyword (backward compatibility)
    if message_upper == "ARTIST":
        return True, "Client requested artist handover"

    # Trigger 1: High complexity (complexity_level == 3, realism, coverup)
    if lead.complexity_level == 3:
        return True, "High complexity/realism project requires artist assessment"

    # Check if coverup (from answers or flag)
    # This would need to be checked from LeadAnswer or a flag
    # For now, check message for coverup keywords
    coverup_keywords = ["cover", "coverup", "cover-up", "rework", "touch up", "touchup"]
    if any(keyword.upper() in message_upper for keyword in coverup_keywords):
        return True, "Cover-up/rework requires creative assessment"

    # Trigger 2: Client asking lots of off-script questions
    # This would require tracking question count - simplified for Phase 1
    # Can check if message contains question marks and is long
    if "?" in message and len(message) > 100:
        # Multiple questions or complex question
        question_indicators = [
            "how much",
            "how long",
            "can i",
            "what if",
            "is it possible",
            "do you",
            "will you",
            "when can",
            "where can",
        ]
        if any(indicator.upper() in message_upper for indicator in question_indicators):
            return True, "Complex questions require artist response"

    # Trigger 3: High purchase intent + hesitation
    # Phrases like "I'm ready but...", "I want to but...", "I'm interested but..."
    hesitation_phrases = [
        "i'm ready but",
        "i want to but",
        "i'm interested but",
        "i'd like to but",
        "i'm thinking but",
        "i'm considering but",
    ]
    if any(phrase.upper() in message_upper for phrase in hesitation_phrases):
        return True, "Client hesitation requires personal touch"

    # Trigger 4: Question outside predefined booking logic
    # Price negotiation attempts
    price_negotiation = [
        "cheaper",
        "discount",
        "lower price",
        "can you do",
        "best price",
        "negotiate",
        "deal",
        "offer",
    ]
    if any(phrase.upper() in message_upper for phrase in price_negotiation):
        return True, "Price negotiation - bot cannot handle"

    # Request for specific artist availability or scheduling details
    scheduling_requests = [
        "when are you available",
        "what dates",
        "your schedule",
        "when can you",
        "next available",
        "earliest appointment",
    ]
    if any(phrase.upper() in message_upper for phrase in scheduling_requests):
        return True, "Specific scheduling questions require artist"

    # Default: no handover
    return False, None


def get_handover_message(reason: str, lead_id: int | None = None) -> str:
    """
    Get handover message for client.

    Args:
        reason: Reason for handover
        lead_id: Lead ID for deterministic variant selection

    Returns:
        Formatted message
    """
    from app.services.messaging.message_composer import render_message

    # Select message key based on reason
    if "cover" in reason.lower() or "coverup" in reason.lower():
        return render_message("handover_coverup", lead_id=lead_id)
    elif "question" in reason.lower() or "clarify" in reason.lower():
        return render_message("handover_question", lead_id=lead_id)
    else:
        return render_message("handover_generic", lead_id=lead_id)
