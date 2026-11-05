"""add notifications table

Revision ID: c51a029eb101
Revises: 11ca57a159f0
Create Date: 2026-09-21 11:55:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c51a029eb101'
down_revision: Union[str, None] = '11ca57a159f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()
    if 'notifications' not in tables:
        op.create_table(
            'notifications',
            sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column('type', sa.String(length=50), nullable=False),
            sa.Column('contact_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_input_id', sa.Integer(), sa.ForeignKey('user_inputs.id', ondelete='CASCADE'), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('action_url', sa.String(length=255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('read_at', sa.DateTime(), nullable=True),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
            sa.Column('reference_id', sa.String(length=150), nullable=True),
        )
        op.create_index('ix_notifications_type', 'notifications', ['type'])
        op.create_index('ix_notifications_contact_id', 'notifications', ['contact_id'])
        op.create_index('ix_notifications_user_input_id', 'notifications', ['user_input_id'])
        op.create_index('ix_notifications_created_at', 'notifications', ['created_at'])
        op.create_index('ix_notifications_read_at', 'notifications', ['read_at'])
        op.create_index('ix_notifications_expires_at', 'notifications', ['expires_at'])
        op.create_index('ix_notifications_reference_id', 'notifications', ['reference_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_notifications_reference_id', table_name='notifications')
    op.drop_index('ix_notifications_expires_at', table_name='notifications')
    op.drop_index('ix_notifications_read_at', table_name='notifications')
    op.drop_index('ix_notifications_created_at', table_name='notifications')
    op.drop_index('ix_notifications_user_input_id', table_name='notifications')
    op.drop_index('ix_notifications_contact_id', table_name='notifications')
    op.drop_index('ix_notifications_type', table_name='notifications')
    op.drop_table('notifications')
