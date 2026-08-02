"""Session briefing — hard-capped context injection for session continuity."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
import structlog

from harness.persistence.database import get_session
from harness.persistence.models import Session, Task, UserPreference
from harness.core.error_memory import get_top_pitfalls
from sqlalchemy import select, desc

logger = structlog.get_logger(__name__)

BRIEFING_CHAR_BUDGET = 4000  # ~1k tokens at chars//4


@dataclass
class SessionBriefing:
    """Immutable briefing snapshot for a session."""
    session_id: str
    text: str


async def build_briefing(session_id: str, user_id: str, project_root: Path) -> SessionBriefing:
    """Build a hard-capped session briefing for continuity.

    Sections are included whole or dropped entirely; never truncated mid-structure.
    Priority order: continuity header > user preferences > architecture decisions >
    open threads > pitfall pointer.

    Args:
        session_id: Current session ID (for recording context)
        user_id: User identifier (for user_preferences lookup)
        project_root: Project root path (for context)

    Returns:
        SessionBriefing with guaranteed len(text) <= 4000 chars
    """
    async with get_session() as db_session:
        # Section 1: Continuity header (~200 ch)
        sections = []
        prior_sessions = await db_session.execute(
            select(Session)
            .order_by(desc(Session.created_at))
            .limit(2)
        )
        prior = prior_sessions.scalars().all()

        continuity = _render_continuity(prior, user_id)
        sections.append((1, continuity))

        # Section 2: User preferences (~400 ch, cap 12)
        prefs = await db_session.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        all_prefs = prefs.scalars().all()
        preferences = _render_preferences(all_prefs[:12])
        sections.append((2, preferences))

        # Section 3: Architecture decisions (~1200 ch, cap 6)
        if prior and len(prior) > 0:
            # Get last 3 completed tasks from prior session
            tasks = await db_session.execute(
                select(Task)
                .where(Task.session_id == prior[0].session_id, Task.status == "completed")
                .order_by(desc(Task.completed_at))
                .limit(3)
            )
            completed = tasks.scalars().all()
            decisions = _render_decisions(completed)
            sections.append((3, decisions))

        # Section 4: Open threads (~800 ch, cap 4)
        if prior and len(prior) > 0:
            open_tasks = await db_session.execute(
                select(Task)
                .where(
                    Task.session_id == prior[0].session_id,
                    Task.status.in_(["running", "paused", "failed"])
                )
                .order_by(desc(Task.updated_at))
                .limit(4)
            )
            unfinished = open_tasks.scalars().all()
            threads = _render_open_threads(unfinished)
            sections.append((4, threads))

    # Section 5: Pitfall pointer (~250 ch, cap 3)
    pitfalls = await get_top_pitfalls(limit=3)
    pitfall_ptr = _render_pitfall_pointer(pitfalls)
    sections.append((5, pitfall_ptr))

    # Render with budget constraint
    text = _render(sections, BRIEFING_CHAR_BUDGET)
    return SessionBriefing(session_id=session_id, text=text)


def _render_continuity(prior_sessions: list, user_id: str) -> str:
    """Render continuity header from prior sessions."""
    if not prior_sessions:
        return ""

    session = prior_sessions[0]
    unfinished = len([t for t in prior_sessions if hasattr(t, "tasks")])
    status = "interrupted" if session.completed_at is None else "completed"

    return (
        f"Prior session {session.session_id[:8]}: {status} "
        f"({unfinished} unfinished tasks)\n"
    )


def _render_preferences(prefs: list[UserPreference]) -> str:
    """Render user preferences block."""
    if not prefs:
        return ""

    lines = ["## User Preferences", ""]
    for pref in prefs[:12]:
        lines.append(f"- {pref.key}: {pref.value}")

    return "\n".join(lines)


def _render_decisions(tasks: list[Task]) -> str:
    """Render architecture decisions from task decision_log."""
    if not tasks:
        return ""

    lines = ["## Architecture Decisions", ""]
    for task in tasks[:6]:
        if task.decision_log:
            lines.append(f"- {task.description[:50]}: {task.decision_log[:100]}")

    return "\n".join(lines) if len(lines) > 2 else ""


def _render_open_threads(tasks: list[Task]) -> str:
    """Render open/paused tasks as unfinished threads."""
    if not tasks:
        return ""

    lines = ["## Open Threads", ""]
    for task in tasks[:4]:
        status = task.status.upper()
        error = f" — {task.error[:60]}" if task.error else ""
        lines.append(f"- [{status}] {task.description[:60]}{error}")

    return "\n".join(lines) if len(lines) > 2 else ""


def _render_pitfall_pointer(pitfalls: list) -> str:
    """Render pitfall pointer with Tier-2 handoff instruction."""
    if not pitfalls:
        return "No known pitfalls. Use MemorySearch('pitfalls') to explore past errors."

    lines = ["## Common Pitfalls", ""]
    for pitfall in pitfalls[:3]:
        sig = getattr(pitfall, "signature", "Unknown")[:40]
        resolution = (getattr(pitfall, "resolution", None) or "")[:60]
        lines.append(f"- {sig}: {resolution}")

    lines.append("")
    lines.append("Call MemorySearch with source='errors' for full context, or for pitfalls not listed.")

    return "\n".join(lines)


def _render(sections: list[tuple[int, str]], budget: int) -> str:
    """Assemble sections in priority order, stopping before budget overflow.

    Sections are included whole or dropped entirely, never truncated mid-structure.

    Args:
        sections: List of (priority, text) tuples (1=highest priority)
        budget: Character budget (e.g., 4000)

    Returns:
        Assembled text with len(result) <= budget
    """
    # Sort by priority (ascending)
    sections_sorted = sorted(sections, key=lambda x: x[0])

    result = []
    current_len = 0

    for priority, text in sections_sorted:
        if not text:
            continue
        if current_len + len(text) + 2 <= budget:  # +2 for newlines
            result.append(text)
            current_len += len(text) + 2
        else:
            # Section would exceed budget, drop it
            logger.debug(f"Briefing budget exceeded, dropping priority {priority} section")
            break

    assembled = "\n\n".join(result)
    if len(assembled) > budget:
        logger.warning(f"Briefing exceeded budget: {len(assembled)} > {budget}")

    return assembled
