"""Capability-scoped prompt fragments.

The sub-agent system prompt is *composed* at spawn time, never fixed. It equals:

    base_scaffold + Σ(fragment.render for fragment where fragment.applies_to(cfg)) + pin

A fragment ships alongside a capability and gates on the agent's own granted
toolset. Install a plugin that grants `ctx_*` tools → its doctrine block renders
for eligible agents. Spawn a narrow agent without those tools → the block never
appears. No plugin name is ever hardcoded in the prompt builder: fragments are
collected from a registry, ordered by zone, and rendered in place.

context-mode is simply the first fragment. Any future capability registers its
own the same way, with zero edits to `_compose_system_message`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, TYPE_CHECKING

if TYPE_CHECKING:
    from harness.orchestration.agent import AgentConfig


class Zone(Enum):
    """Where a fragment sits in the composed prompt. Lower value = earlier."""

    DOCTRINE = 1   # right after the operating manual / tool schemas
    ROLE = 2       # alongside the agent persona
    POST_TASK = 9  # re-injected before the child's final answer turn


@dataclass
class PromptFragment:
    """A gated, self-rendering slice of a system prompt.

    applies_to is THE GATE: it receives the agent config and returns True only
    when this fragment is relevant to *that* agent. render produces the XML block
    (it may read the config for dynamic values like the working directory).
    """

    id: str
    zone: Zone
    applies_to: Callable[["AgentConfig"], bool]
    render: Callable[["AgentConfig"], str]
    priority: int = 100  # tie-breaker within a zone; lower renders first


class FragmentRegistry:
    """Holds fragments and returns the ones that apply to a given agent, in order.

    Population is dynamic: at startup, each installed capability contributes its
    fragment via register(). A process with no capabilities registered yields an
    empty DOCTRINE zone — i.e. a clean, minimal prompt.
    """

    def __init__(self) -> None:
        self._fragments: List[PromptFragment] = []

    def register(self, fragment: PromptFragment) -> None:
        """Add a fragment. Re-registering the same id replaces the prior one."""
        self._fragments = [f for f in self._fragments if f.id != fragment.id]
        self._fragments.append(fragment)

    def collect(self, cfg: "AgentConfig") -> List[PromptFragment]:
        """Return applicable fragments sorted by (zone, priority, id).

        A fragment whose applies_to raises is treated as not-applicable rather
        than crashing prompt composition — a broken plugin must never break spawn.
        """

        def _applies(f: PromptFragment) -> bool:
            try:
                return bool(f.applies_to(cfg))
            except Exception:
                return False

        applicable = [f for f in self._fragments if _applies(f)]
        return sorted(applicable, key=lambda f: (f.zone.value, f.priority, f.id))

    def collect_zone(self, cfg: "AgentConfig", zone: Zone) -> List[PromptFragment]:
        """Applicable fragments restricted to a single zone, in order."""
        return [f for f in self.collect(cfg) if f.zone is zone]


# --------------------------------------------------------------------------- #
# Capability gate                                                              #
# --------------------------------------------------------------------------- #

def granted_tool_names(cfg: "AgentConfig") -> List[str]:
    """The tool names this specific agent holds.

    Prefers an explicit cfg.granted_tools (set by whatever granted the
    capability). Falls back to the built-in tool names implied by the agent's
    permission scope, so the gate always reflects real capability rather than a
    global flag.
    """
    explicit = getattr(cfg, "granted_tools", None)
    if explicit:
        return list(explicit)

    # Fall back to the built-in handlers the scope would produce. Mirrors the
    # gating logic in build_scoped_router without importing the router itself.
    from harness.tools.definitions import TOOL_REGISTRY
    from harness.tools.models import ToolType

    scope = getattr(cfg, "permission_scope", None)
    names: List[str] = []
    for tool_type, defn in TOOL_REGISTRY.items():
        tool_name = defn.name
        # Map ToolType to permission scope tool names
        scope_tool_name = {
            ToolType.READ: "Read",
            ToolType.WRITE: "Write",
            ToolType.EDIT: "Edit",
            ToolType.BASH: "Bash",
            ToolType.GREP: "Grep",
            ToolType.GLOB: "Glob",
            ToolType.SPAWN_AGENT: "spawn_agent",
        }.get(tool_type)

        if scope is not None and scope_tool_name:
            allowed, _ = scope.check(scope_tool_name)
            if not allowed:
                continue

        names.append(tool_name)
    return names


def has_ctx_tools(cfg: "AgentConfig") -> bool:
    """Gate: does THIS agent hold any context-mode (`ctx_*`) tool?"""
    return any(name.startswith("ctx_") for name in granted_tool_names(cfg))


# --------------------------------------------------------------------------- #
# context-mode doctrine fragment                                              #
# --------------------------------------------------------------------------- #

def render_context_mode_block(cfg: "AgentConfig") -> str:
    """Teach an eligible agent the context-mode discipline.

    Dynamic values (working directory, tool budget) are injected from the agent's
    own config so two same-type agents in different folders get correct, distinct
    guidance.
    """
    work_dir = getattr(cfg, "working_dir", None)
    if not work_dir and getattr(cfg, "project_context", None):
        work_dir = str(cfg.project_context.root)
    work_dir = work_dir or "the project root"

    budget = getattr(cfg, "token_budget", None)
    budget_line = (
        f"Your output token budget for this run is ~{budget}. Spend it on findings, "
        "not on echoing raw tool output."
        if budget
        else "Keep raw tool output out of your final answer; report only what you derived."
    )

    return f"""<context_mode>
You have context-mode (`ctx_*`) tools. Follow the Think-in-Code discipline:
- The bytes your code processes never enter your conversation — only what you
  print does. To answer a question ABOUT data (filter, count, parse, aggregate),
  run code over it with `ctx_execute` / `ctx_execute_file` and print only the
  derived answer, instead of reading raw output into context.
- To recall web docs or large text later, index it (`ctx_fetch_and_index`,
  `ctx_index`) and retrieve sections on demand with `ctx_search` rather than
  holding the full content in context.
- {budget_line}
- Scope file and execution work to: {work_dir}
</context_mode>"""


# --------------------------------------------------------------------------- #
# POST_TASK re-assertion fragment                                             #
# --------------------------------------------------------------------------- #

def render_objective_reassertion(cfg: "AgentConfig") -> str:
    """One line, injected before the final turn, to counter goal-drift.

    Only meaningful for a sub-agent working a pinned objective — the orchestrator
    manages its own goals.
    """
    objective = getattr(cfg, "task_description", "") or ""
    criteria = getattr(cfg, "success_criteria", None) or "the task is addressed and the result returned"
    return (
        f"<objective_reminder>Your objective was: {objective}\n"
        f"Success = {criteria}. Emit your return contract now: findings + evidence "
        f"+ verdict, without echoing raw tool output.</objective_reminder>"
    )


def _reassertion_applies(cfg: "AgentConfig") -> bool:
    return not getattr(cfg, "is_orchestrator", False)


# --------------------------------------------------------------------------- #
# The objective pin (system-region, high-attention)                           #
# --------------------------------------------------------------------------- #

def render_objective_pin(cfg: "AgentConfig") -> str:
    """Render the focused sub-agent "pin": objective, success, scope, non-goals.

    Placed high in the system region so it stays in the model's attention across
    a long run. The scope clause is descriptive here; the actual enforcement is
    the narrowed permission scope applied at spawn time.
    """
    objective = getattr(cfg, "task_description", "") or ""
    criteria = getattr(cfg, "success_criteria", None) or "task addressed and result returned"

    work_dir = getattr(cfg, "working_dir", None)
    if not work_dir and getattr(cfg, "project_context", None):
        work_dir = str(cfg.project_context.root)
    work_dir = work_dir or "the project root"

    non_goals = getattr(cfg, "non_goals", None) or []
    non_goals_block = (
        "\n".join(f"  - {g}" for g in non_goals) if non_goals else "  - (none specified)"
    )

    return f"""<objective>{objective}</objective>
<success_criteria>{criteria}</success_criteria>
<scope>
  <working_directory>{work_dir}</working_directory>
  Restrict file and execution operations to this directory unless explicitly told otherwise.
</scope>
<non_goals>
{non_goals_block}
</non_goals>
<return_contract>Return only your findings, the evidence for them, and a verdict. Do not echo raw tool output.</return_contract>"""


# --------------------------------------------------------------------------- #
# Default registry population                                                  #
# --------------------------------------------------------------------------- #

CONTEXT_MODE_FRAGMENT = PromptFragment(
    id="context-mode",
    zone=Zone.DOCTRINE,
    priority=10,
    applies_to=has_ctx_tools,          # only if THIS agent holds ctx_* tools
    render=render_context_mode_block,
)

OBJECTIVE_REASSERTION_FRAGMENT = PromptFragment(
    id="objective-reassertion",
    zone=Zone.POST_TASK,
    priority=10,
    applies_to=_reassertion_applies,   # sub-agents only
    render=render_objective_reassertion,
)


def build_default_registry() -> FragmentRegistry:
    """A FragmentRegistry pre-populated with the harness's own fragments.

    Additional capabilities register their fragments onto this instance at
    startup — the builder here hardcodes no plugin, only the harness's built-ins.
    """
    registry = FragmentRegistry()
    registry.register(CONTEXT_MODE_FRAGMENT)
    registry.register(OBJECTIVE_REASSERTION_FRAGMENT)
    return registry


# Process-wide default registry. Capabilities may import and register onto this.
_DEFAULT_REGISTRY = build_default_registry()


def get_fragment_registry() -> FragmentRegistry:
    """Return the process-wide fragment registry."""
    return _DEFAULT_REGISTRY
