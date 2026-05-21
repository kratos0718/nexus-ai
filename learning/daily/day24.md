# Day 24 — Test Suite Expansion & README Polish

## What I Built

- **4 new test modules** covering observability traces, cache admin, JWT/password security, and rate limiter
- **README rewritten** — CI badge, 24-endpoint API table, Testing section, updated counts (10 modules, 291+ Q&As)

## New Test Files

### `backend/tests/test_traces.py`
Tests observability trace endpoints:
- Auth enforcement (list + stats both return 401 without token)
- Empty state: `traces == []`, all stats zero including `p95_duration_ms`
- After inserting records via `trace_service.record()` directly: stats reflect correct totals
- Pagination: `?limit=3` returns 3 records; `?limit=999` returns 422 (FastAPI validates `le=100`)

### `backend/tests/test_cache_admin.py`
Tests `/api/v1/cache/stats` and `/api/v1/cache/flush`:
- Auth enforcement
- Response shape: all 6 fields present, correct types (`bool`, `int`, `float`)
- Graceful degradation: without Redis, returns zeros and `redis_connected: False`
- Mocked Redis: flush returns correct count, stats show correct query count and memory

### `backend/tests/test_core_security.py`
Pure unit tests — no HTTP client needed:
- `hash_password`: returns string, not plaintext, different hashes per call (bcrypt random salt)
- `verify_password`: correct→True, wrong→False
- `create_access_token`: decodes with correct sub/email/type fields, has `exp`
- `decode_token`: invalid/tampered/empty all return None
- `create_refresh_token`: type="refresh", different token from access
- Expired token (backdated `exp`): returns None

### `backend/tests/test_rate_limit.py`
Unit tests with mocked Redis (no real Redis needed):
- First/within/at-boundary requests allowed, return correct remaining count
- Over limit raises `RateLimitExceeded` with `limit` and `retry_after` attributes
- User key (prefix `user:`) uses 100/hr limit; IP key uses 30/hr limit
- `ConnectionError` / `TimeoutError` from Redis → allow through (fail open), return limit value
- Custom limit override works for per-endpoint tighter limits

## Key Decisions

**Why insert traces directly via `trace_service.record()` not via HTTP?**
The `/api/v1/chat/query` endpoint makes a real LLM call. Using the service directly inserts realistic trace data without needing Groq. This tests the stats aggregation logic, not the LLM call.

**Why test ownership isolation as 404 not 403?**
Returning 403 (Forbidden) reveals that the resource exists — an attacker learns to keep guessing IDs. 404 (Not Found) gives zero information about resources belonging to other users.

**Why `side_effect = ConnectionError(...)` for Redis tests?**
We need to test graceful degradation — if Redis goes down, the app must continue working rather than returning 500. `side_effect` forces the mock to raise an exception, simulating Redis unavailability.

**Why `patch("app.core.rate_limit._get_redis")` and not `patch("redis.Redis")`?**
`patch` works at the import site — where the code uses the object. `rate_limit.py` imports and uses `_get_redis`, so that's what we patch. Patching `redis.Redis` would affect the redis module itself, not the already-imported reference in rate_limit.

## Commands Run

```bash
# Run new test files
pytest tests/test_traces.py -v
pytest tests/test_cache_admin.py -v
pytest tests/test_core_security.py -v
pytest tests/test_rate_limit.py -v

# Full suite with coverage
pytest tests/ --cov=app --cov-report=term-missing -v

# Verify no ruff issues
ruff check app/ tests/ --select E,F,W,I --ignore E501
```

## Interview Q&As (Q292–Q296)

**Q292. What is the difference between a unit test and an integration test?**
A: Unit tests isolate one function — all external deps are mocked. They run in milliseconds. Integration tests use real components wired together (real DB, real HTTP routing) — they run in seconds. Nexus AI uses integration tests for endpoints (real SQLite, real FastAPI) and unit tests for pure logic (JWT, hashing, rate limiter) where mocking the external dep (Redis) is straightforward.

**Q293. How do you test endpoints that require authentication without making real auth calls in each test?**
A: The `auth_client` fixture creates a user + logs in once, then sets `client.headers["Authorization"]` for all subsequent requests in that test. It returns `(client, user)` so tests can assert on the user's ID. This avoids repeating the register+login dance in every test while keeping auth logic exercised.

**Q294. What is `dependency_overrides` in FastAPI and why is it better than mocking the ORM?**
A: `dependency_overrides` swaps a FastAPI dependency (like `get_db`) with a test version at the ASGI layer. Every endpoint that calls `Depends(get_db)` gets the test session instead. Mocking the ORM directly couples tests to implementation (which ORM methods are called, in what order). Overriding `get_db` is a clean contract: "give me a DB session." The swap is automatically scoped — clear overrides after each test.

**Q295. What does `--cov-fail-under=40` do and how do you decide on the threshold?**
A: It fails the pytest run if total line coverage drops below 40%. This prevents adding large untested features. Set the threshold to your current coverage (so it passes today) and raise it gradually. Raising it forces developers to add tests as they add features. Never lower it — only raise.

**Q296. How do you test that your app gracefully handles Redis being unavailable?**
A: Mock the Redis client to raise `ConnectionError` on any call. Then assert that the endpoint returns 200 with sensible defaults (zeros, `connected: false`) rather than 500. The key code pattern: wrap all Redis calls in try/except and return a degraded response. The test verifies the catch path runs correctly.
