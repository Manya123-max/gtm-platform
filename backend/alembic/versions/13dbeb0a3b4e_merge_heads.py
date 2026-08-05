"""merge heads

Revision ID: 13dbeb0a3b4e
Revises: 9cf04bf77b5d, dfcff01e52f1
Create Date: 2026-07-31 12:33:29.785695

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '13dbeb0a3b4e'
down_revision: Union[str, None] = ('9cf04bf77b5d', 'dfcff01e52f1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
