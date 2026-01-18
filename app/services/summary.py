"""
Summary formatting service - extracts and formats lead summaries for artist review.
"""

import logging

from app.db.models import Lead

logger = logging.getLogger(__name__)


def extract_phase1_summary_context(lead: Lead) -> dict:
    """
    Extract normalized Phase 1 summary context from a lead.

    Args:
        lead: Lead object

    Returns:
        Dict with all summary fields (safe getters, no KeyErrors)
    """
    # Get answers
    answers = {}
    for answer in lead.answers:
        answers[answer.question_key] = answer.answer_text

    # Parse budget
    budget_text = answers.get("budget", "")
    budget_amount = None
    if budget_text:
        try:
            import re

            budget_clean = budget_text.replace("£", "").replace("$", "").replace(",", "").strip()
            match = re.search(r"\d+\.?\d*", budget_clean)
            if match:
                budget_gbp = float(match.group())
                budget_amount = int(budget_gbp * 100)  # Convert to pence
        except (ValueError, AttributeError):
            pass

    # Format complexity
    complexity_map = {1: "Simple", 2: "Medium", 3: "High detail"}
    complexity_display = complexity_map.get(
        lead.complexity_level, lead.complexity_level or "Not specified"
    )

    # Format deposit
    deposit_gbp = None
    if lead.estimated_deposit_amount:
        deposit_gbp = lead.estimated_deposit_amount / 100

    # Format min budget
    min_budget_gbp = None
    if lead.min_budget_amount:
        min_budget_gbp = lead.min_budget_amount / 100

    # Format budget display
    budget_display = ""
    if budget_amount:
        budget_gbp_display = budget_amount / 100
        budget_display = f"£{budget_gbp_display:.0f}"
        if min_budget_gbp:
            budget_display += f" (Min: £{min_budget_gbp:.0f})"
            if lead.below_min_budget:
                budget_display += " ⚠️ BELOW MIN"

    # Tour status
    tour_status = ""
    if lead.waitlisted:
        tour_status = f"Waitlisted for {lead.requested_city or 'requested city'}"
    elif lead.offered_tour_city:
        if lead.tour_offer_accepted:
            tour_status = f"Tour conversion accepted: {lead.offered_tour_city}"
        else:
            tour_status = f"Tour conversion offered: {lead.offered_tour_city} ({lead.offered_tour_dates_text or 'dates TBD'})"
    elif lead.requested_city and lead.requested_city != lead.location_city:
        tour_status = f"Requested city: {lead.requested_city}"
    else:
        tour_status = "On tour / Standard location"

    # Slot preference (if stored - Phase 1 manual booking)
    slot_preference = "Not selected yet"  # Phase 1: manual booking, no slot stored yet

    return {
        # Basic info
        "lead_id": lead.id,
        "idea": answers.get("idea", ""),
        "placement": answers.get("placement", ""),
        "dimensions": answers.get("dimensions", ""),
        "style": answers.get("style", ""),
        "complexity": complexity_display,
        "complexity_level": lead.complexity_level,
        "coverup": answers.get("coverup", "").upper() in ["YES", "Y", "TRUE", "1"],
        # Location
        "location_city": lead.location_city or "",
        "location_country": lead.location_country or "",
        "region_bucket": lead.region_bucket or "",
        "requested_city": lead.requested_city or "",
        # Budget & money
        "budget_text": budget_text,
        "budget_amount": budget_amount,
        "budget_display": budget_display,
        "min_budget_gbp": min_budget_gbp,
        "below_min_budget": lead.below_min_budget or False,
        # Estimation
        "estimated_category": lead.estimated_category or "",
        "estimated_deposit_amount": lead.estimated_deposit_amount,
        "deposit_gbp": deposit_gbp,
        # Social
        "instagram_handle": lead.instagram_handle or "",
        # Tour
        "tour_status": tour_status,
        "offered_tour_city": lead.offered_tour_city or "",
        "tour_offer_accepted": lead.tour_offer_accepted,
        "waitlisted": lead.waitlisted or False,
        # Booking
        "slot_preference": slot_preference,
        "calendar_event_id": lead.calendar_event_id or "",
        # Handover & notes
        "handover_reason": lead.handover_reason or "",
        "admin_notes": lead.admin_notes or "",
        # Timing
        "timing": answers.get("timing", ""),
        # Status
        "status": lead.status,
    }


def format_summary_message(ctx: dict) -> str:
    """
    Format a structured summary message from Phase 1 context.

    Args:
        ctx: Dict from extract_phase1_summary_context()

    Returns:
        Formatted summary string (WhatsApp-friendly)
    """
    lines = [
        f"🎨 *Lead #{ctx['lead_id']} — Ready for review*\n",
    ]

    # Idea (1-line summary)
    idea = ctx.get("idea", "")
    if idea:
        # Truncate to first line or 100 chars
        idea_short = idea.split("\n")[0][:100]
        if len(idea) > 100:
            idea_short += "..."
        lines.append(f"💭 *Idea:* {idea_short}\n")

    # Placement | Size | Complexity
    placement = ctx.get("placement", "")
    dimensions = ctx.get("dimensions", "")
    complexity = ctx.get("complexity", "")

    detail_parts = []
    if placement:
        detail_parts.append(f"Placement: {placement}")
    if dimensions:
        detail_parts.append(f"Size: {dimensions}")
    if complexity:
        detail_parts.append(f"Complexity: {complexity}")

    if detail_parts:
        lines.append(f"📍 {' | '.join(detail_parts)}")

    # Location
    city = ctx.get("location_city", "")
    country = ctx.get("location_country", "")
    region = ctx.get("region_bucket", "")

    location_parts = []
    if city and country:
        location_parts.append(f"{city}, {country}")
    elif city:
        location_parts.append(city)
    elif country:
        location_parts.append(country)

    if region:
        location_parts.append(f"({region})")

    if location_parts:
        lines.append(f"🌍 *Location:* {' '.join(location_parts)}")

    # Budget
    budget_display = ctx.get("budget_display", "")
    if budget_display:
        lines.append(f"💰 *Budget:* {budget_display}")

    # Instagram
    instagram = ctx.get("instagram_handle", "")
    if instagram:
        lines.append(f"📱 *IG:* {instagram}")

    # Estimate & Deposit
    category = ctx.get("estimated_category", "")
    deposit_gbp = ctx.get("deposit_gbp")

    if category:
        estimate_line = f"📊 *Estimate:* {category}"
        if deposit_gbp:
            estimate_line += f" | Deposit: £{deposit_gbp:.0f}"
        lines.append(estimate_line)

    # Tour
    tour_status = ctx.get("tour_status", "")
    if tour_status:
        lines.append(f"✈️ *Tour:* {tour_status}")

    # Slot preference
    slot_pref = ctx.get("slot_preference", "")
    if slot_pref and slot_pref != "Not selected yet":
        lines.append(f"📅 *Slot:* {slot_pref}")

    # Notes / Red flags
    notes_parts = []

    if ctx.get("coverup"):
        notes_parts.append("Cover-up")

    # Below min budget is already shown in budget line, but add to notes if needed
    if ctx.get("below_min_budget") and "BELOW MIN" not in ctx.get("budget_display", ""):
        notes_parts.append("Below minimum budget")

    handover_reason = ctx.get("handover_reason", "")
    if handover_reason:
        notes_parts.append(f"Handover: {handover_reason}")

    admin_notes = ctx.get("admin_notes", "")
    if admin_notes:
        notes_parts.append(admin_notes[:100])  # Truncate long notes

    if notes_parts:
        lines.append(f"⚠️ *Notes:* {', '.join(notes_parts)}")

    # Actions (will be added by artist_notifications when action tokens available)
    lines.append("")  # Blank line

    return "\n".join(lines)


def format_summary_message_legacy(answers: dict) -> str:
    """
    Legacy format_summary_message - kept for backward compatibility.
    Use format_summary_message() with extract_phase1_summary_context() instead.
    """
    # Convert old answer keys to new format for compatibility
    ctx = {
        "lead_id": 0,  # Not available in legacy
        "idea": answers.get("idea", ""),
        "placement": answers.get("placement", ""),
        "dimensions": answers.get("dimensions") or answers.get("size", ""),
        "style": answers.get("style", ""),
        "complexity": "",
        "location_city": "",
        "location_country": "",
        "region_bucket": "",
        "budget_display": answers.get("budget") or answers.get("budget_range", ""),
        "instagram_handle": "",
        "estimated_category": "",
        "deposit_gbp": None,
        "tour_status": "",
        "slot_preference": "",
        "handover_reason": "",
        "admin_notes": "",
        "coverup": False,
        "below_min_budget": False,
        "status": "",
    }

    return format_summary_message(ctx)
