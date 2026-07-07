"""Command handlers for terminal UI."""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .terminal import TerminalUI


class CommandActions:
    """Handlers for all command palette commands."""

    def __init__(self, ui: "TerminalUI"):
        self.ui = ui

    async def run_task(self) -> None:
        """Handler for :run-task command."""
        self.ui.main_panel.add_info("Entering task mode...")
        self.ui.input_bar.state.in_task_mode = True
        self.ui.main_panel.add_line("Enter task description and press Enter:")
        await asyncio.sleep(0.1)

    async def pause(self) -> None:
        """Handler for :pause command."""
        self.ui.state.pause()
        self.ui.main_panel.add_success("Execution paused")

    async def resume(self) -> None:
        """Handler for :resume command."""
        self.ui.state.resume()
        self.ui.main_panel.add_success("Execution resumed")

    async def cancel(self) -> None:
        """Handler for :cancel command."""
        self.ui.state.pause()
        self.ui.main_panel.add_error("Operation cancelled")

    async def search_logs(self) -> None:
        """Handler for :search-logs command."""
        self.ui.main_panel.add_info("Search logs mode...")
        self.ui.input_bar.state.in_search_mode = True
        self.ui.main_panel.add_line("Enter search query:")
        await asyncio.sleep(0.1)

    async def clear(self) -> None:
        """Handler for :clear command."""
        self.ui.main_panel.clear()
        self.ui.main_panel.add_info("Panel cleared")

    async def export(self) -> None:
        """Handler for :export command."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"export_{timestamp}.txt"

        try:
            lines = self.ui.main_panel.buffer
            with open(filename, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self.ui.main_panel.add_success(f"Exported to {filename}")
        except Exception as e:
            self.ui.main_panel.add_error(f"Export failed: {str(e)}")

    async def help(self) -> None:
        """Handler for :help command."""
        self.ui.main_panel.add_section("Command Palette Help", "")
        self.ui.main_panel.add_line("")
        self.ui.main_panel.add_info("Available Commands:")
        self.ui.main_panel.add_line("")

        help_text = [
            ":run-task      - Create and run a new task",
            ":pause         - Pause current execution",
            ":resume        - Resume from checkpoint",
            ":cancel        - Cancel and cleanup",
            ":search-logs   - Search logs for patterns",
            ":clear         - Clear the main panel",
            ":export        - Export logs to file",
            ":help          - Show this help",
            ":quit          - Exit the harness",
            "",
            "Keyboard Shortcuts:",
            "Ctrl+K         - Open command palette",
            "Ctrl+L         - Clear panel",
            "Ctrl+C         - Cancel operation",
            "Ctrl+D         - Quit",
            "Up/Down arrows - Input history",
        ]

        for line in help_text:
            self.ui.main_panel.add_line(line)

    async def quit(self) -> None:
        """Handler for :quit command."""
        self.ui.main_panel.add_info("Shutting down...")
        await asyncio.sleep(0.1)
        self.ui.shutdown()
