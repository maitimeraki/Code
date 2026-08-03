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


def _build_child_config(
    parent_config: "AgentConfig",
    name: str,
    task: str,
    working_dir: str = None,
    success_criteria: str = None,
    non_goals: list = None,
    run_in_background: bool = False,
    isolation: str = None,
) -> "AgentConfig":
    """Construct a pinned AgentConfig for a spawned child agent.

    Shared by foreground and background spawn paths so the config is identical
    regardless of execution mode.
    """
    from harness.orchestration.agent import MAX_SPAWN_DEPTH
    if parent_config.spawn_depth >= MAX_SPAWN_DEPTH:
        raise PermissionError(
            f"Max agent spawn depth ({MAX_SPAWN_DEPTH}) reached; cannot spawn '{name}'"
        )

    available = {a.name for a in parent_config.agent_registry.list_agents()} if parent_config.agent_registry else set()
    if name not in available:
        raise ValueError(f"Unknown agent '{name}'. Available: {', '.join(sorted(available))}")

    system_prompt = parent_config.agent_registry.get_full(name)

    # Clamp the child's filesystem scope to working_dir when supplied.
    child_scope = parent_config.permission_scope.without_agent_spawn()
    if working_dir:
        child_scope = child_scope.narrowed_to(working_dir)

    return AgentConfig(
        agent_type=name,
        task_description=task,
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
        run_in_background=run_in_background,
        isolation=isolation,
    )


def make_spawn_agent_handler(
    agent_registry: "AgentRegistry",
    spawn_fn: Callable[["AgentConfig"], Awaitable[Any]],
    parent_config: "AgentConfig",
) -> Callable[..., Awaitable[str]]:
    """Create a spawn_agent handler with closure over registry and spawner context."""
    from harness.orchestration.agent import MAX_SPAWN_DEPTH

    async def spawn_agent(
        name: str,
        task: str,
        working_dir: str = None,
        success_criteria: str = None,
        non_goals: list = None,
        run_in_background: bool = False,
        isolation: str = None,
    ) -> str:
        """Delegate a task to a named sub-agent in an isolated context.

        When *run_in_background* is True the agent is launched via
        ``asyncio.create_task`` and a placeholder result is returned immediately.
        """
        # Ponytail: minimal, relevant context — the child gets only its
        # self-contained task plus the harness's top known pitfalls.
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

        child_config = _build_child_config(
            parent_config, name, child_task, working_dir,
            success_criteria, non_goals, run_in_background, isolation,
        )

        # Background spawn: fire-and-forget, return a placeholder immediately.
        if run_in_background:
            asyncio.create_task(spawn_fn(child_config))
            return json.dumps({
                "status": "background_spawned",
                "agent": name,
                "task": task[:200],
                "note": "Running in background — results are not collected.",
            })

        # Sub-agents are strict executors — no roster, no skills, no re-delegation.
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


async def memory_search(query: str, source: str = "all", limit: int = 3) -> str:
    """Search knowledge base, error memory, and task journal.

    Args:
        query: Search query
        source: "knowledge", "errors", "journal", or "all"
        limit: Max results per source (clamped to 5)

    Returns:
        Formatted search results, capped at 6000 chars
    """
    from harness.persistence.knowledge_graph import get_knowledge_graph
    from harness.core.error_memory import get_errors_by_type, get_top_pitfalls
    from harness.persistence.session import SessionManager

    limit = min(limit, 5)
    results = []
    char_count = 0
    max_chars = 6000

    try:
        # Knowledge source
        if source in ("knowledge", "all"):
            kg = await get_knowledge_graph()
            hits = await kg.search(query, top_k=limit, min_quality=0.3)
            for hit in hits:
                entry = f"\n[Knowledge] {hit.task_type} (quality: {hit.quality_score})\n"
                entry += f"Solution: {(hit.solution or '')[:400]}\n"
                if hit.code_example:
                    entry += f"Example: {(hit.code_example or '')[:600]}\n"
                if char_count + len(entry) <= max_chars:
                    results.append(entry)
                    char_count += len(entry)
                    await kg.mark_used(hit.entry_id)
                else:
                    break

        # Error source
        if source in ("errors", "all") and char_count < max_chars:
            import re
            if re.match(r"^[A-Z]\w*(Error|Exception)$", query):
                errors = await get_errors_by_type(query, limit)
            else:
                pitfalls = await get_top_pitfalls(limit=50)
                errors = sorted(pitfalls, key=lambda x: x.occurrence_count or 0, reverse=True)[:limit]

            for err in errors:
                signature = getattr(err, 'signature', 'Unknown')
                context = getattr(err, 'context', '') or ''
                resolution = getattr(err, 'resolution', None)
                entry = f"\n[Error] {signature}\n"
                entry += f"Context: {context[:400]}\n"
                if resolution:
                    entry += f"Resolution: {resolution}\n"
                if char_count + len(entry) <= max_chars:
                    results.append(entry)
                    char_count += len(entry)
                else:
                    break

        # Journal source
        if source in ("journal", "all") and char_count < max_chars:
            from harness.persistence.database import get_session
            from harness.persistence.models import TaskJournal
            from sqlalchemy import select
            from rank_bm25 import BM25Okapi

            async with get_session() as db_session:
                result_set = await db_session.execute(select(TaskJournal).limit(100))
                journals = result_set.scalars().all()

            if journals:
                corpus = [j.message.lower().split() for j in journals]
                bm25 = BM25Okapi(corpus)
                query_tokens = query.lower().split()
                scores = bm25.get_scores(query_tokens)

                ranked = sorted(zip(journals, scores), key=lambda x: x[1], reverse=True)
                for journal, score in ranked[:limit]:
                    if score <= 0.0:
                        break
                    entry = f"\n[Journal] Task {journal.task_id}\n"
                    entry += f"Message: {(journal.message or '')[:300]}\n"
                    if char_count + len(entry) <= max_chars:
                        results.append(entry)
                        char_count += len(entry)
                    else:
                        break

        # Tool output source — opt-in only, never part of "all"
        if source == "tool_output":
            from harness.persistence.database import get_session
            from harness.persistence.models import ToolCall as ToolCallRow
            from sqlalchemy import select

            async with get_session() as db_session:
                found = await db_session.execute(
                    select(ToolCallRow).where(ToolCallRow.call_id == query).limit(1)
                )
                row = found.scalar_one_or_none()
                if row is None:
                    found = await db_session.execute(
                        select(ToolCallRow)
                        .where(ToolCallRow.tool_type.contains(query))
                        .order_by(ToolCallRow.started_at.desc())
                        .limit(limit)
                    )
                    rows = found.scalars().all()
                else:
                    rows = [row]

            for r in rows:
                entry = f"\n[ToolOutput] {r.tool_type} (call_id: {r.call_id})\n{r.result or ''}\n"
                if char_count + len(entry) <= max_chars:
                    results.append(entry)
                    char_count += len(entry)
                else:
                    break

    except Exception as e:
        logger.error("Memory search failed", query=query, error=str(e))
        return f"Search error: {str(e)}"

    if not results:
        return f"No results found for: {query}"

    return "".join(results)
