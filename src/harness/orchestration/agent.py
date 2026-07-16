"""Agent configuration and execution models."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, TYPE_CHECKING, Union
from datetime import datetime
from pathlib import Path

if TYPE_CHECKING:
    from harness.tools.permissions import PermissionScope
    from harness.context.project_context import ProjectContext
    from harness.registry.definitions import AgentRegistry, SkillRegistry

MAX_SPAWN_DEPTH = 3


class AgentType(Enum):
    """Supported agent types."""
    ARCHITECT = "architect"
    CODE_REVIEWER = "code-reviewer"
    TDD_GUIDE = "tdd-guide"
    SECURITY_REVIEWER = "security-reviewer"
    PYTHON_REVIEWER = "python-reviewer"
    RUST_REVIEWER = "rust-reviewer"
    TYPESCRIPT_REVIEWER = "typescript-reviewer"
    PLANNER = "planner"
    PERFORMANCE_OPTIMIZER = "performance-optimizer"


class AgentStatus(Enum):
    """Agent execution status."""
    IDLE = "idle"
    SPAWNING = "spawning"
    RUNNING = "running"
    THINKING = "thinking"
    TOOL_CALLING = "tool_calling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentConfig:
    """Configuration for spawning an agent."""
    agent_type: Union[AgentType, str]
    task_description: str
    context: Dict[str, Any] = field(default_factory=dict)
    max_retries: int = 3
    timeout_seconds: int = 300
    model: str = "claude-3-5-sonnet-20241022"
    temperature: float = 0.7
    max_tokens: int = 4096
    permission_scope: Optional["PermissionScope"] = None
    max_tool_iterations: int = 10
    tool_token_budget: Optional[int] = None
    system_prompt: Optional[str] = None
    project_context: Optional["ProjectContext"] = None
    agent_registry: Optional["AgentRegistry"] = None
    skill_registry: Optional["SkillRegistry"] = None
    spawn_depth: int = 0

    def __post_init__(self) -> None:
        """Initialize permission_scope and agent_name."""
        if self.permission_scope is None:
            from harness.tools.permissions import PermissionScope
            self.permission_scope = PermissionScope.default_for_project(Path.cwd())
        self.agent_name: str = self.agent_type.value if isinstance(self.agent_type, AgentType) else str(self.agent_type)


@dataclass
class AgentResult:
    """Result from agent execution."""
    agent_type: Union[AgentType, str]
    status: AgentStatus
    output: Optional[str] = None
    error: Optional[str] = None
    tokens_used: int = 0
    iterations: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def success(self) -> bool:
        return self.status == AgentStatus.COMPLETED and self.error is None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
