"""add_user_input_id_to_contacts

Revision ID: dfcff01e52f1
Revises: 6b72f10b
Create Date: 2026-07-28 05:51:06.135488

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dfcff01e52f1'
down_revision: Union[str, None] = '6b72f10b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('contacts', sa.Column('user_input_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_contacts_user_input_id', 'contacts', 'user_inputs', ['user_input_id'], ['id'])
    op.create_index('ix_contacts_user_input_id', 'contacts', ['user_input_id'])


def downgrade() -> None:
    op.drop_index('ix_contacts_user_input_id', table_name='contacts')
    op.drop_constraint('fk_contacts_user_input_id', 'contacts', type_='foreignkey')
    op.drop_column('contacts', 'user_input_id')

