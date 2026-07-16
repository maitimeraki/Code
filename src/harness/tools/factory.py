"""Factory for building scoped tool routers with permission enforcement."""

from typing import Callable, Any

from .models import ToolType
from .router import ToolRouter
from .permissions import PermissionScope, PathGuard, CommandGuard
from . import handlers



def build_scoped_router(
    scope: PermissionScope,
    agent_registry: Any = None,
    spawn_fn: Callable = None,
    parent_config: Any = None,
) -> ToolRouter:
    """Build a ToolRouter with permission-guarded handlers.

    Each handler is wrapped with its corresponding permission checks:
    - File operations: PathGuard for allowed_paths
    - Bash: CommandGuard for bash allowlist/denylist
    - Write operations: scope.allow_write gate

    Args:
        scope: The PermissionScope defining what this router can do.
        agent_registry: Optional agent registry for spawn_agent handler.
        spawn_fn: Optional spawn function for spawning nested agents.
        parent_config: Optional parent agent config for nested spawns.

    Returns:
        A ToolRouter with handlers registered and guarded.
    """
    router = ToolRouter()

    # READ — file read with path guard
    async def read_file_guarded(**kwargs: Any) -> str:
        path = kwargs.get("path")
        if path:
            PathGuard.resolve_and_check(path, scope, "read")
        return await handlers.read_file(**kwargs)

    router.register_handler(ToolType.READ, read_file_guarded)

    # WRITE — file write with write permission gate + path guard
    async def write_file_guarded(**kwargs: Any) -> str:
        if not scope.allow_write:
            raise PermissionError("Write access is not allowed in this scope")
        path = kwargs.get("path")
        if path:
            PathGuard.resolve_and_check(path, scope, "write")
        return await handlers.write_file(**kwargs)

    router.register_handler(ToolType.WRITE, write_file_guarded)

    # EDIT — file edit with path guard (also a write operation)
    async def edit_file_guarded(**kwargs: Any) -> str:
        if not scope.allow_write:
            raise PermissionError("Write access is not allowed in this scope")
        path = kwargs.get("path")
        if path:
            PathGuard.resolve_and_check(path, scope, "write")
        return await handlers.edit_file(**kwargs)

    router.register_handler(ToolType.EDIT, edit_file_guarded)

    # BASH — shell execution with bash permission gate + command guard
    async def bash_exec_guarded(**kwargs: Any) -> str:
        if not scope.allow_bash:
            raise PermissionError("Bash execution is not allowed in this scope")
        command = kwargs.get("command")
        if command:
            CommandGuard.check(command, scope)
        return await handlers.bash_exec(**kwargs)

    router.register_handler(ToolType.BASH, bash_exec_guarded)

    # GREP — file search with path guard
    async def grep_search_guarded(**kwargs: Any) -> str:
        path = kwargs.get("path", ".")
        PathGuard.resolve_and_check(path, scope, "read")
        return await handlers.grep_search(**kwargs)

    router.register_handler(ToolType.GREP, grep_search_guarded)

    # GLOB — glob pattern matching with path guard
    async def glob_search_guarded(**kwargs: Any) -> str:
        path = kwargs.get("path", ".")
        PathGuard.resolve_and_check(path, scope, "read")
        return await handlers.glob_search(**kwargs)

    router.register_handler(ToolType.GLOB, glob_search_guarded)
    

    # SPAWN_AGENT — agent spawning with permission gate (only if scope allows AND params supplied)
    if (
        scope.allow_agent_spawn
        and agent_registry is not None
        and spawn_fn is not None
        and parent_config is not None
    ):
        async def spawn_agent_guarded(**kwargs: Any) -> str:
            if not scope.allow_agent_spawn:
                raise PermissionError("Agent spawning is not allowed in this scope")
            spawn_agent_handler = handlers.make_spawn_agent_handler(
                agent_registry, spawn_fn, parent_config
            )
            return await spawn_agent_handler(**kwargs)

        router.register_handler(ToolType.SPAWN_AGENT, spawn_agent_guarded)

    return router
