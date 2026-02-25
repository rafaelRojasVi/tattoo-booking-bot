"""
HTTP client helper with standardized timeout configuration.

Ensures all outbound HTTP calls have explicit timeouts to prevent
worker blocking on slow or hanging external services.
"""

import httpx


def get_httpx_timeout() -> httpx.Timeout:
    """
    Get standardized timeout configuration for HTTP clients.

    Returns:
        httpx.Timeout with appropriate timeout values for webhook handlers
    """
    # httpx.Timeout API: first arg is default timeout, then keyword args for specific timeouts
    return httpx.Timeout(
        10.0,  # Default timeout for all operations
        connect=5.0,  # Time to establish connection
        read=10.0,  # Time to read response
        write=5.0,  # Time to write request
        pool=5.0,  # Time to get connection from pool
    )


def create_httpx_client() -> httpx.AsyncClient:
    """
    Create an httpx.AsyncClient with standardized timeout configuration.

    Returns:
        httpx.AsyncClient configured with appropriate timeouts
    """
    return httpx.AsyncClient(timeout=get_httpx_timeout())
