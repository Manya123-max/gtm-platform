"""add salesforce verification tables

Revision ID: g3b8c9d0e1f2
Revises: f2a7b8c9d0e1
Create Date: 2026-11-02 18:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g3b8c9d0e1f2'
down_revision: Union[str, None] = 'f2a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. company_salesforce_verifications
    op.execute("""
        CREATE TABLE IF NOT EXISTS company_salesforce_verifications (
            id VARCHAR(36) PRIMARY KEY,
            company_name VARCHAR(255) NOT NULL,
            company_domain VARCHAR(255),
            apollo_organization_id VARCHAR(100),
            verification_status VARCHAR(50) NOT NULL DEFAULT 'not_verified',
            verification_summary TEXT,
            last_checked_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_company_salesforce_verifications_company_name ON company_salesforce_verifications (company_name);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_company_salesforce_verifications_company_domain ON company_salesforce_verifications (company_domain);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_company_salesforce_verifications_apollo_org_id ON company_salesforce_verifications (apollo_organization_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_company_salesforce_verifications_status ON company_salesforce_verifications (verification_status);")

    # 2. salesforce_verification_evidences
    op.execute("""
        CREATE TABLE IF NOT EXISTS salesforce_verification_evidences (
            id VARCHAR(36) PRIMARY KEY,
            verification_id VARCHAR(36) NOT NULL REFERENCES company_salesforce_verifications(id) ON DELETE CASCADE,
            evidence_type VARCHAR(100) NOT NULL,
            evidence_description TEXT NOT NULL,
            source_name VARCHAR(255) NOT NULL,
            source_url TEXT,
            evidence_excerpt TEXT,
            evidence_date TIMESTAMP WITHOUT TIME ZONE,
            checked_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            is_valid BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_salesforce_verification_evidences_ver_id ON salesforce_verification_evidences (verification_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_salesforce_verification_evidences_type ON salesforce_verification_evidences (evidence_type);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS salesforce_verification_evidences CASCADE;")
    op.execute("DROP TABLE IF EXISTS company_salesforce_verifications CASCADE;")

