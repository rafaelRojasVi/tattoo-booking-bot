from sqlalchemy.orm import Session
from sqlalchemy import select
from app.db.models import Lead

def get_or_create_lead(db: Session, wa_from: str) -> Lead:
    stmt = select(Lead).where(Lead.wa_from == wa_from)
    lead = db.execute(stmt).scalar_one_or_none()
    if lead:
        return lead

    lead = Lead(wa_from=wa_from, status="NEW")
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead
