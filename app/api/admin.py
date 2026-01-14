from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.deps import get_db
from app.db.models import Lead

router = APIRouter()


@router.get("/leads")
def list_leads(db: Session = Depends(get_db)):
    leads = db.execute(select(Lead).order_by(Lead.created_at.desc())).scalars().all()
    return [
        {
            "id": l.id,
            "wa_from": l.wa_from,
            "status": l.status,
            "created_at": l.created_at,
        }
        for l in leads
    ]
