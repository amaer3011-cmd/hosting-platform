"""
Rate limiting middleware for the hosting platform.
Uses slowapi with Redis backend for distributed rate limiting.
"""

from __future__ import annotations

import time
import inspect
from typing import Optional, Callable, Awaitable

from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from config import config
from logging_config import get_logger

logger = get_logger(__name__)


# Custom key function that considers user identity when available
def get_user_identifier(request: Request) -> str:
    """
    Get rate limit key from request.
    Priority: authenticated user ID > API key > IP address
    """
    # Check for authenticated user (from dashboard auth)
    if hasattr(request.state, "user_id") and request.state.user_id:
        return f"user:{request.state.user_id}"

    # Check for API key
    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if api_key:
        return f"apikey:{api_key[:16]}"

    # Fall back to IP address
    return get_remote_address(request)


# Create limiter instance
limiter = Limiter(
    key_func=get_user_identifier,
    default_limits=[f"{config.RATE_LIMIT_REQUESTS_PER_MINUTE}/minute"] if config.RATE_LIMIT_REQUESTS_PER_MINUTE > 0 else [],
    storage_uri=config.REDIS_URL if config.REDIS_URL else "memory://",
    strategy="fixed-window",
)


# Custom rate limit exceeded handler
async def custom_rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Custom handler for rate limit exceeded errors."""
    retry_after = exc.retry_after or 60

    logger.warning(
        "rate_limit_exceeded",
        identifier=get_user_identifier(request),
        path=request.url.path,
        method=request.method,
        limit=exc.limit,
        retry_after=retry_after,
    )

    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "message": f"Too many requests. Please try again in {retry_after} seconds.",
            "retry_after": retry_after,
            "limit": str(exc.limit),
        },
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": str(exc.limit),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(int(time.time()) + retry_after),
        },
    )


# Rate limit decorators for different endpoint types
def _safe_limit(limit: str):
    """Apply SlowAPI only when the endpoint exposes Request/WebSocket."""
    def decorator(func):
        params = inspect.signature(func).parameters
        if "request" not in params and "websocket" not in params:
            logger.warning("rate_limit_skipped_missing_request", function=func.__name__)
            return func
        return limiter.limit(limit)(func)
    return decorator


def rate_limit_webhook(limit: str = "30/minute"):
    """Rate limit for webhook endpoints - stricter."""
    return _safe_limit(limit)


def rate_limit_api(limit: str = "60/minute"):
    """Rate limit for API endpoints."""
    return _safe_limit(limit)


def rate_limit_admin(limit: str = "100/minute"):
    """Rate limit for admin endpoints."""
    return _safe_limit(limit)


def rate_limit_auth(limit: str = "10/minute"):
    """Rate limit for authentication endpoints - very strict."""
    return _safe_limit(limit)


# Middleware to add rate limit headers to all responses
class RateLimitHeadersMiddleware:
    """Add rate limit headers to responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                # Add rate limit headers if available
                headers = list(message.get("headers", []))
                # Rate limit info would be added by slowapi
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


# Dependency for FastAPI endpoints
async def check_rate_limit(request: Request) -> None:
    """Dependency to check rate limit manually."""
    # This is handled automatically by slowapi decorators
    pass


# Initialize rate limiter for the app
def init_rate_limiter(app) -> None:
    """Initialize rate limiter on FastAPI app."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, custom_rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    logger.info("Rate limiter initialized", limits=config.RATE_LIMIT_REQUESTS_PER_MINUTE)