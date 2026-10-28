"""add_user_integrations_and_cal_com

Revision ID: e1f8a92d4b5c
Revises: ('b8e9102f431a', 'c51a029eb101')
Create Date: 2026-09-30 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e1f8a92d4b5c'
down_revision: Union[str, Sequence[str], None] = ('b8e9102f431a', 'c51a029eb101')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    tables = insp.get_table_names()

    # 1. Create user_integrations table if it doesn't exist
    if 'user_integrations' not in tables:
        op.create_table(
            'user_integrations',
            sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column('user_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('provider', sa.String(50), nullable=False, server_default='google'),
            sa.Column('provider_account_email', sa.String(255), nullable=True, index=True),
            sa.Column('encrypted_access_token', sa.Text(), nullable=True),
            sa.Column('encrypted_refresh_token', sa.Text(), nullable=True),
            sa.Column('token_expires_at', sa.DateTime(), nullable=True),
            sa.Column('scopes', sa.Text(), nullable=True),
            sa.Column('status', sa.String(50), nullable=False, server_default='connected'),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.UniqueConstraint('user_id', 'provider', name='uq_user_provider')
        )

    # 2. Add columns to users if missing
    if 'users' in tables:
        user_cols = [c['name'] for c in insp.get_columns('users')]
        if 'cal_com_event_slug' not in user_cols:
            op.add_column('users', sa.Column('cal_com_event_slug', sa.String(100), nullable=True))
        if 'cal_com_booking_url' not in user_cols:
            op.add_column('users', sa.Column('cal_com_booking_url', sa.String(255), nullable=True))
        if 'slack_user_id' not in user_cols:
            op.add_column('users', sa.Column('slack_user_id', sa.String(50), nullable=True))

    # 3. Add user_id to outreach_drafts if missing
    if 'outreach_drafts' in tables:
        draft_cols = [c['name'] for c in insp.get_columns('outreach_drafts')]
        if 'user_id' not in draft_cols:
            op.add_column('outreach_drafts', sa.Column('user_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('users.id'), nullable=True))
            op.create_index('ix_outreach_drafts_user_id', 'outreach_drafts', ['user_id'])

    # 4. Add amount_source to deals if missing
    if 'deals' in tables:
        deal_cols = [c['name'] for c in insp.get_columns('deals')]
        if 'amount_source' not in deal_cols:
            op.add_column('deals', sa.Column('amount_source', sa.String(100), nullable=True))

    # 5. Add user_id to outreach_log if missing
    if 'outreach_log' in tables:
        log_cols = [c['name'] for c in insp.get_columns('outreach_log')]
        if 'user_id' not in log_cols:
            op.add_column('outreach_log', sa.Column('user_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('users.id'), nullable=True))
            op.create_index('ix_outreach_log_user_id', 'outreach_log', ['user_id'])


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if 'deals' in tables:
        deal_cols = [c['name'] for c in insp.get_columns('deals')]
        if 'amount_source' in deal_cols:
            op.drop_column('deals', 'amount_source')

    if 'outreach_drafts' in tables:
        draft_cols = [c['name'] for c in insp.get_columns('outreach_drafts')]
        if 'user_id' in draft_cols:
            op.drop_index('ix_outreach_drafts_user_id', table_name='outreach_drafts')
            op.drop_column('outreach_drafts', 'user_id')

    if 'users' in tables:
        user_cols = [c['name'] for c in insp.get_columns('users')]
        if 'slack_user_id' in user_cols:
            op.drop_column('users', 'slack_user_id')
        if 'cal_com_booking_url' in user_cols:
            op.drop_column('users', 'cal_com_booking_url')
        if 'cal_com_event_slug' in user_cols:
            op.drop_column('users', 'cal_com_event_slug')

    if 'user_integrations' in tables:
        op.drop_table('user_integrations')
