"""
Redis query cache — avoid re-running expensive LLM calls for identical questions.

Cache key  = SHA256(question.lower() + document_filter)
Cache value = serialized QueryResponse JSON
TTL        = 1 hour (configurable)

Hit/miss counters:
  nexus:cache:hits   — incremented on every cache hit
  nexus:cache:misses — incremented on every cache miss

Cache miss → run full RAG pipeline → store result → return
Cache hit  → return stored result immediately (no LLM call, no embedding)
"""

import hashlib
import json
import os
from typing import Optional

from loguru import logger

_redis_client = None

_KEY_PREFIX = "nexus:query:"
_HIT_KEY = "nexus:cache:hits"
_MISS_KEY = "nexus:cache:misses"


def _get_redis():
    global _redis_client
    if _redis_client is None:
        import redis
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = redis.from_url(url, decode_responses=True)
    return _redis_client


def _make_key(question: str, document_filter: Optional[dict] = None) -> str:
    content = f"{question.strip().lower()}:{json.dumps(document_filter or {}, sort_keys=True)}"
    digest = hashlib.sha256(content.encode()).hexdigest()
    return f"{_KEY_PREFIX}{digest}"


def get_cached_query(question: str, document_filter: Optional[dict] = None) -> Optional[dict]:
    """Return cached result dict, or None on miss / Redis unavailable."""
    try:
        r = _get_redis()
        raw = r.get(_make_key(question, document_filter))
        if raw:
            r.incr(_HIT_KEY)
            logger.info(f"Cache HIT for query: '{question[:60]}'")
            return json.loads(raw)
        else:
            r.incr(_MISS_KEY)
    except Exception as e:
        logger.warning(f"Cache get failed (Redis down?): {e}")
    return None


def set_cached_query(
    question: str,
    result: dict,
    document_filter: Optional[dict] = None,
    ttl: int = 3600,
) -> None:
    """Store result in Redis. Silently no-ops if Redis is unavailable."""
    try:
        r = _get_redis()
        r.setex(_make_key(question, document_filter), ttl, json.dumps(result))
        logger.info(f"Cache SET for query: '{question[:60]}' (TTL {ttl}s)")
    except Exception as e:
        logger.warning(f"Cache set failed (Redis down?): {e}")


def invalidate_document_cache(document_id: str) -> None:
    """
    Called when a document is deleted — we can't invalidate specific query keys
    (they're hashed), so we clear the entire query cache namespace.

    Uses SCAN instead of KEYS: KEYS blocks Redis until all keys are scanned (O(N)).
    SCAN iterates incrementally in small batches — safe on production instances.
    """
    try:
        r = _get_redis()
        keys = list(r.scan_iter(f"{_KEY_PREFIX}*"))
        if keys:
            r.delete(*keys)
            logger.info(f"Invalidated {len(keys)} cache entries after document deletion")
    except Exception as e:
        logger.warning(f"Cache invalidation failed: {e}")


def get_cache_stats() -> dict:
    """
    Returns cache health metrics.
    On Redis unavailable, returns a disconnected state with zero counts.
    """
    try:
        r = _get_redis()
        r.ping()  # confirm connection

        # Count cached query entries using SCAN (non-blocking)
        entry_count = sum(1 for _ in r.scan_iter(f"{_KEY_PREFIX}*"))
        hits = int(r.get(_HIT_KEY) or 0)
        misses = int(r.get(_MISS_KEY) or 0)
        total = hits + misses
        hit_rate = round(hits / total * 100, 1) if total > 0 else 0.0

        # Redis memory info
        info = r.info("memory")
        used_mb = round(info.get("used_memory", 0) / 1024 / 1024, 2)

        return {
            "redis_connected": True,
            "cached_queries": entry_count,
            "hits": hits,
            "misses": misses,
            "hit_rate_pct": hit_rate,
            "redis_memory_mb": used_mb,
        }
    except Exception as e:
        logger.warning(f"Cache stats unavailable: {e}")
        return {
            "redis_connected": False,
            "cached_queries": 0,
            "hits": 0,
            "misses": 0,
            "hit_rate_pct": 0.0,
            "redis_memory_mb": 0.0,
        }


def flush_query_cache() -> int:
    """
    Delete all cached query entries. Returns number of keys deleted.
    Uses SCAN to avoid blocking Redis on large caches.
    """
    try:
        r = _get_redis()
        keys = list(r.scan_iter(f"{_KEY_PREFIX}*"))
        if keys:
            r.delete(*keys)
        logger.info(f"Flushed {len(keys)} cache entries")
        return len(keys)
    except Exception as e:
        logger.warning(f"Cache flush failed: {e}")
        return 0
