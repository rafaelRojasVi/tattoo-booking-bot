from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    wa_from: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="NEW")
    current_step: Mapped[int] = mapped_column(Integer, default=0)

    # Location fields
    location_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    location_country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    region_bucket: Mapped[str | None] = mapped_column(String(20), nullable=True)  # UK, EUROPE, ROW

    # Tour fields (Phase 1)
    requested_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requested_country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    offered_tour_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    offered_tour_dates_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tour_offer_accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    waitlisted: Mapped[bool | None] = mapped_column(Boolean, default=False)

    # Size and budget
    size_category: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # SMALL, MEDIUM, LARGE (legacy)
    size_measurement: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # Optional cm/inches
    budget_range_text: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Estimation fields (Phase 1)
    complexity_level: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-3 scale
    estimated_category: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # SMALL, MEDIUM, LARGE, XL
    estimated_deposit_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)  # in pence
    min_budget_amount: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # region minimum in pence
    below_min_budget: Mapped[bool | None] = mapped_column(Boolean, default=False)

    # Instagram handle (Phase 1)
    instagram_handle: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Summary and derived fields
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Deposit fields
    deposit_amount_pence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_payment_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    deposit_paid_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deposit_sent_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Booking fields (Phase 1 - manual booking)
    booking_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    booking_tool: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # FRESHA, CALENDLY, GCAL, OTHER (legacy)
    booking_link_sent_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    booked_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    booking_pending_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Calendar fields (Phase 1 - optional detection)
    calendar_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    calendar_start_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    calendar_end_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps for reminders and tracking
    last_client_message_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_bot_message_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_qualifying_sent_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_booking_sent_24h_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_booking_sent_72h_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stale_marked_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    abandoned_marked_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Phase 1 funnel timestamps
    qualifying_started_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    qualifying_completed_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pending_approval_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    needs_follow_up_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    needs_artist_reply_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    needs_follow_up_notified_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # Track notification to prevent duplicates
    needs_artist_reply_notified_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # Track notification to prevent duplicates
    stale_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    abandoned_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Admin fields
    approved_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_admin_action: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_admin_action_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Handover fields (Phase 1)
    handover_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    preferred_handover_channel: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="CALL"
    )  # CALL, CHAT
    call_availability_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationship to answers
    answers: Mapped[list["LeadAnswer"]] = relationship(
        "LeadAnswer", back_populates="lead", cascade="all, delete-orphan"
    )


class LeadAnswer(Base):
    __tablename__ = "lead_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(Integer, ForeignKey("leads.id"), index=True)
    question_key: Mapped[str] = mapped_column(String(64), index=True)
    answer_text: Mapped[str] = mapped_column(Text)

    # Media handling (for reference images)
    message_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # WhatsApp message ID
    media_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Meta media ID
    media_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )  # Media URL if downloaded

    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationship back to lead
    lead: Mapped["Lead"] = relationship("Lead", back_populates="answers")


class ProcessedMessage(Base):
    """Idempotency table - stores processed WhatsApp message IDs, Stripe event IDs, and other events to prevent duplicates."""

    __tablename__ = "processed_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(
        String(255), unique=True, index=True
    )  # Can be message ID, event ID, etc.
    event_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # e.g., "whatsapp.message", "stripe.checkout.session.completed"
    lead_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("leads.id"), nullable=True, index=True
    )
    processed_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ActionToken(Base):
    """Action tokens for Mode B - secure single-use links for admin actions."""

    __tablename__ = "action_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # Secure random token
    lead_id: Mapped[int] = mapped_column(Integer, ForeignKey("leads.id"), index=True)
    action_type: Mapped[str] = mapped_column(
        String(32)
    )  # approve, reject, send_deposit, send_booking_link, mark_booked
    required_status: Mapped[str] = mapped_column(
        String(32)
    )  # Status lead must be in for this action
    used: Mapped[bool] = mapped_column(Boolean, default=False)  # Single-use flag
    used_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True))  # Expiry (default 7 days)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationship to lead
    lead: Mapped["Lead"] = relationship("Lead")
