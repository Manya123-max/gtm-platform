"""add prospect interest fields to contacts

Revision ID: f100_interest_fields
Revises: 13dbeb0a3b4e
Create Date: 2026-09-16 18:25:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'f100_interest_fields'
down_revision = '13dbeb0a3b4e'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('contacts', sa.Column('interest_score', sa.Float(), nullable=True, server_default='0.0'))
    op.add_column('contacts', sa.Column('interest_status', sa.String(length=50), nullable=True, server_default='INACTIVE'))
    op.add_column('contacts', sa.Column('interest_score_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('contacts', sa.Column('conversation_summary', sa.Text(), nullable=True))
    op.add_column('contacts', sa.Column('last_response_at', sa.DateTime(), nullable=True))
    op.add_column('contacts', sa.Column('last_outreach_at', sa.DateTime(), nullable=True))
    op.add_column('contacts', sa.Column('response_count', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('contacts', sa.Column('outreach_count', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('contacts', sa.Column('interest_updated_at', sa.DateTime(), nullable=True))

    op.create_index(op.f('ix_contacts_interest_score'), 'contacts', ['interest_score'], unique=False)
    op.create_index(op.f('ix_contacts_interest_status'), 'contacts', ['interest_status'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_contacts_interest_status'), table_name='contacts')
    op.drop_index(op.f('ix_contacts_interest_score'), table_name='contacts')
    op.drop_column('contacts', 'interest_updated_at')
    op.drop_column('contacts', 'outreach_count')
    op.drop_column('contacts', 'response_count')
    op.drop_column('contacts', 'last_outreach_at')
    op.drop_column('contacts', 'last_response_at')
    op.drop_column('contacts', 'conversation_summary')
    op.drop_column('contacts', 'interest_score_breakdown')
    op.drop_column('contacts', 'interest_status')
    op.drop_column('contacts', 'interest_score')
