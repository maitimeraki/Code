"""Interactive Terminal UI application (Claude Code style)."""

import asyncio
from typing import Optional

from harness.config import get_settings, export_env_from_settings, get_app_settings
from harness.logging import configure_logging, get_logger
from harness.ui.terminal import TerminalUI
from harness.orchestration import HarnessOrchestrator
from harness.orchestration.llm_client import LLMClient
from harness.core.task_manager import TaskStateManager
from harness.core.loop import LoopController
from harness.core.completion import CompletionChecker


logger = get_logger(__name__)


class HarnessApp:
    """Main application with interactive Terminal UI + agent orchestration."""

    def __init__(self, auto_command: Optional[dict] = None):
        self.settings = get_settings()
        configure_logging(self.settings.log_level)

        export_env_from_settings()
        llm_client = LLMClient()
        self.ui = TerminalUI(llm_client=llm_client)
        self.orchestrator = HarnessOrchestrator(ui=self.ui)
        self.auto_command = auto_command

    async def run(self) -> None:
        """Main application loop (Phase 2: UI + Orchestration)."""
        # If auto_command provided, execute it concurrently with UI
        if self.auto_command:
            # Run UI and auto-command concurrently
            await asyncio.gather(
                self.ui.run(),
                self._execute_auto_command_with_delay(),
                return_exceptions=True
            )
        else:
            # Just run UI
            await self.ui.run()

    async def _execute_auto_command_with_delay(self) -> None:
        """Execute auto-command after UI initializes."""
        await asyncio.sleep(0.5)
        await self._execute_auto_command()

    async def _execute_auto_command(self) -> None:
        """Execute auto-command based on CLI args."""
        try:
            cmd = self.auto_command.get("command")

            if cmd == "run":
                task_desc = self.auto_command.get("task")
                max_iterations = self.auto_command.get("max_iterations", 10)
                await self._run_task(task_desc, max_iterations)

            elif cmd == "resume":
                task_id = self.auto_command.get("task_id")
                await self._resume_task(task_id)

            elif cmd == "status":
                await self._show_status()

            elif cmd == "init":
                await self._init_project()

            elif cmd == "knowledge-search":
                query = self.auto_command.get("query")
                limit = self.auto_command.get("limit", 5)
                await self._search_knowledge(query, limit)

        except Exception as e:
            self.ui.add_message(f"Error executing command: {str(e)}", level="error")
            logger.error("Auto-command error", error=str(e))

    async def _run_task(self, task_description: str, max_iterations: int) -> None:
        """Run a task automatically."""
        self.ui.add_message(f"Running task: {task_description}")
        manager = TaskStateManager(self.settings.get_data_dir())
        controller = LoopController(self.settings.get_data_dir())

        state = await manager.create_task(
            description=task_description,
            success_criteria={},
            max_iterations=max_iterations,
        )

        async def dummy_work(s):
            s.results["status"] = f"Iteration {s.iteration} completed"
            self.ui.add_message(f"Iteration {s.iteration}/{max_iterations}")

        controller.register_handler("execute", dummy_work)
        checker = CompletionChecker.create_simple({})

        result = await controller.run(state, checker)
        self.ui.add_message(f"Task completed: {result.status.value}", level="success")

    async def _resume_task(self, task_id: str) -> None:
        """Resume a paused task."""
        self.ui.add_message(f"Resuming task: {task_id}")
        manager = TaskStateManager(self.settings.get_data_dir())

        state = await manager.load_state(task_id)
        if not state:
            self.ui.add_message(f"No checkpoint found for task {task_id}", level="error")
            return

        controller = LoopController(self.settings.get_data_dir())

        async def dummy_work(s):
            s.results["status"] = f"Iteration {s.iteration} completed"

        controller.register_handler("execute", dummy_work)
        checker = CompletionChecker.create_simple({})

        result = await controller.resume(task_id, checker)
        self.ui.add_message(f"Task completed: {result.status.value}", level="success")

    async def _show_status(self) -> None:
        """Show status of all tasks."""
        manager = TaskStateManager(self.settings.get_data_dir())
        task_ids = await manager.list_tasks()

        self.ui.add_message("Active Tasks:")
        if not task_ids:
            self.ui.add_message("  (none)")
            return

        for task_id in task_ids:
            state = await manager.load_state(task_id)
            if state:
                self.ui.add_message(f"  {task_id[:8]}... - {state.description}")
                self.ui.add_message(f"    Status: {state.status.value}, Iteration: {state.iteration}/{state.max_iterations}")

    async def _init_project(self) -> None:
        """Initialize project."""
        self.settings.get_data_dir()
        self.settings.get_templates_dir()
        self.ui.add_message("Harness initialized", level="success")

    async def _search_knowledge(self, query: str, limit: int) -> None:
        """Search knowledge graph."""
        self.ui.add_message(f"Searching: {query}")
        self.ui.add_message("Not yet implemented - awaiting Phase 5 (Knowledge Graph)", level="info")

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

