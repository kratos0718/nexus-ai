# Celery: Distributed Task Queue

## The Problem Celery Solves

HTTP has a timeout. Embedding a 100-page PDF takes 2–5 minutes. You can't keep an HTTP connection open that long.

```
Without Celery:
  Client → POST /upload → wait 3 minutes... → response
  (connection often drops, user confused, server blocks thread)

With Celery:
  Client → POST /upload → 202 Accepted (instant)
         ↓
     Celery task queued in Redis
         ↓
  Worker picks up task, runs for 3 min in background
         ↓
  Client polls GET /documents/{id}/status → READY
```

The HTTP handler returns **immediately**. The heavy work runs separately.

---

## Architecture

```
┌─────────────┐    dispatch    ┌─────────────┐    pop task    ┌──────────────┐
│  FastAPI    │ ─────────────▶ │    Redis    │ ◀──────────── │ Celery       │
│  (producer) │                │  (broker)   │               │ Worker       │
└─────────────┘                └─────────────┘               │ (consumer)   │
                                      │                       └──────────────┘
                                      │ store result                 │
                                      ▼                              │
                               ┌─────────────┐                      │ update DB
                               │  Redis      │                       ▼
                               │  (backend)  │               ┌──────────────┐
                               └─────────────┘               │  PostgreSQL  │
                                                             └──────────────┘
```

Three components:
1. **Broker** — message queue (Redis db 1). Stores "please run this task"
2. **Worker** — separate OS process that reads from broker and executes tasks
3. **Backend** — result store (Redis db 2). Stores "task X finished with result Y"

---

## Defining a Task

```python
from celery import Celery

celery_app = Celery(
    "nexus_ai",
    broker="redis://localhost:6379/1",
    backend="redis://localhost:6379/2",
)

@celery_app.task(
    bind=True,           # gives access to `self` (the task instance)
    max_retries=3,       # retry up to 3 times on failure
    default_retry_delay=60,  # wait 60s between retries
)
def index_document(self, document_id: str, file_path: str, filename: str):
    try:
        # ... do work ...
        pass
    except Exception as exc:
        raise self.retry(exc=exc)   # re-queue with delay
```

Key decorator options:
- `bind=True` — `self` is the task instance, gives access to `self.retry()`, `self.request.id`, etc.
- `max_retries=3` — after 3 failures, the task is marked FAILURE and not retried
- `default_retry_delay=60` — exponential backoff can be configured too
- `name=` — explicit task name (prevents issues with module renaming)

---

## Dispatching Tasks

```python
# In FastAPI endpoint (async context)
from app.workers.document_tasks import index_document

# .delay() = shortcut for .apply_async() with no options
index_document.delay(document_id, str(temp_path), file.filename)
# Returns an AsyncResult immediately — does NOT wait for task to finish
```

The endpoint returns 202 and the task runs in a worker process. Arguments must be **JSON-serializable** — no Python objects, no database sessions.

---

## Task States

```
PENDING → STARTED → SUCCESS
                 ↘ FAILURE → (retry) → STARTED → ...
                                               ↘ FAILURE (exhausted)
```

- `PENDING` — queued but not started
- `STARTED` — worker picked it up (requires `task_track_started=True`)
- `SUCCESS` — completed
- `FAILURE` — crashed and retries exhausted
- `RETRY` — waiting for next retry attempt

Nexus tracks this differently — it writes status directly to PostgreSQL:
```python
doc.status = DocumentStatus.PROCESSING  # STARTED
doc.status = DocumentStatus.READY       # SUCCESS
doc.status = DocumentStatus.FAILED      # FAILURE
```
This lets the FastAPI endpoint query status from the DB without needing the Celery result backend.

---

## Retry Pattern

```python
except Exception as exc:
    # Update DB to show failure
    doc.status = DocumentStatus.FAILED
    doc.error_message = str(exc)[:500]
    db.commit()

    # Re-raise through Celery's retry mechanism
    raise self.retry(exc=exc)
    # ^ waits default_retry_delay seconds, then re-runs the task
    # After max_retries, raises the exception as MaxRetriesExceededError
```

Why `raise self.retry(exc=exc)` instead of just `self.retry(exc=exc)`?
- `self.retry()` raises a `Retry` exception internally
- Without `raise`, Python continues executing after the call (unexpected behavior)
- With `raise`, it propagates up and Celery's machinery catches it

---

## Async FastAPI + Sync Celery

FastAPI uses `async def` and `asyncio`. Celery workers run synchronous code. They can't share the same SQLAlchemy session.

```python
# FastAPI (async)
async_engine = create_async_engine("postgresql+asyncpg://...")
AsyncSessionLocal = async_sessionmaker(...)

async def get_db():              # FastAPI dependency
    async with AsyncSessionLocal() as session:
        yield session

# Celery (sync)
sync_engine = create_engine("postgresql://...")  # no asyncpg driver
SyncSessionLocal = sessionmaker(...)

def get_sync_db() -> Session:   # Celery helper
    return SyncSessionLocal()
```

Same database, two access paths:
- FastAPI → `asyncpg` driver → `AsyncSession`
- Celery → `psycopg2` driver → `Session`

This is normal. SQLAlchemy supports both from one `DATABASE_URL` (Nexus strips the `+asyncpg` for the sync engine).

---

## Running Workers

```bash
# Start one worker, consuming from "documents" queue
celery -A app.core.celery_app worker --loglevel=info -Q documents

# Production: multiple workers for parallelism
celery -A app.core.celery_app worker --loglevel=info -Q documents --concurrency=4

# Monitor tasks in real-time (Flower UI)
celery -A app.core.celery_app flower --port=5555
```

`task_routes` in `celery_app.py` sends document tasks to the `documents` queue — you can have separate queues for different priority levels (e.g., `critical`, `documents`, `reports`).

---

## Fallback Pattern (Nexus Design)

Nexus falls back to FastAPI's built-in `BackgroundTasks` when Celery/Redis isn't available:

```python
celery_dispatched = False
try:
    from app.workers.document_tasks import index_document
    index_document.delay(document_id, str(temp_path), file.filename)
    celery_dispatched = True
except Exception:
    pass

if not celery_dispatched:
    background_tasks.add_task(rag_service.index_file_background, ...)
```

FastAPI `BackgroundTasks` vs Celery:
| | FastAPI BackgroundTasks | Celery |
|---|---|---|
| Process | Same process as API | Separate worker process |
| Survives API crash | No | Yes (task stays in queue) |
| Retries | No | Yes |
| Monitoring | No | Yes (Flower, Celery events) |
| Scaling | No (tied to API workers) | Yes (add more Celery workers) |
| Redis required | No | Yes |

---

## `task_acks_late=True`

By default, Celery acknowledges (removes) a task from the queue **before** running it. If the worker crashes mid-task, the task is lost.

With `task_acks_late=True`:
- Task is acknowledged **after** it completes (success or failure)
- If worker crashes, task goes back to queue and another worker picks it up
- Risk: task may run twice if worker crashes after completing but before ack

For document indexing, running twice is safe (re-indexing overwrites existing chunks). For tasks with side effects like sending emails, you'd need **idempotency keys** to prevent duplicates.

---

## Interview Questions

**Q: What's the difference between Celery and threading for background tasks?**
Threading runs in the same process and shares memory — good for I/O-bound tasks but limited by the GIL for CPU-bound work. Celery uses separate processes (even separate machines) — no shared memory, survives crashes, horizontally scalable. For long-running AI tasks (embeddings), Celery is the right choice.

**Q: Why does Celery need both a broker and a backend?**
Broker (Redis/RabbitMQ) is a task queue — "please run this". Backend (Redis/DB) is a result store — "this task returned X". You can use Celery without a backend if you don't need to retrieve results (just fire-and-forget), which is Nexus's approach (results go to PostgreSQL directly).

**Q: How would you handle a task that should only run once at a time per document?**
Use a Celery `lock` pattern: store a key in Redis like `indexing:{document_id}` before starting, delete it after. If the key already exists, the task returns early (idempotency guard). Alternative: database-level check on the PROCESSING status.

**Q: What is `worker_prefetch_multiplier=1` and why?**
By default, each Celery worker pre-fetches 4 tasks from the queue (even if only running 1). For long tasks (embedding takes 3 minutes), prefetching blocks other workers from picking up tasks. Setting `prefetch_multiplier=1` means each worker only holds 1 task at a time — fairer distribution.
