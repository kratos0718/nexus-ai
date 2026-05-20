"""
Alembic environment — wires our SQLAlchemy models into the migration system.

Key decisions:
- DATABASE_URL from environment (falls back to SQLite for local dev)
- Alembic uses SYNCHRONOUS connections even when the app uses async
  (asyncpg doesn't support Alembic's connection protocol)
- We strip "async" drivers (aiosqlite, asyncpg) and replace with sync
  equivalents (sqlite, psycopg2) just for migrations
"""

import os
import re
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# ── Import all models so autogenerate can find them ──────────────────────────
# These imports register the models with Base.metadata
from app.core.database import Base  # noqa: F401
import app.models  # noqa: F401 — triggers __init__.py which imports all models

# ── Alembic config object ────────────────────────────────────────────────────
alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

target_metadata = Base.metadata


def get_sync_url() -> str:
    """
    Return a synchronous DB URL for Alembic.

    The app uses async drivers (aiosqlite, asyncpg) which Alembic can't use.
    We swap them out for their sync counterparts here.
    """
    url = os.getenv(
        "DATABASE_URL",
        "sqlite:///./nexus.db",   # sync SQLite — note: no +aiosqlite
    )
    # If someone set an async URL in env, strip the async driver
    url = re.sub(r"sqlite\+aiosqlite", "sqlite", url)
    url = re.sub(r"postgresql\+asyncpg", "postgresql", url)
    return url


def run_migrations_offline() -> None:
    """
    Offline mode: generate SQL script without a live DB connection.
    Useful for reviewing migrations before applying them.

    Run with: alembic upgrade head --sql
    """
    context.configure(
        url=get_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Online mode: connect to the database and run migrations directly.
    This is the default when you run `alembic upgrade head`.
    """
    sync_url = get_sync_url()
    alembic_config.set_main_option("sqlalchemy.url", sync_url)

    connectable = engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,   # don't pool connections for migrations
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            # batch_mode lets Alembic handle SQLite's lack of ALTER TABLE
            # by using copy-and-move. Harmless on PostgreSQL.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
