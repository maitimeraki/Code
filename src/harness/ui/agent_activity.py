"""Live activity tracker for parallel sub-agents.

When the main orchestrator delegates to several sub-agents at once (concurrent
``spawn_agent`` calls), their tool calls otherwise interleave into one flat
scrollback and become impossible to tell apart. This component keeps a separate,
live card per running sub-agent — keyed by a unique ``agent_id`` so two agents of
the same name don't collide — showing each one's status, its *current* tool call,
and a step counter. Finished agents drop out of the live view after a short grace
period, so the panel always reflects "what is running right now".
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

from rich.columns import Columns
from rich.panel import Panel
from rich.text import Text
from rich.console import Group

from .claude_code_style import Colors, Styles


# Statuses that mean the agent is no longer doing work.
_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}

# Per-status glyph + color for the card header.
_STATUS_STYLE = {
    "RUNNING": ("🔄", Colors.AGENT_GOLD),
    "THINKING": ("🧠", Colors.AGENT_GOLD),
    "TOOL_CALLING": ("⚙", Colors.TOOL_CYAN),
    "COMPLETED": ("✓", Colors.SUCCESS_GREEN),
    "FAILED": ("✗", Colors.ERROR_RED),
    "CANCELLED": ("⊘", Colors.TEXT_DIM),
}

# Distinct border palette so adjacent parallel agents are visually separable.
_BORDER_PALETTE = [
    Colors.AGENT_GOLD,
    Colors.ACCENT_PURPLE,
    Colors.TOOL_CYAN,
    Colors.ACCENT_BLUE,
    Colors.SUCCESS_GREEN,
    Colors.WARNING_YELLOW,
]


@dataclass
class AgentActivity:
    """Live state of one delegated sub-agent."""
    agent_id: str
    name: str
    depth: int = 1
    status: str = "RUNNING"
    task: str = ""
    current_tool: str = ""       # e.g. "read_file(path=…)"
    step: int = 0                # number of tool calls issued so far
    color_index: int = 0         # stable index into _BORDER_PALETTE
    finished_at: Optional[datetime] = None


class AgentActivityTracker:
    """Tracks concurrent sub-agents and renders them as side-by-side cards.

    The tracker is fed the same stream events as the main panel, but only reacts
    to those attributed to a sub-agent (``depth >= 1``). Orchestrator-level events
    (depth 0) are left for the main pipeline and ignored here.
    """

    def __init__(self, keep_finished_frames: int = 20):
        # Ordered so cards keep a stable left-to-right position as they appear.
        self.agents: "OrderedDict[str, AgentActivity]" = OrderedDict()
        self._next_color = 0
        # How many render frames a finished card lingers before being dropped.
        self.keep_finished_frames = keep_finished_frames
        self._finished_frames: dict[str, int] = {}

    # ---- event intake -------------------------------------------------

    def _ensure(self, agent_id: str, name: str, depth: int) -> AgentActivity:
        activity = self.agents.get(agent_id)
        if activity is None:
            activity = AgentActivity(
                agent_id=agent_id,
                name=name,
                depth=depth,
                color_index=self._next_color % len(_BORDER_PALETTE),
            )
            self._next_color += 1
            self.agents[agent_id] = activity
        return activity

    def on_status(self, agent_id: str, name: str, status: str, detail: str = "", depth: int = 1) -> None:
        """Handle an ``agent_status`` event for a sub-agent."""
        if not agent_id:
            return
        activity = self._ensure(agent_id, name, depth)
        activity.status = status
        if status == "RUNNING" and detail and not activity.task:
            activity.task = detail
        if status in _TERMINAL:
            activity.finished_at = datetime.now()
            if detail:
                activity.task = activity.task or detail
            self._finished_frames.setdefault(agent_id, 0)

    def on_tool(
        self,
        agent_id: str,
        name: str,
        tool_name: str,
        args: Optional[dict] = None,
        is_result: bool = False,
        depth: int = 1,
    ) -> None:
        """Handle a ``tool`` event for a sub-agent.

        A call (``is_result=False``) advances the step counter and becomes the
        card's *current* tool. A result leaves the step counter alone (it just
        confirms the in-flight call finished).
        """
        if not agent_id:
            return
        activity = self._ensure(agent_id, name, depth)
        if is_result:
            return
        activity.step += 1
        activity.status = "TOOL_CALLING"
        activity.current_tool = self._format_tool(tool_name, args)

    @staticmethod
    def _format_tool(tool_name: str, args: Optional[dict]) -> str:
        """Compact one-line rendering of the current tool call."""
        if not args:
            return f"{tool_name}()"
        # Show the most informative single argument to keep the card narrow.
        for key in ("path", "pattern", "command", "name", "query"):
            if key in args and args[key]:
                val = str(args[key])
                if len(val) > 40:
                    val = val[:40] + "…"
                return f"{tool_name}({key}={val})"
        first = next(iter(args))
        return f"{tool_name}({first}=…)"

    def has_activity(self) -> bool:
        """True if any sub-agent card should currently be shown."""
        return bool(self.agents)

    # ---- rendering ----------------------------------------------------

    def _render_card(self, activity: AgentActivity) -> Panel:
        icon, color = _STATUS_STYLE.get(activity.status, ("•", Colors.TEXT_PRIMARY))
        border = _BORDER_PALETTE[activity.color_index]

        header = Text()
        header.append(f"{icon} ", style=f"bold {color}")
        header.append(activity.name, style="bold")
        header.append(f"  #{activity.agent_id}", style=Styles.HINT)

        status_line = Text()
        status_line.append("status: ", style=Styles.HINT)
        status_line.append(activity.status.lower(), style=color)
        status_line.append(f"   step {activity.step}", style=Styles.HINT)

        tool_line = Text()
        tool_line.append("→ ", style=f"bold {Colors.TOOL_CYAN}")
        if activity.status in _TERMINAL:
            tool_line.append("done", style=Styles.HINT)
        elif activity.current_tool:
            tool_line.append(activity.current_tool, style=Styles.INPUT_TEXT)
        else:
            tool_line.append("thinking…", style=Styles.AGENT_THINKING)

        if activity.task:
            task_line = Text(activity.task[:60], style=Styles.HINT)
            body = Group(header, status_line, tool_line, task_line)
        else:
            body = Group(header, status_line, tool_line)

        return Panel(
            body,
            border_style=border,
            padding=(0, 1),
            title=f"[{border}]sub-agent[/{border}]",
            title_align="left",
        )

    def render(self) -> Optional[Panel]:
        """Render all live sub-agent cards side by side, or None if idle.

        Also ages out finished cards: each render frame increments a counter for
        terminal agents and drops them once the grace period elapses.
        """
        self._age_finished()
        if not self.agents:
            return None

        cards = [self._render_card(a) for a in self.agents.values()]
        running = sum(1 for a in self.agents.values() if a.status not in _TERMINAL)
        title = (
            f"[bold {Colors.AGENT_GOLD}]Parallel Sub-Agents[/] "
            f"[dim]({running} running / {len(self.agents)} shown)[/dim]"
        )
        return Panel(
            Columns(cards, expand=True, equal=True),
            title=title,
            border_style=Styles.BORDER,
            padding=(0, 0),
        )

    def _age_finished(self) -> None:
        """Drop finished cards after keep_finished_frames render passes."""
        expired = []
        for agent_id in list(self._finished_frames.keys()):
            self._finished_frames[agent_id] += 1
            if self._finished_frames[agent_id] >= self.keep_finished_frames:
                expired.append(agent_id)
        for agent_id in expired:
            self.agents.pop(agent_id, None)
            self._finished_frames.pop(agent_id, None)
