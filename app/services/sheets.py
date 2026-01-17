"""
Google Sheets logging service - logs leads and status updates to Google Sheets.

This service acts as the universal log for both Mode A (Sheets control) and Mode B (WhatsApp links).
Currently implemented as a stub that logs to console - can be swapped for real Google Sheets API.
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session
from app.db.models import Lead

logger = logging.getLogger(__name__)


def log_lead_to_sheets(db: Session, lead: Lead) -> bool:
    """
    Log or update a lead in Google Sheets (one row per lead).
    
    This is called:
    - When a new lead is created
    - When lead status changes
    - When admin actions occur
    - When deposit is paid
    
    Args:
        db: Database session
        lead: Lead object to log
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Get lead answers for summary
        answers = {}
        for answer in lead.answers:
            answers[answer.question_key] = answer.answer_text
        
        row_data = {
            "lead_id": lead.id,
            "wa_from": lead.wa_from,
            "status": lead.status,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
            "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
            
            # Location
            "location_city": lead.location_city,
            "location_country": lead.location_country,
            "region_bucket": lead.region_bucket,
            
            # Size and budget
            "size_category": lead.size_category,
            "size_measurement": lead.size_measurement,
            "budget_range_text": lead.budget_range_text,
            
            # Summary
            "summary_text": lead.summary_text,
            
            # Deposit status
            "deposit_amount_pence": lead.deposit_amount_pence,
            "deposit_status": lead.stripe_payment_status or "not_paid",
            "deposit_paid_at": lead.deposit_paid_at.isoformat() if lead.deposit_paid_at else None,
            "stripe_checkout_session_id": lead.stripe_checkout_session_id,
            
            # Booking
            "booking_link": lead.booking_link,
            "booking_tool": lead.booking_tool,
            "booking_link_sent_at": lead.booking_link_sent_at.isoformat() if lead.booking_link_sent_at else None,
            "booked_at": lead.booked_at.isoformat() if lead.booked_at else None,
            
            # Admin actions
            "approved_at": lead.approved_at.isoformat() if lead.approved_at else None,
            "rejected_at": lead.rejected_at.isoformat() if lead.rejected_at else None,
            "last_admin_action": lead.last_admin_action,
            "last_admin_action_at": lead.last_admin_action_at.isoformat() if lead.last_admin_action_at else None,
            "admin_notes": lead.admin_notes,
            
            # Key answers (for quick reference in sheet)
            "tattoo_idea": answers.get("tattoo_idea", ""),
            "placement": answers.get("placement", ""),
            "style": answers.get("style", ""),
            "preferred_timing": answers.get("preferred_timing", ""),
            
            # Timestamps
            "last_client_message_at": lead.last_client_message_at.isoformat() if lead.last_client_message_at else None,
            "last_bot_message_at": lead.last_bot_message_at.isoformat() if lead.last_bot_message_at else None,
        }
        
        logger.info(f"[SHEETS-STUB] Would log/update lead {lead.id} to Google Sheets: {row_data}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to log lead {lead.id} to Sheets: {e}")
        return False


def update_lead_status_in_sheets(db: Session, lead_id: int, status: str) -> bool:
    """
    Update only the status field for a lead in Google Sheets.
    Quick update for status changes.
    
    Args:
        db: Database session
        lead_id: Lead ID
        status: New status
        
    Returns:
        True if successful, False otherwise
    """
    try:
        lead = db.get(Lead, lead_id)
        if not lead:
            logger.warning(f"Lead {lead_id} not found for Sheets update")
            return False
        
        # For now, just log (stub)
        logger.info(f"[SHEETS-STUB] Would update lead {lead_id} status to '{status}' in Google Sheets")
        
        # When implementing real Google Sheets:
        # Find row by lead_id and update status column
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to update lead {lead_id} status in Sheets: {e}")
        return False
