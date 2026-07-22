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
    logger.info("Database initialised")


async def close_db():
    await engine.dispose()
