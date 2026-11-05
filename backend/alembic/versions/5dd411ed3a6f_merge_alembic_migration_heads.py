"""Merge alembic migration heads

Revision ID: 5dd411ed3a6f
Revises: cdd7e925ba8b, d12e669634ad
Create Date: 2026-09-04 06:23:40.544126

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5dd411ed3a6f'
down_revision: Union[str, None] = ('cdd7e925ba8b', 'd12e669634ad')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
