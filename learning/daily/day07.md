# Day 7 — Alembic Migrations + Pytest Test Suite + Docker

## What We Built Today

| Component | File | Purpose |
|-----------|------|---------|
| Alembic config | `backend/alembic/env.py` | Wires models → migrations, batch mode for SQLite |
| Initial migration | `alembic/versions/*_initial_schema.py` | Creates all tables from scratch |
| Auth tests | `tests/test_auth.py` | 10 tests: register, login, refresh, /me |
| Document tests | `tests/test_documents.py` | 8 tests: upload, list, delete, isolation |
| Conversation tests | `tests/test_conversations.py` | 7 tests: CRUD, cross-user isolation |
| pytest config | `backend/pytest.ini` | asyncio_mode = auto |
| Test fixtures | `tests/conftest.py` | In-memory DB, client, auth fixtures |
| Backend Dockerfile | `backend/Dockerfile` | Multi-stage production image |
| Frontend Dockerfile | `frontend/Dockerfile` | Multi-stage Next.js standalone |
| Docker Compose | `docker-compose.yml` | Dev infra + prod profile |
| Next.js config | `frontend/next.config.ts` | `output: "standalone"` for Docker |

**Test results: 26/26 passing**

---

## Alembic — Database Migration System

### Why Migrations?

Without Alembic, schema changes are manual and dangerous:
```bash
# What you do WITHOUT migrations (bad):
sqlite3 nexus.db "ALTER TABLE documents ADD COLUMN user_id INTEGER"
# What happens when your colleague pulls the code?
# Their DB doesn't have user_id. App crashes. No history. No rollback.

# What you do WITH migrations (good):
alembic revision --autogenerate -m "add_user_id_to_documents"
alembic upgrade head
# Every developer runs this. Version-controlled. Reversible. Reproducible.
```

Migrations are the diff system for your database schema.

### How Alembic Works

```
SQLAlchemy Models (Python classes)
        ↓
alembic revision --autogenerate
        ↓
Migration file (versions/abc123_description.py)
    upgrade() → SQL to apply the change
    downgrade() → SQL to reverse it
        ↓
alembic upgrade head
        ↓
alembic_version table in DB tracks which revision is current
```

### env.py — The Critical Config File

```python
# alembic/env.py

# 1. Import ALL models so their tables appear in Base.metadata
from app.core.database import Base
import app.models   # side-effect import: registers Document, User, Conversation, Message

target_metadata = Base.metadata   # Alembic compares this against the live DB

# 2. Use SYNC driver — Alembic doesn't support async
def get_sync_url():
    url = os.getenv("DATABASE_URL", "sqlite:///./nexus.db")
    url = re.sub(r"sqlite\+aiosqlite", "sqlite", url)        # strip async driver
    url = re.sub(r"postgresql\+asyncpg", "postgresql", url)  # strip async driver
    return url

# 3. batch_alter_table for SQLite compatibility
context.configure(
    connection=connection,
    target_metadata=target_metadata,
    render_as_batch=True,   # ← uses copy-and-move on SQLite instead of ALTER TABLE
)
```

**Why strip async drivers?** Alembic uses synchronous SQLAlchemy internally. `aiosqlite` and `asyncpg` are async drivers that Alembic's connection protocol can't use. We swap them for sync equivalents only for migrations — the app still uses async drivers at runtime.

**Why `render_as_batch=True`?** SQLite doesn't support `ALTER TABLE ... ADD CONSTRAINT` or `ALTER TABLE ... DROP COLUMN`. Batch mode works around this by: (1) creating a new temp table with the new schema, (2) copying data, (3) dropping old table, (4) renaming temp table. PostgreSQL uses the normal `ALTER TABLE` statements. Setting `render_as_batch=True` is safe on both databases.

### Migration File Anatomy

```python
# versions/73f34ca87f5c_initial_schema.py

revision = '73f34ca87f5c'        # unique ID for this migration
down_revision = None             # None = first migration; UUID = previous migration
                                 # forms a linked list: head → ... → base

def upgrade():
    """Run when: alembic upgrade head (or upgrade +1)"""
    op.create_table('users', ...)
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # For existing tables: use batch_alter_table
    with op.batch_alter_table('documents') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_documents_user_id', 'users', ['user_id'], ['id'])

def downgrade():
    """Run when: alembic downgrade -1 (or downgrade base)"""
    with op.batch_alter_table('documents') as batch_op:
        batch_op.drop_constraint('fk_documents_user_id', type_='foreignkey')
        batch_op.drop_column('user_id')
    op.drop_table('users')
```

### Key Alembic Commands

```bash
# Generate migration from model changes
alembic revision --autogenerate -m "add_user_settings_table"

# Apply all pending migrations
alembic upgrade head

# Apply one migration
alembic upgrade +1

# Roll back one migration
alembic downgrade -1

# Roll back to specific revision
alembic downgrade 73f34ca87f5c

# Roll back everything
alembic downgrade base

# See current revision
alembic current

# See full history
alembic history --verbose

# Mark DB as at current head without running migrations (for existing DBs)
alembic stamp head

# Generate SQL script without running (for review)
alembic upgrade head --sql
```

### When to Use `alembic stamp head`

When you already have the schema in your DB (e.g., from `create_tables()` called at startup), but you're adding Alembic for the first time. The migration would fail trying to create tables that already exist. Instead:
1. Write the migration that would create the current schema from scratch
2. `alembic stamp head` — tells Alembic "the DB is already at this revision, don't run it"
3. Future changes will generate new migrations on top

---

## Pytest — Testing Async FastAPI Applications

### Why Testing Matters for Placements

Interviewers often ask: "How do you know your code works?" Having 26 passing tests on a project you built in a week is a strong answer. It also shows you understand:
- Dependency injection (overriding `get_db` and `get_current_user`)
- Test isolation (in-memory DB, per-test cleanup)
- Mocking external dependencies (RAG pipeline, vector store)

### The Fixture Stack

```python
# conftest.py — runs before every test

@pytest_asyncio.fixture(scope="function")
async def db_engine():
    # Fresh in-memory SQLite per test — no leftover data between tests
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    # Teardown: drop all tables, dispose engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest_asyncio.fixture
async def client(db_session):
    # Override FastAPI's get_db to use test session
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()  # ← always clean up after test
```

**`scope="function"`** — default, creates new fixture for each test. This is what you want for DB isolation.

**`ASGITransport`** — makes HTTPX communicate with the FastAPI app directly in-process, without starting a real HTTP server. Faster and more reliable than `TestClient`.

### Overriding Dependencies

FastAPI's `app.dependency_overrides` is the key to testable applications:

```python
# Replace any dependency for a test
app.dependency_overrides[get_db] = lambda: test_db_session
app.dependency_overrides[get_current_user] = lambda: fake_user

# All endpoints that Depend() on these now get the test versions
response = await client.get("/api/v1/documents/")

# Always clean up — otherwise overrides bleed into other tests
app.dependency_overrides.clear()
```

This is why the service layer matters — if endpoints directly instantiated their own DB connections, you couldn't override them.

### Mocking External Services

The RAG pipeline loads ML models (384MB sentence-transformer). We don't want that in tests. Mock at the service layer:

```python
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_upload_document_success(auth_client):
    client, _ = auth_client

    # Mock the background indexing — don't actually embed or store
    with patch("app.services.rag_service.RAGService.index_file_background",
               new_callable=AsyncMock):
        res = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("policy.txt", io.BytesIO(b"content"), "text/plain")},
        )

    assert res.status_code == 202   # still tests the HTTP layer, validation, DB record creation
```

`new_callable=AsyncMock` is required for async functions — `MagicMock` is synchronous and would cause "coroutine was never awaited" errors.

### Testing Security — Isolation Tests

The most important tests verify that users can't access each other's data:

```python
@pytest.mark.asyncio
async def test_get_other_users_document_returns_404(auth_client, client, db_session):
    user1_client, _ = auth_client
    # User 1 uploads a document
    upload = await user1_client.post("/api/v1/documents/upload", ...)
    doc_id = upload.json()["document_id"]

    # User 2 registers
    reg2 = await client.post("/api/v1/auth/register", json={...})
    client.headers["Authorization"] = f"Bearer {reg2.json()['access_token']}"

    # User 2 tries to access user 1's document
    res = await client.get(f"/api/v1/documents/{doc_id}/status")
    assert res.status_code == 404   # not 403 — don't reveal document exists!
```

**Why 404 not 403?** 403 Forbidden tells the attacker "this document exists, you just can't access it." 404 Not Found reveals nothing. Correct security behavior: treat unauthorized-access as not-found.

---

## Docker Multi-Stage Builds

### Why Multi-Stage?

Without multi-stage:
```
FROM python:3.11
RUN apt-get install build-essential gcc libpq-dev ...  # 500MB
COPY requirements.txt .
RUN pip install -r requirements.txt                     # compiles C extensions
COPY . .
# Final image: ~2GB (build tools + packages + code)
```

With multi-stage:
```
# Stage 1: build — has all tools
FROM python:3.11-slim AS deps
RUN apt-get install build-essential ...  # 500MB here, discarded
RUN pip install -r requirements.txt      # compiles extensions

# Stage 2: runtime — only what we need to RUN the app
FROM python:3.11-slim AS runtime
COPY --from=deps /usr/local/lib/python3.11/site-packages ...  # just the packages
COPY --from=deps /usr/local/bin ...                            # just the scripts
# Final image: ~400MB (no build tools)
```

### Backend Dockerfile Pattern

```dockerfile
FROM python:3.11-slim AS deps

RUN apt-get install build-essential libpq-dev ...  # needed to COMPILE packages
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim AS runtime

# Copy ONLY site-packages from deps — not the build tools
COPY --from=deps /usr/local/lib/python3.11/site-packages ...
COPY --from=deps /usr/local/bin ...

# Runtime libs only (not dev tools)
RUN apt-get install libpq5 curl ...

COPY . .

# Non-root user — security best practice
RUN useradd -m -u 1000 nexus && chown -R nexus:nexus /app
USER nexus

HEALTHCHECK CMD curl -f http://localhost:8000/health

# Run migrations first, then start the server
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app ..."]
```

**Why run migrations in CMD?** `alembic upgrade head` is idempotent (safe to run repeatedly). Running it at container startup means every deployment automatically applies schema changes before the server starts. No separate migration step needed.

### Next.js Standalone Build

```dockerfile
# Stage 2: Next.js builder
FROM node:20-alpine AS builder
RUN npm run build
# .next/standalone/ contains a self-contained Node.js server — no node_modules needed

# Stage 3: runtime
FROM node:20-alpine AS runtime
COPY --from=builder /app/.next/standalone ./    # ~ 50MB vs 500MB with node_modules
COPY --from=builder /app/.next/static ./.next/static
CMD ["node", "server.js"]   # standalone server, no Next.js CLI needed
```

**`output: "standalone"` in `next.config.ts`** — tells Next.js to bundle everything the server needs into `.next/standalone/`. Without this, you'd need to copy `node_modules` (500MB+) into the Docker image.

### Docker Compose Profiles

```yaml
services:
  postgres:
    # No profile — always starts with docker compose up

  backend:
    profiles: ["prod"]    # Only starts with: docker compose --profile prod up

  frontend:
    profiles: ["prod"]
```

**For development:** `docker compose up postgres redis -d` — just the infrastructure. FastAPI and Next.js run locally with hot reload.

**For production:** `docker compose --profile prod up -d` — everything containerized.

---

## Files Changed Today

```
backend/alembic/                           ← NEW: Alembic directory
backend/alembic/env.py                     ← configured for our models + batch mode
backend/alembic/versions/*_initial_schema  ← initial migration (all tables)
backend/alembic.ini                        ← configured file_template
backend/pytest.ini                         ← asyncio_mode = auto
backend/tests/conftest.py                  ← DB fixtures, client, auth fixtures
backend/tests/test_auth.py                 ← 10 auth tests
backend/tests/test_documents.py            ← 8 document tests (incl. isolation)
backend/tests/test_conversations.py        ← 7 conversation tests (incl. isolation)
backend/requirements.txt                   ← added alembic, pytest, bcrypt pin
backend/Dockerfile                         ← multi-stage production image
frontend/Dockerfile                        ← multi-stage Next.js standalone
frontend/next.config.ts                    ← output: standalone
docker-compose.yml                         ← dev infra + prod profile
```
