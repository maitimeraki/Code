"""Tool execution models."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any, Dict
from datetime import datetime


class ToolType(Enum):
    """Supported tool types."""
    READ = "read"
    WRITE = "write"
    EDIT = "edit"
    BASH = "bash"
    GREP = "grep"
    GLOB = "glob"
    GIT = "git"
    HTTP = "http"


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
    total_tokens: int = 1000000
    tokens_used: int = 0
    max_concurrent_tools: int = 16

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.total_tokens - self.tokens_used)

    @property
    def has_budget(self) -> bool:
        return self.remaining_tokens > 0
