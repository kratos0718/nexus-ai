# Database Migrations — Alembic, Schema Versioning, and Safe Deployments

## The Problem Migrations Solve

Your code and your database schema must always be in sync. Without a migration system:

```
Developer A adds column:   ALTER TABLE users ADD COLUMN avatar_url TEXT
Developer B pulls code:    App crashes — their DB doesn't have avatar_url
Production deploy:         You forgot to run the ALTER. App is down.
Rollback:                  What was the schema before? No one knows.
```

Migrations are **version control for your database schema**. Each change is a numbered, reversible file that every environment applies in the same order.

---

## How Alembic Fits the SQLAlchemy Ecosystem

```
SQLAlchemy Models (Python)
    ↓ alembic revision --autogenerate
Migration file (versions/abc123.py)
    upgrade()    ← SQL to apply
    downgrade()  ← SQL to reverse
    ↓ alembic upgrade head
alembic_version table (tracks current revision)
    ↓
Database matches models exactly
```

Alembic reads your `Base.metadata` (the collection of all SQLAlchemy model tables) and compares it against the current database state. The diff becomes the migration.

---

## env.py — The Config That Makes It Work

```python
# alembic/env.py

# Step 1: Import ALL models so Alembic sees their tables
from app.core.database import Base
import app.models  # side-effect: registers User, Document, Conversation, Message

target_metadata = Base.metadata

# Step 2: Strip async drivers — Alembic is synchronous
def get_sync_url():
    url = os.getenv("DATABASE_URL", "sqlite:///./nexus.db")
    url = re.sub(r"sqlite\+aiosqlite", "sqlite", url)        # async → sync
    url = re.sub(r"postgresql\+asyncpg", "postgresql", url)  # async → sync
    return url

# Step 3: Configure for SQLite compatibility
context.configure(
    connection=connection,
    target_metadata=target_metadata,
    compare_type=True,            # detect column type changes
    compare_server_default=True,  # detect default value changes
    render_as_batch=True,         # SQLite workaround (see below)
)
```

**Why strip async drivers?** Alembic uses synchronous SQLAlchemy internally. `aiosqlite` and `asyncpg` are async-only drivers. Alembic needs the sync equivalents (`sqlite`, `postgresql`) to open a real connection and inspect the schema.

**Why `render_as_batch=True`?** SQLite has a fundamental limitation: it doesn't support `ALTER TABLE ... ADD CONSTRAINT` or `ALTER TABLE ... DROP COLUMN`. Batch mode works around this by:
1. Creating a new temp table with the desired schema
2. Copying all data from the old table
3. Dropping the old table
4. Renaming the temp table

This is safe on both SQLite and PostgreSQL (PostgreSQL uses normal `ALTER TABLE` statements when batch mode produces them).

---

## Migration File Anatomy

```python
# versions/73f34ca87f5c_initial_schema.py

revision = '73f34ca87f5c'   # unique ID for this migration
down_revision = None         # None = first migration; UUID = parent migration

# This forms a linked list: current_head → ... → first_migration (None)

def upgrade():
    """Applied when: alembic upgrade head"""
    # Create tables that don't have FK dependencies first
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # For tables that need FK to existing tables: use batch_alter_table
    with op.batch_alter_table('documents') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_documents_user_id', 'users', ['user_id'], ['id']
        )

def downgrade():
    """Applied when: alembic downgrade -1"""
    with op.batch_alter_table('documents') as batch_op:
        batch_op.drop_constraint('fk_documents_user_id', type_='foreignkey')
        batch_op.drop_column('user_id')
    op.drop_table('users')
```

The linked list of revisions forms the migration history. Each migration knows its parent (`down_revision`) and Alembic walks the chain to compute what to apply.

---

## Essential Commands

```bash
# Generate migration from model changes (reads Python models, diffs against DB)
alembic revision --autogenerate -m "add_user_settings_table"

# Apply all pending migrations (idempotent — safe to run repeatedly)
alembic upgrade head

# Step forward one migration
alembic upgrade +1

# Roll back one migration
alembic downgrade -1

# Roll back to a specific revision
alembic downgrade 73f34ca87f5c

# Roll back everything (to empty schema)
alembic downgrade base

# See what revision the DB is at now
alembic current

# See all migrations with details
alembic history --verbose

# Generate SQL without running (for DBA review or audit)
alembic upgrade head --sql > migration.sql

# Mark DB as at current head WITHOUT running migration
# Use when: tables already exist (e.g., from create_all at startup) and
# you're adding Alembic for the first time
alembic stamp head
```

---

## `alembic stamp head` — When and Why

Scenario: your app created tables at startup with `Base.metadata.create_all()`. Now you want to add Alembic. If you run `alembic upgrade head`, it tries to `CREATE TABLE users` — but users already exists. Error.

Solution:
1. Write the initial migration that would create the current schema from scratch
2. `alembic stamp head` — inserts the current revision into `alembic_version` without running any SQL
3. From this point forward, model changes generate new migrations on top

---

## Production Deployment Pattern

```dockerfile
# In Dockerfile CMD — migrations run before the server starts
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
```

Why this works: `alembic upgrade head` is idempotent. If no new migrations exist, it exits immediately. If migrations are pending, they're applied before the app accepts traffic. Every deploy is zero-manual-steps.

---

## Autogenerate Gotchas

Things autogenerate **detects**:
- New/dropped tables
- New/dropped columns
- Type changes (with `compare_type=True`)
- New/dropped indexes
- New/dropped unique constraints

Things autogenerate **misses** (must add manually):
- CHECK constraints
- Stored procedures / views
- Partial indexes
- Data migrations (moving data between columns)
- Enum type additions in PostgreSQL

Always review the generated migration file before committing. Autogenerate is a first draft, not a final answer.

---

## Interview Answers

**"How do you handle schema changes in production without downtime?"**

Use backward-compatible migrations: add nullable columns first (no data backfill needed), deploy the new code, then in a second migration make the column not-null after all rows are populated. This is a two-phase deploy. Alembic makes each phase version-controlled and reversible.

**"What's the difference between synchronous and asynchronous database drivers?"**

Async drivers (asyncpg, aiosqlite) return coroutines — they yield control to the event loop while waiting for I/O. This allows one server process to handle thousands of concurrent connections. Sync drivers block — one connection per OS thread. FastAPI runs async; Alembic uses sync because migration tools don't need concurrency.

**"How do you roll back a bad migration in production?"**

`alembic downgrade -1` reverts the last migration. The `downgrade()` function is the mirror of `upgrade()` — it must correctly undo every change made in `upgrade()`. In practice: always test both `upgrade()` and `downgrade()` in development before deploying. For data migrations, think carefully about data loss (adding a nullable column is reversible; dropping a column with data is not).
