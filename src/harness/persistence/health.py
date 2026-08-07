"""Database health checks and monitoring."""

from pathlib import Path
from datetime import datetime
import structlog
from sqlalchemy import text

from harness.persistence.database import get_session, get_engine

logger = structlog.get_logger(__name__)


class DatabaseHealth:
    """Check database health, size, and performance."""

    @staticmethod
    async def check_connection() -> bool:
        """Test database connection."""
        try:
            engine = await get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Database connection check: OK")
            return True
        except Exception as e:
            logger.error("Database connection failed", error=str(e))
            return False

    @staticmethod
    async def get_database_size() -> int:
        """Get database file size in bytes."""
        try:
            db_path = Path.home() / ".code" / "harness.db"
            if db_path.exists():
                size = db_path.stat().st_size
                logger.info("Database size", bytes=size, mb=size / (1024 * 1024))
                return size
            return 0
        except Exception as e:
            logger.error("Failed to get database size", error=str(e))
            return 0

    @staticmethod
    async def get_table_stats() -> dict:
        """Get row counts per table."""
        try:
            async with get_session() as db_session:
                tables = [
                    'sessions', 'tasks', 'agent_executions', 'tool_calls',
                    'knowledge_entries', 'task_journals', 'projects'
                ]
                stats = {}
                for table in tables:
                    try:
                        result = await db_session.execute(
                            text(f"SELECT COUNT(*) FROM {table}")
                        )
                        count = result.scalar()
                        stats[table] = count
                    except Exception:
                        stats[table] = 0

                logger.info("Table statistics", stats=stats)
                return stats
        except Exception as e:
            logger.error("Failed to get table statistics", error=str(e))
            return {}

    @staticmethod
    async def optimize_database() -> None:
        """Run VACUUM and PRAGMA optimize for performance."""
        try:
            async with get_session() as db_session:
                await db_session.execute(text("VACUUM"))
                await db_session.execute(text("PRAGMA optimize"))
                await db_session.commit()
            logger.info("Database optimized successfully")
        except Exception as e:
            logger.error("Database optimization failed", error=str(e))
            raise

    @staticmethod
    async def check_indexes() -> dict:
        """Check database index health."""
        try:
            async with get_session() as db_session:
                result = await db_session.execute(
                    text("SELECT name, tbl_name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")
                )
                indexes = result.fetchall()
                logger.info("Database indexes", count=len(indexes))
                return {"index_count": len(indexes)}
        except Exception as e:
            logger.error("Failed to check indexes", error=str(e))
            return {}

    @staticmethod
    async def health_check_summary() -> dict:
        """Run all health checks and return summary."""
        try:
            connection_ok = await DatabaseHealth.check_connection()
            db_size = await DatabaseHealth.get_database_size()
            table_stats = await DatabaseHealth.get_table_stats()
            indexes = await DatabaseHealth.check_indexes()

            summary = {
                "timestamp": datetime.now().isoformat(),
                "connection_ok": connection_ok,
                "database_size_bytes": db_size,
                "database_size_mb": round(db_size / (1024 * 1024), 2),
                "table_stats": table_stats,
                "indexes": indexes,
                "healthy": connection_ok and db_size > 0,
            }

            logger.info("Health check complete", healthy=summary["healthy"])
            return summary
        except Exception as e:
            logger.error("Health check failed", error=str(e))
            return {"healthy": False, "error": str(e)}
