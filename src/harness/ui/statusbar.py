"""Status bar component for terminal UI."""

from dataclasses import dataclass
from rich.text import Text
from rich.console import Console
from .claude_code_style import Styles


@dataclass
class StatusInfo:
    """Status information displayed in status bar."""
    project_name: str = "Agent Harness"
    branch: str = "main"
    has_changes: bool = False
    status: str = "ready"
    version: str = "0.1.0"
    connected: bool = True


class StatusBar:
    """Renders Claude Code-style status bar."""

    def __init__(self, console: Console):
        self.console = console
        self.status_info = StatusInfo()

    def update(self, info: StatusInfo) -> None:
        """Update status information."""
        self.status_info = info

    def render(self) -> Text:
        """Render status bar with semantic status indicator and connection status.

        Professional one-liner with icon, project metadata, and connection state.
        Status colors: ready=green, executing=yellow, error=red, paused=dim.
        """
        status_icons = {
            "ready": "✓",
            "executing": "⟳",
            "paused": "⏸",
            "error": "⚠",
        }

        status_colors = {
            "ready": "#3fb950",      # green
            "executing": "#d29922",  # yellow
            "paused": "#6e7681",     # dim
            "error": "#f85149",      # red
        }

        status_icon = status_icons.get(self.status_info.status, "?")
        status_color = status_colors.get(self.status_info.status, "#6e7681")
        connect_icon = "⟲" if self.status_info.connected else "✕"
        connect_color = "#3fb950" if self.status_info.connected else "#f85149"

        # One-line status bar: icon + status, then metadata right-aligned
        result = Text()
        result.append(f"{status_icon} {self.status_info.status} ", style=f"bold {status_color}")
        result.append("· ", style="dim")
        result.append(self.status_info.project_name, style="dim #6e7681")
        result.append(" ", style="dim")
        result.append(f"via {connect_icon}", style=f"dim {connect_color}")

        return result

    def display(self) -> None:
        """Print status bar to console."""
        self.console.print(self.render())
