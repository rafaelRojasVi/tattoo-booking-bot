"""Database session helpers."""

from sqlalchemy.orm import Session


def commit_and_refresh(db: Session, *instances) -> None:
    """
    Commit the transaction and refresh each given instance.
    Use only where the code already did db.commit() followed by db.refresh(instance).
    """
    db.commit()
    for obj in instances:
        if obj is not None:
            db.refresh(obj)
