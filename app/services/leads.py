from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.db.models import Lead


def get_or_create_lead(db: Session, wa_from: str) -> Lead:
    """
    Get existing lead or create a new one.
    
    Args:
        db: Database session
        wa_from: WhatsApp phone number
        
    Returns:
        Lead object
        
    Raises:
        SQLAlchemyError: If database operation fails
        ValueError: If wa_from is invalid
    """
    if not wa_from or not isinstance(wa_from, str):
        raise ValueError("wa_from must be a non-empty string")
    
    try:
        stmt = select(Lead).where(Lead.wa_from == wa_from)
        lead = db.execute(stmt).scalar_one_or_none()
        if lead:
            return lead

        lead = Lead(wa_from=wa_from, status="NEW")
        db.add(lead)
        db.commit()
        db.refresh(lead)
        return lead
    except SQLAlchemyError as e:
        db.rollback()
        raise
