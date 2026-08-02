"""Database migration utilities for schema evolution."""

from sqlalchemy import text
import structlog

logger = structlog.get_logger(__name__)


async def migrate_v0_to_v1(session) -> None:
    """Migrate schema from v0 to v1: Add phase tracking and causality fields.

    Phase tracking (working memory):
    - task.phase (planning/executing/completing)
    - task.decision_log (JSON array of decisions)
    - task.context_hash (hash for resume detection)

    Causality tracking (episodic memory):
    - agent_executions.parent_execution_id
    - agent_executions.trace_id
    - agent_executions.decision_context
    """
    try:
        # Check if columns already exist
        result = await session.execute(
            text("PRAGMA table_info(tasks)")
        )
        columns = {row[1] for row in result.fetchall()}

        # Add phase tracking columns if missing
        if "phase" not in columns:
            await session.execute(
                text("ALTER TABLE tasks ADD COLUMN phase VARCHAR(50) DEFAULT 'planning'")
            )
            logger.info("Added phase column to tasks")

        if "decision_log" not in columns:
            await session.execute(
                text("ALTER TABLE tasks ADD COLUMN decision_log JSON DEFAULT '[]'")
            )
            logger.info("Added decision_log column to tasks")

        if "context_hash" not in columns:
            await session.execute(
                text("ALTER TABLE tasks ADD COLUMN context_hash VARCHAR(64)")
            )
            logger.info("Added context_hash column to tasks")

        # Add causality tracking columns if missing
        result = await session.execute(
            text("PRAGMA table_info(agent_executions)")
        )
        columns = {row[1] for row in result.fetchall()}

        if "parent_execution_id" not in columns:
            await session.execute(
                text("ALTER TABLE agent_executions ADD COLUMN parent_execution_id VARCHAR(36)")
            )
            logger.info("Added parent_execution_id column to agent_executions")

        if "trace_id" not in columns:
            await session.execute(
                text("ALTER TABLE agent_executions ADD COLUMN trace_id VARCHAR(36) NOT NULL DEFAULT ''")
            )
            logger.info("Added trace_id column to agent_executions")

        if "decision_context" not in columns:
            await session.execute(
                text("ALTER TABLE agent_executions ADD COLUMN decision_context JSON DEFAULT '{}'")
            )
            logger.info("Added decision_context column to agent_executions")

        # Create indexes for production queries
        await session.execute(
            text("""
                CREATE INDEX IF NOT EXISTS ix_task_phase_status
                ON tasks(phase, status)
            """)
        )
        logger.info("Created ix_task_phase_status index")

        await session.execute(
            text("""
                CREATE INDEX IF NOT EXISTS ix_agentexec_trace
                ON agent_executions(trace_id, created_at)
            """)
        )
        logger.info("Created ix_agentexec_trace index")

        await session.execute(
            text("""
                CREATE INDEX IF NOT EXISTS ix_agentexec_task_parent
                ON agent_executions(task_id, parent_execution_id)
            """)
        )
        logger.info("Created ix_agentexec_task_parent index")

        await session.execute(
            text("""
                CREATE INDEX IF NOT EXISTS ix_toolcall_task_time
                ON tool_calls(task_id, created_at)
            """)
        )
        logger.info("Created ix_toolcall_task_time index")

        await session.commit()
        logger.info("Database migration v0->v1 complete")

    except Exception as e:
        logger.warning("Migration already applied or failed", error=str(e))
        await session.rollback()


async def migrate_v1_to_v2(session) -> None:
    """Migrate schema from v1 to v2: Add updated_at to tasks."""
    try:
        result = await session.execute(
            text("PRAGMA table_info(tasks)")
        )
        columns = {row[1] for row in result.fetchall()}

        if "updated_at" not in columns:
            await session.execute(
                text("ALTER TABLE tasks ADD COLUMN updated_at DATETIME")
            )
            await session.commit()
            logger.info("Added updated_at column to tasks")

        logger.info("Database migration v1->v2 complete")

    except Exception as e:
        await session.rollback()
        logger.error("Migration v1→v2 failed", error=str(e))
        raise


async def apply_migrations(session) -> None:
    """Apply all pending migrations in order."""
    try:
        await migrate_v0_to_v1(session)
        await migrate_v1_to_v2(session)
    except Exception as e:
        logger.error("Migration failed", error=str(e))
        raise
