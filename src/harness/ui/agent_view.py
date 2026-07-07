"""Agent state display component."""

from dataclasses import dataclass
from typing import List, Dict, Optional
from enum import Enum
from rich.table import Table
from rich.text import Text
from .claude_code_style import Styles


class AgentStatus(Enum):
    """Agent execution status."""
    IDLE = "idle"
    RUNNING = "running"
    THINKING = "thinking"
    TOOL_CALLING = "tool_calling"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class Agent:
    """Represents an active agent."""
    name: str
    status: AgentStatus = AgentStatus.IDLE
    tokens_used: int = 0
    tokens_total: int = 0
    iterations: int = 0
    errors: int = 0
    last_update: str = ""
    result: Optional[str] = None


class AgentView:
    """Displays active agents and their status."""

    def __init__(self):
        self.agents: Dict[str, Agent] = {}
        self.active_agent: Optional[str] = None

    def add_agent(self, name: str) -> None:
        """Start tracking an agent."""
        if name not in self.agents:
            self.agents[name] = Agent(name=name)
            self.active_agent = name

    def update_agent(
        self,
        name: str,
        status: AgentStatus,
        tokens_used: int = 0,
        iterations: int = 0,
        last_update: str = "",
    ) -> None:
        """Update agent state."""
        if name not in self.agents:
            self.add_agent(name)

        agent = self.agents[name]
        agent.status = status
        agent.tokens_used = tokens_used
        agent.iterations = iterations
        agent.last_update = last_update

    def set_agent_result(self, name: str, result: str) -> None:
        """Set agent result."""
        if name in self.agents:
            self.agents[name].result = result
            self.agents[name].status = AgentStatus.COMPLETED

    def set_agent_error(self, name: str, error: str) -> None:
        """Set agent error."""
        if name in self.agents:
            self.agents[name].errors += 1
            self.agents[name].status = AgentStatus.ERROR
            self.agents[name].result = f"Error: {error}"

    def remove_agent(self, name: str) -> None:
        """Stop tracking an agent."""
        if name in self.agents:
            del self.agents[name]
            if self.active_agent == name:
                self.active_agent = None

    def render(self) -> Table:
        """Render agents as a Rich table."""
        table = Table(title="Active Agents", show_header=True, header_style=Styles.TITLE)
        table.add_column("Agent", style=Styles.PROMPT)
        table.add_column("Status", style=Styles.INPUT_TEXT)
        table.add_column("Tokens", style=Styles.HINT)
        table.add_column("Iter", style=Styles.HINT)
        table.add_column("Errors", style=Styles.HINT)
        table.add_column("Update", style=Styles.HINT)

        if not self.agents:
            table.add_row("(no active agents)", "", "", "", "", "")
            return table

        for name, agent in self.agents.items():
            status_icons = {
                AgentStatus.IDLE: "⬜",
                AgentStatus.RUNNING: "🟦",
                AgentStatus.THINKING: "🤔",
                AgentStatus.TOOL_CALLING: "🔧",
                AgentStatus.PAUSED: "⏸",
                AgentStatus.COMPLETED: "✅",
                AgentStatus.ERROR: "❌",
            }
            status_icon = status_icons.get(agent.status, "?")
            status_text = f"{status_icon} {agent.status.value}"

            if agent.tokens_total > 0:
                token_text = f"{agent.tokens_used}/{agent.tokens_total}"
            else:
                token_text = str(agent.tokens_used)

            marker = "→ " if self.active_agent == name else "  "

            table.add_row(
                f"{marker}{name}",
                status_text,
                token_text,
                str(agent.iterations),
                str(agent.errors) if agent.errors > 0 else "0",
                agent.last_update[:20] if agent.last_update else "",
            )

        return table

    def get_summary(self) -> str:
        """Get summary text."""
        if not self.agents:
            return "No active agents"

        active = [a for a in self.agents.values() if a.status == AgentStatus.RUNNING]
        completed = [a for a in self.agents.values() if a.status == AgentStatus.COMPLETED]
        errors = [a for a in self.agents.values() if a.status == AgentStatus.ERROR]

        return (
            f"Agents: {len(self.agents)} | "
            f"Running: {len(active)} | "
            f"Done: {len(completed)} | "
            f"Errors: {len(errors)}"
        )
