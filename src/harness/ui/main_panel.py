"""Main content panel component for terminal UI."""

from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from .claude_code_style import Styles


@dataclass
class MainPanelState:
    """State for main panel content."""
    lines: deque = field(default_factory=lambda: deque(maxlen=10000))
    scroll_position: int = 0
    title: str = "Agent Harness"
    max_height: Optional[int] = None

    def add_line(self, text: str, style: str = "") -> None:
        """Add a line to panel content."""
        self.lines.append((text, style))

    def add_text(self, text: Text) -> None:
        """Add Rich Text to panel content."""
        self.lines.append(text)

    def clear(self) -> None:
        """Clear all content."""
        self.lines.clear()
        self.scroll_position = 0

    def get_visible_lines(self, height: int) -> List:
        """Get lines to display based on scroll position and height."""
        total_lines = len(self.lines)
        if total_lines <= height:
            return list(self.lines)

        start = max(0, total_lines - height - self.scroll_position)
        end = start + height
        return list(self.lines)[start:end]

    def scroll_down(self, lines: int = 1) -> None:
        """Scroll down."""
        self.scroll_position = max(0, self.scroll_position - lines)

    def scroll_up(self, lines: int = 1) -> None:
        """Scroll up."""
        max_scroll = max(0, len(self.lines) - (self.max_height or 10))
        self.scroll_position = min(max_scroll, self.scroll_position + lines)


class MainPanel:
    """Scrollable main content panel."""

    def __init__(self, console: Console, height: Optional[int] = None):
        self.console = console
        self.state = MainPanelState(max_height=height)

    def add_section(self, title: str, content: str, style: str = "") -> None:
        """Add a titled section."""
        self.state.add_line("")
        title_text = Text(title, style=Styles.WELCOME)
        self.state.add_text(title_text)
        self.state.add_line(content, style)

    def add_line(self, text: str, style: str = "") -> None:
        """Add a line of text."""
        self.state.add_line(text, style)

    def add_success(self, text: str) -> None:
        """Add success message."""
        self.state.add_text(Text(text, style=Styles.SUCCESS))

    def add_error(self, text: str) -> None:
        """Add error message."""
        self.state.add_text(Text(text, style=Styles.ERROR))

    def add_info(self, text: str) -> None:
        """Add info message."""
        self.state.add_text(Text(text, style=Styles.INFO))

    def clear(self) -> None:
        """Clear all content."""
        self.state.clear()

    def render(self, height: int) -> Panel:
        """Render panel as Rich Panel."""
        self.state.max_height = height
        visible_lines = self.state.get_visible_lines(height - 2)

        content = Text()
        for line in visible_lines:
            if isinstance(line, tuple):
                text, style = line
                content.append(text + "\n", style=style if style else Styles.INPUT_TEXT)
            else:
                content.append(line if isinstance(line, Text) else str(line))
                content.append("\n")

        return Panel(
            content,
            title=f"[bold blue]{self.state.title}[/bold blue]",
            border_style=Styles.BORDER,
            padding=(0, 1),
        )

    def display(self, height: int) -> None:
        """Print panel to console."""
        self.console.print(self.render(height))
