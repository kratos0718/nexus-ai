"""
Database engine, session factory, and base model for SQLAlchemy.

Async engine  → FastAPI (all HTTP request handlers)
Sync engine   → Celery tasks (background workers — can't use asyncio)
"""

import os
import re

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker


def _get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./nexus.db")
    if "postgresql" in url:
        # asyncpg does not accept sslmode or channel_binding — strip them
        url = re.sub(r"[?&]sslmode=[^&]*", "", url)
        url = re.sub(r"[?&]channel_binding=[^&]*", "", url)
        url = re.sub(r"\?$", "", url)  # remove trailing ? if params were stripped
    return url


def _to_sync_url(url: str) -> str:
    """Strip async drivers — required for sync SQLAlchemy (Alembic, Celery)."""
    url = re.sub(r"sqlite\+aiosqlite", "sqlite", url)
    url = re.sub(r"postgresql\+asyncpg", "postgresql", url)
    return url


# ── Async engine (FastAPI) ────────────────────────────────────────────────────

_async_url = _get_database_url()
if "sqlite" in _async_url:
    _connect_args = {"check_same_thread": False}
elif "postgresql" in _async_url:
    _connect_args = {"ssl": True}  # Neon always requires SSL
else:
    _connect_args = {}

async_engine = create_async_engine(_async_url, echo=False, connect_args=_connect_args)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── Sync engine (Celery workers) ──────────────────────────────────────────────

_sync_url = _to_sync_url(_get_database_url())
_sync_connect_args = {"check_same_thread": False} if "sqlite" in _sync_url else {}

sync_engine = create_engine(_sync_url, connect_args=_sync_connect_args)
SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """All ORM models inherit from this. Gives them __tablename__, metadata, etc."""
    pass


async def create_tables():
    """Create all tables. Called once at app startup."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """FastAPI dependency — one async session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_sync_db() -> Session:
    """Celery dependency — one sync session per task. Caller must close."""
    return SyncSessionLocal()
