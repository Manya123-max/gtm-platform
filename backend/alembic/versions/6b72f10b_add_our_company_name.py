"""add_our_company_name

Revision ID: 6b72f10b
Revises: 6a61e90a
Create Date: 2026-07-23 16:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b72f10b'
down_revision: Union[str, None] = '6a61e90a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add our_company_name column with a default of ''
    op.add_column('user_inputs', sa.Column('our_company_name', sa.String(300), nullable=False, server_default=''))


def downgrade() -> None:
    # Drop our_company_name column
    op.drop_column('user_inputs', 'our_company_name')
