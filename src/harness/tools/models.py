"""Tool execution models."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any, Dict
from datetime import datetime


class ToolType(Enum):
    """Supported tool types."""
    READ = "Read"
    WRITE = "Write"
    EDIT = "Update"
    BASH = "Bash"
    GREP = "Pattern"
    GLOB = "Search"
    GIT = "Git"
    HTTP = "HTTP"
    SPAWN_AGENT = "Agent"
    ATTEMPT_COMPLETION = "Is_completion"
    ASK_USER_QUESTION = "AskUserQuestion"
    SKILL = "Skill"
    TASK_CREATE = "TaskCreate"
    TASK_GET = "TaskGet"
    TASK_LIST = "TaskList"
    TASK_OUTPUT = "TaskOutput"
    TASK_STOP = "TaskStop"
    TASK_UPDATE = "TaskUpdate"


class ToolStatus(Enum):
    """Tool execution status."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ToolCall:
    """A tool invocation."""
    tool_type: ToolType
    args: Dict[str, Any] = field(default_factory=dict)
    status: ToolStatus = ToolStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    tokens_used: int = 0
    cache_hit: bool = False
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def success(self) -> bool:
        return self.status == ToolStatus.SUCCESS


@dataclass
class ToolResult:
    """Result from tool execution."""
    tool_call: ToolCall
    cached: bool = False
    retry_count: int = 0
    total_retries: int = 0


@dataclass
class ToolBudget:
    """Context budget tracking for tool calls."""
    total_tokens: int = 200000
    tokens_used: int = 0
    max_concurrent_tools: int = 16

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.total_tokens - self.tokens_used)

    @property
    def has_budget(self) -> bool:
        return self.remaining_tokens > 0
