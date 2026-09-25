"""merge heads

Revision ID: 11ca57a159f0
Revises: af549813d1dd, b80f35ba9cd7
Create Date: 2026-09-17 12:40:54.784810

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11ca57a159f0'
down_revision: Union[str, None] = ('af549813d1dd', 'b80f35ba9cd7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
