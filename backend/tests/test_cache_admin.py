"""
Tests for the cache management endpoints.

Redis is not running in CI — the cache functions gracefully degrade.
These tests verify the API contract (response shape, auth, HTTP codes),
not the Redis internals (covered by unit tests of cache.py).
"""

import pytest


# ── Auth enforcement ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cache_stats_requires_auth(client):
    res = await client.get("/api/v1/cache/stats")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_cache_flush_requires_auth(client):
    res = await client.delete("/api/v1/cache/flush")
    assert res.status_code == 401


# ── Response shape (Redis down → graceful degradation) ────────────────────────

@pytest.mark.asyncio
async def test_cache_stats_returns_expected_fields(auth_client):
    client, _ = auth_client
    res = await client.get("/api/v1/cache/stats")
    assert res.status_code == 200
    data = res.json()

    # All fields must be present regardless of Redis availability
    assert "redis_connected" in data
    assert "cached_queries" in data
    assert "hits" in data
    assert "misses" in data
    assert "hit_rate_pct" in data
    assert "redis_memory_mb" in data

    # Types
    assert isinstance(data["redis_connected"], bool)
    assert isinstance(data["cached_queries"], int)
    assert isinstance(data["hits"], int)
    assert isinstance(data["misses"], int)
    assert isinstance(data["hit_rate_pct"], float)


@pytest.mark.asyncio
async def test_cache_stats_no_redis_returns_zeros(auth_client):
    """Without Redis in CI, all counts should be zero and connected should be False."""
    client, _ = auth_client
    res = await client.get("/api/v1/cache/stats")
    assert res.status_code == 200
    data = res.json()

    # In CI without Redis: disconnected state, zero counts
    if not data["redis_connected"]:
        assert data["cached_queries"] == 0
        assert data["hits"] == 0
        assert data["misses"] == 0
        assert data["hit_rate_pct"] == 0.0


@pytest.mark.asyncio
async def test_cache_flush_returns_count(auth_client):
    client, _ = auth_client
    res = await client.delete("/api/v1/cache/flush")
    assert res.status_code == 200
    data = res.json()
    assert "flushed" in data
    assert isinstance(data["flushed"], int)
    assert "message" in data


@pytest.mark.asyncio
async def test_cache_flush_with_redis_mocked(auth_client):
    """Verify flush returns correct count when Redis has entries."""
    from unittest.mock import patch, MagicMock

    client, _ = auth_client

    mock_redis = MagicMock()
    mock_redis.scan_iter.return_value = iter(["key1", "key2", "key3"])
    mock_redis.delete.return_value = 3

    with patch("app.core.cache._get_redis", return_value=mock_redis):
        res = await client.delete("/api/v1/cache/flush")
        assert res.status_code == 200
        assert res.json()["flushed"] == 3


@pytest.mark.asyncio
async def test_cache_stats_with_redis_mocked(auth_client):
    """Verify stats return correct values when Redis is available."""
    from unittest.mock import patch, MagicMock

    client, _ = auth_client

    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    mock_redis.scan_iter.return_value = iter(["q1", "q2"])
    mock_redis.get.side_effect = lambda key: "10" if "hits" in key else "4"
    mock_redis.info.return_value = {"used_memory": 4 * 1024 * 1024}  # 4 MB

    with patch("app.core.cache._get_redis", return_value=mock_redis):
        res = await client.get("/api/v1/cache/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["redis_connected"] is True
        assert data["cached_queries"] == 2
        assert data["redis_memory_mb"] == 4.0
