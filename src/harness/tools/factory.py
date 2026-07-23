"""Factory for building scoped tool routers with permission enforcement."""

from typing import Callable, Any, Optional

from .models import ToolType
from .router import ToolRouter
from .permissions import PermissionScope, PathGuard, CommandGuard
from . import handlers



def build_scoped_router(
    scope: PermissionScope,
    agent_registry: Any = None,
    spawn_fn: Callable = None,
    parent_config: Any = None,
    ask_user_question_callback: Optional[Callable] = None,
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
        allowed, mode = scope.check("Read", kwargs.get("path", ""))
        if not allowed:
            raise PermissionError("Read access is not allowed in this scope")
        path = kwargs.get("path")
        if path:
            PathGuard.resolve_and_check(path, scope, "read")
        return await handlers.read_file(**kwargs)

    router.register_handler(ToolType.READ, read_file_guarded)

    # WRITE — file write with tool permission check + path guard
    async def write_file_guarded(**kwargs: Any) -> str:
        allowed, mode = scope.check("Write", kwargs.get("path", ""))
        if not allowed:
            raise PermissionError("Write access is not allowed in this scope")
        path = kwargs.get("path")
        if path:
            PathGuard.resolve_and_check(path, scope, "write")
        return await handlers.write_file(**kwargs)

    router.register_handler(ToolType.WRITE, write_file_guarded)

    # EDIT — file edit with tool permission check + path guard
    async def edit_file_guarded(**kwargs: Any) -> str:
        allowed, mode = scope.check("Edit", kwargs.get("path", ""))
        if not allowed:
            raise PermissionError("Edit access is not allowed in this scope")
        path = kwargs.get("path")
        if path:
            PathGuard.resolve_and_check(path, scope, "write")
        return await handlers.edit_file(**kwargs)

    router.register_handler(ToolType.EDIT, edit_file_guarded)

    # BASH — shell execution with tool permission check + command guard
    async def bash_exec_guarded(**kwargs: Any) -> str:
        command = kwargs.get("command", "")
        allowed, mode = scope.check("Bash", command)
        if not allowed:
            raise PermissionError("Bash execution is not allowed in this scope")
        if command:
            CommandGuard.check(command, scope)
        return await handlers.bash_exec(**kwargs)

    router.register_handler(ToolType.BASH, bash_exec_guarded)

    # GREP — file search with tool permission check + path guard
    async def grep_search_guarded(**kwargs: Any) -> str:
        allowed, mode = scope.check("Grep", kwargs.get("path", "."))
        if not allowed:
            raise PermissionError("Grep access is not allowed in this scope")
        path = kwargs.get("path", ".")
        PathGuard.resolve_and_check(path, scope, "read")
        return await handlers.grep_search(**kwargs)

    router.register_handler(ToolType.GREP, grep_search_guarded)

    # GLOB — glob pattern matching with tool permission check + path guard
    async def glob_search_guarded(**kwargs: Any) -> str:
        allowed, mode = scope.check("Glob", kwargs.get("path", "."))
        if not allowed:
            raise PermissionError("Glob access is not allowed in this scope")
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
            allowed, mode = scope.check("spawn_agent")
            if not allowed:
                raise PermissionError("Agent spawning is not allowed in this scope")
            spawn_agent_handler = handlers.make_spawn_agent_handler(
                agent_registry, spawn_fn, parent_config
            )
            return await spawn_agent_handler(**kwargs)

        router.register_handler(ToolType.SPAWN_AGENT, spawn_agent_guarded)

    # ── AskUserQuestion — interaction tool with permission check ────────────
    async def ask_user_question_guarded(**kwargs: Any) -> str:
        allowed, mode = scope.check("AskUserQuestion")
        if not allowed:
            raise PermissionError("AskUserQuestion is not allowed in this scope")
        if ask_user_question_callback:
            return await ask_user_question_callback(**kwargs)
        return await handlers.ask_user_question(**kwargs)

    router.register_handler(ToolType.ASK_USER_QUESTION, ask_user_question_guarded)

    # ── Skill — skill execution with permission check ───────────────────────
    async def execute_skill_guarded(**kwargs: Any) -> str:
        allowed, mode = scope.check("Skill")
        if not allowed:
            raise PermissionError("Skill execution is not allowed in this scope")
        return await handlers.execute_skill(**kwargs)

    router.register_handler(ToolType.SKILL, execute_skill_guarded)

    # ── Task management tools with permission check ─────────────────────────
    async def task_create_guarded(**kwargs: Any) -> str:
        allowed, mode = scope.check("TaskCreate")
        if not allowed:
            raise PermissionError("TaskCreate is not allowed in this scope")
        return await handlers.task_create(**kwargs)

    router.register_handler(ToolType.TASK_CREATE, task_create_guarded)

    async def task_get_guarded(**kwargs: Any) -> str:
        allowed, mode = scope.check("TaskGet")
        if not allowed:
            raise PermissionError("TaskGet is not allowed in this scope")
        return await handlers.task_get(**kwargs)

    router.register_handler(ToolType.TASK_GET, task_get_guarded)

    async def task_list_guarded(**kwargs: Any) -> str:
        allowed, mode = scope.check("TaskList")
        if not allowed:
            raise PermissionError("TaskList is not allowed in this scope")
        return await handlers.task_list(**kwargs)

    router.register_handler(ToolType.TASK_LIST, task_list_guarded)

    async def task_output_guarded(**kwargs: Any) -> str:
        allowed, mode = scope.check("TaskOutput")
        if not allowed:
            raise PermissionError("TaskOutput is not allowed in this scope")
        return await handlers.task_output(**kwargs)

    router.register_handler(ToolType.TASK_OUTPUT, task_output_guarded)

    async def task_stop_guarded(**kwargs: Any) -> str:
        allowed, mode = scope.check("TaskStop")
        if not allowed:
            raise PermissionError("TaskStop is not allowed in this scope")
        return await handlers.task_stop(**kwargs)

    router.register_handler(ToolType.TASK_STOP, task_stop_guarded)

    async def task_update_guarded(**kwargs: Any) -> str:
        allowed, mode = scope.check("TaskUpdate")
        if not allowed:
            raise PermissionError("TaskUpdate is not allowed in this scope")
        return await handlers.task_update(**kwargs)

    router.register_handler(ToolType.TASK_UPDATE, task_update_guarded)

    return router
