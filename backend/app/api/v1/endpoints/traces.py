"""
Observability endpoints.

GET /traces/       — recent LLM calls for the current user
GET /traces/stats  — aggregate metrics (tokens, latency, cost estimate)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.services.trace_service import trace_service

router = APIRouter()


@router.get("/")
async def list_traces(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Recent LLM calls made by the current user, newest first."""
    traces = await trace_service.list_traces(db, user_id=current_user.id, limit=limit, offset=offset)
    return {
        "traces": [
            {
                "trace_id": t.trace_id,
                "trace_type": t.trace_type,
                "question": t.question[:120] + "…" if len(t.question) > 120 else t.question,
                "model": t.model,
                "prompt_tokens": t.prompt_tokens,
                "completion_tokens": t.completion_tokens,
                "total_tokens": t.total_tokens,
                "duration_ms": t.duration_ms,
                "error": t.error,
                "created_at": t.created_at.isoformat(),
            }
            for t in traces
        ],
        "count": len(traces),
    }


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregate usage stats for the current user."""
    return await trace_service.get_stats(db, user_id=current_user.id)
