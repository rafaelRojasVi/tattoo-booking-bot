"""
Correlation ID middleware for request tracing.

Reads X-Correlation-ID from incoming request or generates a UUID.
Stores in request.state and contextvar for use throughout the request lifecycle.
"""

import logging
import uuid
from contextvars import ContextVar
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

HEADER_CORRELATION_ID = "X-Correlation-ID"

# Context var for async/sync code that doesn't have request (e.g. nested calls)
_correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id(request: Request | None = None) -> str | None:
    """
    Get correlation ID for the current request.
    Prefers request.state, then contextvar. Returns None if neither set.
    """
    if request is not None and hasattr(request.state, "correlation_id") and request.state.correlation_id:
        return request.state.correlation_id
    return _correlation_id_var.get()


def set_correlation_id(correlation_id: str) -> None:
    """Set correlation ID in contextvar (for background tasks that receive it)."""
    _correlation_id_var.set(correlation_id)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware that sets correlation_id on every request.
    Reads X-Correlation-ID header if present, otherwise generates UUID.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        incoming = request.headers.get(HEADER_CORRELATION_ID)
        if incoming and len(incoming) <= 128:
            cid = incoming.strip()
        else:
            cid = str(uuid.uuid4())
        request.state.correlation_id = cid
        token = _correlation_id_var.set(cid)
        try:
            response = await call_next(request)
        finally:
            _correlation_id_var.reset(token)
        # Echo back so clients can correlate
        response.headers[HEADER_CORRELATION_ID] = request.state.correlation_id
        return response
