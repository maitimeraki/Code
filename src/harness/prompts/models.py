"""Prompt and context models."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List, Any
from datetime import datetime


class AgentRole(Enum):
    """Agent role definitions."""
    ARCHITECT = "architect"
    CODE_REVIEWER = "code-reviewer"
    TDD_GUIDE = "tdd-guide"
    SECURITY_REVIEWER = "security-reviewer"
    PYTHON_REVIEWER = "python-reviewer"
    RUST_REVIEWER = "rust-reviewer"
    TYPESCRIPT_REVIEWER = "typescript-reviewer"
    PLANNER = "planner"
    PERFORMANCE_OPTIMIZER = "performance-optimizer"


class BehaviorMode(Enum):
    """Agent behavior mode."""
    PONYTAIL = "ponytail"  # Lazy: efficient, minimal code
    KARPATHY = "karpathy"  # Careful: thorough, defensive
    STANDARD = "standard"  # Default balanced approach


@dataclass
class PromptConstraint:
    """Constraints for prompt generation."""
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 1.0
    guardrails: List[str] = field(default_factory=list)
    must_include: List[str] = field(default_factory=list)
    must_avoid: List[str] = field(default_factory=list)


@dataclass
class ContextEntry:
    """A single piece of context (prior solution, code snippet, example)."""
    title: str
    content: str
    source: str  # File path, prior task ID, etc.
    relevance_score: float = 0.0
    created_at: Optional[datetime] = None


@dataclass
class PromptContext:
    """Context injected into prompt."""
    task_description: str
    prior_solutions: List[ContextEntry] = field(default_factory=list)
    code_examples: List[ContextEntry] = field(default_factory=list)
    tool_examples: List[ContextEntry] = field(default_factory=list)
    related_errors: List[ContextEntry] = field(default_factory=list)
    codebase_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GeneratedPrompt:
    """Result from prompt generation."""
    role: AgentRole
    behavior_mode: BehaviorMode
    system_prompt: str
    user_prompt: str
    constraints: PromptConstraint
    context_entries_used: int
    token_estimate: int
    generated_at: datetime = field(default_factory=datetime.now)

    @property
    def full_prompt(self) -> str:
        return f"{self.system_prompt}\n\n{self.user_prompt}"
