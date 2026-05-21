# Day 17 — Production Hardening

## What we built

Four production-readiness improvements: request ID middleware (log correlation), structured logging configuration, detailed health checks (per-subsystem status), and a rewritten README + cleaned `.env.example`.

---

## Files created / modified

| File | Change |
|------|--------|
| `backend/app/middleware/request_id.py` | NEW: X-Request-ID middleware |
| `backend/app/middleware/__init__.py` | NEW: package marker |
| `backend/app/main.py` | Logging config, RequestIDMiddleware, enhanced /health |
| `.env.example` | Cleaned up — accurate vars with explanations |
| `README.md` | Complete rewrite — architecture diagram, features, quick start |
| `learning/concepts/25_production_api_design.md` | 8-level concept guide |

---

## Request ID middleware

Every HTTP request now gets a unique identifier:

```
Request arrives:
  Header X-Request-ID: abc-123 (client supplied)
  → or → X-Request-ID: <generated UUID>

During request:
  request.state.request_id = "abc-123"
  All log lines include: request_id=abc-123

Response sent:
  Header X-Request-ID: abc-123
  → client can read this and log it too
```

Implementation uses Starlette's `BaseHTTPMiddleware`:

```python
class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
```

**The middleware stack order matters.** Registered after CORS but before routes — so the ID is available in all endpoint handlers.

**Unhandled exception handler now includes the request ID:**
```python
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(f"request_id={request_id} | {type(exc).__name__}: {exc}")
    return JSONResponse(500, {"detail": "...", "request_id": request_id})
```
When a user reports an error, they can share the `request_id` from the response body and you can find the exact log line in seconds.

---

## Structured logging

Two modes controlled by `LOG_FORMAT` env var:

```python
def _configure_logging():
    if os.getenv("LOG_FORMAT", "text") == "json":
        logger.add(sys.stdout, serialize=True, enqueue=True)
        # Output: {"time": "...", "level": "INFO", "message": "Query received", ...}
    else:
        logger.add(sys.stdout, colorize=True, format="...", enqueue=True)
        # Output: 2026-05-21 14:32 | INFO | app.main:45 | Nexus AI ready
```

`enqueue=True` makes logging thread-safe — all log writes go through an internal queue, preventing interleaving when multiple async tasks log simultaneously.

**Production:** set `LOG_FORMAT=json` → log aggregators (Datadog, Grafana Loki, CloudWatch) can index fields and run queries like `SELECT * WHERE duration_ms > 5000`.

**Development:** default `LOG_FORMAT=text` → human-readable with colours.

---

## Enhanced health endpoint

The old health check always returned `{"status": "healthy"}` — useless. The new one probes each subsystem:

```
GET /health

{
  "status": "healthy",          ← or "degraded" if database fails
  "version": "1.0.0",
  "checks": {
    "database":     "ok",       ← SELECT 1 against PostgreSQL/SQLite
    "redis":        "ok",       ← redis_client.ping()
    "pipeline":     "ready",    ← _pipeline is not None
    "vector_store": "ok (147 chunks)"  ← collection_info()
  }
}
```

**Status semantics:**
- `ok` — subsystem is healthy
- `degraded` — subsystem is down but service still works (Redis)
- `error` — subsystem is down and service will malfunction (DB)
- `not_initialized` — lazy-loaded, not yet used (pipeline on cold start)

Docker HEALTHCHECK in `docker-compose.yml` hits `/health`. A `"degraded"` overall status means the DB failed — Docker stops routing traffic to this container.

---

## README rewrite

The old README had:
- Outdated progress tracker ("In Progress" for Day 1-5)
- Architecture diagram missing most components
- No API reference table
- No project structure section
- Generic feature list

The new README has:
- Complete ASCII architecture diagram showing all layers
- Accurate feature list with all Day 1-17 capabilities
- Quick start that works (SQLite by default, no Docker required)
- API reference table with all major endpoints
- Configuration table (which vars are required vs optional)
- Full project structure tree
- Accurate tech stack

---

## .env.example cleanup

The old `.env.example` had 76 lines with many unused variables (`APP_NAME`, `APP_ENV`, `DEBUG`, `ANTHROPIC_API_KEY`, `LANGFUSE_*`, etc.) that the codebase doesn't actually read.

The new one:
- Only documents variables the code actually uses
- Groups by: Required → Database → Redis → Vector Store → Embeddings → CORS → Logging → Frontend
- Each section explains when it applies and the default

The key principle: `.env.example` is documentation. Unused variables create confusion ("why do I need ANTHROPIC_API_KEY?").
