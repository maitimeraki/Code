"""Tests for Core Loop Engine (Phase 1)."""

import asyncio
import pytest
from pathlib import Path

from harness.core.models import TaskState, TaskStatus, ExitCondition
from harness.core.task_manager import TaskStateManager
from harness.core.completion import CompletionChecker
from harness.core.loop import LoopController


@pytest.fixture
def temp_data_dir(tmp_path):
    """Temporary data directory for tests."""
    return tmp_path / "data"


@pytest.mark.asyncio
async def test_create_task(temp_data_dir):
    """Test creating a new task."""
    manager = TaskStateManager(temp_data_dir)

    state = await manager.create_task(
        description="Test task",
        success_criteria={"test_pass": True},
    )

    assert state.description == "Test task"
    assert state.status == TaskStatus.PENDING
    assert state.iteration == 0
    assert len(state.task_id) > 0


@pytest.mark.asyncio
async def test_save_and_restore_state(temp_data_dir):
    """Test checkpoint save and restore."""
    manager = TaskStateManager(temp_data_dir)

    state1 = await manager.create_task(
        description="Test task",
        success_criteria={"coverage": 0.80},
    )
    state1.iteration = 5
    state1.results = {"coverage": 0.85}

    await manager.save_state(state1)

    # Restore
    state2 = await manager.load_state(state1.task_id)

    assert state2 is not None
    assert state2.iteration == 5
    assert state2.results == {"coverage": 0.85}


@pytest.mark.asyncio
async def test_loop_completion(temp_data_dir):
    """Test loop exits on completion."""
    manager = TaskStateManager(temp_data_dir)
    controller = LoopController(temp_data_dir)

    state = await manager.create_task(
        description="Simple test",
        success_criteria={"count": 3},
    )

    # Simulate incremental progress
    async def simulate_work(s):
        s.results["count"] = s.results.get("count", 0) + 1

    controller.register_handler("execute", simulate_work)

    # Use simple checker: count >= 3
    checker = CompletionChecker.create_simple({"count": 3})

    result = await controller.run(state, checker)

    assert result.status == TaskStatus.COMPLETED
    assert result.exit_condition == ExitCondition.SUCCESS
    assert result.results["count"] == 3


@pytest.mark.asyncio
async def test_loop_max_iterations(temp_data_dir):
    """Test loop exits on max iterations."""
    manager = TaskStateManager(temp_data_dir)
    controller = LoopController(temp_data_dir)

    state = await manager.create_task(
        description="Never completes",
        success_criteria={"impossible": True},
        max_iterations=3,
    )

    async def noop(s):
        pass

    controller.register_handler("execute", noop)
    checker = CompletionChecker.create_simple({"impossible": True})

    result = await controller.run(state, checker)

    assert result.status != TaskStatus.COMPLETED
    assert result.exit_condition == ExitCondition.MAX_ITERATIONS
    assert result.iteration == 3


@pytest.mark.asyncio
async def test_checkpoint_and_resume(temp_data_dir):
    """Test pause and resume from checkpoint."""
    manager = TaskStateManager(temp_data_dir)
    controller = LoopController(temp_data_dir)

    state = await manager.create_task(
        description="Pauseable task",
        success_criteria={"stage": "complete"},
    )

    # First run: execute once, then pause
    async def single_step(s):
        s.results["stage"] = "partial"

    controller.register_handler("execute", single_step)
    checker = CompletionChecker.create_simple({"stage": "complete"})

    # Run one iteration
    state.iteration = 1
    state.results["stage"] = "partial"
    await controller.pause(state)

    assert state.status == TaskStatus.PAUSED

    # Resume and complete
    async def complete_step(s):
        s.results["stage"] = "complete"

    controller.register_handler("execute", complete_step)
    resumed = await controller.resume(state.task_id, checker)

    assert resumed.status == TaskStatus.COMPLETED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
