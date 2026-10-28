"""add_signal_summary_columns

Revision ID: b8e9102f431a
Revises: af549813d1dd
Create Date: 2026-09-16 14:41:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e9102f431a'
down_revision: Union[str, None] = 'af549813d1dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    contact_cols = [c['name'] for c in insp.get_columns('contacts')]
    if 'signal_summary' not in contact_cols:
        op.add_column('contacts', sa.Column('signal_summary', sa.Text(), nullable=True))

    signal_cols = [c['name'] for c in insp.get_columns('signal_events')]
    if 'summary' not in signal_cols:
        op.add_column('signal_events', sa.Column('summary', sa.Text(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    signal_cols = [c['name'] for c in insp.get_columns('signal_events')]
    if 'summary' in signal_cols:
        op.drop_column('signal_events', 'summary')

    contact_cols = [c['name'] for c in insp.get_columns('contacts')]
    if 'signal_summary' in contact_cols:
        op.drop_column('contacts', 'signal_summary')
