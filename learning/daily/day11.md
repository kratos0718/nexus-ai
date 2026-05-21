# Day 11 — LLM Observability & Request Tracing

**Date:** 2026-05-21  
**Focus:** Logging every LLM call to the database for monitoring, debugging, and cost tracking

---

## The Problem

After Day 10, the system works — but it's a black box in production:
- How long do queries actually take?
- How many tokens is each user consuming?
- Which questions are failing?
- What is this costing?

Without answers to these, you can't debug issues, can't optimize, can't set budgets.

---

## What We Built

### `LLMTrace` model (`app/models/trace.py`)
New database table that records one row per LLM call:
- `trace_id` — UUID, unique identifier for each call
- `question` / `answer` — what was asked and answered (capped at 2k/5k chars)
- `model` — which LLM model was used
- `prompt_tokens` / `completion_tokens` / `total_tokens` — exact token counts from Groq API
- `duration_ms` — wall-clock time for the full query (monotonic clock)
- `trace_type` — "rag" or "agent"
- `user_id` / `document_id` — for per-user and per-document analysis
- `error` — null on success, error string on failure
- `created_at` — indexed for time-series queries

### `TraceService` (`app/services/trace_service.py`)
- `record()` — writes one trace row; swallows all exceptions (tracing never breaks queries)
- `list_traces()` — recent calls for a user, paginated, newest-first
- `get_stats()` — aggregate metrics: total calls, tokens, avg/min/max latency, error rate, cost estimate

### Chat endpoint wiring (`app/api/v1/endpoints/chat.py`)
```python
t0 = time.monotonic()
result = await rag_service.query(...)
duration_ms = (time.monotonic() - t0) * 1000
background_tasks.add_task(trace_service.record, db=db, duration_ms=duration_ms, ...)
```
Trace is written AFTER the response is sent — zero latency impact on the user.

### Traces API (`app/api/v1/endpoints/traces.py`)
- `GET /traces/` — last 20 calls (paginated, up to 100)
- `GET /traces/stats` — aggregated metrics as JSON

### Migration (`alembic/versions/a1b2c3d4e5f6_add_llm_traces_table.py`)
Creates the `llm_traces` table with 4 indexes: trace_id (unique), user_id, document_id, created_at.

---

## Architecture — Where Tracing Fits

```
POST /chat/query
    │
    ├── check rate limit (Redis)
    ├── check cache (Redis)
    ├── run RAG pipeline (thread pool)
    ├── save conversation messages (PostgreSQL)
    ├── return response to user  ← user gets answer here
    │
    └── [BackgroundTask] write LLMTrace row (PostgreSQL)
```

The trace is always the last thing — it never delays the user.

---

## Key Design Decisions

**Why PostgreSQL (not a log file)?**
SQL enables `AVG()`, `SUM()`, `GROUP BY`, joins with users. Log files require grep/regex — no aggregation.

**Why BackgroundTask (not inline)?**
If the DB write is slow or fails, it should not affect the user's response. Tracing is a side effect, not part of the critical path.

**Why cap text length?**
Long documents produce long answers (10k+ chars). Storing full text would bloat the table over time. 2k/5k cap keeps rows small while retaining enough for debugging.

**Why `time.monotonic()` not `time.time()`?**
`time.time()` can go backward (NTP sync, DST). `time.monotonic()` only increases — safe for measuring elapsed time.

**Why `coalesce()` in aggregate query?**
`SUM()` on an empty table returns NULL, not 0. `coalesce(sum(...), 0)` converts NULL → 0, preventing divide-by-zero and null errors downstream.

---

## Files Changed / Created

```
backend/app/models/trace.py                         ← NEW: LLMTrace model
backend/app/models/__init__.py                      ← UPDATED: register LLMTrace
backend/app/services/trace_service.py               ← NEW: TraceService
backend/app/api/v1/endpoints/traces.py              ← NEW: /traces/ and /traces/stats
backend/app/api/v1/endpoints/chat.py                ← UPDATED: timing + fire-and-forget trace
backend/app/api/v1/router.py                        ← UPDATED: mount /traces
backend/alembic/versions/a1b2c3d4e5f6_add_llm_traces_table.py ← NEW: migration
learning/concepts/18_llm_observability.md           ← NEW (8 levels, basic→advanced)
```

---

## What You Can Now Answer in an Interview

**"How do you know if your AI system is working well?"**
→ Every LLM call is traced to PostgreSQL — latency, token count, model, user, question. We expose `/traces/stats` which shows avg latency, total tokens, error rate, and cost estimate. We track "I don't know" responses to detect retrieval quality degradation.

**"How do you track costs?"**
→ Groq's API returns exact prompt_tokens and completion_tokens in every response. We store both. The stats endpoint multiplies by price-per-million-tokens ($0.59 prompt, $0.79 completion) to show estimated spend per user.

**"What would you do if the LLM suddenly got slow?"**
→ Query `llm_traces` for average duration_ms in the last hour vs previous hour. If it jumped, check whether it's LLM inference time (which we can't control) or retrieval time (embedding + vector search — we can add caching or optimize indexes).
