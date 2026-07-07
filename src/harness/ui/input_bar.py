"""Input bar component for terminal UI."""

import asyncio
from dataclasses import dataclass, field
from typing import List, Optional
from rich.console import Console
from rich.text import Text
from .claude_code_style import Styles


@dataclass
class InputBarState:
    """State for input bar."""
    buffer: str = ""
    history: List[str] = field(default_factory=list)
    history_index: int = -1
    hint: str = "< for agents"


class InputBar:
    """Input prompt bar at bottom of terminal."""

    def __init__(self, console: Console):
        self.console = console
        self.state = InputBarState()

    def clear(self) -> None:
        """Clear input buffer."""
        self.state.buffer = ""
        self.state.history_index = -1

    def add_to_history(self, text: str) -> None:
        """Add text to input history."""
        if text and (not self.state.history or self.state.history[-1] != text):
            self.state.history.append(text)
        self.state.history_index = -1

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

    def render(self) -> Text:
        """Render input bar."""
        prompt_text = Text()
        prompt_text.append("> ", style=Styles.PROMPT)
        prompt_text.append(self.state.buffer, style=Styles.INPUT_TEXT)
        prompt_text.append("|", style=Styles.PROMPT)
        return prompt_text

    def render_hint(self) -> Text:
        """Render hint text."""
        return Text(self.state.hint, style=Styles.HINT)

    def display(self) -> None:
        """Print input bar and hint to console."""
        self.console.print(self.render())
        self.console.print(self.render_hint())

    async def get_input(self) -> str:
        """Get user input asynchronously (Phase 2B will enhance)."""
        return await asyncio.get_event_loop().run_in_executor(
            None, input, "> "
        )
