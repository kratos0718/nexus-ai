"""initial_schema

Revision ID: 73f34ca87f5c
Revises:
Create Date: 2026-05-20

Creates all initial tables and adds user_id ownership column to documents.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '73f34ca87f5c'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── New tables (FK inline — works on all dialects) ──────────────────────
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    op.create_table(
        'conversations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('conversation_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('document_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_conversations_conversation_id', 'conversations', ['conversation_id'], unique=True)
    op.create_index('ix_conversations_user_id', 'conversations', ['user_id'], unique=False)

    op.create_table(
        'messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('message_id', sa.String(length=36), nullable=False),
        sa.Column('conversation_id', sa.String(length=36), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('sources', sa.Text(), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False),
        sa.Column('completion_tokens', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.conversation_id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_messages_message_id', 'messages', ['message_id'], unique=True)

    # ── Alter existing documents table — use batch for SQLite compat ─────────
    # batch_alter_table uses copy-and-move on SQLite, ALTER TABLE on PostgreSQL
    with op.batch_alter_table('documents') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_documents_user_id', ['user_id'], unique=False)
        batch_op.create_foreign_key('fk_documents_user_id', 'users', ['user_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('documents') as batch_op:
        batch_op.drop_constraint('fk_documents_user_id', type_='foreignkey')
        batch_op.drop_index('ix_documents_user_id')
        batch_op.drop_column('user_id')

    op.drop_index('ix_messages_message_id', table_name='messages')
    op.drop_table('messages')
    op.drop_index('ix_conversations_user_id', table_name='conversations')
    op.drop_index('ix_conversations_conversation_id', table_name='conversations')
    op.drop_table('conversations')
    op.drop_index('ix_users_email', table_name='users')
    op.drop_table('users')
