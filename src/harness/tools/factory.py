"""Factory for building scoped tool routers with permission enforcement."""

from typing import Callable, Any, Optional

from .models import ToolType
from .router import ToolRouter
from .permissions import PermissionScope, PathGuard, CommandGuard, ApprovalRequired
from harness.core.approval_policy import is_granted, is_denied
from . import handlers


def _gate(scope: PermissionScope, tool_name: str, resource: str = "") -> bool:
    """Gate a tool+resource against the scope before it runs.

    Raises:
        PermissionError: the tool+resource is denied outright (config or a
            session denial).
        ApprovalRequired: the tool+resource needs human approval and has not yet
            been granted; the executor parks the call as AWAITING_APPROVAL.
    """
    allowed, mode = scope.check(tool_name, resource)
    if not allowed:
        raise PermissionError(f"{tool_name} is not allowed in this scope")
    if mode == "requires_approval" and tool_name != "AskUserQuestion":
        # Denied this session / exact call? Block outright.
        if is_denied(tool_name, resource):
            raise PermissionError(f"{tool_name} was denied for this session")
        # Already approved (session or exact)? Then let it run — otherwise park it.
        if not is_granted(tool_name, resource):
            raise ApprovalRequired(tool_name)
    return False



def build_scoped_router(
    scope: PermissionScope,
    agent_registry: Any = None,
    spawn_fn: Callable = None,
    parent_config: Any = None,
    ask_user_question_callback: Optional[Callable] = None,
    mcp_manager: Any = None,
    skill_registry: Any = None,
) -> ToolRouter:
    """Build a ToolRouter with permission-guarded handlers.

    Each handler is wrapped with corresponding permission checks:
    - File operations: PathGuard for allowed_paths, scope.check() for tool permissions
    - Bash: CommandGuard + scope.check() for command patterns
    - Agent spawn: scope.check() for agent spawning permission

    Args:
        scope: The PermissionScope defining what this router can do.
        agent_registry: Optional agent registry for spawn_agent handler.
        spawn_fn: Optional spawn function for spawning nested agents.
        parent_config: Optional parent agent config for nested spawns.

    Returns:
        A ToolRouter with handlers registered and guarded.
    """
    router = ToolRouter()

    # READ — file read with tool permission check + path guard
    async def read_file_guarded(**kwargs: Any) -> str:
        _gate(scope, "Read", kwargs.get("path", ""))
        path = kwargs.get("path")
        if path:
            PathGuard.resolve_and_check(path, scope, "read")
        return await handlers.read_file(**kwargs)

    router.register_handler(ToolType.READ, read_file_guarded)

    # WRITE — file write with tool permission check + path guard
    async def write_file_guarded(**kwargs: Any) -> str:
        _gate(scope, "Write", kwargs.get("path", ""))
        path = kwargs.get("path")
        if path:
            PathGuard.resolve_and_check(path, scope, "write")
        return await handlers.write_file(**kwargs)

    router.register_handler(ToolType.WRITE, write_file_guarded)

    # EDIT — file edit with tool permission check + path guard
    async def edit_file_guarded(**kwargs: Any) -> str:
        _gate(scope, "Edit", kwargs.get("path", ""))
        path = kwargs.get("path")
        if path:
            PathGuard.resolve_and_check(path, scope, "write")
        return await handlers.edit_file(**kwargs)

    router.register_handler(ToolType.EDIT, edit_file_guarded)

    # BASH — shell execution with tool permission check + command guard
    async def bash_exec_guarded(**kwargs: Any) -> str:
        command = kwargs.get("command", "")
        _gate(scope, "Bash", command)
        if command:
            CommandGuard.check(command, scope)
        return await handlers.bash_exec(**kwargs)

    router.register_handler(ToolType.BASH, bash_exec_guarded)

    # GREP — file search with tool permission check + path guard
    async def grep_search_guarded(**kwargs: Any) -> str:
        _gate(scope, "Grep", kwargs.get("path", "."))
        path = kwargs.get("path", ".")
        PathGuard.resolve_and_check(path, scope, "read")
        return await handlers.grep_search(**kwargs)

    router.register_handler(ToolType.GREP, grep_search_guarded)

    # GLOB — glob pattern matching with tool permission check + path guard
    async def glob_search_guarded(**kwargs: Any) -> str:
        _gate(scope, "Glob", kwargs.get("path", "."))
        path = kwargs.get("path", ".")
        PathGuard.resolve_and_check(path, scope, "read")
        return await handlers.glob_search(**kwargs)

    router.register_handler(ToolType.GLOB, glob_search_guarded)

    # ATTEMPT_COMPLETION — control-flow signal, available to every agent, no gate.
    # The spawner intercepts this call to run the task's verifier; the handler here
    # only echoes the summary so the tool is present in the LLM tools payload.
    async def attempt_completion_handler(**kwargs: Any) -> str:
        return kwargs.get("summary", "")

    router.register_handler(ToolType.ATTEMPT_COMPLETION, attempt_completion_handler)


    # SPAWN_AGENT — agent spawning with permission check (only if scope allows AND params supplied)
    spawn_agent_perm = scope.tools.get("spawn_agent")
    if (
        spawn_agent_perm is None or spawn_agent_perm.mode != "deny"
    ) and (
        agent_registry is not None
        and spawn_fn is not None
        and parent_config is not None
    ):
        async def spawn_agent_guarded(**kwargs: Any) -> str:
            _gate(scope, "spawn_agent")
            spawn_agent_handler = handlers.make_spawn_agent_handler(
                agent_registry, spawn_fn, parent_config
            )
            return await spawn_agent_handler(**kwargs)

        router.register_handler(ToolType.SPAWN_AGENT, spawn_agent_guarded)

    # ── AskUserQuestion — interaction tool with permission check ────────────
    async def ask_user_question_guarded(**kwargs: Any) -> str:
        _gate(scope, "AskUserQuestion")
        if ask_user_question_callback:
            return await ask_user_question_callback(**kwargs)
        return await handlers.ask_user_question(**kwargs)

    router.register_handler(ToolType.ASK_USER_QUESTION, ask_user_question_guarded)

    # ── Skill — skill execution with permission check ───────────────────────
    async def execute_skill_guarded(**kwargs: Any) -> str:
        _gate(scope, "Skill")
        return await handlers.execute_skill(**kwargs, skill_registry=skill_registry)

    router.register_handler(ToolType.SKILL, execute_skill_guarded)

    # ── Task management tools with permission check ─────────────────────────
    # session_id comes from the agent config, never from the LLM — tasks must stay
    # scoped to the session that created them so a later prompt still sees them.
    task_session_id = ""
    if parent_config is not None:
        task_session_id = (getattr(parent_config, "context", None) or {}).get("session_id") or ""

    async def task_create_guarded(**kwargs: Any) -> str:
        _gate(scope, "TaskCreate")
        return await handlers.task_create(**kwargs, session_id=task_session_id)

    router.register_handler(ToolType.TASK_CREATE, task_create_guarded)

    async def task_get_guarded(**kwargs: Any) -> str:
        _gate(scope, "TaskGet")
        return await handlers.task_get(**kwargs, session_id=task_session_id)

    router.register_handler(ToolType.TASK_GET, task_get_guarded)

    async def task_list_guarded(**kwargs: Any) -> str:
        _gate(scope, "TaskList")
        return await handlers.task_list(**kwargs, session_id=task_session_id)

    router.register_handler(ToolType.TASK_LIST, task_list_guarded)

    async def task_output_guarded(**kwargs: Any) -> str:
        _gate(scope, "TaskOutput")
        return await handlers.task_output(**kwargs)

    router.register_handler(ToolType.TASK_OUTPUT, task_output_guarded)

    async def task_stop_guarded(**kwargs: Any) -> str:
        _gate(scope, "TaskStop")
        return await handlers.task_stop(**kwargs)

    router.register_handler(ToolType.TASK_STOP, task_stop_guarded)

    async def task_update_guarded(**kwargs: Any) -> str:
        _gate(scope, "TaskUpdate")
        return await handlers.task_update(**kwargs, session_id=task_session_id)

    router.register_handler(ToolType.TASK_UPDATE, task_update_guarded)

    # MEMORY_SEARCH — read-only, registered unconditionally
    async def memory_search_handler(**kwargs: Any) -> str:
        return await handlers.memory_search(**kwargs)

    router.register_handler(ToolType.MEMORY_SEARCH, memory_search_handler)

    # PLUGIN_CONTEXT — read-only (fetches installed plugin commands/instructions/
    # rules on demand), registered unconditionally like memory_search.
    async def plugin_context_handler(**kwargs: Any) -> str:
        return await handlers.plugin_context(**kwargs)

    router.register_handler(ToolType.PLUGIN_CONTEXT, plugin_context_handler)

    # ── Dynamically registered MCP tools ───────────────────────────────────
    # Each healthy server's tools are namespaced ``mcp__server__tool`` and gated by
    # the same PermissionScope (so deny/ask rules target them by their namespaced
    # name). A degraded server contributes no tools to this router.
    if mcp_manager is not None:
        for definition in mcp_manager.all_tools():
            full_name = definition.name
            router.mcp_tools[full_name] = definition

            # Bind the tool name by default arg: a closure over the loop var would
            # late-bind every handler to the last tool's name.
            async def mcp_guarded(_name: str = full_name, **kwargs: Any) -> str:
                _gate(scope, _name)
                return await mcp_manager.call(_name, kwargs)

            router.register_handler(full_name, mcp_guarded)

    return router
