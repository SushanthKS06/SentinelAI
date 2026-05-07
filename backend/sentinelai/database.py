"""SentinelAI Database Module.

This module provides database connection management, session handling,
and base models for all services.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, AsyncGenerator, Generic, TypeVar

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, sessionmaker
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool
from typing_extensions import Self

from sentinelai.config import settings

logger = logging.getLogger(__name__)

# Context variable for async session
_async_session_context: ContextVar[AsyncSession | None] = ContextVar(
    "_async_session_context", default=None
)

# Type variable for generic models
T = TypeVar("T")


class Base(DeclarativeBase):
    """Base class for all database models.

    Provides common functionality like table naming and timestamps.
    """

    @declared_attr
    def __tablename__(cls) -> str:
        """Generate table name from class name."""
        # Convert CamelCase to snake_case
        name = cls.__name__
        result = []
        for i, char in enumerate(name):
            if char.isupper() and i > 0:
                result.append("_")
            result.append(char.lower())
        return "".join(result)

    id: Column[String] = Column(
        String(36), primary_key=True, nullable=False, index=True
    )
    created_at: Column[DateTime] = Column(
        DateTime(timezone=True), nullable=False, default=lambda: None
    )
    updated_at: Column[DateTime] = Column(
        DateTime(timezone=True), nullable=False, default=lambda: None
    )


class TimestampMixin:
    """Mixin for automatic timestamp handling."""

    @declared_attr
    def created_at(cls) -> Column[DateTime]:
        return Column(
            DateTime(timezone=True),
            nullable=False,
            default=lambda: None,
        )

    @declared_attr
    def updated_at(cls) -> Column[DateTime]:
        return Column(
            DateTime(timezone=True),
            nullable=False,
            default=lambda: None,
            onupdate=lambda: None,
        )


class DatabaseManager:
    """Database connection and session manager.

    Handles async engine creation, session management, and connection pooling.
    Implements the repository pattern for database access.
    """

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        self._sync_engine = None

    def create_engine(self) -> AsyncEngine:
        """Create async database engine with connection pooling."""
        if self._engine is not None:
            return self._engine

        # Determine pool class based on environment
        pool_class = (
            NullPool if settings.app_env == "testing" else AsyncAdaptedQueuePool
        )

        self._engine = create_async_engine(
            settings.database_url,
            echo=settings.postgres_echo,
            pool_size=settings.postgres_pool_size,
            max_overflow=settings.postgres_max_overflow,
            pool_timeout=settings.postgres_pool_timeout,
            pool_pre_ping=True,
            poolclass=pool_class,
            connect_args={
                "server_settings": {"application_name": "sentinelai"},
                "timeout": 30,
            },
        )

        # Add event listeners for logging
        if settings.app_env != "production":
            event.listen(
                self._engine.sync_engine,
                "connect",
                self._on_connect,
            )

        logger.info(
            f"Database engine created: {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        )
        return self._engine

    def create_sync_engine(self):
        """Create sync database engine for migrations and scripts."""
        if self._sync_engine is not None:
            return self._sync_engine

        self._sync_engine = create_engine(
            settings.sync_database_url,
            echo=settings.postgres_echo,
            pool_size=5,
            max_overflow=10,
        )

        return self._sync_engine

    def _on_connect(self, dbapi_connection: Any, connection_record: Any) -> None:
        """Log database connections in development."""
        logger.debug(f"Database connection established: {id(dbapi_connection)}")

    def create_session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Create async session factory."""
        if self._session_factory is not None:
            return self._session_factory

        engine = self.create_engine()
        self._session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

        return self._session_factory

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get database session with automatic cleanup.

        Yields:
            AsyncSession: Database session
        """
        factory = self.create_session_factory()
        session = factory()

        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    @asynccontextmanager
    async def session_context(
        self,
    ) -> AsyncGenerator[AsyncSession, None]:
        """Get database session from context or create new one.

        This method supports nested session management for operations
        that require multiple database calls in the same context.

        Yields:
            AsyncSession: Database session
        """
        # Check if session already exists in context
        existing_session = _async_session_context.get()

        if existing_session is not None:
            # Reuse existing session
            yield existing_session
        else:
            # Create new session and store in context
            factory = self.create_session_factory()
            session = factory()
            _async_session_context.set(session)

            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
                _async_session_context.set(None)

    async def get_session(self) -> AsyncSession:
        """Get a new database session.

        Note: Caller is responsible for closing the session.

        Returns:
            AsyncSession: New database session
        """
        factory = self.create_session_factory()
        return factory()

    async def dispose(self) -> None:
        """Dispose of database connections."""
        if self._engine is not None:
            await self._engine.dispose()
            logger.info("Database engine disposed")

        if self._sync_engine is not None:
            self._sync_engine.dispose()
            logger.info("Sync database engine disposed")


# Global database manager instance
db_manager = DatabaseManager()


# Repository base class
class Repository(Generic[T]):
    """Base repository class for database operations.

    Provides common CRUD operations and query building utilities.
    """

    def __init__(self, model: type[T]) -> None:
        self.model = model

    @property
    def session(self) -> AsyncSession:
        """Get current database session."""
        session = _async_session_context.get()
        if session is None:
            raise RuntimeError("No database session in context")
        return session

    async def get_by_id(self, id: str) -> T | None:
        """Get entity by ID."""
        from sqlalchemy import select

        result = await self.session.execute(
            select(self.model).where(self.model.id == id)
        )
        return result.scalar_one_or_none()

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[T]:
        """Get all entities with pagination."""
        from sqlalchemy import select

        result = await self.session.execute(
            select(self.model).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def create(self, entity: T) -> T:
        """Create new entity."""
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def update(self, entity: T) -> T:
        """Update existing entity."""
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def delete(self, entity: T) -> None:
        """Delete entity."""
        await self.session.delete(entity)
        await self.session.flush()

    async def count(self) -> int:
        """Count total entities."""
        from sqlalchemy import func, select

        result = await self.session.execute(
            select(func.count()).select_from(self.model)
        )
        return result.scalar_one()


# Decorator for automatic session management
def with_session(func):
    """Decorator to automatically manage database sessions."""

    async def wrapper(*args, **kwargs):
        async with db_manager.session() as session:
            # Inject session into function if it accepts it
            import inspect

            sig = inspect.signature(func)
            if "session" in sig.parameters:
                kwargs["session"] = session
            return await func(*args, **kwargs)

    return wrapper


# Utility functions
async def init_db() -> None:
    """Initialize database tables."""
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db() -> None:
    """Drop all database tables."""
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# Import engine property for compatibility
@property
def engine(self) -> AsyncEngine:
    return self.create_engine()


# Add engine property to DatabaseManager
DatabaseManager.engine = engine


# Export commonly used items
__all__ = [
    "Base",
    "TimestampMixin",
    "DatabaseManager",
    "db_manager",
    "Repository",
    "with_session",
    "init_db",
    "drop_db",
    "AsyncSession",
    "AsyncEngine",
]
