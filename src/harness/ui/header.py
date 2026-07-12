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
        self.path = r"C:\Users\Anupam\.local\bin\harness.exe"
        self.command_context = "/agents"

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
        """Render first header line: git branch + version + connection status."""
        line = Text()
        line.append("Code on [", style=Styles.INFO)
        line.append(self.branch, style="bold blue")
        line.append("] is ", style=Styles.INFO)
        line.append(f"v{self.version}", style=Styles.VERSION)
        line.append(" via ", style=Styles.INFO)
        line.append("⟲", style=Styles.INFO)
        return line

    def render_line2(self) -> Text:
        """Render second header line: system path + command context."""
        line = Text()
        line.append(self.path, style=Styles.PATH)
        line.append(f"  {self.command_context}", style=Styles.INFO)
        return line

    def render(self) -> Text:
        """Render both header lines stacked."""
        header = Text()
        header.append(self.render_line1())
        header.append("\n")
        header.append(self.render_line2())
        return header
