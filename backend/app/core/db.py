from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import get_settings

# Create async SQLAlchemy engine from settings
_engine = None


async def init_db():
    """Initialize database engine at application startup."""
    global _engine
    settings = get_settings()
    _engine = create_async_engine(
        settings.database_url,
        echo=False,  # Set to True for SQL logging during development
        pool_size=15,
        max_overflow=10,
    )


async def close_db():
    """Close database engine at application shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()


# Async session factory
async_session_maker: async_sessionmaker = None


async def setup_session_maker():
    """Initialize session factory after engine is created."""
    global async_session_maker
    async_session_maker = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield async database session."""
    if async_session_maker is None:
        raise RuntimeError("Session maker not initialized. Call setup_session_maker() at startup.")
    
    async with async_session_maker() as session:
        yield session