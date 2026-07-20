"""Task state management with persistence."""

import asyncio
from pathlib import Path
from typing import Any, Optional
from datetime import datetime
from uuid import uuid4
import msgpack
import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from harness.core.models import TaskState, TaskStatus, CheckpointData
from harness.persistence.database import get_session
from harness.persistence.models import Task, TaskJournal


logger = structlog.get_logger(__name__)


class TaskStateManager:
    """Manage task state with file-based persistence."""

    def __init__(self, data_dir: Path = Path("data")):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.journal_dir = self.data_dir / "journals"
        self.journal_dir.mkdir(exist_ok=True)

    def _get_journal_path(self, task_id: str) -> Path:
        """Get path for task's journal file."""
        return self.journal_dir / f"{task_id}.msgpack"

    async def save_state(self, state: TaskState) -> None:
        """Persist task state: SQLite (authoritative) + msgpack (cache).

        DB is truth. Msgpack is optional fast-cache for offline access.
        """
        # Write to SQLite (authoritative)
        async with get_session() as session:
            # Upsert Task row
            task_record = await session.get(Task, state.task_id)
            if task_record is None:
                task_record = Task(task_id=state.task_id)
                session.add(task_record)

            # Update all fields
            task_record.session_id = state.task_id
            task_record.description = state.description
            task_record.status = state.status.value
            task_record.result = state.result
            task_record.error = state.error
            task_record.iterations = state.iteration
            task_record.max_iterations = state.max_iterations
            task_record.tokens_used = state.tokens_used
            task_record.started_at = state.started_at
            task_record.completed_at = state.completed_at
            task_record.metadata_json = {
                "results": state.results,
                "errors": state.errors,
                "criteria_met": state.criteria_met,
                "success_criteria": state.success_criteria,
                "exit_condition": state.exit_condition.value if state.exit_condition else None,
            }
            task_record.updated_at = datetime.now()

            await session.commit()

        # Write to msgpack (cache)
        checkpoint = CheckpointData(
            task_id=state.task_id,
            status=state.status.value,
            iteration=state.iteration,
            results=state.results,
            errors=state.errors,
            criteria_met=state.criteria_met,
            created_at=state.created_at.isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        journal_path = self._get_journal_path(state.task_id)
        data = msgpack.packb(checkpoint.__dict__, use_bin_type=True)
        await asyncio.to_thread(journal_path.write_bytes, data)

        logger.info("Saved task state", task_id=state.task_id, iteration=state.iteration)

    async def load_state(self, task_id: str) -> Optional[TaskState]:
        """Restore task state from SQLite (authoritative source)."""
        async with get_session() as session:
            task_record = await session.get(Task, task_id)

            if task_record is None:
                logger.warning("No task found", task_id=task_id)
                return None

            metadata = task_record.metadata_json or {}
            state = TaskState(
                task_id=task_record.task_id,
                description=task_record.description,
                status=TaskStatus(task_record.status),
                iteration=task_record.iterations,
                max_iterations=task_record.max_iterations,
                result=task_record.result,
                error=task_record.error,
                tokens_used=task_record.tokens_used,
                results=metadata.get("results", {}),
                errors=metadata.get("errors", []),
                criteria_met=metadata.get("criteria_met", {}),
                success_criteria=metadata.get("success_criteria", {}),
                created_at=task_record.created_at or datetime.now(),
                updated_at=task_record.updated_at or datetime.now(),
                started_at=task_record.started_at,
                completed_at=task_record.completed_at,
            )

            logger.info("Loaded task state", task_id=task_id, iteration=state.iteration)
            return state

    async def create_task(self, description: str, success_criteria: dict[str, Any], max_iterations: int = 10) -> TaskState:
        """Create a new task with initial state."""
        state = TaskState(
            description=description,
            success_criteria=success_criteria,
            max_iterations=max_iterations,
        )
        state.criteria_met = {key: False for key in success_criteria.keys()}

        await self.save_state(state)
        logger.info("Created task", task_id=state.task_id, description=description)
        return state

    async def list_tasks(self) -> list[str]:
        """List all task IDs from journal."""
        return [f.stem for f in self.journal_dir.glob("*.msgpack")]
