from sqlalchemy import String, Integer, DateTime, func, ForeignKey, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from app.db.base import Base

class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    wa_from: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="NEW")
    current_step: Mapped[int] = mapped_column(Integer, default=0)

    # Location fields
    location_city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    location_country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    region_bucket: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # UK, EUROPE, ROW

    # Size and budget
    size_category: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # SMALL, MEDIUM, LARGE
    size_measurement: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # Optional cm/inches
    budget_range_text: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Summary and derived fields
    summary_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Deposit fields
    deposit_amount_pence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stripe_checkout_session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    stripe_payment_intent_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    stripe_payment_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    deposit_paid_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Booking fields
    booking_link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    booking_tool: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # FRESHA, CALENDLY, GCAL, OTHER
    booking_link_sent_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    booked_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps for reminders and tracking
    last_client_message_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_bot_message_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_qualifying_sent_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_booking_sent_24h_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_booking_sent_72h_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    stale_marked_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    abandoned_marked_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Admin fields
    approved_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_admin_action: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_admin_action_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    admin_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationship to answers
    answers: Mapped[list["LeadAnswer"]] = relationship("LeadAnswer", back_populates="lead", cascade="all, delete-orphan")


class LeadAnswer(Base):
    __tablename__ = "lead_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(Integer, ForeignKey("leads.id"), index=True)
    question_key: Mapped[str] = mapped_column(String(64), index=True)
    answer_text: Mapped[str] = mapped_column(Text)
    
    # Media handling (for reference images)
    message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # WhatsApp message ID
    media_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Meta media ID
    media_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Media URL if downloaded
    
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationship back to lead
    lead: Mapped["Lead"] = relationship("Lead", back_populates="answers")


class ProcessedMessage(Base):
    """Idempotency table - stores processed WhatsApp message IDs to prevent duplicates."""
    __tablename__ = "processed_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    lead_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("leads.id"), nullable=True, index=True)
    processed_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
