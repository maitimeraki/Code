"""Task state management with persistence."""

import asyncio
from pathlib import Path
from typing import Any, Optional
from datetime import datetime
import msgpack
import structlog

from harness.core.models import TaskState, TaskStatus, CheckpointData


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
        """Persist task state as binary msgpack."""
        checkpoint = CheckpointData(
            task_id=state.task_id,
            status=state.status.value,
            iteration=state.iteration,
            results=state.results,
            errors=state.errors,
            criteria_met=state.criteria_met,
            created_at=state.created_at.isoformat(),
            updated_at=datetime.now().isoformat(),
            started_at=state.started_at.isoformat() if state.started_at else None,
            completed_at=state.completed_at.isoformat() if state.completed_at else None,
        )

        journal_path = self._get_journal_path(state.task_id)
        data = msgpack.packb(checkpoint.__dict__, use_bin_type=True)

        await asyncio.to_thread(journal_path.write_bytes, data)
        logger.info("Saved task state", task_id=state.task_id, iteration=state.iteration)

    async def load_state(self, task_id: str) -> Optional[TaskState]:
        """Restore task state from checkpoint."""
        journal_path = self._get_journal_path(task_id)

        if not journal_path.exists():
            logger.warning("No checkpoint found", task_id=task_id)
            return None

        data = await asyncio.to_thread(journal_path.read_bytes)
        checkpoint_dict = msgpack.unpackb(data, raw=False)

        # Reconstruct TaskState
        state = TaskState(
            task_id=checkpoint_dict["task_id"],
            status=TaskStatus(checkpoint_dict["status"]),
            iteration=checkpoint_dict["iteration"],
            results=checkpoint_dict["results"],
            errors=checkpoint_dict["errors"],
            criteria_met=checkpoint_dict["criteria_met"],
            created_at=datetime.fromisoformat(checkpoint_dict["created_at"]),
            updated_at=datetime.fromisoformat(checkpoint_dict["updated_at"]),
            started_at=datetime.fromisoformat(checkpoint_dict["started_at"]) if checkpoint_dict["started_at"] else None,
            completed_at=datetime.fromisoformat(checkpoint_dict["completed_at"]) if checkpoint_dict["completed_at"] else None,
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
