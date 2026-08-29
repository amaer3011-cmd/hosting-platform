"""
Enhanced rate limiting middleware with per-user and global limits.
Replaces slowapi with custom async-friendly implementation.
"""

from __future__ import annotations

import time
from typing import Dict, Optional, Tuple
from collections import defaultdict
from datetime import datetime, timedelta
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import asyncio

from config import config
from logging_config import get_logger

logger = get_logger(__name__)


class RateLimitStore:
    """In-memory rate limit store with cleanup."""
    
    def __init__(self):
        self.requests: Dict[str, list[float]] = defaultdict(list)
        self.lock = asyncio.Lock()
        self.cleanup_interval = 300  # Cleanup every 5 minutes
        self.last_cleanup = time.time()
    
    async def is_allowed(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> bool:
        """Check if request is allowed under rate limit."""
        async with self.lock:
            now = time.time()
            window_start = now - window_seconds
            
            # Clean old requests
            if key in self.requests:
                self.requests[key] = [
                    req_time for req_time in self.requests[key]
                    if req_time > window_start
                ]
            
            # Check limit
            if len(self.requests[key]) >= max_requests:
                return False
            
            # Add current request
            self.requests[key].append(now)
            
            # Cleanup if needed
            if now - self.last_cleanup > self.cleanup_interval:
                await self._cleanup_old_keys(window_start)
                self.last_cleanup = now
            
            return True
    
    async def _cleanup_old_keys(self, window_start: float) -> None:
        """Remove keys with no recent requests."""
        keys_to_delete = [
            key for key, reqs in self.requests.items()
            if not reqs or all(t < window_start for t in reqs)
        ]
        for key in keys_to_delete:
            del self.requests[key]
        
        if keys_to_delete:
            logger.debug(f"Cleaned up {len(keys_to_delete)} rate limit keys")
    
    def get_stats(self, key: str) -> Dict[str, int]:
        """Get rate limit statistics for a key."""
        now = time.time()
        window_start = now - 60  # Last minute
        
        if key not in self.requests:
            return {"requests": 0, "limit": config.rate_limit_msgs_per_minute}
        
        recent = [
            t for t in self.requests[key]
            if t > window_start
        ]
        
        return {
            "requests": len(recent),
            "limit": config.rate_limit_msgs_per_minute,
        }


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Enhanced rate limiting middleware with per-user tracking.
    """
    
    def __init__(self, app, store: Optional[RateLimitStore] = None):
        super().__init__(app)
        self.store = store or RateLimitStore()
        self.enabled = config.rate_limit_enabled
    
    async def dispatch(self, request: Request, call_next):
        """Process request with rate limiting."""
        
        if not self.enabled:
            return await call_next(request)
        
        # Get user identifier
        user_id = self._get_user_id(request)
        
        if not user_id:
            return await call_next(request)
        
        # Check rate limit
        is_allowed = await self.store.is_allowed(
            key=user_id,
            max_requests=config.rate_limit_msgs_per_minute,
            window_seconds=60,
        )
        
        if not is_allowed:
            stats = self.store.get_stats(user_id)
            logger.warning(
                f"Rate limit exceeded for user {user_id}: "
                f"{stats['requests']}/{stats['limit']}"
            )
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again in a few seconds.",
                headers={"Retry-After": "60"},
            )
        
        # Continue to next middleware
        response = await call_next(request)
        
        # Add rate limit headers
        stats = self.store.get_stats(user_id)
        response.headers["X-RateLimit-Limit"] = str(stats["limit"])
        response.headers["X-RateLimit-Remaining"] = str(
            stats["limit"] - stats["requests"]
        )
        response.headers["X-RateLimit-Reset"] = str(
            int(time.time()) + 60
        )
        
        return response
    
    def _get_user_id(self, request: Request) -> Optional[str]:
        """Extract user identifier from request."""
        # Try to get from query params (for Telegram bot)
        if "user_id" in request.query_params:
            return f"user_{request.query_params['user_id']}"
        
        # Try to get from headers (for API calls)
        if "X-User-ID" in request.headers:
            return f"api_{request.headers['X-User-ID']}"
        
        # Fall back to IP address
        client_ip = request.client.host if request.client else "unknown"
        return f"ip_{client_ip}"


class TokenBucketRateLimiter:
    """
    Token bucket algorithm for more sophisticated rate limiting.
    Allows burst traffic while maintaining average rate limit.
    """
    
    def __init__(self, capacity: int, refill_rate: float):
        """
        Initialize token bucket.
        
        Args:
            capacity: Maximum tokens in bucket
            refill_rate: Tokens added per second
        """
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate
        self.last_refill = time.time()
        self.lock = asyncio.Lock()
    
    async def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns True if successful."""
        async with self.lock:
            now = time.time()
            elapsed = now - self.last_refill
            
            # Refill tokens
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.refill_rate
            )
            self.last_refill = now
            
            # Try to consume
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            
            return False
    
    async def wait_until_available(self, tokens: int = 1) -> float:
        """Wait until tokens are available. Returns wait time."""
        async with self.lock:
            now = time.time()
            elapsed = now - self.last_refill
            
            # Refill tokens
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.refill_rate
            )
            self.last_refill = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return 0.0
            
            # Calculate wait time
            needed = tokens - self.tokens
            wait_time = needed / self.refill_rate
            
            return wait_time


# Global rate limit store
_rate_limit_store = RateLimitStore()


async def check_rate_limit(user_id: str) -> bool:
    """Check if user is within rate limit."""
    return await _rate_limit_store.is_allowed(
        key=user_id,
        max_requests=config.rate_limit_msgs_per_minute,
        window_seconds=60,
    )


def get_rate_limit_stats(user_id: str) -> Dict[str, int]:
    """Get rate limit statistics for user."""
    return _rate_limit_store.get_stats(user_id)


def init_rate_limiter(app) -> None:
    """Initialize rate limiter middleware."""
    if config.rate_limit_enabled:
        app.add_middleware(RateLimitMiddleware, store=_rate_limit_store)
        logger.info(
            f"Rate limiter initialized: "
            f"{config.rate_limit_msgs_per_minute} requests/minute"
        )
