"""Command palette for terminal UI."""

from dataclasses import dataclass
from typing import List, Callable, Awaitable, Optional


@dataclass
class Command:
    """A single command in the palette."""
    name: str
    description: str
    shortcut: str
    handler: Optional[Callable[[], Awaitable[None]]] = None


class CommandPalette:
    """Fuzzy-searchable command palette."""

    def __init__(self):
        self.commands: List[Command] = []
        self.search_query = ""
        self._init_default_commands()

    def _init_default_commands(self) -> None:
        """Initialize built-in commands."""
        self.register(
            Command(
                name="Run Task",
                description="Create and run a new task",
                shortcut=":run-task",
            )
        )
        self.register(
            Command(
                name="Resume Task",
                description="Resume a paused task from checkpoint",
                shortcut=":resume",
            )
        )
        self.register(
            Command(
                name="Pause",
                description="Pause current agent execution",
                shortcut=":pause",
            )
        )
        self.register(
            Command(
                name="Cancel",
                description="Cancel and cleanup current execution",
                shortcut=":cancel",
            )
        )
        self.register(
            Command(
                name="Search Logs",
                description="Search logs for patterns or errors",
                shortcut=":search-logs",
            )
        )
        self.register(
            Command(
                name="Clear",
                description="Clear the main panel",
                shortcut=":clear",
            )
        )
        self.register(
            Command(
                name="Export",
                description="Export task results to file",
                shortcut=":export",
            )
        )
        self.register(
            Command(
                name="Help",
                description="Show help and available commands",
                shortcut=":help",
            )
        )
        self.register(
            Command(
                name="Quit",
                description="Exit the harness",
                shortcut=":quit",
            )
        )

    def register(self, command: Command) -> None:
        """Register a new command."""
        if not any(c.shortcut == command.shortcut for c in self.commands):
            self.commands.append(command)

    def search(self, query: str) -> List[Command]:
        """Search commands by name, description, or shortcut."""
        self.search_query = query.lower()

        if not query:
            return self.commands

        results = []
        for cmd in self.commands:
            name_match = self._score_match(cmd.name, query)
            shortcut_match = self._score_match(cmd.shortcut, query)
            desc_match = self._score_match(cmd.description, query)

            best_score = max(name_match, shortcut_match, desc_match)
            if best_score > 0:
                results.append((cmd, best_score))

        results.sort(key=lambda x: x[1], reverse=True)
        return [cmd for cmd, _ in results]

    def _score_match(self, text: str, query: str) -> float:
        """Score how well query matches text."""
        text_lower = text.lower()
        query_lower = query.lower()

        if query_lower in text_lower:
            return 2.0

        if self._fuzzy_match(text_lower, query_lower):
            return 1.0

        return 0.0

    def _fuzzy_match(self, text: str, query: str) -> bool:
        """Check if query chars appear in order in text."""
        query_idx = 0
        for char in text:
            if query_idx < len(query) and char == query[query_idx]:
                query_idx += 1
        return query_idx == len(query)

    def get_command(self, shortcut: str) -> Optional[Command]:
        """Get command by shortcut."""
        for cmd in self.commands:
            if cmd.shortcut == shortcut:
                return cmd
        return None

    def format_results(self, results: List[Command]) -> str:
        """Format search results for display."""
        if not results:
            return "No commands found"

        lines = []
        for i, cmd in enumerate(results[:10], 1):
            lines.append(f"{i}. {cmd.shortcut:<15} {cmd.description}")

        return "\n".join(lines)
