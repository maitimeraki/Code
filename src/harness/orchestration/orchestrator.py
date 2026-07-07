"""Harness orchestrator - main integration point."""

import asyncio
from typing import Optional
import structlog

from harness.core.loop import LoopController
from harness.core.models import TaskState, TaskStatus
from harness.core.completion import CompletionChecker
from harness.ui import TerminalUI, StreamListener, LogEntry, LogLevel
from .agent import AgentConfig, AgentType
from .spawner import AgentSpawner

logger = structlog.get_logger(__name__)


class HarnessOrchestrator:
    """Coordinate loop execution with Terminal UI and agents."""

    def __init__(self, ui: Optional[TerminalUI] = None):
        self.ui = ui
        self.loop_controller = LoopController()
        self.agent_spawner = AgentSpawner()
        self.stream_listener = ui.stream_listener if ui else None

    def _log_to_ui(self, message: str, level: str = "info") -> None:
        """Log message to UI stream."""
        if self.stream_listener:
            entry = LogEntry(
                level=LogLevel.SYSTEM,
                message=message,
                timestamp="",
            )
            asyncio.create_task(self.stream_listener.emit(entry))

        logger.info(message)

    def register_handlers(self) -> None:
        """Register loop handlers for orchestration."""

        async def prepare_handler(state: TaskState) -> None:
            """Prepare next iteration."""
            self._log_to_ui(f"Preparing iteration {state.iteration}", "info")
            if self.ui:
                self.ui.main_panel.add_info(f"Iteration {state.iteration}")

        async def execute_handler(state: TaskState) -> None:
            """Execute agents for current iteration."""
            self._log_to_ui(f"Executing iteration {state.iteration}", "info")

            # Example: Spawn an architect agent
            config = AgentConfig(
                agent_type=AgentType.ARCHITECT,
                task_description=state.task,
            )

            result = await self.agent_spawner.spawn(config)

            if result.success:
                self._log_to_ui(f"Agent result: {result.output}", "info")
                state.result = result.output
            else:
                self._log_to_ui(f"Agent failed: {result.error}", "error")

        async def cleanup_handler(state: TaskState) -> None:
            """Cleanup after iteration."""
            self._log_to_ui(f"Completed iteration {state.iteration}", "info")

        self.loop_controller.register_handler("prepare", prepare_handler)
        self.loop_controller.register_handler("execute", execute_handler)
        self.loop_controller.register_handler("cleanup", cleanup_handler)

    async def run_task(self, task_description: str) -> TaskState:
        """Run a task through the harness."""
        self._log_to_ui(f"Starting task: {task_description}", "info")

        state = TaskState(
            task_id="task_001",
            task=task_description,
            max_iterations=3,
        )

        completion_checker = CompletionChecker()
        self.register_handlers()

        try:
            state = await self.loop_controller.run(state, completion_checker)
            self._log_to_ui(f"Task completed: {state.status.value}", "info")
        except Exception as e:
            self._log_to_ui(f"Task failed: {str(e)}", "error")
            state.status = TaskStatus.FAILED

        return state
