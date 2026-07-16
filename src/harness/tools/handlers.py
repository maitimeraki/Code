"""Tool handlers for common operations."""

import asyncio
from pathlib import Path
from typing import Optional, Callable, Awaitable, Any
import structlog

logger = structlog.get_logger(__name__)


async def read_file(path: str) -> str:
    """Read file contents."""
    try:
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        content = file_path.read_text(encoding="utf-8")
        logger.info(f"Read file: {path}", size=len(content))
        return content

    except Exception as e:
        logger.error(f"Read failed: {path}", error=str(e))
        raise


async def write_file(path: str, content: str) -> str:
    """Write content to file."""
    try:
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        logger.info(f"Wrote file: {path}", size=len(content))
        return f"Wrote {len(content)} bytes to {path}"

    except Exception as e:
        logger.error(f"Write failed: {path}", error=str(e))
        raise


async def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Edit file by replacing text."""
    try:
        file_path = Path(path)
        content = file_path.read_text(encoding="utf-8")

        if old_text not in content:
            raise ValueError(f"Text not found in {path}")

        new_content = content.replace(old_text, new_text, 1)
        file_path.write_text(new_content, encoding="utf-8")
        logger.info(f"Edited file: {path}")
        return f"Successfully edited {path}"

    except Exception as e:
        logger.error(f"Edit failed: {path}", error=str(e))
        raise


async def bash_exec(command: str, timeout: int = 30) -> str:
    """Execute bash command."""
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"Command timed out after {timeout}s: {command}")

        output = stdout.decode(errors="replace")
        error = stderr.decode(errors="replace")

        if stderr and proc.returncode != 0:
            logger.warning(f"Command failed: {command}", returncode=proc.returncode)
            return error

        logger.info(f"Executed command: {command}")
        return output

    except Exception as e:
        logger.error(f"Bash exec failed: {command}", error=str(e))
        raise


async def grep_search(pattern: str, path: str = ".") -> str:
    """Search for pattern in files using grep directly (no shell)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "grep", "-rn", pattern, path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"Grep search timed out after 10s: {pattern}")

        output = stdout.decode(errors="replace")
        error = stderr.decode(errors="replace")

        if stderr and proc.returncode != 0:
            logger.warning(f"Grep search failed: {pattern}", returncode=proc.returncode)
            return error

        logger.info(f"Grep search: {pattern}")
        return output

    except Exception as e:
        logger.error(f"Grep failed: {pattern}", error=str(e))
        raise


async def glob_search(pattern: str, path: str = ".") -> str:
    """Find files matching glob pattern."""
    try:
        from pathlib import Path
        base_path = Path(path)
        matches = list(base_path.glob(pattern))
        result = "\n".join(str(m) for m in matches)
        logger.info(f"Glob search: {pattern}", matches=len(matches))
        return result

    except Exception as e:
        logger.error(f"Glob failed: {pattern}", error=str(e))
        raise
from harness.registry.definitions import AgentRegistry
from harness.orchestration.agent import AgentConfig
# from harness.app import AgentRegistry, AgentConfig
def make_spawn_agent_handler(
    agent_registry: "AgentRegistry",
    spawn_fn: Callable[["AgentConfig"], Awaitable[Any]],
    parent_config: "AgentConfig",
) -> Callable[[str, str], Awaitable[str]]:
    """Create a spawn_agent handler with closure over registry and spawner context."""
    from harness.orchestration.agent import MAX_SPAWN_DEPTH

    async def spawn_agent(name: str, task: str) -> str:
        """Delegate a task to a named sub-agent in an isolated context."""
        if parent_config.spawn_depth >= MAX_SPAWN_DEPTH:
            raise PermissionError(
                f"Max agent spawn depth ({MAX_SPAWN_DEPTH}) reached; cannot spawn '{name}'"
            )

        available = {a.name for a in agent_registry.list_agents()}
        if name not in available:
            raise ValueError(f"Unknown agent '{name}'. Available: {', '.join(sorted(available))}")

        system_prompt = agent_registry.get_full(name)

        # Sub-agents are strict executors: no roster, no skills, no re-delegation.
        # The orchestrator owns decomposition and hands each child a self-contained task.
        child_config = AgentConfig(
            agent_type=name,
            task_description=task,
            system_prompt=system_prompt,
            project_context=parent_config.project_context,
            is_orchestrator=False,
            agent_registry=None,
            skill_registry=None,
            permission_scope=parent_config.permission_scope.without_agent_spawn(),
            spawn_depth=parent_config.spawn_depth + 1,
            model=parent_config.model,
            max_tool_iterations=parent_config.max_tool_iterations,
        )

        result = await spawn_fn(child_config)
        if not result.success:
            return f"Sub-agent '{name}' failed: {result.error}"
        return result.output or "(sub-agent produced no output)"

    return spawn_agent
