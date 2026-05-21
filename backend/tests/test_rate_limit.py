"""
Unit tests for the Redis-based rate limiter.

Uses mocked Redis so tests run without a live Redis instance.
"""

import pytest
from unittest.mock import patch, MagicMock

from app.core.rate_limit import check_rate_limit, RateLimitExceeded


def _make_redis_mock(current_count: int):
    """Return a MagicMock Redis client that returns `current_count` from INCR."""
    mock = MagicMock()
    mock.incr.return_value = current_count
    mock.expire.return_value = True
    return mock


# ── Normal operation ──────────────────────────────────────────────────────────

def test_first_request_allowed():
    with patch("app.core.rate_limit._get_redis", return_value=_make_redis_mock(1)):
        remaining = check_rate_limit("user:1", limit=100)
        assert remaining == 99


def test_request_within_limit_allowed():
    with patch("app.core.rate_limit._get_redis", return_value=_make_redis_mock(50)):
        remaining = check_rate_limit("user:1", limit=100)
        assert remaining == 50


def test_request_at_limit_boundary_allowed():
    with patch("app.core.rate_limit._get_redis", return_value=_make_redis_mock(100)):
        remaining = check_rate_limit("user:1", limit=100)
        assert remaining == 0


# ── Limit exceeded ────────────────────────────────────────────────────────────

def test_request_over_limit_raises():
    with patch("app.core.rate_limit._get_redis", return_value=_make_redis_mock(101)):
        with pytest.raises(RateLimitExceeded) as exc:
            check_rate_limit("user:1", limit=100)
        assert exc.value.limit == 100
        assert exc.value.retry_after > 0


def test_rate_limit_exceeded_has_retry_after():
    with patch("app.core.rate_limit._get_redis", return_value=_make_redis_mock(200)):
        with pytest.raises(RateLimitExceeded) as exc:
            check_rate_limit("user:99", limit=100)
        assert isinstance(exc.value.retry_after, int)
        assert exc.value.retry_after >= 1


# ── Per-identifier isolation ──────────────────────────────────────────────────

def test_user_key_uses_user_limit():
    """Identifiers starting with 'user:' use the user limit (100/hr default)."""
    mock = _make_redis_mock(1)
    with patch("app.core.rate_limit._get_redis", return_value=mock):
        check_rate_limit("user:42")
    # Should succeed (count=1 < 100)


def test_ip_key_uses_ip_limit():
    """Identifiers not starting with 'user:' use the IP limit (30/hr default)."""
    mock = _make_redis_mock(1)
    with patch("app.core.rate_limit._get_redis", return_value=mock):
        remaining = check_rate_limit("ip:1.2.3.4")
    assert remaining == 29  # 30 - 1


def test_ip_limit_exceeded():
    with patch("app.core.rate_limit._get_redis", return_value=_make_redis_mock(31)):
        with pytest.raises(RateLimitExceeded):
            check_rate_limit("ip:1.2.3.4")


# ── Graceful degradation ──────────────────────────────────────────────────────

def test_redis_unavailable_allows_request():
    """If Redis is down, check_rate_limit must NOT block the request."""
    mock = MagicMock()
    mock.incr.side_effect = ConnectionError("Redis connection refused")

    with patch("app.core.rate_limit._get_redis", return_value=mock):
        # Should not raise — returns limit (allow through)
        result = check_rate_limit("user:1", limit=100)
        assert result == 100


def test_redis_timeout_allows_request():
    mock = MagicMock()
    mock.incr.side_effect = TimeoutError("Redis timeout")

    with patch("app.core.rate_limit._get_redis", return_value=mock):
        result = check_rate_limit("user:2", limit=50)
        assert result == 50


# ── Custom limit override ─────────────────────────────────────────────────────

def test_custom_limit_override():
    """Caller can pass a custom limit — useful for tighter per-endpoint limits."""
    with patch("app.core.rate_limit._get_redis", return_value=_make_redis_mock(6)):
        with pytest.raises(RateLimitExceeded):
            check_rate_limit("user:1", limit=5)


def test_custom_limit_allows_under():
    with patch("app.core.rate_limit._get_redis", return_value=_make_redis_mock(3)):
        remaining = check_rate_limit("user:1", limit=10)
        assert remaining == 7
