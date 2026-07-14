"""Tool definitions, schemas, and registry for LLM tool-calling."""

from dataclasses import dataclass
from typing import Dict, Type, Literal, Optional
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
    timeout: int = 30


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


@dataclass
class ToolDefinition:
    """Definition of a tool for LLM tool-calling."""
    name: str
    tool_type: ToolType
    description: str
    args_model: Type[BaseModel]
    permission_kind: Literal["fs_read", "fs_write", "shell", "agent_spawn"]


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
        description="Delegate a task to a named sub-agent that runs in its own isolated context.",
        args_model=SpawnAgentArgs,
        permission_kind="agent_spawn",
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
