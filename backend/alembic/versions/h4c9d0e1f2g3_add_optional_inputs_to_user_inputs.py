"""add optional input fields to user_inputs

Revision ID: h4c9d0e1f2g3
Revises: g3b8c9d0e1f2
Create Date: 2026-11-04 16:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h4c9d0e1f2g3'
down_revision: Union[str, None] = 'g3b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS company_lookalike TEXT;")
    op.execute("ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS signals TEXT;")
    op.execute("ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS funding_stages TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE user_inputs DROP COLUMN IF EXISTS company_lookalike;")
    op.execute("ALTER TABLE user_inputs DROP COLUMN IF EXISTS signals;")
    op.execute("ALTER TABLE user_inputs DROP COLUMN IF EXISTS funding_stages;")
