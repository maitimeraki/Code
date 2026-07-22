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
    NEEDS_APPROVAL = "needs_approval"  # Phase 4: Sub-agent proposes action, waits for approval


@dataclass
class AgentConfig:
    """Configuration for spawning an agent."""
    agent_type: Union[AgentType, str]
    task_description: str
    context: Dict[str, Any] = field(default_factory=dict)
    max_retries: int = 3
    timeout_seconds: int = 1800
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    permission_scope: Optional["PermissionScope"] = None
    max_tool_iterations: int = 50
    tool_token_budget: Optional[int] = None
    system_prompt: Optional[str] = None
    project_context: Optional["ProjectContext"] = None
    agent_registry: Optional["AgentRegistry"] = None
    skill_registry: Optional["SkillRegistry"] = None
    spawn_depth: int = 0
    is_orchestrator: bool = False
    verify_command: Optional[str] = None

    # --- Focused sub-agent "pin" ---------------------------------------- #
    # A sub-agent is spawned against a pinned objective. working_dir bounds its
    # file/exec operations (enforced by a narrowed permission scope, not just the
    # prompt). success_criteria and non_goals sharpen the objective and are
    # rendered into the pin + the POST_TASK re-assertion.
    working_dir: Optional[str] = None
    success_criteria: Optional[str] = None
    non_goals: Optional[list] = None

    # --- Capability set (drives capability-scoped prompt fragments) ------ #
    # Explicit tool names this agent holds. When set, the fragment gates read
    # from it directly; when None, the gate falls back to the tools implied by
    # the permission scope. This is how e.g. the context-mode doctrine block is
    # attached only to agents that actually hold ctx_* tools.
    granted_tools: Optional[list] = None

    # Output token budget for this run (surfaced in the context-mode doctrine).
    token_budget: Optional[int] = None

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

    # Phase 4: HITL support for sub-agents
    proposed_action: Optional[Dict[str, Any]] = None  # When status == NEEDS_APPROVAL
    artifact_refs: list[str] = field(default_factory=list)  # External resource references

    @property
    def success(self) -> bool:
        return self.status == AgentStatus.COMPLETED and self.error is None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


@dataclass
class SubAgentCapsule:
    """Minimal context slice for sub-agents.

    Instead of giving sub-agents access to full orchestrator context/history,
    pass only the essential information needed to complete their objective.
    Sub-agents receive this capsule, propose actions, and return results.
    The orchestrator owns all pause/approval decisions.
    """

    # What the sub-agent needs to accomplish
    objective: str  # E.g., "Review this Python file for security issues"

    # How to know when it's done
    success_criteria: Dict[str, Any]  # E.g., {"found_issues": bool, "issues_detail": str}

    # What the sub-agent can work with
    inputs: Dict[str, Any]  # E.g., {"file_path": "...", "file_content": "..."}

    # What tools it's allowed to use
    tool_allowlist: list[str]  # E.g., ["read_file", "run_analyzer"]

    # Where it can write (if at all)
    write_scope: Optional[str] = None  # E.g., "temp" | "project" | None

    # Resource budgets
    token_budget: int = 4096  # Max tokens for this sub-agent
    time_budget_seconds: int = 300  # Max time (5 minutes)

    # Context injection
    user_preferences: Optional[Dict[str, Any]] = None  # User settings
    known_pitfalls: Optional[list[Dict[str, Any]]] = None  # Top errors + how to fix
    relevant_knowledge: Optional[list[Dict[str, Any]]] = None  # BM25 search results
