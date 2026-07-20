"""Main execution loop controller."""

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
import structlog

from harness.core.models import TaskState, TaskStatus, ExitCondition
from harness.core.task_manager import TaskStateManager
from harness.core.completion import CompletionChecker
from harness.core.error_memory import normalize_error
from harness.config import get_settings


logger = structlog.get_logger(__name__)


class LoopController:
    """Orchestrate task execution loop with checkpointing."""

    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir is None:
            data_dir = get_settings().get_data_dir()
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

        settings = get_settings()

        # Self-heal guard: identical errors on consecutive iterations mean we are
        # not making progress; bail instead of burning iterations on the same wall.
        # Errors are compared by normalized fingerprint, so a stack trace whose only
        # difference is a line number or address still counts as "the same error".
        MAX_CONSECUTIVE_SAME_ERROR = 3
        last_error_sig: Optional[str] = None
        same_error_count = 0

        # No-progress guard: distinct errors every turn but nothing ever advances.
        # Track the set of error fingerprints seen; if N straight iterations add no
        # NEW fingerprint and never succeed, we are churning — stop. 0 = disabled.
        no_progress_limit = settings.no_progress_limit
        seen_error_sigs: set[str] = set()
        no_progress_streak = 0

        # Wall-clock budget (seconds). 0 (default) = no cap.
        max_wall = state.max_wall_seconds or settings.max_wall_seconds
        wall_start = time.monotonic()

        while state.can_continue():
            # Wall-clock guard: a single slow iteration must not let the loop run
            # far past its time budget. Checked at the top of each iteration.
            if max_wall and (time.monotonic() - wall_start) >= max_wall:
                state.status = TaskStatus.FAILED
                state.exit_condition = ExitCondition.WALL_CLOCK
                logger.error(
                    "Wall-clock budget exceeded; stopping",
                    task_id=state.task_id,
                    max_wall_seconds=max_wall,
                )
                break

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

                # Iteration finished without an exception: reset the streaks.
                same_error_count = 0
                last_error_sig = None
                no_progress_streak = 0

                # Checkpoint after each iteration
                await self.task_manager.save_state(state)
                self._trace(state, wall_start)
                if "checkpoint" in self.loop_handlers:
                    await self.loop_handlers["checkpoint"](state)

                await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                # User/system cancellation is not recoverable — checkpoint and propagate.
                state.status = TaskStatus.PAUSED
                state.exit_condition = ExitCondition.USER_CANCEL
                await self.task_manager.save_state(state)
                raise

            except Exception as e:
                # Self-heal: record the error, feed it to the next iteration, and
                # keep looping. Errors are input for the next attempt, not a reason
                # to abort — the loop only gives up on repeated identical failure
                # or when max_iterations is exhausted.
                error_msg = str(e)
                logger.error("Loop iteration error; will retry", task_id=state.task_id, error=error_msg)
                state.errors.append(error_msg)
                state.error = error_msg
                # Next iteration's execute handler reads this to fix the failure.
                state.results["last_error"] = error_msg

                # Compare errors by normalized fingerprint, not raw string, so a
                # trace that only differs by line number / address still repeats.
                error_sig = f"{type(e).__name__}:{normalize_error(error_msg)}"
                if error_sig == last_error_sig:
                    same_error_count += 1
                else:
                    last_error_sig = error_sig
                    same_error_count = 1

                # No-progress: did this iteration surface any error skeleton we
                # haven't seen before? If not, we're churning without advancing.
                if error_sig in seen_error_sigs:
                    no_progress_streak += 1
                else:
                    seen_error_sigs.add(error_sig)
                    no_progress_streak = 0

                # record the failure so future runs learn from it.
                # Best-effort: never let error-logging mask the original error.
                try:
                    from harness.core.error_memory import upsert_error
                    await upsert_error(
                        error_type=type(e).__name__,
                        error_message=error_msg,
                        context=f"loop:{state.task_id}",
                    )
                except Exception as mem_err:
                    logger.debug("Error memory upsert skipped", error=str(mem_err))

                await self.task_manager.save_state(state)

                if same_error_count >= MAX_CONSECUTIVE_SAME_ERROR:
                    state.status = TaskStatus.FAILED
                    state.exit_condition = ExitCondition.CRITICAL_ERROR
                    logger.error(
                        "Same error repeated; giving up",
                        task_id=state.task_id,
                        error=error_msg,
                        repeats=same_error_count,
                    )
                    break

                if no_progress_limit and no_progress_streak >= no_progress_limit:
                    state.status = TaskStatus.FAILED
                    state.exit_condition = ExitCondition.NO_PROGRESS
                    logger.error(
                        "No new progress across iterations; giving up",
                        task_id=state.task_id,
                        streak=no_progress_streak,
                    )
                    break

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

    def _trace(self, state: TaskState, wall_start: float) -> None:
        """Append a per-iteration JSONL trace line. Best-effort; never raises."""
        try:
            import json

            trace_dir = get_settings().get_data_dir() / "traces"
            trace_dir.mkdir(parents=True, exist_ok=True)
            line = {
                "task_id": state.task_id,
                "iteration": state.iteration,
                "status": state.status.value,
                "tokens_used": state.tokens_used,
                "elapsed_seconds": round(time.monotonic() - wall_start, 3),
                "last_error": state.results.get("last_error"),
            }
            with open(trace_dir / f"{state.task_id}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(line) + "\n")
        except Exception as trace_err:
            logger.debug("Trace write skipped", error=str(trace_err))

    async def park_for_approval(
        self,
        state: TaskState,
        tool_call: dict,
        risk_level: str = "medium",
        summary: str = "",
    ) -> str:
        """Park task for approval before risky tool execution.

        Returns approval_id for tracking.
        """
        from harness.core.approval_manager import park_for_approval as park
        approval_id = await park(state, tool_call, risk_level, summary)
        await self.task_manager.save_state(state)
        return approval_id

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

        # Check if task is waiting for approval; execute if approved
        if state.status == TaskStatus.WAITING_APPROVAL and state.waiting_on:
            from harness.core.approval_manager import check_and_execute_once

            approval_id = state.waiting_on
            logger.info("Task waiting for approval; checking status", task_id=task_id, approval_id=approval_id)

            async def noop_executor(idempotency_key: str):
                # Approval is for tool execution; resume loop will handle it
                return {"status": "approved_and_ready"}

            success, result, error = await check_and_execute_once(approval_id, noop_executor)
            if not success:
                logger.warning("Approval still pending or rejected", approval_id=approval_id, error=error)
                state.status = TaskStatus.PAUSED
                await self.task_manager.save_state(state)
                return state

            logger.info("Approval granted; resuming execution", approval_id=approval_id)

        state.status = TaskStatus.RUNNING
        logger.info("Resuming task", task_id=task_id, from_iteration=state.iteration)

        return await self.run(state, completion_checker)