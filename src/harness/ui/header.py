"""AI Code Assistant-style header with pink logo, model info, and path."""

from rich.text import Text
from rich.console import Console
from .claude_code_style import Colors, Styles


class Header:
    """Renders the Claude Code header: logo, title, model, path.

    Layout:
      🟪  AI Code Assistant v1.0
          cc/deepseek-v4-flash-free with high effort · API Usage Billing
          ~/Desktop/AI AGENTS/Code
    """

    def __init__(self, console: Console):
        self.console = console
        self._model = "cc/deepseek-v4-flash-free"
        self._effort = "high effort"
        self._billing = "API Usage Billing"
        self._path = r"~\Desktop\AI AGENTS\Code"
        self._version = "v1.0"
        self._title = "AI Code Assistant"

    def update(self, model: str = None, effort: str = None,
               billing: str = None, path: str = None) -> None:
        """Update header information dynamically."""
        if model is not None:
            self._model = model
        if effort is not None:
            self._effort = effort
        if billing is not None:
            self._billing = billing
        if path is not None:
            self._path = path

    def render(self) -> Text:
        """Render the three-line Claude Code header."""
        h = Text()

        # Line 1: 🟪  Claude Code v2.1.191
        h.append("🟪", style=Styles.LOGO)
        h.append("  ", style=Styles.HEADER_META)
        h.append(f"{self._title} ", style=Styles.HEADER_TITLE)
        h.append(self._version, style=Styles.HEADER_META)
        h.append("\n")

        # Line 2: model · billing (indented)
        h.append("    ", style=Styles.HEADER_META)
        h.append(self._model, style=Styles.HEADER_META)
        h.append(f" with {self._effort}", style=Styles.HEADER_META)
        h.append(" · ", style=Styles.HEADER_META)
        h.append(self._billing, style=Styles.HEADER_META)
        h.append("\n")

        # Line 3: path (indented)
        h.append("    ", style=Styles.HEADER_META)
        h.append(self._path, style=Styles.HEADER_META)

        return h
