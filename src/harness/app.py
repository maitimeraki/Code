"""Interactive Terminal UI application (Claude Code style)."""

import asyncio
from pathlib import Path

from harness.config import get_settings
from harness.logging import configure_logging, get_logger
from harness.tui import HarnessUI
from harness.core.task_manager import TaskStateManager
from harness.core.loop import LoopController
from harness.core.completion import CompletionChecker


logger = get_logger(__name__)


class HarnessApp:
    """Main application with interactive TUI."""

    def __init__(self):
        self.settings = get_settings()
        configure_logging(self.settings.log_level)

        self.ui = HarnessUI()
        self.task_manager = TaskStateManager(self.settings.data_dir)
        self.loop_controller = LoopController(self.settings.data_dir)

    async def run(self) -> None:
        """Main application loop."""
        self.ui.show_header()

        while True:
            choice = self.ui.show_main_menu()

            try:
                if choice == "1":
                    await self._create_and_run_task()
                elif choice == "2":
                    await self._resume_task()
                elif choice == "3":
                    await self._show_task_status()
                elif choice == "4":
                    self.ui.show_info(
                        "Knowledge Graph Search",
                        "[yellow]Coming in Phase 5 (Persistence layer)[/yellow]",
                    )
                elif choice == "5":
                    self._show_settings()
                elif choice == "0":
                    self.ui.console.print("[bold cyan]Goodbye![/bold cyan]")
                    break
                else:
                    self.ui.show_error("Invalid choice. Please try again.")
                    continue

                if choice != "0":
                    if not self.ui.prompt_continue():
                        break

            except Exception as e:
                logger.error("Application error", error=str(e))
                self.ui.show_error(f"Error: {str(e)}")
                if not self.ui.prompt_continue():
                    break

    async def _create_and_run_task(self) -> None:
        """Create a new task and run it."""
        description, params = self.ui.create_task_form()

        self.ui.show_success(f"Creating task: {description}")

        # Create task
        state = await self.task_manager.create_task(
            description=description,
            success_criteria=params.get("success_criteria", {}),
            max_iterations=params.get("max_iterations", 10),
        )

        logger.info("Task created", task_id=state.task_id)

        # Register dummy handler (Phase 2 will add real agents)
        async def dummy_work(s):
            s.results["status"] = f"Iteration {s.iteration} completed"

        self.loop_controller.register_handler("execute", dummy_work)

        # Run with progress display
        checker = CompletionChecker.create_simple(state.success_criteria)

        await self.ui.show_task_progress(
            state.task_id,
            self.task_manager.load_state,
            max_iterations=state.max_iterations,
        )

        # Show results
        final_state = await self.task_manager.load_state(state.task_id)
        if final_state:
            self.ui.show_task_result(final_state)

    async def _resume_task(self) -> None:
        """Resume a paused task."""
        task_ids = await self.task_manager.list_tasks()

        if not task_ids:
            self.ui.show_error("No tasks found")
            return

        # Show available tasks
        self.ui.console.print("[bold cyan]Available Tasks:[/bold cyan]")
        task_map = {}
        for i, task_id in enumerate(task_ids, 1):
            state = await self.task_manager.load_state(task_id)
            if state:
                task_map[str(i)] = task_id
                self.ui.console.print(
                    f"  [{i}] {task_id[:8]}... - {state.description} "
                    f"({state.status.value}, iter {state.iteration})"
                )

        choice = self.ui.console.input("[bold cyan]Select task number:[/bold cyan] ").strip()

        if choice not in task_map:
            self.ui.show_error("Invalid selection")
            return

        task_id = task_map[choice]
        state = await self.task_manager.load_state(task_id)

        if not state:
            self.ui.show_error(f"Could not load task {task_id}")
            return

        # Resume
        self.ui.show_success(f"Resuming task: {state.description}")

        async def dummy_work(s):
            s.results["status"] = f"Iteration {s.iteration} completed"

        self.loop_controller.register_handler("execute", dummy_work)
        checker = CompletionChecker.create_simple(state.success_criteria)

        await self.ui.show_task_progress(
            task_id,
            self.task_manager.load_state,
            max_iterations=state.max_iterations,
        )

        final_state = await self.task_manager.load_state(task_id)
        if final_state:
            self.ui.show_task_result(final_state)

    async def _show_task_status(self) -> None:
        """Display status of all tasks."""
        task_ids = await self.task_manager.list_tasks()

        if not task_ids:
            self.ui.show_info("Task Status", "[yellow]No tasks yet[/yellow]")
            return

        tasks = []
        for task_id in task_ids:
            state = await self.task_manager.load_state(task_id)
            if state:
                tasks.append(
                    {
                        "task_id": state.task_id,
                        "description": state.description,
                        "status": state.status.value,
                        "iteration": state.iteration,
                        "max_iterations": state.max_iterations,
                    }
                )

        self.ui.show_task_table(tasks)

    def _show_settings(self) -> None:
        """Display current settings."""
        settings_text = (
            f"[cyan]Database:[/cyan] {self.settings.database_url}\n"
            f"[cyan]Execution Mode:[/cyan] {self.settings.execution_mode}\n"
            f"[cyan]Max Parallel Agents:[/cyan] {self.settings.max_parallel_agents}\n"
            f"[cyan]Max Retries:[/cyan] {self.settings.max_agent_retries}\n"
            f"[cyan]Tool Timeout:[/cyan] {self.settings.tool_timeout_seconds}s\n"
            f"[cyan]Log Level:[/cyan] {self.settings.log_level}"
        )
        self.ui.show_info("Settings", settings_text)


async def main():
    """Entry point for interactive app."""
    app = HarnessApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
