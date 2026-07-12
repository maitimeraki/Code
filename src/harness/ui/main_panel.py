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
    """State for main panel content (scrollback buffer)."""
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

    def scroll_down(self, rows: int = 1) -> None:
        """Scroll down (toward newer content)."""
        self.scroll_position = max(0, self.scroll_position - rows)

    def scroll_up(self, rows: int = 1) -> None:
        """Scroll up (toward older content)."""
        self.scroll_position = min(self.scroll_position + rows, 10000)  # Cap at deque max


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

    def add_text(self, text: Text) -> None:
        """Add Rich Text object."""
        self.state.add_text(text)

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

    def render(self, height: int, width: int) -> Panel:
        """Render responsive scrollable panel with row-aware windowing.

        Windows by rendered terminal rows (after word-wrap at current width),
        not by logical entry count. This ensures the visible area always fills
        exactly the allocated height without overflow, even at narrow widths.
        """
        self.state.max_height = height
        available_height = max(1, height - 2)
        content_width = max(1, width - 4)  # Account for border + padding

        # Walk lines from tail (newest) backward, computing wrapped rows per entry
        # until we accumulate enough rows to fill available_height + scroll_position
        # Collect as chunks (one chunk per entry) to preserve internal row order per entry
        row_chunks = []
        rows_needed = available_height + self.state.scroll_position
        rows_seen = 0

        for entry in reversed(list(self.state.lines)):
            if rows_seen >= rows_needed:
                break

            # Convert (text, style) tuple or Text object to a Text object
            if isinstance(entry, tuple):
                text_str, style = entry
                entry_text = Text(text_str, style=style if style else Styles.INPUT_TEXT)
            else:
                entry_text = entry if isinstance(entry, Text) else Text(str(entry))

            # Wrap at content_width to get real rendered rows
            wrapped_rows = entry_text.wrap(self.console, content_width)
            rows_seen += len(wrapped_rows)
            row_chunks.append(wrapped_rows)

        # Reverse chunk order to chronological (oldest-first), preserving internal row order per chunk
        row_chunks.reverse()
        visible_rows = [row for chunk in row_chunks for row in chunk]
        start_row = max(0, len(visible_rows) - available_height - self.state.scroll_position)
        end_row = start_row + available_height
        displayed_rows = visible_rows[start_row:end_row]

        # Join rows with newlines (between only, not after the last row)
        content = Text()
        for i, row in enumerate(displayed_rows):
            content.append(row)
            if i < len(displayed_rows) - 1:
                content.append("\n")

        return Panel(
            content,
            title=f"[bold blue]{self.state.title}[/bold blue]",
            border_style=Styles.BORDER,
            padding=(0, 1),
            height=height,
        )

    def display(self, height: int, width: int) -> None:
        """Print panel to console."""
        self.console.print(self.render(height, width))
