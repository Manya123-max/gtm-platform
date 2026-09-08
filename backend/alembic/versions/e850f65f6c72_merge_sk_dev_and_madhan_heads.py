"""merge sk_dev and Madhan heads

Revision ID: e850f65f6c72
Revises: 13dbeb0a3b4e, 5c911b991893
Create Date: 2026-08-04 07:27:09.077452

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e850f65f6c72'
down_revision: Union[str, None] = ('13dbeb0a3b4e', '5c911b991893')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
