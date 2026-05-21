"""
Redis query cache — avoid re-running expensive LLM calls for identical questions.

Cache key  = SHA256(question + document_filter)
Cache value = serialized QueryResponse JSON
TTL        = 1 hour (configurable)

Cache miss → run full RAG pipeline → store result → return
Cache hit  → return stored result immediately (no LLM call, no embedding)
"""

import hashlib
import json
import os
from typing import Optional
from loguru import logger

_redis_client = None


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
    return f"nexus:query:{digest}"


def get_cached_query(question: str, document_filter: Optional[dict] = None) -> Optional[dict]:
    """Return cached result dict, or None on miss / Redis unavailable."""
    try:
        r = _get_redis()
        raw = r.get(_make_key(question, document_filter))
        if raw:
            logger.info(f"Cache HIT for query: '{question[:60]}'")
            return json.loads(raw)
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
    Acceptable trade-off: cache is rebuilt on next queries.
    """
    try:
        r = _get_redis()
        keys = r.keys("nexus:query:*")
        if keys:
            r.delete(*keys)
            logger.info(f"Invalidated {len(keys)} cache entries after document deletion")
    except Exception as e:
        logger.warning(f"Cache invalidation failed: {e}")
