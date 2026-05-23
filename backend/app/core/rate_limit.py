"""
Redis-based rate limiting using a fixed window counter.

Two limits enforced:
  - Per-user (authenticated): 100 requests / hour
  - Per-IP (unauthenticated fallback): 30 requests / hour

Fixed window: each window period gets a fresh counter.
Simple, fast, slightly bursty at window boundaries — good enough for an API.

Usage:
    from app.core.rate_limit import check_rate_limit, RateLimitExceeded
    check_rate_limit(identifier="user:42")   # raises on limit hit
"""

import os
import time

from loguru import logger

# Limits — tweak via env vars for easy prod config
_USER_LIMIT = int(os.getenv("RATE_LIMIT_USER_PER_HOUR", "100"))
_IP_LIMIT = int(os.getenv("RATE_LIMIT_IP_PER_HOUR", "30"))
_WINDOW_SECONDS = 3600  # 1 hour


class RateLimitExceeded(Exception):
    def __init__(self, limit: int, window_seconds: int, retry_after: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self.retry_after = retry_after
        super().__init__(f"Rate limit {limit} req/{window_seconds}s exceeded")


def _get_redis():
    """Lazy singleton — same pattern as cache.py."""
    import redis as redis_lib
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis_lib.from_url(url, decode_responses=True)


def check_rate_limit(identifier: str, limit: int | None = None) -> int:
    """
    Increment the request counter for `identifier`. Returns remaining requests.
    Raises RateLimitExceeded if the limit is hit.
    If Redis is unavailable, silently allows the request (graceful degradation).

    identifier: "user:42" for auth users, "ip:1.2.3.4" for anonymous
    limit: override the default limit (useful in tests)
    """
    # Pick limit based on identifier type
    if limit is None:
        limit = _USER_LIMIT if identifier.startswith("user:") else _IP_LIMIT

    try:
        r = _get_redis()

        # Key includes the current window (floor to hour boundary)
        window = int(time.time()) // _WINDOW_SECONDS
        key = f"nexus:ratelimit:{identifier}:{window}"

        # INCR is atomic — safe under concurrent requests
        count = r.incr(key)

        # Set TTL only on the first increment (avoids resetting it on every call)
        if count == 1:
            r.expire(key, _WINDOW_SECONDS + 60)  # +60s buffer so key outlives window

        if count > limit:
            # When does the current window end?
            window_end = (window + 1) * _WINDOW_SECONDS
            retry_after = max(1, int(window_end - time.time()))
            logger.warning(f"Rate limit hit: {identifier} ({count}/{limit})")
            raise RateLimitExceeded(limit=limit, window_seconds=_WINDOW_SECONDS, retry_after=retry_after)

        logger.debug(f"Rate limit: {identifier} {count}/{limit}")
        return limit - count

    except RateLimitExceeded:
        raise
    except Exception as e:
        # Redis down → allow request (don't block users because of infra issue)
        logger.warning(f"Rate limit check failed (Redis down?): {e}")
        return limit
