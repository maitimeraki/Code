"""Async SQLite database engine and session management.

Phase 0 foundation: all persistence layers depend on this.
"""

import logging
from pathlib import Path
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.pool import StaticPool
from sqlalchemy import event

from harness.persistence.models import Base

logger = logging.getLogger(__name__)

_engine = None
_async_session_maker = None


def _sqlite_pragma_setup(dbapi_conn, connection_record):
    """Apply SQLite pragmas on every new connection for safety and concurrency."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")  # Write-ahead logging for concurrent read
    cursor.execute("PRAGMA busy_timeout=5000")  # 5 second timeout on lock contention
    cursor.execute("PRAGMA foreign_keys=ON")   # Enforce foreign key constraints
    cursor.execute("PRAGMA cache_size=50000")  # 50MB page cache for performance
    cursor.close()


async def init_db():
    """Initialize database: create engine, apply pragmas, create all tables.

    Database location: ~/.code/harness.db (user-level, shared across projects)
    Call once at startup. Safe to call multiple times (idempotent).
    """
    global _engine, _async_session_maker

    if _engine is not None:
        return

    try:
        # Resolve database path to ~/.code/harness.db (user-level)
        db_path = Path.home() / ".code" / "harness.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        database_url = f"sqlite+aiosqlite:///{db_path}?timeout=30&check_same_thread=False"

        # Create async engine with optimized pool config
        _engine = create_async_engine(
            database_url,
            echo=False,
            poolclass=StaticPool,
            connect_args={"timeout": 5.0, "check_same_thread": False},
        )

        # Attach pragma setup to every new connection
        @event.listens_for(_engine.sync_engine, "connect")
        def receive_connect(dbapi_conn, connection_record):
            _sqlite_pragma_setup(dbapi_conn, connection_record)

        # Create async session maker
        _async_session_maker = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        # Create all tables
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Apply schema migrations
        async with _async_session_maker() as session:
            from harness.persistence.migrations import apply_migrations
            await apply_migrations(session)

        logger.info(f"Database initialized at: {db_path}")
    except ConnectionError as e:
        logger.error(f"Database initialization error: {e}")
        raise


@asynccontextmanager
async def get_session():
    """Async context manager for database sessions.

    Usage:
        async with get_session() as session:
            result = await session.execute(...)
    """
    if _async_session_maker is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with _async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_engine():
    """Get the async engine (for raw connections if needed)."""
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine


async def dispose_db():
    """Dispose the engine and reset module state.

    Call on shutdown, or between tests, to release SQLite connections
    (StaticPool otherwise holds one open) and allow a fresh init_db().
    """
    global _engine, _async_session_maker

    if _engine is not None:
        await _engine.dispose()

    _engine = None
    _async_session_maker = None
