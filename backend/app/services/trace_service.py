"""
Tracing service — writes LLMTrace rows after every LLM call.

Design decisions:
  - Fire-and-forget: trace failures never crash the main request
  - Async: uses the existing AsyncSession, no extra threads
  - Called from rag_service.query() after the pipeline returns
  - Keeps generator.py clean (no DB imports in the ML layer)
"""

import uuid
from typing import Optional

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trace import LLMTrace


class TraceService:

    async def record(
        self,
        db: AsyncSession,
        question: str,
        answer: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        duration_ms: float,
        trace_type: str = "rag",
        user_id: Optional[int] = None,
        document_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Persist one trace row. Swallows all exceptions — tracing must never
        break a user's query.
        """
        try:
            trace = LLMTrace(
                trace_id=str(uuid.uuid4()),
                user_id=user_id,
                document_id=document_id,
                trace_type=trace_type,
                question=question[:2000],        # cap very long questions
                answer=(answer or "")[:5000],    # cap very long answers
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                duration_ms=round(duration_ms, 2),
                error=error,
            )
            db.add(trace)
            await db.commit()
        except Exception as e:
            logger.warning(f"Trace write failed (non-critical): {e}")

    async def list_traces(
        self,
        db: AsyncSession,
        user_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[LLMTrace]:
        q = select(LLMTrace).order_by(LLMTrace.created_at.desc()).limit(limit).offset(offset)
        if user_id is not None:
            q = q.where(LLMTrace.user_id == user_id)
        result = await db.execute(q)
        return list(result.scalars().all())

    async def get_stats(
        self,
        db: AsyncSession,
        user_id: Optional[int] = None,
    ) -> dict:
        """
        Aggregate stats: total calls, tokens, latency percentiles, error rate.
        P95 is computed in Python after fetching all durations — acceptable for
        typical trace counts (thousands, not millions).
        """
        q = select(
            func.count(LLMTrace.id).label("total_calls"),
            func.coalesce(func.sum(LLMTrace.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(LLMTrace.prompt_tokens), 0).label("total_prompt_tokens"),
            func.coalesce(func.sum(LLMTrace.completion_tokens), 0).label("total_completion_tokens"),
            func.coalesce(func.avg(LLMTrace.duration_ms), 0).label("avg_duration_ms"),
            func.coalesce(func.min(LLMTrace.duration_ms), 0).label("min_duration_ms"),
            func.coalesce(func.max(LLMTrace.duration_ms), 0).label("max_duration_ms"),
            func.count(LLMTrace.error).label("error_count"),
        )
        if user_id is not None:
            q = q.where(LLMTrace.user_id == user_id)

        row = (await db.execute(q)).one()

        # Fetch all durations to compute P95 (SQLite-compatible; no percentile_cont)
        dur_q = select(LLMTrace.duration_ms)
        if user_id is not None:
            dur_q = dur_q.where(LLMTrace.user_id == user_id)
        durations = sorted((await db.execute(dur_q)).scalars().all())
        p95 = durations[int(0.95 * len(durations))] if durations else 0.0

        total = row.total_calls or 1  # avoid div-by-zero
        return {
            "total_calls": row.total_calls,
            "total_tokens": int(row.total_tokens),
            "total_prompt_tokens": int(row.total_prompt_tokens),
            "total_completion_tokens": int(row.total_completion_tokens),
            "avg_duration_ms": round(float(row.avg_duration_ms), 1),
            "min_duration_ms": round(float(row.min_duration_ms), 1),
            "max_duration_ms": round(float(row.max_duration_ms), 1),
            "p95_duration_ms": round(float(p95), 1),
            "error_count": row.error_count,
            "error_rate_pct": round(row.error_count / total * 100, 1),
            # Rough cost estimate: Groq free tier, but useful for OpenAI users
            # llama-3.3-70b ≈ $0.59/M prompt, $0.79/M completion (if paid)
            "estimated_cost_usd": round(
                row.total_prompt_tokens / 1_000_000 * 0.59
                + row.total_completion_tokens / 1_000_000 * 0.79,
                4,
            ),
        }


trace_service = TraceService()
