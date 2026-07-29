"""Input bar component — between two horizontal lines, Claude Code style."""

from dataclasses import dataclass, field
from typing import List, Optional
from rich.text import Text
from rich.console import Console
from .claude_code_style import Colors, Styles


@dataclass
class InputBarState:
    """State for input bar."""
    buffer: str = ""
    history: List[str] = field(default_factory=list)
    history_index: int = -1
    cursor_pos: int = 0
    is_processing: bool = False


class InputBar:
    """Input bar between two horizontal lines, always at screen bottom."""

    def __init__(self, console: Console):
        self.console = console
        self.state = InputBarState()

    def clear(self) -> None:
        """Clear input buffer."""
        self.state.buffer = ""
        self.state.cursor_pos = 0
        self.state.history_index = -1

    def add_to_history(self, text: str) -> None:
        """Add text to input history."""
        if text and (not self.state.history or self.state.history[-1] != text):
            self.state.history.append(text)
        self.state.history_index = -1

    def add_char(self, char: str) -> None:
        """Add character at cursor position."""
        pos = self.state.cursor_pos
        self.state.buffer = self.state.buffer[:pos] + char + self.state.buffer[pos:]
        self.state.cursor_pos = min(pos + 1, len(self.state.buffer))

    def delete_char(self) -> None:
        """Delete character before cursor."""
        if self.state.cursor_pos > 0:
            pos = self.state.cursor_pos
            self.state.buffer = self.state.buffer[:pos - 1] + self.state.buffer[pos:]
            self.state.cursor_pos = max(0, pos - 1)

    def set_buffer(self, text: str) -> None:
        """Set input buffer and cursor to end."""
        self.state.buffer = text
        self.state.cursor_pos = len(text)

    def get_previous(self) -> Optional[str]:
        """Get previous history entry."""
        if not self.state.history:
            return None
        if self.state.history_index < len(self.state.history) - 1:
            self.state.history_index += 1
            return self.state.history[-(self.state.history_index + 1)]
        return None

    def get_next(self) -> Optional[str]:
        """Get next history entry."""
        if self.state.history_index > 0:
            self.state.history_index -= 1
            return self.state.history[-(self.state.history_index + 1)]
        elif self.state.history_index == 0:
            self.state.history_index = -1
            return ""
        return None

    def get_current_input(self) -> str:
        """Get current input buffer."""
        return self.state.buffer

    def render(self) -> Text:
        """Render input bar between two horizontal lines.

        Top line: ─────────────────────────────────────────────────
        Input:    > |
        Bottom line: ──────────────────────────────────────────────
        """
        width = self.console.width if self.console.width else 80

        result = Text()

        # Top horizontal line
        result.append("─" * width, style=Styles.INPUT_LINE)
        result.append("\n")

        # Input line: "> " + buffer + blinking cursor block
        result.append("> ", style=Styles.USER_PROMPT)
        result.append(self.state.buffer, style=Styles.USER_TEXT)
        # ponytail: static cursor block (full block █) — Rich Live doesn't
        # animate per-frame easily, so a constant block is the visual anchor.
        result.append("█", style=Styles.USER_TEXT)
        result.append("\n")

        # Bottom horizontal line
        result.append("─" * width, style=Styles.INPUT_LINE)

        return result
