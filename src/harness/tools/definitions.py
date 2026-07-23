"""Tool definitions, schemas, and registry for LLM tool-calling."""

from dataclasses import dataclass
from typing import Dict, Type, Literal, Optional, Any
from pydantic import BaseModel

from .models import ToolType


class ReadFileArgs(BaseModel):
    """Arguments for read_file tool."""
    path: str


class WriteFileArgs(BaseModel):
    """Arguments for write_file tool."""
    path: str
    content: str


class EditFileArgs(BaseModel):
    """Arguments for edit_file tool."""
    path: str
    old_text: str
    new_text: str


class BashExecArgs(BaseModel):
    """Arguments for bash_exec tool."""
    command: str
    timeout: int = 120


class GrepSearchArgs(BaseModel):
    """Arguments for grep_search tool."""
    pattern: str
    path: str = "."


class GlobSearchArgs(BaseModel):
    """Arguments for glob_search tool."""
    pattern: str
    path: str = "."


class SpawnAgentArgs(BaseModel):
    """Arguments for spawn_agent tool."""
    name: str
    task: str
    working_dir: Optional[str] = None
    success_criteria: Optional[str] = None
    non_goals: Optional[list[str]] = None


class AttemptCompletionArgs(BaseModel):
    """Arguments for attempt_completion tool."""
    summary: str


# ── New tool argument models ──────────────────────────────────────────────

class AskUserQuestionArgs(BaseModel):
    """Arguments for ask_user_question tool."""
    questions: list[dict] = []
    multi_select: bool = False
    preview: Optional[dict] = None


class SkillArgs(BaseModel):
    """Arguments for skill tool."""
    skill: str
    args: str = ""


class TaskCreateArgs(BaseModel):
    """Arguments for task_create tool."""
    subject: str
    description: str = ""
    active_form: str = ""
    metadata: Optional[dict[str, Any]] = None


class TaskGetArgs(BaseModel):
    """Arguments for task_get tool."""
    task_id: str


class TaskListArgs(BaseModel):
    """Arguments for task_list tool."""
    status: Optional[str] = None


class TaskOutputArgs(BaseModel):
    """Arguments for task_output tool."""
    task_id: str
    block: bool = True
    timeout: int = 60000


class TaskStopArgs(BaseModel):
    """Arguments for task_stop tool."""
    task_id: str


class TaskUpdateArgs(BaseModel):
    """Arguments for task_update tool."""
    task_id: str
    status: Optional[str] = None
    subject: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


@dataclass
class ToolDefinition:
    """Definition of a tool for LLM tool-calling."""
    name: str
    tool_type: ToolType
    description: str
    args_model: Type[BaseModel]
    permission_kind: Literal["fs_read", "fs_write", "shell", "agent_spawn", "interaction", "skill", "task"]


# Static tool registry — one entry per tool that has an actual handler.
TOOL_REGISTRY: Dict[ToolType, ToolDefinition] = {
    ToolType.READ: ToolDefinition(
        name="read",
        tool_type=ToolType.READ,
        description="Read the contents of a file.",
        args_model=ReadFileArgs,
        permission_kind="fs_read",
    ),
    ToolType.WRITE: ToolDefinition(
        name="write",
        tool_type=ToolType.WRITE,
        description="Write content to a file, creating it if it doesn't exist.",
        args_model=WriteFileArgs,
        permission_kind="fs_write",
    ),
    ToolType.EDIT: ToolDefinition(
        name="edit",
        tool_type=ToolType.EDIT,
        description="Replace text in a file at a specific location.",
        args_model=EditFileArgs,
        permission_kind="fs_write",
    ),
    ToolType.BASH: ToolDefinition(
        name="bash",
        tool_type=ToolType.BASH,
        description="Execute a bash command in a shell.",
        args_model=BashExecArgs,
        permission_kind="shell",
    ),
    ToolType.GREP: ToolDefinition(
        name="grep",
        tool_type=ToolType.GREP,
        description="Search for a pattern in files recursively.",
        args_model=GrepSearchArgs,
        permission_kind="fs_read",
    ),
    ToolType.GLOB: ToolDefinition(
        name="glob",
        tool_type=ToolType.GLOB,
        description="Find files matching a glob pattern.",
        args_model=GlobSearchArgs,
        permission_kind="fs_read",
    ),
    ToolType.SPAWN_AGENT: ToolDefinition(
        name="spawn_agent",
        tool_type=ToolType.SPAWN_AGENT,
        description=(
            "Delegate a task to a named sub-agent that runs in its own isolated context. "
            "You may call this multiple times in a single turn to run several sub-agents "
            "concurrently on independent goals; their results return together. "
            "Optionally pass working_dir to bound the sub-agent's file/exec operations to "
            "one directory (enforced, not advisory), success_criteria to define done, and "
            "non_goals to fence off what it must not do."
        ),
        args_model=SpawnAgentArgs,
        permission_kind="agent_spawn",
    ),
    ToolType.ATTEMPT_COMPLETION: ToolDefinition(
        name="attempt_completion",
        tool_type=ToolType.ATTEMPT_COMPLETION,
        description=(
            "Signal that you believe the task is complete. Pass a short summary of "
            "what you accomplished. If a verification step is configured for this task, "
            "your completion is only accepted when that check passes; if it fails, you "
            "will be told why and must continue until it passes."
        ),
        args_model=AttemptCompletionArgs,
        permission_kind="fs_read",
    ),
    # ── Interaction tools ────────────────────────────────────────────────────
    ToolType.ASK_USER_QUESTION: ToolDefinition(
        name="AskUserQuestion",
        tool_type=ToolType.ASK_USER_QUESTION,
        description=(
            "Asks multiple-choice questions of 2 or 3 options to gather requirements or clarify ambiguity. "
            "Questions stay open until you answer them: there's no idle timeout by default. "
            "To have an idle dialog auto-continue instead, set the askUserQuestionTimeout "
            "setting to 60s, 5m, or 10m. Once the chosen idle time passes with no input, "
            "the dialog closes on its own: it submits any options you'd already selected "
            "and tells Claude you may be away from your keyboard, so Claude proceeds on "
            "its own judgment and can re-ask later."
        ),
        args_model=AskUserQuestionArgs,
        permission_kind="interaction",
    ),
    ToolType.SKILL: ToolDefinition(
        name="Skill",
        tool_type=ToolType.SKILL,
        description="Execute a skill within the main conversation.",
        args_model=SkillArgs,
        permission_kind="skill",
    ),
    # ── Task management tools ────────────────────────────────────────────────
    ToolType.TASK_CREATE: ToolDefinition(
        name="TaskCreate",
        tool_type=ToolType.TASK_CREATE,
        description="Create a new task in the task list.",
        args_model=TaskCreateArgs,
        permission_kind="task",
    ),
    ToolType.TASK_GET: ToolDefinition(
        name="TaskGet",
        tool_type=ToolType.TASK_GET,
        description="Retrieve full details for a specific task.",
        args_model=TaskGetArgs,
        permission_kind="task",
    ),
    ToolType.TASK_LIST: ToolDefinition(
        name="TaskList",
        tool_type=ToolType.TASK_LIST,
        description="List all tasks with their current status.",
        args_model=TaskListArgs,
        permission_kind="task",
    ),
    ToolType.TASK_OUTPUT: ToolDefinition(
        name="TaskOutput",
        tool_type=ToolType.TASK_OUTPUT,
        description=(
            "Retrieve output from a background task. Deprecated in favor of Read "
            "on the task's output file path. When no task matches the ID, the error "
            "lists the running background agents by ID and description."
        ),
        args_model=TaskOutputArgs,
        permission_kind="task",
    ),
    ToolType.TASK_STOP: ToolDefinition(
        name="TaskStop",
        tool_type=ToolType.TASK_STOP,
        description=(
            "Stop a running background task by ID. It also accepts an agent-team "
            "teammate or a named background agent by agent ID or name."
        ),
        args_model=TaskStopArgs,
        permission_kind="task",
    ),
    ToolType.TASK_UPDATE: ToolDefinition(
        name="TaskUpdate",
        tool_type=ToolType.TASK_UPDATE,
        description="Update task status, dependencies, details, or delete tasks.",
        args_model=TaskUpdateArgs,
        permission_kind="task",
    ),
}


def to_llm_tool_schema(definition: ToolDefinition) -> dict:
    """Convert a ToolDefinition to OpenAI/litellm tool schema format."""
    return {
        "type": "function",
        "function": {
            "name": definition.name,
            "description": definition.description,
            "parameters": definition.args_model.model_json_schema(),
        },
    }

from harness.registry.definitions import AgentRegistry
def get_tools_payload(router, agent_registry: Optional["AgentRegistry"] = None) -> list[dict]:
    """Build tools payload for LLM, filtering to only registered handlers.

    For spawn_agent, dynamically appends available agent names+descriptions to the tool description.
    """
    tools = []
    for tool_type in router.handlers.keys():
        if tool_type not in TOOL_REGISTRY:
            continue
        definition = TOOL_REGISTRY[tool_type]
        schema = to_llm_tool_schema(definition)
        if tool_type == ToolType.SPAWN_AGENT and agent_registry is not None:
            agents = agent_registry.list_agents()
            listing = "\n".join(f"- {a.name}: {a.description}" for a in agents) or "(no agents available)"
            schema["function"]["description"] += f"\n\nAvailable agents:\n{listing}"
        tools.append(schema)
    return tools


def validate_args(tool_type: ToolType, raw_args: dict) -> BaseModel:
    """Validate and parse tool arguments against the tool's args schema.

    Raises pydantic.ValidationError if arguments don't match the schema.
    """
    if tool_type not in TOOL_REGISTRY:
        raise ValueError(f"Unknown tool type: {tool_type.value}")

    definition = TOOL_REGISTRY[tool_type]
    return definition.args_model.model_validate(raw_args)
