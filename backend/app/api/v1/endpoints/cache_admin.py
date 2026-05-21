"""
Cache management endpoints.

GET    /cache/stats  — hit rate, entry count, Redis memory usage
DELETE /cache/flush  — flush all cached queries (useful after bulk document updates)
"""

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.models.user import User
from app.core.cache import get_cache_stats, flush_query_cache

router = APIRouter()


@router.get("/stats")
async def cache_stats(current_user: User = Depends(get_current_user)):
    """
    Returns Redis cache performance metrics for the current session.

    Hits and misses are global (not per-user) — shared cache benefits all users.
    """
    return get_cache_stats()


@router.delete("/flush", status_code=200)
async def flush_cache(current_user: User = Depends(get_current_user)):
    """
    Flush all cached query results.

    Use after bulk document updates or when cached answers are stale.
    The cache rebuilds automatically on the next queries.
    """
    deleted = flush_query_cache()
    return {"flushed": deleted, "message": f"Deleted {deleted} cached query entries"}
