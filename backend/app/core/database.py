from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

from app.models import models

from sqlalchemy import text
from app.core.config import settings
import structlog
from app.core.config import settings
from sqlalchemy.pool import NullPool


DATABASE_URL = settings.DATABASE_URL

logger = structlog.get_logger()

engine = create_async_engine(
    DATABASE_URL,
    poolclass=NullPool,
    echo=False,
    future=True
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)



async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        # Enable pgvector extension
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        # Create all tables
        print("Registered Tables:")
        print(Base.metadata.tables.keys())

        await conn.run_sync(Base.metadata.create_all)
        await _bootstrap_multi_user_schema(conn)
    logger.info("Database initialised")


async def _bootstrap_multi_user_schema(conn, migration_owner_email: Optional[str] = None) -> None:
    """
    Idempotent schema migration for multi-user support (safe to run on every
    startup). Creates the ownership columns/indexes that `create_all` cannot
    add to pre-existing tables, then backfills legacy rows to the configured
    migration owner (never silently — only when GTM_MIGRATION_OWNER_EMAIL is
    explicitly set).
    """
    statements = [
        "ALTER TABLE users ALTER COLUMN role SET DEFAULT 'SALES_REPRESENTATIVE'",
        "ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "ALTER TABLE revenue_forecasts ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "CREATE INDEX IF NOT EXISTS ix_user_inputs_user_id ON user_inputs (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_contacts_user_id ON contacts (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_workflow_runs_user_id ON workflow_runs (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_revenue_forecasts_user_id ON revenue_forecasts (user_id)",
        # Ensure contacts email index is not globally unique across users
        "DROP INDEX IF EXISTS ix_contacts_email",
        "CREATE INDEX IF NOT EXISTS ix_contacts_email ON contacts (email)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_contacts_user_email ON contacts (user_id, email) WHERE user_id IS NOT NULL",
        # outreach_log columns
        "ALTER TABLE outreach_log ADD COLUMN IF NOT EXISTS sequence_step INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE outreach_log ADD COLUMN IF NOT EXISTS call_script TEXT",
        "ALTER TABLE outreach_log ADD COLUMN IF NOT EXISTS linkedin_note TEXT",
        "ALTER TABLE outreach_log ADD COLUMN IF NOT EXISTS outreach_provider_message_id VARCHAR(100)",
        "ALTER TABLE outreach_log ADD COLUMN IF NOT EXISTS prompt_variant_id VARCHAR(50)",
        # signal_events columns
        "ALTER TABLE signal_events ADD COLUMN IF NOT EXISTS sequence_step INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE signal_events ADD COLUMN IF NOT EXISTS next_step_due_at TIMESTAMP WITHOUT TIME ZONE",
    ]
    for stmt in statements:
        await conn.execute(text(stmt))

    if migration_owner_email is not None:
        owner_email = migration_owner_email.strip().lower()
    else:
        owner_email = (settings.GTM_MIGRATION_OWNER_EMAIL or "").strip().lower()

    if not owner_email:
        logger.warning(
            "GTM_MIGRATION_OWNER_EMAIL not set — legacy (anonymous) rows keep "
            "user_id NULL and will be invisible to authenticated users."
        )
        return

    # Resolve or create the migration owner account
    owner_id_row = await conn.execute(
        text("SELECT id FROM users WHERE email = :email"), {"email": owner_email}
    )
    owner_row = owner_id_row.first()
    if owner_row is None:
        from app.core.security import hash_password
        import secrets as _secrets
        raw_password = (settings.GTM_MIGRATION_OWNER_PASSWORD or "").strip() or _secrets.token_urlsafe(24)
        await conn.execute(
            text(
                "INSERT INTO users (id, name, email, password_hash, is_active, role, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :name, :email, :password_hash, true, :role, now(), now()) "
                "ON CONFLICT (email) DO NOTHING"
            ),
            {
                "name": "Migration Owner",
                "email": owner_email,
                "password_hash": hash_password(raw_password),
                "role": "SALES_REPRESENTATIVE",
            },
        )
        owner_id_row = await conn.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": owner_email}
        )
        owner_id = owner_id_row.scalar_one()
        if not settings.GTM_MIGRATION_OWNER_PASSWORD:
            logger.warning(
                "Created migration owner account. Temporary password (rotate immediately): "
                f"{raw_password}"
            )
        else:
            logger.info("Created migration owner account with configured GTM_MIGRATION_OWNER_PASSWORD")
    else:
        owner_id = owner_row[0]
        if settings.GTM_MIGRATION_OWNER_PASSWORD and settings.GTM_MIGRATION_OWNER_PASSWORD.strip():
            from app.core.security import hash_password
            await conn.execute(
                text("UPDATE users SET password_hash = :hash, is_active = true, updated_at = now() WHERE id = :id"),
                {"hash": hash_password(settings.GTM_MIGRATION_OWNER_PASSWORD.strip()), "id": owner_id},
            )
            logger.info("Synchronized migration owner password from GTM_MIGRATION_OWNER_PASSWORD")

    # Backfill legacy rows: user_inputs → contacts inherit from their session
    await conn.execute(text(
        "UPDATE contacts c SET user_id = ui.user_id "
        "FROM user_inputs ui WHERE c.user_input_id = ui.id "
        "AND c.user_id IS NULL AND ui.user_id IS NOT NULL"
    ))
    await conn.execute(text(
        "UPDATE user_inputs SET user_id = :owner WHERE user_id IS NULL"
    ), {"owner": owner_id})
    await conn.execute(text(
        "UPDATE contacts SET user_id = :owner WHERE user_id IS NULL"
    ), {"owner": owner_id})
    await conn.execute(text(
        "UPDATE workflow_runs SET user_id = :owner WHERE user_id IS NULL"
    ), {"owner": owner_id})
    await conn.execute(text(
        "UPDATE revenue_forecasts SET user_id = :owner WHERE user_id IS NULL"
    ), {"owner": owner_id})
    logger.info("Legacy rows backfilled to migration owner", owner_email=owner_email)


async def close_db():
    await engine.dispose()
