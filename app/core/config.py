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
    whatsapp_dry_run: bool = True  # Set to False in production to enable real sending

    stripe_secret_key: str
    stripe_webhook_secret: str
    stripe_deposit_amount_pence: int = 5000

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


# Settings will load from environment variables or .env file
# Required fields will raise ValidationError if missing (fail-fast)
settings = Settings()
