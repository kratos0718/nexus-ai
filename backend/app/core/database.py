"""
Database engine, session factory, and base model for SQLAlchemy.
Uses SQLite for dev (no Docker), PostgreSQL for production (swap DATABASE_URL).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# SQLite for dev — file-based, zero config, no Docker needed
# Switch to postgres+asyncpg://... in production .env
SQLITE_URL = "sqlite+aiosqlite:///./nexus.db"

# Async engine — required for FastAPI (async/await everywhere)
async_engine = create_async_engine(
    SQLITE_URL,
    echo=False,         # set True to log every SQL query (debug)
    connect_args={"check_same_thread": False},  # SQLite-only: allow multi-thread
)

# Session factory — create one session per request, close after
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,   # keep objects usable after commit
)


class Base(DeclarativeBase):
    """All ORM models inherit from this. Gives them __tablename__, metadata, etc."""
    pass


async def create_tables():
    """Create all tables defined in models. Called once at app startup."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """
    FastAPI dependency — yields one DB session per HTTP request.
    Session is automatically closed when the request finishes.

    Usage in endpoint:
        async def my_endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
