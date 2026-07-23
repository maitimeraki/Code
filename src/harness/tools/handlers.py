"""Tool handlers for common operations."""

import asyncio
import json
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


async def bash_exec(command: str, timeout: int = 300) -> str:
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


# ── Interaction handlers ──────────────────────────────────────────────────


async def ask_user_question(
    questions: list[dict] | None = None,
    multi_select: bool = False,
    preview: dict | None = None,
) -> str:
    """Ask the user a multiple-choice question.

    Delegates to the approval/UI callback when available; otherwise returns
    a structured response so the LLM can proceed on its own judgment.
    """
    import json
    payload = {
        "questions": questions or [],
        "multi_select": multi_select,
        "preview": preview,
    }
    # ponytail: approval_callback wired by factory when available
    return json.dumps({"asked": True, "payload": payload, "pending": True})


async def execute_skill(skill: str, args: str = "") -> str:
    """Execute a named skill.

    Delegates to the skill_registry wired by the factory.
    Without a registry, returns a structured error so the LLM adapts.
    """
    import json
    return json.dumps({"skill": skill, "args": args, "executed": False, "reason": "Skill registry not available in this scope"})


# ── Task management handlers ──────────────────────────────────────────────


async def task_create(
    subject: str,
    description: str = "",
    active_form: str = "",
    metadata: dict | None = None,
) -> str:
    """Create a new task."""
    import json
    return json.dumps({"created": True, "subject": subject, "id": "pending"})


async def task_get(task_id: str) -> str:
    """Retrieve task details by ID."""
    import json
    return json.dumps({"task_id": task_id, "found": False, "reason": "Task manager not available in this scope"})


async def task_list(status: str | None = None) -> str:
    """List tasks, optionally filtered by status."""
    import json
    return json.dumps({"tasks": [], "filter": status})


async def task_output(task_id: str, block: bool = True, timeout: int = 60000) -> str:
    """Retrieve output from a background task."""
    import json
    return json.dumps({"task_id": task_id, "output": None, "reason": "Task manager not available in this scope"})


async def task_stop(task_id: str) -> str:
    """Stop a running background task."""
    import json
    return json.dumps({"task_id": task_id, "stopped": False, "reason": "Task manager not available in this scope"})


async def task_update(
    task_id: str,
    status: str | None = None,
    subject: str | None = None,
    description: str | None = None,
    metadata: dict | None = None,
) -> str:
    """Update a task's status, details, or metadata."""
    import json
    return json.dumps({"task_id": task_id, "updated": True, "status": status})


# ── Spawn agent handler factory ───────────────────────────────────────────


def make_spawn_agent_handler(
    agent_registry: "AgentRegistry",
    spawn_fn: Callable[["AgentConfig"], Awaitable[Any]],
    parent_config: "AgentConfig",
) -> Callable[[str, str], Awaitable[str]]:
    """Create a spawn_agent handler with closure over registry and spawner context."""
    from harness.orchestration.agent import MAX_SPAWN_DEPTH

    async def spawn_agent(
        name: str,
        task: str,
        working_dir: str = None,
        success_criteria: str = None,
        non_goals: list = None,
    ) -> str:
        """Delegate a task to a named sub-agent in an isolated context."""
        if parent_config.spawn_depth >= MAX_SPAWN_DEPTH:
            raise PermissionError(
                f"Max agent spawn depth ({MAX_SPAWN_DEPTH}) reached; cannot spawn '{name}'"
            )

        available = {a.name for a in agent_registry.list_agents()}
        if name not in available:
            raise ValueError(f"Unknown agent '{name}'. Available: {', '.join(sorted(available))}")

        system_prompt = agent_registry.get_full(name)

        # Minimal, relevant context: the child gets only its self-contained task
        # plus the harness's top known pitfalls (not orchestrator history/roster).
        # Best-effort — a memory hiccup must never block delegation.
        child_task = task
        try:
            from harness.core.error_memory import get_top_pitfalls

            pitfalls = await get_top_pitfalls(limit=3)
            if pitfalls:
                lines = "\n".join(
                    f"- {p.signature} (seen {p.occurrence_count}x)"
                    + (f" — fix: {p.resolution}" if p.resolution else "")
                    for p in pitfalls
                )
                child_task = f"{task}\n\n<known_pitfalls>\n{lines}\n</known_pitfalls>"
        except Exception:
            pass

        # Clamp the child's filesystem scope to working_dir when supplied. This is
        # the load-bearing half of the pin: two same-type agents in different
        # folders are genuinely isolated because PathGuard denies cross-dir access.
        child_scope = parent_config.permission_scope.without_agent_spawn()
        if working_dir:
            child_scope = child_scope.narrowed_to(working_dir)

        # Sub-agents are strict executors: no roster, no skills, no re-delegation.
        # The orchestrator owns decomposition and hands each child a self-contained
        # task, pinned to an objective + success criteria + non-goals + scope.
        child_config = AgentConfig(
            agent_type=name,
            task_description=child_task,
            system_prompt=system_prompt,
            project_context=parent_config.project_context,
            is_orchestrator=False,
            agent_registry=None,
            skill_registry=None,
            permission_scope=child_scope,
            spawn_depth=parent_config.spawn_depth + 1,
            model=parent_config.model,
            max_tool_iterations=parent_config.max_tool_iterations,
            working_dir=working_dir,
            success_criteria=success_criteria,
            non_goals=non_goals,
        )

        result = await spawn_fn(child_config)

        # Structured return so the orchestrator ingests a capsule, not a transcript.
        status = result.status.value if hasattr(result.status, "value") else str(result.status)
        payload = {
            "status": status,
            "summary": (result.output or "")[:500] if result.success else (result.error or "failed"),
            "artifacts": getattr(result, "artifact_refs", []) or [],
        }
        return json.dumps(payload)

    return spawn_agent
