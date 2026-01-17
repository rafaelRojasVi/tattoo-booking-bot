from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.deps import get_db
from app.db.models import Lead
from app.services.conversation import get_lead_summary

router = APIRouter()


@router.get("/leads")
def list_leads(db: Session = Depends(get_db)):
    leads = db.execute(select(Lead).order_by(Lead.created_at.desc())).scalars().all()
    return [
        {
            "id": l.id,
            "wa_from": l.wa_from,
            "status": l.status,
            "current_step": l.current_step,
            "created_at": l.created_at,
        }
        for l in leads
    ]


@router.get("/leads/{lead_id}")
def get_lead_detail(lead_id: int, db: Session = Depends(get_db)):
    """Get detailed lead information including answers and summary."""
    summary = get_lead_summary(db, lead_id)
    
    if "error" in summary:
        raise HTTPException(status_code=404, detail=summary["error"])
    
    return summary
