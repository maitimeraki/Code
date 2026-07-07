"""Interactive Terminal UI application (Claude Code style)."""

import asyncio
from pathlib import Path

from harness.config import get_settings
from harness.logging import configure_logging, get_logger
from harness.ui.terminal import TerminalUI
from harness.core.task_manager import TaskStateManager
from harness.core.loop import LoopController
from harness.core.completion import CompletionChecker


logger = get_logger(__name__)


class HarnessApp:
    """Main application with interactive Terminal UI (Claude Code style)."""

    def __init__(self):
        self.settings = get_settings()
        configure_logging(self.settings.log_level)

        self.ui = TerminalUI()
        self.task_manager = TaskStateManager(self.settings.data_dir)
        self.loop_controller = LoopController(self.settings.data_dir)

    async def run(self) -> None:
        """Main application loop (Phase 2A: display UI once)."""
        self.ui.initialize()
        self.ui.display_once()

        # Phase 2B will add interactive input loop
        self.ui.add_message(
            "Phase 2A: Claude Code-style Terminal UI loaded!",
            level="success"
        )
        self.ui.display_once()


    # Phase 2B will implement interactive task creation/management
    async def _create_and_run_task(self) -> None:
        """Create a new task and run it."""
        pass

    async def _resume_task(self) -> None:
        """Resume a paused task."""
        pass

    async def _show_task_status(self) -> None:
        """Display status of all tasks."""
        pass

    def _show_settings(self) -> None:
        """Display current settings."""
        pass


async def main():
    """Entry point for interactive app."""
    app = HarnessApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())

