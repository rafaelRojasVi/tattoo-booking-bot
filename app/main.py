import logging

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from app.api.actions import router as actions_router
from app.api.admin import router as admin_router
from app.api.demo import router as demo_router
from app.api.webhooks import router as webhooks_router
from app.core.config import settings
from app.db.deps import get_db
from app.middleware.rate_limit import RateLimitMiddleware

logger = logging.getLogger(__name__)

app = FastAPI(title="Tattoo Booking Bot")

# Add rate limiting middleware for admin and action endpoints
app.add_middleware(
    RateLimitMiddleware,
    rate_limited_paths=["/admin", "/a/"],  # Admin endpoints and action tokens
)


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

    # Production-specific validation (fail-fast if in production)
    if settings.app_env == "production":
        production_errors = []

        # Require ADMIN_API_KEY in production
        if not settings.admin_api_key:
            production_errors.append(
                "ADMIN_API_KEY is required in production. "
                "Set ADMIN_API_KEY environment variable with a strong random key."
            )

        # Require WHATSAPP_APP_SECRET in production (for webhook signature verification)
        if not settings.whatsapp_app_secret:
            production_errors.append(
                "WHATSAPP_APP_SECRET is required in production for webhook signature verification. "
                "Set WHATSAPP_APP_SECRET environment variable with your Meta App Secret."
            )

        # Require STRIPE_WEBHOOK_SECRET in production (should already be checked above, but double-check)
        if not settings.stripe_webhook_secret:
            production_errors.append(
                "STRIPE_WEBHOOK_SECRET is required in production. "
                "Set STRIPE_WEBHOOK_SECRET environment variable with your Stripe webhook signing secret."
            )

        # Require DEMO_MODE to be False in production
        if settings.demo_mode:
            production_errors.append(
                "DEMO_MODE must be False in production. "
                "Set DEMO_MODE=false or remove DEMO_MODE from environment variables."
            )

        if production_errors:
            error_message = (
                "Production environment validation failed:\n\n"
                + "\n".join(f"  • {error}" for error in production_errors)
                + "\n\n"
                "The application cannot start in production with these missing or invalid settings. "
                "Please fix the configuration and restart."
            )
            logger.error(error_message)
            raise RuntimeError(error_message)

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
    
    Returns 200 immediately - used for basic health checks.
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


@app.get("/ready")
def ready(db: Session = Depends(get_db)):
    """
    Readiness check endpoint - verifies database connectivity.
    
    Returns 200 if database is accessible, 503 if not.
    Used by load balancers and orchestration systems.
    """
    from sqlalchemy import text

    try:
        # Simple SELECT 1 query to verify database connection
        db.execute(text("SELECT 1"))
        return {"ok": True, "database": "connected"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        from fastapi import status
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"ok": False, "database": "disconnected", "error": str(e)},
        )


app.include_router(webhooks_router, prefix="/webhooks")
app.include_router(admin_router, prefix="/admin", tags=["admin"])
app.include_router(actions_router, tags=["actions"])
app.include_router(demo_router, prefix="/demo", tags=["demo"])
