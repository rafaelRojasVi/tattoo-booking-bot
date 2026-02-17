from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        validate_assignment=True,
    )

    app_env: str = "dev"
    database_url: str

    whatsapp_verify_token: str
    whatsapp_access_token: str
    whatsapp_phone_number_id: str
    whatsapp_app_secret: str | None = None  # App Secret for webhook signature verification
    whatsapp_dry_run: bool = True  # Set to False in production to enable real sending

    stripe_secret_key: str
    stripe_webhook_secret: str
    stripe_deposit_amount_pence: int = 5000

    # Deposit rule version (increment when deposit calculation logic changes)
    deposit_rule_version: str = "v1"

    fresha_booking_url: str

    ai_provider: str = "openai"
    openai_api_key: str | None = None

    admin_api_key: str | None = (
        None  # Optional - if not set, admin endpoints are unprotected (dev mode)
    )

    # Google Sheets (for lead logging)
    google_sheets_enabled: bool = False  # Set to True when Google Sheets API is configured
    google_sheets_spreadsheet_id: str | None = None  # Google Sheets spreadsheet ID
    google_sheets_credentials_json: str | None = (
        None  # Path to service account JSON or JSON content
    )

    # Google Calendar (for slot suggestions)
    google_calendar_enabled: bool = False  # Set to True when Google Calendar API is configured
    google_calendar_id: str | None = None  # Google Calendar ID (email address)
    google_calendar_credentials_json: str | None = (
        None  # Path to service account JSON or JSON content
    )
    booking_duration_minutes: int = 180  # Default booking duration (3 hours)
    slot_suggestions_count: int = 8  # Number of slots to suggest (5-10)

    # Action tokens (Mode B - WhatsApp action links)
    action_token_base_url: str = (
        "http://localhost:8000"  # Base URL for action links (set in production)
    )
    action_token_expiry_days: int = 7

    # Artist WhatsApp (for Mode B - sending summaries with action links)
    artist_whatsapp_number: str | None = None  # Artist's WhatsApp number (with country code, no +)

    # Stripe checkout URLs
    stripe_success_url: str = "http://localhost:8000/payment/success"  # Success redirect URL
    stripe_cancel_url: str = "http://localhost:8000/payment/cancel"  # Cancel redirect URL

    # Feature Flags (Phase 1 production hardening)
    feature_sheets_enabled: bool = True  # Google Sheets logging
    feature_calendar_enabled: bool = True  # Calendar slot suggestions
    feature_reminders_enabled: bool = True  # Automated reminders
    feature_notifications_enabled: bool = True  # Artist notifications
    feature_panic_mode_enabled: bool = (
        False  # When true: pause automation, only log + notify artist
    )

    # Demo mode (development/demo only - must be False in production)
    demo_mode: bool = False  # When true: enables demo endpoints for local testing

    # Pilot mode (restrict access to allowlisted numbers only)
    pilot_mode_enabled: bool = False  # When true: only allowlisted numbers can start consultation
    pilot_allowlist_numbers: str = (
        ""  # Comma-separated list of WhatsApp numbers (with country code, no +)
    )

    # Supabase Storage (for reference images)
    supabase_url: str | None = None  # Supabase project URL
    supabase_service_role_key: str | None = None  # Service role key (server-only, never exposed)
    supabase_storage_bucket: str = "reference-images"  # Storage bucket name
    supabase_signed_url_ttl_seconds: int = 3600  # TTL for signed URLs (1 hour default)

    # Rate limiting
    rate_limit_enabled: bool = True  # Enable rate limiting for admin/action endpoints
    rate_limit_requests: int = 10  # Number of requests allowed per window
    rate_limit_window_seconds: int = 60  # Time window in seconds

    # Outbox-lite for WhatsApp (durable retries when enabled)
    outbox_enabled: bool = False  # When True: persist send intent, retry on failure


# Settings will load from environment variables or .env file
# Required fields will raise ValidationError if missing (fail-fast)
settings = Settings()
