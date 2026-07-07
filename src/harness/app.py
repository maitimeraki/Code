"""Interactive Terminal UI application (Claude Code style)."""

import asyncio
from pathlib import Path

from harness.config import get_settings
from harness.logging import configure_logging, get_logger
from harness.ui.terminal import TerminalUI
from harness.orchestration import HarnessOrchestrator


logger = get_logger(__name__)


class HarnessApp:
    """Main application with interactive Terminal UI + agent orchestration."""

    def __init__(self):
        self.settings = get_settings()
        configure_logging(self.settings.log_level)

        self.ui = TerminalUI()
        self.orchestrator = HarnessOrchestrator(ui=self.ui)

    async def run(self) -> None:
        """Main application loop (Phase 2: UI + Orchestration)."""
        # Initialize UI and orchestrator
        self.ui.initialize()
        self.ui.add_message("Phase 2: Terminal UI + Agent Orchestration Ready", "info")

        # Run UI event loops (input, display, streams) concurrently
        await self.ui.run()

    async def _create_and_run_task(self, task_description: str) -> None:
        """Create and run a task through orchestration."""
        self.ui.main_panel.add_info(f"Running task: {task_description}")
        state = await self.orchestrator.run_task(task_description)
        self.ui.main_panel.add_success(f"Task completed: {state.status.value}")

    async def _resume_task(self, task_id: str) -> None:
        """Resume a paused task."""
        self.ui.main_panel.add_info(f"Resuming task: {task_id}")

    async def _show_task_status(self) -> None:
        """Display status of all tasks."""
        self.ui.main_panel.add_info("Task status")

    def _show_settings(self) -> None:
        """Display current settings."""
        pass


async def main():
    """Entry point for interactive app."""
    app = HarnessApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())

