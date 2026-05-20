# Testing Async FastAPI Applications — Fixtures, Dependency Overrides, Mocking

## Why Testing Matters for Production Systems

Every system breaks eventually. Tests catch breakage before users do. More specifically:

- **Regression prevention**: new code can't silently break existing endpoints
- **Refactoring confidence**: you can reorganize code knowing tests will catch behavior changes
- **Documentation**: tests describe exactly how the API behaves — better than comments
- **Security verification**: isolation tests prove users can't access each other's data

For a placement project: 26 passing tests on a system you built in a week is a strong interview signal. It shows you understand dependency injection, test isolation, and mocking — not just "I wrote some code."

---

## The Fixture Stack

pytest fixtures are functions that set up state before a test and tear it down after. They compose: one fixture can depend on another.

```
db_engine           ← creates in-memory SQLite engine, drops all tables after test
    ↓
db_session          ← opens a transaction, rolls back after test (never commits to disk)
    ↓
client              ← overrides get_db with test session, creates HTTPX AsyncClient
    ↓
auth_client         ← registers a test user, logs in, returns (client, user_data)
    ↓
your test           ← gets an authenticated HTTP client hitting an in-memory DB
```

```python
# conftest.py

@pytest_asyncio.fixture(scope="function")  # "function" = fresh fixture per test
async def db_engine():
    # sqlite+aiosqlite:///:memory: — in-memory, gone when connection closes
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # create tables
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)    # drop tables
    await engine.dispose()                              # close all connections

@pytest_asyncio.fixture
async def db_session(db_engine):
    async with AsyncSession(db_engine, expire_on_commit=False) as session:
        yield session

@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),  # in-process, no real HTTP server
        base_url="http://test"
    ) as c:
        yield c

    app.dependency_overrides.clear()  # critical — clean up or fixtures bleed into next test
```

**`scope="function"`** — the default. Creates a new fixture instance for each test function. Use for DB isolation. Other scopes: `"module"` (once per file), `"session"` (once per entire test run) — use for expensive, read-only setup.

**`ASGITransport`** — makes HTTPX send requests directly to the FastAPI ASGI app in-process. No TCP, no port binding, no real HTTP server. 10-100x faster than `TestClient` with a live server.

**`expire_on_commit=False`** — SQLAlchemy ORM objects normally expire after commit (so the next access re-fetches from DB). In tests this causes errors when you access attributes after the session closes. Setting `False` keeps the Python-side data intact.

---

## Dependency Overrides — The Key to Testable Code

FastAPI's `app.dependency_overrides` is a dict that swaps any `Depends()` dependency for a test version:

```python
# Production: Depends(get_db) → opens a real DB session
# Test: Depends(get_db) → yields the test session instead

app.dependency_overrides[get_db] = lambda: test_session

# ALL endpoints that use Depends(get_db) now get the test session
response = await client.get("/api/v1/documents/")

# Clean up — otherwise this override affects the next test
app.dependency_overrides.clear()
```

You can override any dependency:

```python
# Skip auth for a test
fake_user = User(id=1, email="test@test.com")
app.dependency_overrides[get_current_user] = lambda: fake_user

# Or test auth explicitly by NOT overriding it
# (the real JWT verification runs against the test request headers)
```

This is why the service layer matters architecturally: if your endpoints directly instantiated DB sessions or HTTP clients, you couldn't intercept and swap them. Dependencies make the seams explicit.

---

## Mocking External Services

The RAG pipeline loads a 384MB sentence-transformer model. You don't want that in CI. Mock at the boundary where external services are called:

```python
from unittest.mock import patch, AsyncMock

async def test_upload_document_success(auth_client):
    client, _ = auth_client

    # Mock the background indexing — don't load the ML model
    with patch(
        "app.services.rag_service.RAGService.index_file_background",
        new_callable=AsyncMock  # REQUIRED for async functions
    ):
        res = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("policy.txt", io.BytesIO(b"content"), "text/plain")},
        )

    assert res.status_code == 202
    # This test still verified: HTTP routing, file parsing, DB record creation,
    # auth validation — just not the ML embedding step
```

**`AsyncMock` vs `MagicMock`**: `MagicMock` returns a regular value when called. `AsyncMock` returns a coroutine. If you mock an async function with `MagicMock`, calling it returns a coroutine object that's never awaited — Python logs "RuntimeWarning: coroutine was never awaited" and the code breaks. Always use `AsyncMock` for `async def` functions.

**Mock at the right layer**: mock at the service call boundary, not deep inside libraries. This tests your code paths while skipping the actual side effect.

---

## Security Testing — Isolation Tests

The most important security tests verify that users can't access each other's data. This is multi-tenancy correctness:

```python
async def test_get_other_users_document_returns_404(auth_client, client, db_session):
    user1_client, _ = auth_client

    # User 1 uploads a document
    with patch("app.services.rag_service.RAGService.index_file_background",
               new_callable=AsyncMock):
        upload = await user1_client.post("/api/v1/documents/upload",
            files={"file": ("doc.txt", io.BytesIO(b"content"), "text/plain")})
    doc_id = upload.json()["document_id"]

    # Register User 2
    await client.post("/api/v1/auth/register", json={
        "email": "user2@test.com", "password": "ValidPass123", "full_name": "User Two"
    })
    login2 = await client.post("/api/v1/auth/login",
        data={"username": "user2@test.com", "password": "ValidPass123"})
    client.headers["Authorization"] = f"Bearer {login2.json()['access_token']}"

    # User 2 tries to access User 1's document
    res = await client.get(f"/api/v1/documents/{doc_id}/status")
    assert res.status_code == 404  # not 403!
```

**Why 404, not 403?**

- 403 Forbidden tells the attacker: "this resource exists, you just can't access it"
- 404 Not Found reveals nothing: "I don't know what you're talking about"

Correct security posture: treat unauthorized access as "not found." The attacker learns nothing about what resources exist for other users. This is standard practice (GitHub, AWS S3 use this).

---

## pytest.ini — Configuration

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

`asyncio_mode = auto` makes pytest-asyncio automatically detect `async def test_*` functions and run them on the event loop. Without this, you need `@pytest.mark.asyncio` on every async test. The `auto` mode was added in pytest-asyncio 0.21 and is the current recommended approach.

---

## Test Organization Pattern

```
tests/
├── conftest.py          ← shared fixtures (db, client, auth_client)
├── test_auth.py         ← register, login, /me, token refresh, edge cases
├── test_documents.py    ← upload, list, delete, isolation
└── test_conversations.py← CRUD, cross-user isolation
```

Each file focuses on one resource. Fixtures are shared via conftest. Coverage per file:
- Happy path (what should work)
- Auth guards (missing token → 401, invalid token → 401)
- Validation (short password, duplicate email)
- Isolation (user A can't touch user B's data)
- Edge cases (delete nonexistent, get empty list)

---

## Interview Answers

**"How do you test async FastAPI endpoints?"**

Use `pytest-asyncio` with `asyncio_mode = auto`, `httpx.AsyncClient` with `ASGITransport` (in-process, no real server), and `pytest_asyncio.fixture` for async fixtures. Override `get_db` via `app.dependency_overrides` to inject a per-test in-memory SQLite database. Each test gets a fresh DB — no state bleeds between tests.

**"How do you mock async functions in Python?"**

Use `unittest.mock.AsyncMock` instead of `MagicMock`. `AsyncMock` returns a coroutine when called, so `await mock()` works. `MagicMock` returns a plain value — `await mock()` raises `TypeError: object MagicMock can't be used in 'await' expression`. For patching: `with patch("path.to.function", new_callable=AsyncMock):`.

**"What is dependency injection and why does it make code testable?"**

DI means functions declare what they need (dependencies) rather than creating them directly. FastAPI's `Depends()` is an example. Because dependencies are declared, not hardcoded, tests can swap them out via `app.dependency_overrides`. Without DI, a function that creates its own DB connection can't be tested without a real DB. With DI, you swap in an in-memory DB for tests. Same code, different runtime behavior.
