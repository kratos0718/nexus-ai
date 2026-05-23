"""
Tests for observability / traces endpoints.

Covers: list traces (empty + after records exist), stats endpoint,
        auth enforcement, pagination params.
"""


import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

async def _insert_trace(auth_client, question="What is the policy?"):
    """Insert one trace record via the trace_service directly (no LLM call needed)."""

    client, _ = auth_client
    # We need the db session — get it from the override
    # Easier: just call trace_service.record via HTTP side-effect check
    return question


# ── Auth enforcement ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_traces_requires_auth(client):
    res = await client.get("/api/v1/traces/")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_stats_requires_auth(client):
    res = await client.get("/api/v1/traces/stats")
    assert res.status_code == 401


# ── Empty state ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_traces_empty(auth_client):
    client, _ = auth_client
    res = await client.get("/api/v1/traces/")
    assert res.status_code == 200
    data = res.json()
    assert data["traces"] == []
    assert data["count"] == 0


@pytest.mark.asyncio
async def test_stats_empty_returns_zeros(auth_client):
    client, _ = auth_client
    res = await client.get("/api/v1/traces/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["total_calls"] == 0
    assert data["total_tokens"] == 0
    assert data["avg_duration_ms"] == 0
    assert data["p95_duration_ms"] == 0.0
    assert data["error_rate_pct"] == 0.0
    assert data["estimated_cost_usd"] == 0.0


# ── After data exists ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats_after_traces(auth_client, db_session):
    from app.services.trace_service import trace_service

    client, _ = auth_client

    # Insert trace records directly through the service
    for i in range(3):
        await trace_service.record(
            db=db_session,
            question=f"Question {i}",
            answer="Answer",
            model="llama-test",
            prompt_tokens=100 + i * 10,
            completion_tokens=50,
            duration_ms=1000.0 + i * 200,
            trace_type="rag_standard",
            user_id=1,
        )

    res = await client.get("/api/v1/traces/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["total_calls"] == 3
    assert data["total_prompt_tokens"] == 100 + 110 + 120
    assert data["avg_duration_ms"] > 0
    assert data["p95_duration_ms"] > 0
    assert "estimated_cost_usd" in data


@pytest.mark.asyncio
async def test_list_traces_after_insert(auth_client, db_session):
    from app.services.trace_service import trace_service

    client, _ = auth_client

    await trace_service.record(
        db=db_session,
        question="What does section 3 say?",
        answer="Section 3 says...",
        model="llama-test",
        prompt_tokens=200,
        completion_tokens=100,
        duration_ms=1500.0,
        trace_type="rag_standard",
        user_id=1,
    )

    res = await client.get("/api/v1/traces/")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    trace = data["traces"][0]
    assert "trace_id" in trace
    assert "duration_ms" in trace
    assert "created_at" in trace


# ── Pagination ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_traces_limit_param(auth_client, db_session):
    from app.services.trace_service import trace_service

    client, _ = auth_client

    for i in range(5):
        await trace_service.record(
            db=db_session,
            question=f"Q{i}",
            answer="A",
            model="m",
            prompt_tokens=10,
            completion_tokens=5,
            duration_ms=500.0,
            trace_type="rag_standard",
            user_id=1,
        )

    res = await client.get("/api/v1/traces/?limit=3")
    assert res.status_code == 200
    assert res.json()["count"] == 3


@pytest.mark.asyncio
async def test_list_traces_invalid_limit_rejected(auth_client):
    client, _ = auth_client
    res = await client.get("/api/v1/traces/?limit=999")
    assert res.status_code == 422  # exceeds le=100
