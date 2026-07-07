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
        """Render status bar as Rich Text."""
        status_icons = {
            "ready": "✓",
            "executing": "⟳",
            "paused": "⏸",
            "error": "⚠",
        }

        change_marker = "[!?]" if self.status_info.has_changes else ""
        status_icon = status_icons.get(self.status_info.status, "?")
        connect_icon = "⟲" if self.status_info.connected else "✕"

        status_text = (
            f"{self.status_info.project_name} ▸ {self.status_info.branch} "
            f"{change_marker} is {status_icon} v{self.status_info.version} via {connect_icon}"
        )

        return Text(status_text, style=Styles.STATUS_BAR)

    def display(self) -> None:
        """Print status bar to console."""
        self.console.print(self.render())
