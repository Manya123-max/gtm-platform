"""redesign_user_inputs

Revision ID: 6a61e90a
Revises: cec848bf7bbf
Create Date: 2026-07-23 15:43:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6a61e90a'
down_revision: Union[str, None] = 'cec848bf7bbf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename existing columns
    op.alter_column('user_inputs', 'services', new_column_name='our_services')
    op.alter_column('user_inputs', 'location', new_column_name='target_location')
    op.alter_column('user_inputs', 'company_size', new_column_name='target_company_size')
    op.alter_column('user_inputs', 'job_title', new_column_name='target_job_titles')
    op.alter_column('user_inputs', 'keywords', new_column_name='target_keywords')
    
    # Make target_keywords nullable
    op.alter_column('user_inputs', 'target_keywords', existing_type=sa.String(), nullable=True)

    # Add target_industries column (nullable)
    op.add_column('user_inputs', sa.Column('target_industries', sa.Text(), nullable=True))

    # Drop the old company_name column
    op.drop_column('user_inputs', 'company_name')


def downgrade() -> None:
    # Add back company_name
    op.add_column('user_inputs', sa.Column('company_name', sa.String(), nullable=False, server_default=''))
    
    # Drop target_industries
    op.drop_column('user_inputs', 'target_industries')
    
    # Make target_keywords not nullable again (or rather keywords in the old model)
    op.alter_column('user_inputs', 'target_keywords', existing_type=sa.String(), nullable=False)

    # Rename back columns
    op.alter_column('user_inputs', 'our_services', new_column_name='services')
    op.alter_column('user_inputs', 'target_location', new_column_name='location')
    op.alter_column('user_inputs', 'target_company_size', new_column_name='company_size')
    op.alter_column('user_inputs', 'target_job_titles', new_column_name='job_title')
    op.alter_column('user_inputs', 'target_keywords', new_column_name='keywords')
