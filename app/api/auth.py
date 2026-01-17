"""
Admin authentication dependencies.
"""
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from app.core.config import settings

# API Key header name
API_KEY_HEADER = "X-Admin-API-Key"

# Security scheme
api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


def get_admin_auth(api_key: str | None = Security(api_key_header)) -> bool:
    """
    Verify admin API key from header.
    
    Args:
        api_key: API key from X-Admin-API-Key header
        
    Returns:
        True if authenticated
        
    Raises:
        HTTPException: If API key is missing or invalid
        RuntimeError: If in production without admin_api_key configured
    """
    # Production safety: refuse to start if admin_api_key not set in production
    if settings.app_env == "production" and not settings.admin_api_key:
        raise RuntimeError(
            "ADMIN_API_KEY must be set in production environment. "
            "Set ADMIN_API_KEY environment variable or set APP_ENV=dev for development."
        )
    
    # If no admin_api_key is configured, allow access (dev mode only)
    if not settings.admin_api_key:
        return True
    
    # If API key is configured, require it
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide X-Admin-API-Key header."
        )
    
    if api_key != settings.admin_api_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key."
        )
    
    return True
