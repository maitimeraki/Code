"""Status bar — permission mode + current file, Claude Code style."""

from dataclasses import dataclass
from rich.text import Text
from rich.console import Console
from .claude_code_style import Styles


@dataclass
class StatusInfo:
    """Status information for the Claude Code-style status bar."""
    permission_mode: str = "accept edits on"
    current_file: str = ""
    is_agent_mode: bool = False


class StatusBar:
    """One-line status bar: permission mode on left, filename on right.

    Layout:
      ⏵ accept edits on (shift+tab to cycle) · ↵ for agents    ⧉ In definitions.py
    """

    def __init__(self, console: Console):
        self.console = console
        self.info = StatusInfo()

    def update(self, info: StatusInfo = None, **kwargs) -> None:
        """Update status information."""
        if info:
            self.info = info
        for k, v in kwargs.items():
            if hasattr(self.info, k):
                setattr(self.info, k, v)

    def render(self):
        """Render status bar: permission mode left, file info right."""
        width = self.console.width if self.console.width else 80

        left = Text()
        left.append("⏵ ", style=Styles.STATUS)
        left.append(self.info.permission_mode, style=Styles.STATUS)
        left.append(" (shift+tab to cycle)", style=Styles.STATUS_HINT)
        left.append(" · ", style=Styles.STATUS)
        left.append("↵ for agents", style=Styles.STATUS)

        right = Text()
        if self.info.current_file:
            right.append("  ⧉ ", style=Styles.STATUS)
            right.append(f"In {self.info.current_file}", style=Styles.STATUS)

        # Pad left to fill width, then append right
        left_str = left.plain
        right_str = right.plain
        pad = max(0, width - len(left_str) - len(right_str) - 1)

        result = Text()
        result.append(left)
        result.append(" " * pad, style=Styles.STATUS)
        result.append(right)

        return result
