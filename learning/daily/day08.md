# Day 8 — Redis Caching + Celery Background Tasks

**Date:** 2026-05-21  
**Focus:** Production-grade async document processing + LLM response caching

---

## What I Built

### 1. Redis Query Cache (`app/core/cache.py`)
- SHA256-keyed cache for LLM responses — same question never hits the LLM twice
- TTL = 1 hour, silently degrades if Redis is down
- Skips cache for conversational queries (history changes the answer)
- Full cache invalidation on document deletion (can't reverse SHA256 to find affected keys)

### 2. Celery Task Queue (`app/core/celery_app.py` + `app/workers/document_tasks.py`)
- Document indexing moved from FastAPI BackgroundTasks → Celery worker process
- Redis as broker (db 1) and result backend (db 2)
- 3 automatic retries with 60-second delay between attempts
- `task_acks_late=True` — task stays in queue until worker finishes (crash-safe)
- `worker_prefetch_multiplier=1` — each worker holds only 1 task (fair for long jobs)

### 3. Dual SQLAlchemy Engine (`app/core/database.py`)
- FastAPI: `asyncpg` driver → `AsyncSession` (non-blocking)
- Celery: `psycopg2` driver → `Session` (sync, fine for worker threads)
- Same `DATABASE_URL` env var, URL rewritten to strip async driver prefix

### 4. Endpoint Upgrade (`app/api/v1/endpoints/documents.py`)
- Upload endpoint now dispatches `index_document.delay()` (Celery)
- Falls back to `background_tasks.add_task()` if Celery/Redis not available
- Zero change to response contract — still 202, still poll `/status`

---

## Architecture After Day 8

```
Upload Request
     │
     ▼
FastAPI (202 instant response)
     │
     ├──▶ [Celery available] → Redis broker → Worker process → index file → PostgreSQL
     │
     └──▶ [No Redis] → FastAPI BackgroundTask → index file → PostgreSQL

Query Request
     │
     ▼
FastAPI
     │
     ├──▶ [Cache hit] → Redis → response (< 5ms)
     │
     └──▶ [Cache miss] → Embedder → Vector DB → LLM → Redis (cache) → response
```

---

## Concepts Learned

- **Redis**: In-memory key-value store. `SETEX` for TTL. Pattern-match `KEYS`. Graceful degradation.
- **Cache key design**: Normalize input → include all dimensions → hash for fixed length → namespace with prefix
- **Cache invalidation**: The hardest problem. SHA256 prevents targeted invalidation → flush all.
- **Cache stampede**: Thundering herd when key expires under load. Solutions: lock, jitter, early refresh.
- **Celery**: Separate-process task queue. Broker = queue, Backend = result store.
- **Task retries**: `bind=True` + `self.retry(exc=exc)` + exponential backoff option
- **`task_acks_late`**: At-least-once delivery. Idempotent tasks required.
- **Async vs sync SQLAlchemy**: Same DB, two drivers, two session types — common pattern for FastAPI + Celery

---

## Files Changed

```
backend/app/core/cache.py              ← NEW: Redis query cache
backend/app/core/celery_app.py         ← NEW: Celery configuration
backend/app/core/database.py           ← UPDATED: sync engine for Celery
backend/app/workers/document_tasks.py  ← NEW: index_document Celery task
backend/app/services/rag_service.py    ← UPDATED: cache wired into query() and delete_document()
backend/app/api/v1/endpoints/documents.py ← UPDATED: Celery dispatch with BackgroundTasks fallback
learning/concepts/14_redis_caching.md  ← NEW
learning/concepts/15_celery_background_tasks.md ← NEW
```

---

## How to Run Locally (Day 8+)

```bash
# Terminal 1 — Redis
redis-server

# Terminal 2 — FastAPI
cd backend && uvicorn app.main:app --reload

# Terminal 3 — Celery worker (optional, falls back to BackgroundTasks without this)
cd backend && celery -A app.core.celery_app worker --loglevel=info -Q documents
```

Without Redis: app works, caching and Celery are silently skipped.  
With Redis only: caching works, Celery not needed if worker is running.  
With Redis + Celery: full production path.

---

## Interview Angles

**"How does your system handle large document uploads without timing out?"**
→ POST /upload returns 202 immediately. Celery worker picks up the task, runs embedding in background. Client polls /documents/{id}/status. If worker crashes, Celery retries automatically.

**"What caching strategy do you use for LLM responses?"**
→ Cache-aside with Redis. SHA256 key on (question + document_filter). TTL 1 hour. Skip cache for conversational queries. Invalidate all on document deletion.

**"How do you handle Redis being unavailable in production?"**
→ All cache operations wrapped in try/except. Cache miss = run full pipeline. Celery failure = fall back to FastAPI BackgroundTasks. Redis is an optimization, not a dependency.
