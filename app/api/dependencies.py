"""FastAPI dependencies for API routes."""

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.db.models import Lead


def get_lead_or_404(lead_id: int, db: Session = Depends(get_db)) -> Lead:
    """
    Resolve lead by path parameter lead_id; raise 404 if not found.

    Use as a dependency on routes with path parameter {lead_id}.
    """
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead
