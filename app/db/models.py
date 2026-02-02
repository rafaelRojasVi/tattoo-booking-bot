from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
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
    estimated_days: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # Estimated days for XL projects (e.g., 1.5, 2.0, 2.5 days)
    estimated_deposit_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)  # in pence
    estimated_price_min_pence: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Minimum estimated price in pence (internal use only)
    estimated_price_max_pence: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Maximum estimated price in pence (internal use only)
    pricing_trace_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )  # Pricing calculation trace (internal use only)
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
    deposit_checkout_expires_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # Timestamp when checkout session expires (24h from creation)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_payment_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    deposit_paid_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deposit_sent_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deposit_amount_locked_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # Timestamp when deposit amount was locked
    deposit_rule_version: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # Version of deposit rules used (e.g., "v1")

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
    suggested_slots_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )  # Stores suggested slots when sent: [{"start": "2026-01-25T10:00:00Z", "end": "2026-01-25T12:00:00Z"}, ...]
    selected_slot_start_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # Client's selected slot start time
    selected_slot_end_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # Client's selected slot end time

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
    handover_last_hold_reply_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # Rate-limit holding "I've paused..." message (e.g. once per 6h)
    preferred_handover_channel: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="CALL"
    )  # CALL, CHAT
    call_availability_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Parse failure tracking (two-strikes handover)
    parse_failure_counts: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )  # Tracks parse failures per field: {"dimensions": 2, "budget": 1, "location_city": 0, "slot": 1}

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


class SystemEvent(Base):
    """System events table for logging key system events and failures."""

    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    level: Mapped[str] = mapped_column(String(10), index=True)  # INFO, WARN, ERROR
    event_type: Mapped[str] = mapped_column(
        String(100), index=True
    )  # e.g., "whatsapp.send_failure"
    lead_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("leads.id"), nullable=True, index=True
    )
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Additional event data

    # Relationship to lead (optional)
    lead: Mapped["Lead | None"] = relationship("Lead")


class Attachment(Base):
    """Attachment model for reference images and media files."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    lead_answer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("lead_answers.id"), nullable=True, index=True
    )

    # WhatsApp media tracking
    whatsapp_media_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # Storage provider info
    provider: Mapped[str] = mapped_column(String(50), default="supabase")  # supabase, s3, etc.
    bucket: Mapped[str | None] = mapped_column(String(100), nullable=True)
    object_key: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)

    # File metadata
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Upload status tracking
    upload_status: Mapped[str] = mapped_column(
        String(20), default="PENDING", index=True
    )  # PENDING, UPLOADED, FAILED
    upload_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    lead: Mapped["Lead"] = relationship("Lead")
    lead_answer: Mapped["LeadAnswer | None"] = relationship("LeadAnswer")
