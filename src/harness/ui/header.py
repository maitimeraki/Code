"""Responsive header component for Terminal UI."""

from rich.text import Text
from rich.console import Console
from .claude_code_style import Colors, Styles


class Header:
    """Renders responsive top metadata headers."""

    def __init__(self, console: Console):
        self.console = console
        self.branch = "main"
        self.version = "0.1.0"
        self.path = "harness"
        self.command_context = ""

    def update(self, branch: str = None, version: str = None, path: str = None, context: str = None) -> None:
        """Update header information."""
        if branch:
            self.branch = branch
        if version:
            self.version = version
        if path:
            self.path = path
        if context:
            self.command_context = context

    def render_line1(self) -> Text:
        """Render first header line: project name + branch + version + status.

        Clean, professional header with semantic colors:
        - Project name & branch: blue (identity)
        - Version: yellow/warning (metadata)
        - Status: green (ready)
        """
        line = Text()
        line.append("Agent Harness ", style="bold #58a6ff")
        line.append("on ", style="dim")
        line.append(self.branch, style="bold #58a6ff")
        line.append(" · ", style="dim")
        line.append(f"v{self.version}", style="dim #d29922")
        line.append(" · ", style="dim")
        line.append("ready", style="#3fb950")
        return line

    def render_line2(self) -> Text:
        """Render second header line: system path + command context (muted)."""
        line = Text()
        line.append(self.path, style="dim #6e7681")
        if self.command_context:
            line.append(f"  {self.command_context}", style="dim #6e7681")
        return line

    def render(self) -> Text:
        """Render both header lines stacked."""
        header = Text()
        header.append(self.render_line1())
        header.append("\n")
        header.append(self.render_line2())
        return header
