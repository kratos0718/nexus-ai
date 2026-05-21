"""add_llm_traces_table

Revision ID: a1b2c3d4e5f6
Revises: 73f34ca87f5c
Create Date: 2026-05-21

Records every LLM call: latency, tokens, model, user — for observability.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '73f34ca87f5c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'llm_traces',
        sa.Column('id',                 sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('trace_id',           sa.String(36),    nullable=False),
        sa.Column('user_id',            sa.Integer(),     sa.ForeignKey('users.id'), nullable=True),
        sa.Column('document_id',        sa.String(36),    nullable=True),
        sa.Column('trace_type',         sa.String(20),    nullable=False, server_default='rag'),
        sa.Column('question',           sa.Text(),        nullable=False),
        sa.Column('answer',             sa.Text(),        nullable=True),
        sa.Column('model',              sa.String(100),   nullable=False),
        sa.Column('prompt_tokens',      sa.Integer(),     nullable=False, server_default='0'),
        sa.Column('completion_tokens',  sa.Integer(),     nullable=False, server_default='0'),
        sa.Column('total_tokens',       sa.Integer(),     nullable=False, server_default='0'),
        sa.Column('duration_ms',        sa.Float(),       nullable=False, server_default='0'),
        sa.Column('error',              sa.Text(),        nullable=True),
        sa.Column('created_at',         sa.DateTime(),    nullable=False),
    )
    op.create_index('ix_llm_traces_trace_id',   'llm_traces', ['trace_id'],   unique=True)
    op.create_index('ix_llm_traces_user_id',    'llm_traces', ['user_id'],    unique=False)
    op.create_index('ix_llm_traces_document_id','llm_traces', ['document_id'],unique=False)
    op.create_index('ix_llm_traces_created_at', 'llm_traces', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_llm_traces_created_at',  table_name='llm_traces')
    op.drop_index('ix_llm_traces_document_id', table_name='llm_traces')
    op.drop_index('ix_llm_traces_user_id',     table_name='llm_traces')
    op.drop_index('ix_llm_traces_trace_id',    table_name='llm_traces')
    op.drop_table('llm_traces')
