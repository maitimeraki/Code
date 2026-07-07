"""Main execution loop controller."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
import structlog

from harness.core.models import TaskState, TaskStatus, ExitCondition
from harness.core.task_manager import TaskStateManager
from harness.core.completion import CompletionChecker


logger = structlog.get_logger(__name__)


class LoopController:
    """Orchestrate task execution loop with checkpointing."""

    def __init__(self, data_dir: Path = Path("data")):
        self.task_manager = TaskStateManager(data_dir)
        self.loop_handlers: dict[str, Callable] = {}

    def register_handler(self, iteration_step: str, handler: Callable) -> None:
        """Register handler for specific loop step."""
        self.loop_handlers[iteration_step] = handler

    async def run(
        self,
        state: TaskState,
        completion_checker: CompletionChecker,
    ) -> TaskState:
        """Execute main loop until completion or exit condition."""
        state.status = TaskStatus.RUNNING
        state.started_at = datetime.now()

        logger.info("Starting loop", task_id=state.task_id, max_iterations=state.max_iterations)

        while state.can_continue():
            state.iteration += 1
            logger.info("Loop iteration", task_id=state.task_id, iteration=state.iteration)

            try:
                # Prepare iteration
                if "prepare" in self.loop_handlers:
                    await self.loop_handlers["prepare"](state)

                # Execute
                if "execute" in self.loop_handlers:
                    await self.loop_handlers["execute"](state)

                # Evaluate results
                if "evaluate" in self.loop_handlers:
                    await self.loop_handlers["evaluate"](state)

                # Check completion
                if completion_checker.check(state):
                    state.status = TaskStatus.COMPLETED
                    state.completed_at = datetime.now()
                    state.exit_condition = ExitCondition.SUCCESS
                    logger.info("Task completed", task_id=state.task_id, iteration=state.iteration)
                    break

                # Checkpoint after each iteration
                await self.task_manager.save_state(state)
                if "checkpoint" in self.loop_handlers:
                    await self.loop_handlers["checkpoint"](state)

                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error("Loop error", task_id=state.task_id, error=str(e))
                state.errors.append(str(e))
                state.status = TaskStatus.FAILED
                state.exit_condition = ExitCondition.CRITICAL_ERROR
                await self.task_manager.save_state(state)
                raise

        # Check exit condition
        if state.status != TaskStatus.COMPLETED:
            if state.iteration >= state.max_iterations:
                state.exit_condition = ExitCondition.MAX_ITERATIONS
            state.completed_at = datetime.now()

        await self.task_manager.save_state(state)

        logger.info(
            "Loop exited",
            task_id=state.task_id,
            exit_condition=state.exit_condition.value if state.exit_condition else None,
            iteration=state.iteration,
        )

        return state

    async def pause(self, state: TaskState) -> None:
        """Pause execution and checkpoint."""
        state.status = TaskStatus.PAUSED
        await self.task_manager.save_state(state)
        logger.info("Task paused", task_id=state.task_id, iteration=state.iteration)

    async def resume(self, task_id: str, completion_checker: CompletionChecker) -> TaskState:
        """Resume from checkpoint."""
        state = await self.task_manager.load_state(task_id)
        if not state:
            raise ValueError(f"No checkpoint found for task {task_id}")

        state.status = TaskStatus.RUNNING
        logger.info("Resuming task", task_id=task_id, from_iteration=state.iteration)

        return await self.run(state, completion_checker)
