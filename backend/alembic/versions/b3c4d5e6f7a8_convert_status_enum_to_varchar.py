"""convert_status_enum_to_varchar

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-05-23

SQLAlchemy 2.x SAEnum stores enum .name ("PENDING") instead of .value ("pending")
for native PostgreSQL ENUM types, causing InvalidTextRepresentationError on INSERT.
Convert the column to VARCHAR(20) so the ORM String(20) type matches exactly and
no enum codec mismatch can occur.
"""
from alembic import op
import sqlalchemy as sa


revision: str = 'b3c4d5e6f7a8'
down_revision: str = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Cast the existing documentstatus ENUM values to text, then to varchar
    op.execute(
        "ALTER TABLE documents ALTER COLUMN status TYPE VARCHAR(20) "
        "USING status::text"
    )


def downgrade() -> None:
    # Restore the native ENUM type (values are already lowercase text)
    op.execute(
        "ALTER TABLE documents ALTER COLUMN status TYPE documentstatus "
        "USING status::documentstatus"
    )
