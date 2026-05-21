# Testing Patterns for Production Python APIs

## Why Testing Matters (and the right mental model)

Tests are not about proving code works — they're about **defining a contract** that must hold across all future changes. A test suite you can run in 3 seconds catches regressions that a manual 30-minute QA session misses.

The goal hierarchy:
1. **Correctness** — the code does what it's supposed to
2. **Isolation** — tests are independent, run in any order
3. **Speed** — fast tests get run; slow tests get skipped
4. **Coverage** — enough to give confidence, not 100% (diminishing returns above ~80%)

---

## The Testing Pyramid

```
        /\
       /  \      E2E Tests (slow, few)
      /    \     — "the whole system works"
     /──────\
    /        \   Integration Tests (medium)
   /          \  — "components work together"
  /────────────\
 /              \ Unit Tests (fast, many)
/________________\ — "each function works"
```

**Unit tests** — one function, all external deps mocked. Run in milliseconds.
**Integration tests** — real DB, real HTTP client, no LLM. Run in seconds.
**E2E tests** — real browser, real backend, real everything. Run in minutes.

Nexus AI focuses on integration tests (real SQLite, real HTTP) + unit tests for pure logic (JWT, hashing, rate limiter).

---

## pytest Fundamentals

### Test discovery
pytest finds tests by convention — no configuration needed:
```
tests/test_auth.py        # file must start with test_
  def test_login():       # function must start with test_
  class TestAuth:         # or class starting with Test
    def test_register():  # with methods starting with test_
```

### Fixtures — dependency injection for tests
Fixtures are pytest's killer feature. Instead of setUp/tearDown in each test, declare dependencies as function parameters:

```python
# conftest.py — shared across all tests in directory
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models.base import Base
from app.core.db import get_db

DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite session. Fresh schema for every test."""
    engine = create_async_engine(DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest_asyncio.fixture
async def client(db_session):
    """HTTP test client with DB dependency overridden."""
    async def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

Why `dependency_overrides`? FastAPI resolves dependencies at request time. Overriding `get_db` means every endpoint that calls `Depends(get_db)` gets your test session instead. No monkey-patching, no globals — clean and scoped to the test.

### Fixture scoping
```python
@pytest.fixture(scope="session")   # created once per test run
@pytest.fixture(scope="module")    # created once per test file
@pytest.fixture(scope="function")  # default: new instance per test
```
Use `function` scope for DB sessions (isolation). Use `session` scope for expensive one-time setup (e.g., loading ML models).

---

## FastAPI Integration Testing Pattern

The pattern used throughout Nexus AI:

```python
@pytest.mark.asyncio
async def test_create_document(auth_client):
    client, user = auth_client    # fixture returns tuple (client, user)
    
    res = await client.post("/api/v1/documents/upload", 
                            files={"file": ("test.txt", b"hello", "text/plain")})
    
    assert res.status_code == 201
    data = res.json()
    assert data["filename"] == "test.txt"
    assert data["user_id"] == user.id
```

Key points:
- **`AsyncClient` from httpx** — works with async FastAPI, not Flask's test client
- **`ASGITransport`** — routes requests directly to the ASGI app, no network
- **Assert status codes first** — gives a clear failure before JSON parse
- **Assert shape, not values** — check that `"id" in data`, not `data["id"] == 1` (fragile)

### The `auth_client` fixture pattern
Most endpoints require auth. Creating a user + logging in + getting a token in every test is repetitive. The `auth_client` fixture does it once:

```python
@pytest_asyncio.fixture
async def auth_client(client, db_session):
    # Register
    await client.post("/api/v1/auth/register", json={
        "email": "test@test.com",
        "password": "testpass123",
        "full_name": "Test User"
    })
    # Login
    res = await client.post("/api/v1/auth/login", json={
        "email": "test@test.com", "password": "testpass123"
    })
    token = res.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    
    # Return client + user object for assertions
    from app.models.user import User
    from sqlalchemy import select
    user = (await db_session.execute(select(User))).scalars().first()
    return client, user
```

---

## Mocking Strategies

### When to mock
Mock external I/O that:
1. Would make tests slow (LLM calls, network requests)
2. Would make tests non-deterministic (time, random)
3. Doesn't exist in CI (Redis, Groq API, ChromaDB)

Don't mock:
- Your own database (use real SQLite)
- Your own application logic (that defeats the purpose)
- Code that's fast and deterministic

### `unittest.mock.patch`
```python
from unittest.mock import patch, MagicMock

def test_cache_hit():
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps({"answer": "cached"}).encode()
    
    with patch("app.core.cache._get_redis", return_value=mock_redis):
        result = get_cached_query("what is the policy?")
        assert result == {"answer": "cached"}
        mock_redis.get.assert_called_once()  # verify the call happened
```

`patch` temporarily replaces the named object for the duration of the `with` block. The name must be **where the object is used**, not where it's defined:
```python
# cache.py imports redis — the module using it is app.core.cache
patch("app.core.cache._get_redis")   # CORRECT
patch("redis.Redis")                  # WRONG — patches the class, not the import
```

### `MagicMock` vs `AsyncMock`
```python
from unittest.mock import MagicMock, AsyncMock

# For sync functions
mock = MagicMock()
mock.some_method.return_value = 42

# For async functions (await-able)
mock = AsyncMock()
mock.some_method.return_value = 42
result = await mock.some_method()  # works correctly
```

### `side_effect` for exceptions
```python
mock.incr.side_effect = ConnectionError("Redis connection refused")
# Now calling mock.incr() raises ConnectionError
# Use to test error handling / graceful degradation
```

### `side_effect` as a function
```python
def fake_get(key):
    if "hits" in key:
        return b"10"
    return b"4"

mock.get.side_effect = fake_get
```

---

## Test Isolation Patterns

### Database isolation
Each test gets a **fresh in-memory database**. The fixture creates `Base.metadata.create_all` and drops everything after — no state leaks between tests.

Why not share a database across tests? Tests would depend on execution order. Insert in test_1, query in test_2 — pass if run together, fail if run alone. That's a hidden dependency, not a test.

### HTTP header isolation
```python
# Don't set auth headers globally — it leaks between tests
client.headers["Authorization"] = f"Bearer {token}"  # set in fixture
# Clear after: app.dependency_overrides.clear()        # reset in fixture teardown
```

### Import isolation
Using `patch` as a context manager (with statement) limits the mock to the test function. Prefer this over `@patch` decorator — easier to see scope and nesting.

---

## Coverage

### What coverage measures
Line coverage = percentage of code lines executed by tests. Branch coverage also checks if/else branches.

```
pytest tests/ --cov=app --cov-report=term-missing
```

Output shows which lines were NOT covered:
```
app/core/cache.py    85%    missing: 23-25, 47
```

Lines 23-25 are the exception handler for Redis timeout — you're not testing that path.

### The coverage gate
```yaml
# In CI: fail if coverage drops below threshold
pytest tests/ --cov=app --cov-fail-under=40
```

40% is a minimum, not a target. It catches the case where someone adds a 500-line feature with zero tests. As the project grows, raise the gate incrementally.

### What coverage doesn't measure
Coverage tells you lines were *executed*, not that they were *tested correctly*. You can reach 100% coverage with bad assertions. Coverage is a lower bound, not a quality signal.

---

## Testing Async Code

### `pytest-asyncio` setup
```python
# pyproject.toml or pytest.ini
[tool.pytest.ini_options]
asyncio_mode = "auto"   # mark all async tests automatically

# Or mark individually:
@pytest.mark.asyncio
async def test_something():
    ...
```

### Common async gotcha: event loop conflicts
Each test needs a fresh event loop. `pytest-asyncio` handles this with `function` scope. If you see `RuntimeError: Event loop is closed`, a fixture is holding a resource across loop boundaries — close it in the fixture teardown.

---

## Unit Tests for Pure Logic

For functions with no I/O (JWT, hashing, business logic), you don't need a client or DB:

```python
def test_hash_is_not_plaintext():
    h = hash_password("mysecretpassword")
    assert "mysecretpassword" not in h  # not stored in cleartext

def test_same_password_different_hashes():
    h1 = hash_password("password")
    h2 = hash_password("password")
    assert h1 != h2          # bcrypt uses random salt per call
    assert verify_password("password", h1)  # but verification still works
```

These tests run in milliseconds and catch regressions in security-critical code.

---

## Testing Ownership Isolation

A common security bug: user A can access user B's resources. Test it explicitly:

```python
async def test_ownership_isolation(client, db_session):
    # Create resource as User A
    res_a = await client.post("/api/v1/documents/upload", ...)
    doc_id = res_a.json()["id"]
    
    # Switch to User B
    await client.post("/api/v1/auth/register", json={"email": "b@b.com", ...})
    login = await client.post("/api/v1/auth/login", json={"email": "b@b.com", ...})
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    
    # User B tries to access User A's document
    res = await client.get(f"/api/v1/documents/{doc_id}")
    assert res.status_code == 404   # NOT 403 — don't leak existence
```

Return 404 (not found) instead of 403 (forbidden) — 403 reveals the resource exists and someone else owns it. 404 gives no information.

---

## pytest CLI Cheat Sheet

```bash
pytest tests/ -v                          # verbose: show each test name
pytest tests/ -x                          # stop on first failure
pytest tests/ -k "auth"                   # run tests matching keyword
pytest tests/ --tb=short                  # short traceback format
pytest tests/ -v --tb=long -s             # -s: show print() output

pytest tests/test_auth.py::test_login -v  # single test

pytest tests/ --cov=app --cov-report=html # HTML coverage report
open htmlcov/index.html                   # browse coverage visually
```

---

## Interview Q&A

**Q: What is the difference between a unit test and an integration test?**
A: Unit tests test one function/class in isolation — all external dependencies mocked. Run in milliseconds. Integration tests test how components work together — real DB, real HTTP routing. Run in seconds. Both are needed: unit tests for logic correctness, integration tests for wiring.

**Q: Why use `dependency_overrides` in FastAPI tests instead of mocking the DB?**
A: `dependency_overrides` is FastAPI's built-in DI swap — clean, scoped, type-safe. It routes all `Depends(get_db)` calls in the test to your session without any monkey-patching. When the test ends, you call `app.dependency_overrides.clear()` and the original dependency is restored. Mocking the ORM directly is fragile and couples tests to implementation details.

**Q: What does `patch("app.core.cache._get_redis")` vs `patch("redis.Redis")` do differently?**
A: `patch` replaces the name at the **import site** — where the code uses the object, not where it's defined. If `cache.py` does `from redis import Redis` and assigns it to `_get_redis`, patching `redis.Redis` replaces the class in the redis module but `cache.py` already has a reference to the original — so the patch has no effect. You must patch the name as it appears in the module being tested.

**Q: When would you choose `side_effect` over `return_value`?**
A: `return_value` always returns the same thing. `side_effect` lets you: (1) raise an exception, (2) return different values on successive calls (`side_effect = [1, 2, 3]` returns 1 first, then 2, then 3), or (3) run a function to compute the return value based on arguments. Use `side_effect` for error handling tests and stateful sequences.

**Q: What is a coverage gate and why set it in CI?**
A: A coverage gate fails the CI pipeline if test coverage drops below a threshold (`--cov-fail-under=40`). It prevents a developer from adding a large feature with zero tests — the build fails, forcing them to add tests before merging. Set the threshold to the current coverage level and raise it gradually. Never lower it.
