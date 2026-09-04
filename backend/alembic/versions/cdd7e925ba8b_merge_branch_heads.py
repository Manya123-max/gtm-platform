"""merge branch heads

Revision ID: cdd7e925ba8b
Revises: 13dbeb0a3b4e, 5c911b991893
Create Date: 2026-08-05 06:58:02.673813

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cdd7e925ba8b'
down_revision: Union[str, None] = ('13dbeb0a3b4e', '5c911b991893')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
