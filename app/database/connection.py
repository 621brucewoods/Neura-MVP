"""
Database Connection Module
Configures async SQLAlchemy engine and session factory.
"""

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.database.base import Base

# Disable SQLAlchemy engine query logging
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

# Create async engine with connection pooling
# Use NullPool for serverless/testing, otherwise use default pool
async_engine = create_async_engine(
    settings.database_url,
    echo=False,  # Disable SQL query logging
    future=True,
    pool_pre_ping=True,  # Verify connections before use
)

# Session factory for creating new sessions
async_session_factory = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Don't expire objects after commit
    autocommit=False,
    autoflush=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that provides an async database session.
    
    Usage:
        @app.get("/items")
        async def get_items(session: AsyncSession = Depends(get_async_session)):
            ...
    
    Yields:
        AsyncSession: An async SQLAlchemy session.
    
    Note:
        The session is automatically closed after the request completes.
        Transactions are committed automatically on success, rolled back on error.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database tables.
    
    Note:
        In production, use Alembic migrations instead.
        This is useful for testing and initial development.
    """
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """
    Close database connections.
    Call this during application shutdown.
    """
    await async_engine.dispose()

