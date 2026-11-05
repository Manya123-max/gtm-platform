"""add salesforce crm columns

Revision ID: f2a7b8c9d0e1
Revises: e1f8a92d4b5c
Create Date: 2026-10-05 13:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a7b8c9d0e1'
down_revision: Union[str, None] = 'e1f8a92d4b5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add salesforce_opportunity_id to deals
    op.execute(
        "ALTER TABLE deals ADD COLUMN IF NOT EXISTS salesforce_opportunity_id VARCHAR(100);"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_deals_salesforce_opportunity_id ON deals (salesforce_opportunity_id);"
    )

    # Add salesforce_contact_id to contacts
    op.execute(
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS salesforce_contact_id VARCHAR(100);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_deals_salesforce_opportunity_id;")
    op.execute("ALTER TABLE deals DROP COLUMN IF EXISTS salesforce_opportunity_id;")
    op.execute("ALTER TABLE contacts DROP COLUMN IF EXISTS salesforce_contact_id;")
