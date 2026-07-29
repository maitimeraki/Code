"""Main content panel — no borders, just scrollable inline text."""

from collections import deque
from dataclasses import dataclass, field
from typing import Optional
from rich.console import Console
from rich.text import Text
from .claude_code_style import Styles


@dataclass
class MainPanelState:
    """State for main panel content (scrollback buffer)."""
    lines: deque = field(default_factory=lambda: deque(maxlen=10000))
    scroll_position: int = 0
    max_height: Optional[int] = None
    max_scroll: int = 0

    def add_line(self, text: str, style: str = "") -> None:
        """Add a line of plain text to panel content."""
        self.lines.append((text, style))

    def add_text(self, text: Text) -> None:
        """Add Rich Text to panel content."""
        self.lines.append(text)

    def clear(self) -> None:
        """Clear all content."""
        self.lines.clear()
        self.scroll_position = 0
        self.max_scroll = 0

    def scroll_down(self, rows: int = 1) -> None:
        """Scroll down (toward newer content)."""
        self.scroll_position = max(0, self.scroll_position - rows)

    def scroll_up(self, rows: int = 1) -> None:
        """Scroll up (toward older content)."""
        self.scroll_position += rows


class MainPanel:
    """Scrollable main content area — no borders, inline text only."""

    def __init__(self, console: Console, height: Optional[int] = None):
        self.console = console
        self.state = MainPanelState(max_height=height)

    def add_spacing(self) -> None:
        """Add vertical breathing room."""
        self.state.add_line("")

    def add_line(self, text: str, style: str = "") -> None:
        """Add a line of text."""
        self.state.add_line(text, style)

    def add_text(self, text: Text) -> None:
        """Add Rich Text object."""
        self.state.add_text(text)

    def add_success(self, text: str) -> None:
        """Add a plain text message."""
        self.state.add_text(Text(text))

    def add_error(self, text: str) -> None:
        """Add a plain text message."""
        self.state.add_text(Text(text))

    def add_info(self, text: str) -> None:
        """Add a plain text message."""
        self.state.add_text(Text(text))

    def clear(self) -> None:
        """Clear all content."""
        self.state.clear()

    def render(self, height: int, width: int) -> Text:
        """Render scrollable content as inline text (no Panel/border).

        Windows by rendered terminal rows (after word-wrap), not by
        logical entry count. This ensures the visible area always fills
        exactly the allocated height without overflow.
        """
        self.state.max_height = height
        available_height = max(1, height)
        content_width = max(1, width)

        # Walk lines from tail (newest) backward, computing wrapped rows
        row_chunks = []
        rows_needed = available_height + self.state.scroll_position
        rows_seen = 0
        exhausted = True

        for entry in reversed(list(self.state.lines)):
            if rows_seen >= rows_needed:
                exhausted = False
                break

            if isinstance(entry, tuple):
                text_str, style = entry
                entry_text = Text(text_str, style=style if style else Styles.AI)
            else:
                entry_text = entry if isinstance(entry, Text) else Text(str(entry))

            wrapped_rows = entry_text.wrap(self.console, content_width)
            rows_seen += len(wrapped_rows)
            row_chunks.append(wrapped_rows)

        row_chunks.reverse()
        visible_rows = [row for chunk in row_chunks for row in chunk]

        if exhausted:
            self.state.max_scroll = max(0, len(visible_rows) - available_height)
            if self.state.scroll_position > self.state.max_scroll:
                self.state.scroll_position = self.state.max_scroll
        else:
            self.state.max_scroll = self.state.scroll_position + available_height

        start_row = max(0, len(visible_rows) - available_height - self.state.scroll_position)
        end_row = start_row + available_height
        displayed_rows = visible_rows[start_row:end_row]

        # Join rows with newlines
        content = Text()
        for i, row in enumerate(displayed_rows):
            content.append(row)
            if i < len(displayed_rows) - 1:
                content.append("\n")

        return content
