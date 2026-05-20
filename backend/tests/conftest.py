"""
Shared pytest fixtures for all tests.

Strategy:
- Use an in-memory SQLite database per test (fast, isolated, no cleanup needed)
- Override the get_db dependency so endpoints hit the test DB
- Override get_current_user for tests that need auth without a real JWT
- The RAG pipeline is NOT started in tests — endpoints that need it
  are tested with mocks
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.main import app
from app.core.database import Base, get_db
from app.core.dependencies import get_current_user
from app.models.user import User


# ── In-memory SQLite for each test session ────────────────────────────────────

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


# ── Test HTTP client ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    """
    HTTPX async client that hits the real FastAPI app.
    The get_db dependency is overridden to use the test database session.
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c

    app.dependency_overrides.clear()


# ── Authenticated client fixture ──────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def auth_client(db_session):
    """
    Client with a real registered + logged-in user.
    Returns (client, token, user_data) tuple.
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        # Register
        reg = await c.post("/api/v1/auth/register", json={
            "email": "test@nexus.ai",
            "password": "testpass123",
            "full_name": "Test User",
        })
        assert reg.status_code == 201
        token = reg.json()["access_token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c, token

    app.dependency_overrides.clear()


# ── Mock current user (skip JWT for unit tests) ───────────────────────────────

@pytest.fixture
def mock_user():
    return User(
        id=1,
        email="mock@nexus.ai",
        full_name="Mock User",
        hashed_password="hashed",
        is_active=True,
    )


@pytest_asyncio.fixture
async def authed_client_no_db(mock_user):
    """
    Client with mocked auth but NO real DB override.
    Use for testing endpoints that don't need database queries.
    """
    async def override_user():
        return mock_user

    app.dependency_overrides[get_current_user] = override_user

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c

    app.dependency_overrides.clear()
