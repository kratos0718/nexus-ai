# Production API Design — From Zero to Production

## What makes an API "production-grade"?

A development API does what you need in the demo. A production API does what users need under real conditions: unexpected inputs, partial outages, high concurrency, and the fact that debugging problems at 3am is very different from debugging them during development.

The difference comes down to four properties:
1. **Observable** — you can tell what it's doing and why it failed
2. **Resilient** — partial failures don't cascade into total failures
3. **Debuggable** — you can trace a specific request through the system
4. **Documented** — its behavior is discoverable without reading the source code

---

## Level 1: The 12-Factor App

The 12-Factor App is a methodology for building production software published by Heroku engineers. Every factor addresses a real failure mode.

The most important factors for an API:

**Factor 3: Config (store config in the environment)**
Never hardcode API keys, database URLs, or secrets. Use environment variables.
```python
# Bad
GROQ_API_KEY = "gsk_abc123"  # in source code

# Good
GROQ_API_KEY = os.getenv("GROQ_API_KEY")  # from environment
```
Why: source code is often public (GitHub). Config changes between environments (dev/staging/prod). Secrets in code get leaked in git history even after deletion.

**Factor 11: Logs (treat logs as event streams)**
Don't write logs to files. Write to stdout/stderr. Let the platform (Docker, Kubernetes, systemd) handle log routing to wherever they need to go.
```python
# Bad
with open("/var/log/app.log", "a") as f:
    f.write(f"Query received: {question}\n")

# Good
logger.info(f"Query received: {question}")  # writes to stdout
```
Why: stdout is universal. Log files fill up disks. Containers have no persistent filesystem by default.

---

## Level 2: Health checks

A health check endpoint tells load balancers, orchestration systems, and Docker's HEALTHCHECK whether the service is ready to receive traffic.

**Basic health check (too simple):**
```python
@app.get("/health")
def health():
    return {"status": "ok"}  # always returns ok — even if DB is down
```

**Production health check:**
```python
@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    checks = {}

    # Check each subsystem independently
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = "error"   # critical

    try:
        redis_client.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "degraded"   # non-critical, system still works

    from app.services.rag_service import _pipeline
    checks["pipeline"] = "ready" if _pipeline else "not_initialized"

    # Overall status: degraded if any critical check fails
    overall = "healthy" if checks["database"] == "ok" else "degraded"
    return {"status": overall, "checks": checks}
```

**Why distinguish "error" vs "degraded"?**
- `error`: the subsystem is required and it's down — the service cannot function (DB is down, all reads/writes fail)
- `degraded`: the subsystem is optional and it's down — the service still works but with reduced functionality (Redis is down, caching disabled but queries still work)

A load balancer typically takes a service out of rotation on `error` but not on `degraded`.

---

## Level 3: Request ID middleware

In a distributed system, one user action can generate dozens of log lines across multiple services. Without correlation, you can't tell which logs belong to the same request.

```
# Without request IDs:
2026-05-21 14:32:01 | INFO | Query received: What is chunking?
2026-05-21 14:32:02 | INFO | Retrieved 5 chunks
2026-05-21 14:32:04 | ERROR | LLM call failed: rate limit exceeded
# Which query failed? Can't tell from the logs.

# With request IDs:
2026-05-21 14:32:01 | INFO | request_id=a3f1... | Query received: What is chunking?
2026-05-21 14:32:02 | INFO | request_id=a3f1... | Retrieved 5 chunks
2026-05-21 14:32:04 | ERROR | request_id=a3f1... | LLM call failed: rate limit exceeded
# All three lines belong to the same request — instantly traceable.
```

**Implementation:**
```python
class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Accept client-supplied ID (frontend can correlate too)
        # or generate a new one
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)

        # Echo back in response — frontend can log this for end-to-end tracing
        response.headers["X-Request-ID"] = request_id
        return response
```

The ID is stored in `request.state` — available to any endpoint:
```python
@router.post("/chat/query")
async def query(request: Request, ...):
    rid = getattr(request.state, "request_id", "unknown")
    logger.info(f"request_id={rid} | question={question[:50]}")
```

**End-to-end tracing:**
Frontend generates a UUID before the fetch call, passes it as `X-Request-ID`. If an error occurs, the user's browser console shows the same ID as the backend logs — support can find the exact request in seconds.

---

## Level 4: Structured logging

Unstructured logs are for humans to read. Structured logs are for machines to query.

```python
# Unstructured (text)
logger.info(f"Query from user {user_id}: {question} took {duration_ms:.0f}ms")
# Output: "Query from user 42: What is RAG? took 1234ms"
# Problem: to find all queries > 2000ms, you need regex

# Structured (JSON)
logger.info("query_complete", extra={
    "user_id": user_id,
    "duration_ms": duration_ms,
    "tokens": total_tokens,
})
# Output: {"message": "query_complete", "user_id": 42, "duration_ms": 1234, "tokens": 2891}
# Problem solved: SELECT WHERE duration_ms > 2000 — SQL query on your log aggregator
```

**Loguru JSON serialization:**
```python
if os.getenv("LOG_FORMAT") == "json":
    logger.add(sys.stdout, serialize=True)  # outputs newline-delimited JSON
```

Newline-delimited JSON (ndjson) is the standard format for log aggregators like Datadog, Grafana Loki, AWS CloudWatch, and Google Cloud Logging. Each line is a complete JSON object — they can be ingested, indexed, and queried by field.

**Log levels — what to log at each level:**
- `DEBUG`: detailed diagnostic info, verbose, never enabled in production
- `INFO`: normal operations — request received, query completed, document indexed
- `WARNING`: unexpected but recoverable — Redis down (falling back to no-cache), retrying
- `ERROR`: failed operations that need attention — DB connection failed, unhandled exception
- `CRITICAL`: system cannot function — never log this and continue

---

## Level 5: Graceful degradation

A production system must handle partial failures without taking the whole service down.

**The pattern:**
```python
try:
    result = expensive_operation()
except Exception as e:
    logger.warning(f"Optional service failed: {e}. Falling back to default.")
    result = default_value
```

**Examples in Nexus AI:**
1. Redis down → cache miss, query still runs (just slower)
2. Redis down → rate limiting disabled, requests still served
3. RAGAS import fails → eval runner skips RAGAS, returns custom metrics only
4. HyDE LLM call fails → falls back to original question for retrieval
5. Auto-title generation fails → conversation keeps "New Conversation" title

**The invariant:** Fallbacks should degrade gracefully (slower, less featured) not catastrophically (500 error, data loss).

**Don't degrade silently:** Always log the fallback:
```python
except Exception as e:
    logger.warning(f"Cache unavailable (Redis down?): {e}. Serving uncached.")
    # The WARNING appears in logs — ops team knows caching is degraded
```

---

## Level 6: Error response design

Every error response should give the client enough information to either fix the problem themselves or report it clearly.

```python
# Bad — no context
return JSONResponse(status_code=500, content={"error": "Server error"})

# Good — actionable information
return JSONResponse(
    status_code=422,
    content={
        "detail": "Question contains blocked pattern. Remove injection-like phrases.",
        "type": "ValidationError",
        "request_id": request_id,  # enables support to find the log
    }
)
```

**HTTP status code guide:**
- `200` — success
- `201` — created (POST that creates a resource)
- `202` — accepted (async operation started, check status later)
- `400` — bad request (client's fault — invalid input, missing field)
- `401` — unauthorized (no token or invalid token)
- `403` — forbidden (valid token but insufficient permissions)
- `404` — not found (resource doesn't exist or belongs to another user)
- `409` — conflict (document not ready, duplicate resource)
- `422` — unprocessable entity (Pydantic validation failed — correct data shape but invalid values)
- `429` — too many requests (rate limit exceeded, include `Retry-After` header)
- `500` — internal server error (your fault — log and investigate)
- `503` — service unavailable (temporarily down — load balancer should retry)

**Prefer 404 over 403 for user-scoped resources:**
`GET /documents/{id}` where `id` belongs to another user → return 404, not 403.
Why: 403 reveals that the resource exists; 404 prevents enumeration attacks.

---

## Level 7: Environment-based configuration

Different environments need different behavior without code changes.

```python
# config.py — single source of truth for all settings
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    groq_api_key: str
    jwt_secret_key: str
    database_url: str = "sqlite+aiosqlite:///./nexus.db"
    redis_url: str = "redis://localhost:6379/0"
    log_format: str = "text"
    log_level: str = "INFO"
    allowed_origins: str = "http://localhost:3000"
    debug: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()  # reads from env vars + .env file
```

`pydantic_settings` validates config at startup — if `GROQ_API_KEY` is missing, the app fails immediately with a clear error instead of crashing at runtime when the first query tries to use it.

**`.env.example`** — committed to git, documents all required and optional vars:
```
# Required
GROQ_API_KEY=gsk_your_key_here

# Optional — defaults work for local dev
DATABASE_URL=sqlite+aiosqlite:///./nexus.db
LOG_FORMAT=text
```

`.env` — gitignored, contains real secrets. Developers copy `.env.example` → `.env` and fill in real values.

---

## Level 8: API versioning and backward compatibility

Versioning protects existing clients when you need to change API behavior.

**URL versioning** (what Nexus uses):
```
/api/v1/chat/query    ← stable, never changes
/api/v2/chat/query    ← new version with breaking changes
```

Old clients continue hitting `/v1`. New clients can use `/v2`. Both run simultaneously.

**When to create a new version:**
- Removing a field from a response
- Changing a field's type (string → integer)
- Changing a field's meaning
- Removing an endpoint

**Non-breaking changes (no new version needed):**
- Adding new optional fields to requests (with defaults)
- Adding new fields to responses (clients ignore unknown fields)
- Adding new endpoints

**Request schema evolution:**
```python
# v1 — existing clients send this
class QueryRequestV1(BaseModel):
    question: str

# v2 — add optional field with default = backward compatible
class QueryRequestV2(BaseModel):
    question: str
    retrieval_mode: str = "standard"  # default preserves v1 behavior
```

Adding `retrieval_mode` with a default is backward compatible — v1 clients who don't send it get standard retrieval. No version bump needed.

---

## Quick reference

| Pattern | What it solves |
|---------|----------------|
| 12-Factor config | Secrets never in code, easy environment switching |
| Health endpoint | Load balancers know when service is ready |
| Request ID | Correlate logs across services for one request |
| Structured logs (JSON) | Machine-queryable logs in aggregation systems |
| Graceful degradation | Partial outages don't cascade to total failure |
| Error response design | Clients get actionable, debuggable error info |
| `.env.example` | New developers know all required config without reading code |
| URL versioning | Existing clients survive API changes |
