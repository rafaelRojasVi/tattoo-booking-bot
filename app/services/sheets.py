"""
Google Sheets logging service - logs leads and status updates to Google Sheets.

This service acts as the universal log for both Mode A (Sheets control) and Mode B (WhatsApp links).
Implements real Google Sheets API integration with graceful fallback to stub if not configured.
"""

import json
import logging
import os

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Lead

logger = logging.getLogger(__name__)


def _get_sheets_service():
    """
    Get Google Sheets API service client.

    Returns:
        Google Sheets service object, or None if not configured
    """
    if not settings.google_sheets_enabled or not settings.google_sheets_spreadsheet_id:
        return None

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        # Load credentials
        credentials_json = settings.google_sheets_credentials_json
        if not credentials_json:
            logger.warning("Google Sheets enabled but credentials_json not set")
            return None

        # Parse credentials (can be file path or JSON string)
        if os.path.exists(credentials_json):
            # File path
            credentials = service_account.Credentials.from_service_account_file(
                credentials_json, scopes=["https://www.googleapis.com/auth/spreadsheets"]
            )
        else:
            # Try parsing as JSON string
            try:
                creds_dict = json.loads(credentials_json)
                credentials = service_account.Credentials.from_service_account_info(
                    creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"]
                )
            except json.JSONDecodeError:
                logger.error(
                    "Google Sheets credentials_json is neither a valid file path nor JSON string"
                )
                return None

        # Build service
        service = build("sheets", "v4", credentials=credentials)
        return service

    except ImportError:
        logger.warning(
            "Google Sheets API libraries not installed. Install with: pip install google-api-python-client google-auth"
        )
        return None
    except Exception as e:
        logger.error(f"Failed to initialize Google Sheets service: {e}")
        return None


def _parse_budget_amount(answers: dict[str, str]) -> int | None:
    """Parse budget amount from answers (in pence)."""
    budget_text = answers.get("budget", "")
    if not budget_text:
        return None

    try:
        # Remove currency symbols and whitespace
        budget_clean = budget_text.replace("£", "").replace("$", "").replace(",", "").strip()
        # Extract number (including decimals)
        import re

        match = re.search(r"\d+\.?\d*", budget_clean)
        if match:
            budget_gbp = float(match.group())
            return int(budget_gbp * 100)  # Convert to pence
    except (ValueError, AttributeError):
        pass

    return None


def _count_reference_media(lead: Lead) -> tuple[int, int]:
    """Count reference links and media from lead answers."""
    links_count = 0
    media_count = 0

    for answer in lead.answers:
        if answer.question_key == "reference_images":
            text = answer.answer_text.lower()
            # Count Instagram links
            if "instagram.com" in text or "ig.me" in text:
                links_count += text.count("instagram.com") + text.count("ig.me")
            # Count other URLs
            if "http" in text:
                links_count += text.count("http")
            # Count media (if media_id or media_url is set)
            if answer.media_id or answer.media_url:
                media_count += 1

    return links_count, media_count


# Note: Action links are generated separately when needed, not stored in Sheets row
# They're available via the action token system when admin accesses the lead


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
    from app.core.config import settings

    # Feature flag check
    if not settings.feature_sheets_enabled:
        logger.debug(f"Sheets logging disabled (feature flag) - skipping lead {lead.id}")
        return False

    try:
        # Get lead answers for summary
        answers = {}
        for answer in lead.answers:
            answers[answer.question_key] = answer.answer_text

        # Parse budget amount
        budget_amount = _parse_budget_amount(answers)

        # Count reference media
        reference_links_count, reference_media_count = _count_reference_media(lead)

        # Phase 1: Map all fields to sheet columns (exact match to spec)
        row_data = {
            # Identity
            "lead_id": lead.id,
            "whatsapp_number": lead.wa_from,
            "client_name": None,  # Not captured yet
            "instagram_handle": lead.instagram_handle or "",
            # Request
            "idea_summary": answers.get("idea", ""),
            "placement": answers.get("placement", ""),
            "dimensions": answers.get("dimensions", ""),
            "style": answers.get("style", ""),
            "complexity_level": lead.complexity_level or "",
            "coverup_flag": answers.get("coverup", "").upper() in ["YES", "Y", "TRUE", "1"],
            "reference_links_count": reference_links_count,
            "reference_media_count": reference_media_count,
            # Location / tour
            "city": lead.location_city or "",
            "country": lead.location_country or "",
            "region_bucket": lead.region_bucket or "",
            "requested_city": lead.requested_city or "",
            "offered_tour_city": lead.offered_tour_city or "",
            "tour_offer_accepted": lead.tour_offer_accepted
            if lead.tour_offer_accepted is not None
            else False,
            "waitlisted": lead.waitlisted or False,
            # Money
            "budget_amount": budget_amount,
            "region_min_budget": lead.min_budget_amount,
            "below_min_budget": lead.below_min_budget or False,
            "estimated_category": lead.estimated_category or "",
            "estimated_deposit_amount": lead.estimated_deposit_amount,
            "stripe_checkout_url": f"https://checkout.stripe.com/pay/{lead.stripe_checkout_session_id}"
            if lead.stripe_checkout_session_id
            else "",
            "stripe_session_id": lead.stripe_checkout_session_id or "",
            "deposit_paid": lead.deposit_paid_at is not None,
            "deposit_paid_at": (
                lead.deposit_paid_at.isoformat()
                if lead.deposit_paid_at and hasattr(lead.deposit_paid_at, "isoformat")
                else (str(lead.deposit_paid_at) if lead.deposit_paid_at else "")
            ),
            # Booking
            "booking_status": lead.status if lead.status in ["BOOKING_PENDING", "BOOKED"] else "",
            "calendar_event_id": lead.calendar_event_id or "",
            "calendar_start": (
                lead.calendar_start_at.isoformat()
                if lead.calendar_start_at and hasattr(lead.calendar_start_at, "isoformat")
                else (str(lead.calendar_start_at) if lead.calendar_start_at else "")
            ),
            "calendar_end": (
                lead.calendar_end_at.isoformat()
                if lead.calendar_end_at and hasattr(lead.calendar_end_at, "isoformat")
                else (str(lead.calendar_end_at) if lead.calendar_end_at else "")
            ),
            # Ops
            "status": lead.status,
        }

        # Helper to safely convert SQLAlchemy DateTime to ISO string
        def to_iso(dt) -> str:
            if not dt:
                return ""
            if hasattr(dt, "isoformat"):
                return dt.isoformat()
            return str(dt)

        # Add timestamp fields using helper
        row_data.update(
            {
                "created_at": to_iso(lead.created_at),
                "last_client_message_at": to_iso(lead.last_client_message_at),
                "qualifying_started_at": to_iso(lead.qualifying_started_at),
                "qualifying_completed_at": to_iso(lead.qualifying_completed_at),
                "approved_at": to_iso(lead.approved_at),
                "rejected_at": to_iso(lead.rejected_at),
                "stale_at": to_iso(lead.stale_at),
                "abandoned_at": to_iso(lead.abandoned_at),
                "needs_follow_up_at": to_iso(lead.needs_follow_up_at),
                "needs_artist_reply_at": to_iso(lead.needs_artist_reply_at),
                "deposit_sent_at": to_iso(lead.deposit_sent_at),
                "booking_pending_at": to_iso(lead.booking_pending_at),
                "booked_at": to_iso(lead.booked_at),
            }
        )

        # Add notes fields
        row_data.update(
            {
                "handover_reason": lead.handover_reason or "",
                "admin_notes": lead.admin_notes or "",
                "last_error": "",  # TODO: Track errors
            }
        )

        # Try to write to Google Sheets if enabled
        service = _get_sheets_service()
        if service:
            return _upsert_lead_row_real(service, row_data, lead.id)
        else:
            # Fallback to stub logging
            logger.info(
                f"[SHEETS-STUB] Would log/update lead {lead.id} to Google Sheets: {row_data}"
            )
            return True

    except Exception as e:
        logger.error(f"Failed to log lead {lead.id} to Sheets: {e}")
        return False


def _upsert_lead_row_real(service, row_data: dict, lead_id: int) -> bool:
    """
    Upsert a lead row in Google Sheets using the real API.

    Args:
        service: Google Sheets API service object
        row_data: Dict of column values
        lead_id: Lead ID to find/update row

    Returns:
        True if successful, False otherwise
    """
    try:
        spreadsheet_id = settings.google_sheets_spreadsheet_id
        sheet_name = "Leads"  # Default sheet name

        # Define column order (must match spec exactly)
        columns = [
            "lead_id",
            "whatsapp_number",
            "client_name",
            "instagram_handle",
            "idea_summary",
            "placement",
            "dimensions",
            "style",
            "complexity_level",
            "coverup_flag",
            "reference_links_count",
            "reference_media_count",
            "city",
            "country",
            "region_bucket",
            "requested_city",
            "offered_tour_city",
            "tour_offer_accepted",
            "waitlisted",
            "budget_amount",
            "region_min_budget",
            "below_min_budget",
            "estimated_category",
            "estimated_deposit_amount",
            "stripe_checkout_url",
            "stripe_session_id",
            "deposit_paid",
            "deposit_paid_at",
            "booking_status",
            "calendar_event_id",
            "calendar_start",
            "calendar_end",
            "status",
            "created_at",
            "last_client_message_at",
            "qualifying_started_at",
            "qualifying_completed_at",
            "approved_at",
            "rejected_at",
            "stale_at",
            "abandoned_at",
            "needs_follow_up_at",
            "needs_artist_reply_at",
            "handover_reason",
            "admin_notes",
            "last_error",
        ]

        # Build row values in column order
        row_values = [row_data.get(col, "") for col in columns]

        # Try to find existing row by lead_id
        try:
            result = (
                service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=spreadsheet_id,
                    range=f"{sheet_name}!A:A",  # Check lead_id column
                )
                .execute()
            )

            rows = result.get("values", [])
            row_index = None

            # Skip header row (row 1), search from row 2
            for i, row in enumerate(rows[1:], start=2):
                if row and len(row) > 0 and str(row[0]) == str(lead_id):
                    row_index = i
                    break

            if row_index:
                # Update existing row
                range_name = f"{sheet_name}!{row_index}:{row_index}"
                service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption="RAW",
                    body={"values": [row_values]},
                ).execute()
                logger.info(f"Updated lead {lead_id} in Google Sheets (row {row_index})")
            else:
                # Append new row
                range_name = f"{sheet_name}!A:A"
                service.spreadsheets().values().append(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [row_values]},
                ).execute()
                logger.info(f"Appended lead {lead_id} to Google Sheets")

            return True

        except Exception as e:
            logger.error(f"Google Sheets API error for lead {lead_id}: {e}")
            # Fallback to stub
            logger.info(f"[SHEETS-FALLBACK] Would log lead {lead_id}: {row_data}")
            return False

    except Exception as e:
        logger.error(f"Failed to upsert lead {lead_id} to Google Sheets: {e}")
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

        # Use full upsert (which updates status)
        return log_lead_to_sheets(db, lead)

    except Exception as e:
        logger.error(f"Failed to update lead {lead_id} status in Sheets: {e}")
        return False
