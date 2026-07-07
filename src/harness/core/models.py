"""Core data models for tasks and state."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


class TaskStatus(str, Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class ExitCondition(str, Enum):
    """Why the loop exited."""
    SUCCESS = "success"
    MAX_ITERATIONS = "max_iterations"
    CRITICAL_ERROR = "critical_error"
    TOKEN_BUDGET = "token_budget"
    USER_CANCEL = "user_cancel"


@dataclass
class TaskState:
    """Complete task state for checkpoint/resume."""
    task_id: str = field(default_factory=lambda: str(uuid4()))
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING

    iteration: int = 0
    max_iterations: int = 10

    # Execution results
    results: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    # Timing
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Criteria for completion
    success_criteria: dict[str, Any] = field(default_factory=dict)
    criteria_met: dict[str, bool] = field(default_factory=dict)

    # Exit reason
    exit_condition: Optional[ExitCondition] = None

    def is_complete(self) -> bool:
        """Check if all success criteria are met."""
        if not self.success_criteria:
            return False
        return all(self.criteria_met.values())

    def can_continue(self) -> bool:
        """Check if loop should continue."""
        return (
            self.status == TaskStatus.RUNNING and
            self.iteration < self.max_iterations and
            not self.is_complete()
        )


@dataclass
class CheckpointData:
    """Serializable checkpoint for persistence."""
    task_id: str
    status: str
    iteration: int
    results: dict[str, Any]
    errors: list[str]
    criteria_met: dict[str, bool]
    created_at: str
    updated_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
