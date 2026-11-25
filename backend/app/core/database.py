import asyncio
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

connect_args = {}
if "asyncpg" in DATABASE_URL:
    connect_args["timeout"] = 5

engine = create_async_engine(
    DATABASE_URL,
    poolclass=NullPool,
    connect_args=connect_args,
    echo=False,
    future=True,
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


db_status = {
    "connected": False,
    "error": None,
}


def get_database_status() -> dict:
    return db_status


async def init_db():
    import os
    db_url = settings.DATABASE_URL or ""
    if "dpg-" in db_url and ".render.com" not in db_url and not os.environ.get("RENDER"):
        err_msg = (
            "DATABASE_CONFIG_ERROR: You are running outside Render with an internal Render hostname ('dpg-...'). "
            "Internal hostnames only resolve inside Render's private network. "
            "To connect from localhost, use Render's External Database URL (e.g. host ending in '.oregon-postgres.render.com?sslmode=require') or a local/cloud database."
        )
        logger.error(err_msg)
        db_status["connected"] = False
        db_status["error"] = err_msg

    try:
        async with asyncio.timeout(15.0):
            async with engine.begin() as conn:
                # Enable pgvector and pg_trgm extensions if supported
                try:
                    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                except Exception as exc:
                    logger.warning("Could not enable pgvector extension", error=str(exc))
                try:
                    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
                except Exception as exc:
                    logger.warning("Could not enable pg_trgm extension", error=str(exc))
                # Create all tables
                print("Registered Tables:")
                print(Base.metadata.tables.keys())

                await conn.run_sync(Base.metadata.create_all)
                await _bootstrap_multi_user_schema(conn)
        db_status["connected"] = True
        db_status["error"] = None
        logger.info("Database initialised successfully")
    except Exception as exc:
        db_status["connected"] = False
        db_status["error"] = str(exc)
        logger.error(
            "CRITICAL: Database connection failed during startup. "
            "Ensure PostgreSQL is running and DATABASE_URL is correct.",
            error=str(exc),
        )
        if settings.APP_ENV == "test":
            raise


async def _bootstrap_multi_user_schema(conn, migration_owner_email: Optional[str] = None) -> None:
    """
    Idempotent schema migration for multi-user support (safe to run on every
    startup). Creates the ownership columns/indexes that `create_all` cannot
    add to pre-existing tables, then backfills legacy rows to the configured
    migration owner (never silently — only when GTM_MIGRATION_OWNER_EMAIL is
    explicitly set).
    """
    statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'SALES_REPRESENTATIVE'",
        "ALTER TABLE users ALTER COLUMN role SET DEFAULT 'SALES_REPRESENTATIVE'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS cal_com_username VARCHAR(100)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS cal_com_event_slug VARCHAR(100)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS cal_com_booking_url VARCHAR(255)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS slack_user_id VARCHAR(50)",
        "ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS company_lookalike TEXT",
        "ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS signals TEXT",
        "ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS funding_stages TEXT",
        "ALTER TABLE user_inputs ADD COLUMN IF NOT EXISTS our_company_name TEXT DEFAULT ''",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS prospect_location VARCHAR(200)",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS work_mode VARCHAR(50) DEFAULT 'Not specified'",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS location_source VARCHAR(100)",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS selection_summary TEXT",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS tier VARCHAR(20)",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS priority_rank INTEGER",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS salesforce_contact_id VARCHAR(100)",
        "ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "ALTER TABLE revenue_forecasts ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "ALTER TABLE signal_events ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "ALTER TABLE conversation_threads ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "ALTER TABLE deals ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "ALTER TABLE pending_actions ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "ALTER TABLE funnel_events ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "ALTER TABLE generated_content ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "ALTER TABLE brand_assets ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "ALTER TABLE outreach_drafts ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
        "CREATE INDEX IF NOT EXISTS ix_user_inputs_user_id ON user_inputs (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_contacts_user_id ON contacts (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_workflow_runs_user_id ON workflow_runs (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_revenue_forecasts_user_id ON revenue_forecasts (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_signal_events_user_id ON signal_events (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_conversation_threads_user_id ON conversation_threads (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_deals_user_id ON deals (user_id)",
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
        logger.warning("GTM_MIGRATION_OWNER_EMAIL not set; unowned legacy rows remain unassigned")
        return

    # Resolve or create the migration owner account
    owner_id_row = await conn.execute(
        text("SELECT id, role, password_hash FROM users WHERE email = :email"), {"email": owner_email}
    )
    owner_row = owner_id_row.first()

    if owner_row is None:
        from app.core.security import hash_password
        import secrets
        raw_password = (settings.GTM_MIGRATION_OWNER_PASSWORD or "").strip() or secrets.token_urlsafe(16)
        name = "Migration Owner"
        role = "SALES_REPRESENTATIVE"

        await conn.execute(
            text(
                "INSERT INTO users (id, name, email, password_hash, is_active, role, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :name, :email, :password_hash, true, :role, now(), now()) "
                "ON CONFLICT (email) DO NOTHING"
            ),
            {
                "name": name,
                "email": owner_email,
                "password_hash": hash_password(raw_password),
                "role": role,
            },
        )
        owner_id_row = await conn.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": owner_email}
        )
        owner_id = owner_id_row.scalar_one()
        logger.info(f"Initialized migration owner account: {owner_email} ({role})")
    else:
        owner_id = owner_row[0]
        from app.core.security import hash_password
        if settings.GTM_MIGRATION_OWNER_PASSWORD and settings.GTM_MIGRATION_OWNER_PASSWORD.strip():
            new_hash = hash_password(settings.GTM_MIGRATION_OWNER_PASSWORD.strip())
            await conn.execute(
                text("UPDATE users SET password_hash = :hash, is_active = true, updated_at = now() WHERE id = :id"),
                {"hash": new_hash, "id": owner_id},
            )
            logger.info("Synchronized migration owner password from GTM_MIGRATION_OWNER_PASSWORD")

    # Backfill legacy rows: user_inputs → contacts inherit from their session
    await conn.execute(text(
        "UPDATE contacts c SET user_id = ui.user_id "
        "FROM user_inputs ui WHERE c.user_input_id = ui.id "
        "AND c.user_id IS NULL AND ui.user_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM contacts c2 WHERE c2.user_id = ui.user_id AND c2.email = c.email)"
    ))
    await conn.execute(text(
        "UPDATE user_inputs SET user_id = :owner WHERE user_id IS NULL"
    ), {"owner": owner_id})
    await conn.execute(text(
        "UPDATE contacts c SET user_id = :owner WHERE c.user_id IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM contacts c2 WHERE c2.user_id = :owner AND c2.email = c.email)"
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
