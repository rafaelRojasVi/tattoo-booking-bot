import logging

from fastapi import FastAPI

from app.api.actions import router as actions_router
from app.api.admin import router as admin_router
from app.api.demo import router as demo_router
from app.api.webhooks import router as webhooks_router
from app.core.config import settings

logger = logging.getLogger(__name__)

app = FastAPI(title="Tattoo Booking Bot")


@app.on_event("startup")
async def startup_event():
    """Run startup checks and validation."""
    from app.core.config import settings
    from app.services.template_check import startup_check_templates

    # Validate critical settings (fail-fast if missing)
    required_settings = [
        "database_url",
        "whatsapp_verify_token",
        "whatsapp_access_token",
        "whatsapp_phone_number_id",
        "stripe_secret_key",
        "stripe_webhook_secret",
    ]
    missing = [key for key in required_settings if not getattr(settings, key, None)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Please check your .env file or environment configuration."
        )

    # Log enabled integrations summary (no secrets)
    logger.info(
        "Startup: Configuration loaded - "
        f"Environment: {settings.app_env}, "
        f"Sheets: {settings.google_sheets_enabled}, "
        f"Calendar: {settings.google_calendar_enabled}, "
        f"WhatsApp dry-run: {settings.whatsapp_dry_run}"
    )

    # Warn if demo mode is enabled
    if settings.demo_mode:
        logger.warning("DEMO MODE ENABLED - DO NOT USE IN PROD")

    # Check template configuration
    template_status = startup_check_templates()
    logger.info(
        f"Startup: Template check completed - "
        f"{len(template_status['templates_configured'])} templates configured"
    )


@app.get("/health")
def health():
    """
    Health check endpoint with template and feature flag visibility.
    """
    from app.services.template_check import REQUIRED_TEMPLATES

    return {
        "ok": True,
        "templates_configured": REQUIRED_TEMPLATES,
        "features": {
            "sheets_enabled": settings.feature_sheets_enabled,
            "calendar_enabled": settings.feature_calendar_enabled,
            "reminders_enabled": settings.feature_reminders_enabled,
            "notifications_enabled": settings.feature_notifications_enabled,
            "panic_mode_enabled": settings.feature_panic_mode_enabled,
        },
        "integrations": {
            "google_sheets_enabled": settings.google_sheets_enabled,
            "google_calendar_enabled": settings.google_calendar_enabled,
        },
    }


app.include_router(webhooks_router, prefix="/webhooks")
app.include_router(admin_router, prefix="/admin", tags=["admin"])
app.include_router(actions_router, tags=["actions"])
app.include_router(demo_router, prefix="/demo", tags=["demo"])