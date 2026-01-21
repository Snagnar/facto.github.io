"""Rate limiting middleware using slowapi."""

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from fastapi.responses import JSONResponse

from config import get_settings

settings = get_settings()


def get_real_client_ip(request: Request) -> str:
    """
    Get real client IP, considering reverse proxy headers.

    Order of precedence:
    1. X-Forwarded-For header (standard for proxies)
    2. X-Real-IP header (nginx)
    3. Direct connection IP (fallback)

    Note: Only trust these headers if your server is behind a trusted reverse proxy!
    """
    # X-Forwarded-For can contain multiple IPs: client, proxy1, proxy2, ...
    # Take the first (leftmost) IP which is the original client
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    # X-Real-IP header (commonly set by nginx)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Fallback to direct connection IP
    return get_remote_address(request)


# Create limiter instance using proxy-aware IP detection
limiter = Limiter(
    key_func=get_real_client_ip,
    default_limits=[
        f"{settings.rate_limit_requests}/{settings.rate_limit_window}seconds"
    ],
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Custom handler for rate limit exceeded errors."""
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": "Too many requests. Please wait before trying again.",
        },
    )
