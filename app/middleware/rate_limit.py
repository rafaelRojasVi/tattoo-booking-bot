"""
Rate limiting middleware for FastAPI.

Simple in-memory rate limiter using sliding window approach.
For production at scale, consider Redis-based rate limiting.
"""

import logging
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

logger = logging.getLogger(__name__)

# In-memory store: {client_ip: [(timestamp, ...), ...]}
# For production, use Redis or similar
_rate_limit_store: dict[str, list[float]] = defaultdict(list)


def _clean_old_entries(client_ip: str, window_seconds: int) -> None:
    """Remove entries older than the time window."""
    now = time.time()
    cutoff = now - window_seconds
    _rate_limit_store[client_ip] = [ts for ts in _rate_limit_store[client_ip] if ts > cutoff]


def _is_rate_limited(client_ip: str) -> bool:
    """Check if client has exceeded rate limit."""
    if not settings.rate_limit_enabled:
        return False

    _clean_old_entries(client_ip, settings.rate_limit_window_seconds)

    request_count = len(_rate_limit_store[client_ip])
    if request_count >= settings.rate_limit_requests:
        return True

    # Record this request
    _rate_limit_store[client_ip].append(time.time())
    return False


def get_client_ip(request: Request) -> str:
    """Extract client IP from request, handling proxies."""
    # Check X-Forwarded-For header (from proxies/load balancers)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take first IP in chain
        return forwarded_for.split(",")[0].strip()

    # Check X-Real-IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Fallback to direct client IP
    if request.client:
        return request.client.host

    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware for specific paths."""

    def __init__(self, app, rate_limited_paths: list[str]):
        super().__init__(app)
        self.rate_limited_paths = rate_limited_paths

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Check rate limit for matching paths."""
        # Only apply to specific paths
        path = request.url.path
        should_limit = any(path.startswith(prefix) for prefix in self.rate_limited_paths)

        if should_limit:
            client_ip = get_client_ip(request)
            if _is_rate_limited(client_ip):
                logger.warning(
                    f"Rate limit exceeded for {client_ip} on {path} "
                    f"({settings.rate_limit_requests} requests per "
                    f"{settings.rate_limit_window_seconds}s)"
                )
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": "Rate limit exceeded",
                        "message": f"Too many requests. Limit: {settings.rate_limit_requests} "
                        f"requests per {settings.rate_limit_window_seconds} seconds.",
                        "retry_after": settings.rate_limit_window_seconds,
                    },
                    headers={"Retry-After": str(settings.rate_limit_window_seconds)},
                )

        response = await call_next(request)
        return response
