"""add_user_inputs_table

Revision ID: cec848bf7bbf
Revises: 
Create Date: 2026-07-21 16:41:40.047009

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cec848bf7bbf'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
           'user_inputs',
           sa.Column('id', sa.Integer, primary_key=True),
           sa.Column('company_name', sa.String, nullable=False),
           sa.Column('company_size', sa.String, nullable=False),
           sa.Column('services', sa.String, nullable=False),
           sa.Column('location', sa.String, nullable=False),
           sa.Column('job_title', sa.String, nullable=False),
           sa.Column('keywords', sa.String, nullable=False),
       )


def downgrade() -> None:
    op.drop_table('user_inputs')
