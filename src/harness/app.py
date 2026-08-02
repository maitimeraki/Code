"""Interactive Terminal UI application (Claude Code style)."""

import asyncio
from typing import Optional, Any

from harness.config import get_settings, export_env_from_settings, get_app_settings
from harness.logging import configure_logging, get_logger
from harness.ui.terminal import TerminalUI
from harness.orchestration import HarnessOrchestrator
from harness.orchestration.llm_client import LLMClient
from harness.core.task_manager import TaskStateManager
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
        # Route interactive chat through the main orchestrator agent (real tools + delegation).
        self.ui.orchestrator = self.orchestrator
        self.ui.system_prompt = self.orchestrator.compose_system_message()
        self.auto_command = auto_command

    async def run(self) -> None:
        """Main application loop (Phase 2: UI + Orchestration)."""
        # Initialize persistent storage before anything touches the DB
        # (task state, memory, approvals all depend on this). Idempotent.
        from harness.persistence.database import init_db
        await init_db()

        # Create the session row + build the briefing (Tier 1 memory)
        await self.orchestrator.ensure_session()

        # Phase 1: Initialize transient cache (Redis) for <10ms active task lookup
        # Best-effort: system works without Redis (graceful degradation)
        try:
            from harness.persistence.transient_cache import TransientMemory
            transient_memory = TransientMemory(self.settings.redis_url)
            await transient_memory.connect()
            logger.info("Transient cache initialized")
        except Exception as e:
            logger.info("Transient cache skipped", error=str(e))

        # If auto_command provided, execute it concurrently with UI
        try:
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
        finally:
            # Pause session on exit (normal or crashed)
            if self.orchestrator.session_id:
                await self.orchestrator._session_manager.pause_session(self.orchestrator.session_id)

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

            elif cmd == "approvals":
                task_id = self.auto_command.get("task_id")
                await self._list_approvals(task_id)

            elif cmd == "approve":
                approval_id = self.auto_command.get("approval_id")
                decision = self.auto_command.get("decision", "approved")
                reason = self.auto_command.get("reason")
                await self._apply_approval(approval_id, decision, reason)

        except Exception as e:
            self.ui.add_message(f"Error executing command: {str(e)}", level="error")
            logger.error("Auto-command error", error=str(e))

    async def _run_task(self, task_description: str, max_iterations: int) -> None:
        """Run a task through the real orchestrator loop (agents + tools)."""
        self.ui.add_message(f"Running task: {task_description}")
        result = await self.orchestrator.run_task(task_description, max_iterations)
        self.ui.add_message(f"Task finished: {result.status.value}", level="success")

    async def _resume_task(self, task_id: str) -> None:
        """Resume a paused task through the orchestrator's loop."""
        self.ui.add_message(f"Resuming task: {task_id}")

        self.orchestrator.register_handlers()
        checker = CompletionChecker.create_simple({"agent_done": True})

        try:
            result = await self.orchestrator.loop_controller.resume(task_id, checker)
            self.ui.add_message(f"Task finished: {result.status.value}", level="success")
        except ValueError as e:
            self.ui.add_message(str(e), level="error")

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

    async def _list_approvals(self, task_id: Optional[str] = None) -> None:
        """List pending approval requests."""
        from harness.core.approval_manager import get_pending_approvals
        from harness.persistence.models import ApprovalRequest
        from sqlalchemy import select
        from harness.persistence.database import get_session

        self.ui.add_message("Pending Approvals:")

        if task_id:
            pending = await get_pending_approvals(task_id)
            if not pending:
                self.ui.add_message(f"  No pending approvals for task {task_id}")
                return
            for req in pending:
                self.ui.add_message(f"  {req.approval_id[:8]}... - {req.summary}")
                self.ui.add_message(f"    Risk: {req.risk_level}, Created: {req.created_at}")
        else:
            async with get_session() as db_session:
                result = await db_session.execute(
                    select(ApprovalRequest).where(ApprovalRequest.status == "pending")
                )
                pending = result.scalars().all()
            if not pending:
                self.ui.add_message("  (none)")
                return
            for req in pending:
                self.ui.add_message(f"  {req.approval_id[:8]}... - Task {req.task_id[:8]}... - {req.summary}")
                self.ui.add_message(f"    Risk: {req.risk_level}, Created: {req.created_at}")

    async def _apply_approval(self, approval_id: str, decision: str, reason: Optional[str] = None) -> None:
        """Apply approval decision."""
        from harness.core.approval_manager import apply_decision

        notes = reason or ""
        success = await apply_decision(approval_id, decision, decided_by="cli", notes=notes)

        if success:
            self.ui.add_message(f"✓ Approval decision recorded: {decision}", level="success")
            if reason:
                self.ui.add_message(f"  Reason: {reason}")
        else:
            self.ui.add_message(f"✗ Failed to record decision: {approval_id} not found", level="error")

    async def _create_and_run_task(self, task_description: str) -> None:
        """Create and run a task through orchestration."""
        self.ui.main_panel.add_info(f"Running task: {task_description}")
        state = await self.orchestrator.run_task(task_description)
        self.ui.main_panel.add_success(f"Task completed: {state.status.value}")

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

