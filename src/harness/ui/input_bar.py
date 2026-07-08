"""Input bar component for terminal UI."""

from dataclasses import dataclass, field
from typing import List, Optional, Callable, Awaitable
from rich.console import Console, Group
from rich.text import Text
from rich.rule import Rule
from .claude_code_style import Styles


@dataclass
class InputBarState:
    """State for input bar."""
    buffer: str = ""
    history: List[str] = field(default_factory=list)
    history_index: int = -1
    cursor_pos: int = 0
    hint: str = "< for agents"
    in_palette_mode: bool = False
    palette_buffer: str = ""
    in_task_mode: bool = False
    in_search_mode: bool = False


class InputBar:
    """Input prompt bar at bottom of terminal."""

    def __init__(self, console: Console):
        self.console = console
        self.state = InputBarState()
        self.on_submit: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_buffer_change: Optional[Callable[[], Awaitable[None]]] = None

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
        if self.state.in_palette_mode:
            if self.state.palette_buffer:
                self.state.palette_buffer = self.state.palette_buffer[:-1]
        else:
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

    def enter_palette_mode(self) -> None:
        """Enter command palette mode."""
        self.state.in_palette_mode = True
        self.state.palette_buffer = ""
        self.state.hint = "Type command (e.g. :run-task), press Enter to execute"

    def exit_palette_mode(self) -> None:
        """Exit command palette mode."""
        self.state.in_palette_mode = False
        self.state.palette_buffer = ""
        self.state.hint = "< for agents"

    def render(self) -> Group:
        """Render input bar: full-width rule / prompt / rule / hint (Claude Code style)."""
        prompt_text = Text()

        if self.state.in_palette_mode:
            prompt_text.append(": ", style=Styles.PROMPT)
            prompt_text.append(self.state.palette_buffer, style=Styles.INPUT_TEXT)
        else:
            prompt_text.append("> ", style=Styles.PROMPT)
            prompt_text.append(self.state.buffer, style=Styles.INPUT_TEXT)

        prompt_text.append("|", style=Styles.PROMPT)

        hint_text = Text(self.state.hint, style=Styles.HINT)

        return Group(
            Rule(style=Styles.BORDER),
            prompt_text,
            Rule(style=Styles.BORDER),
            hint_text,
        )

    def get_current_input(self) -> str:
        """Get current input (either buffer or palette buffer)."""
        if self.state.in_palette_mode:
            return self.state.palette_buffer
        return self.state.buffer
