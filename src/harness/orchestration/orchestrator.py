"""Harness orchestrator - main integration point."""

import asyncio
from pathlib import Path
from typing import Optional
import structlog

from harness.core.loop import LoopController
from harness.core.models import TaskState, TaskStatus
from harness.core.completion import CompletionChecker
from harness.context.project_context import load_project_context
from harness.registry.definitions import AgentRegistry, SkillRegistry, ensure_seed_agents
from harness.tools.permissions import PermissionScope
from harness.ui import TerminalUI, StreamListener, LogEntry, LogLevel
from harness.config import get_settings
from .agent import AgentConfig, AgentType
from .spawner import AgentSpawner
from .llm_client import LLMClient

logger = structlog.get_logger(__name__)


class HarnessOrchestrator:
    """Coordinate loop execution with Terminal UI and agents."""

    def __init__(self, ui: Optional[TerminalUI] = None):
        self.ui = ui
        self.loop_controller = LoopController()

        settings = get_settings()

        # Load project context once
        self.project_context = load_project_context(Path.cwd(), settings)

        # Build registries
        self.agent_registry = AgentRegistry(settings.get_agents_dir)
        self.skill_registry = SkillRegistry(settings.get_skills_dir)
        ensure_seed_agents(settings)
        self.agent_registry.scan()
        self.skill_registry.scan()

        # Build shared LLMClient from settings
        llm_client = LLMClient()

        # Get stream listener from UI if available
        self.stream_listener = ui.stream_listener if ui else None

        # Build AgentSpawner with settings-derived config and stream listener
        self.agent_spawner = AgentSpawner(
            llm_client=llm_client,
            max_parallel_agents=settings.max_parallel_agents,
            tool_timeout_seconds=settings.tool_timeout_seconds,
            stream_listener=self.stream_listener,
            approval_callback=ui.request_approval if ui else None,
            ask_user_question_callback=ui.ask_user_question_callback if ui else None,
        )

    def compose_capsule(self, agent_result) -> dict:
        """Compose token-efficient capsule from agent result.

        Extracts: status, summary (first 500 chars of output), artifact refs.
        Returns: {status, summary, artifacts} — suitable for downstream agents.

        Saves ~70% tokens vs. forwarding full agent output + context.
        """
        return {
            "status": agent_result.status.value if hasattr(agent_result.status, "value") else str(agent_result.status),
            "summary": (agent_result.output or "")[:500],
            "artifacts": getattr(agent_result, "artifacts", []) or [],
            "token_usage": {
                "input": getattr(agent_result, "input_tokens", 0),
                "output": getattr(agent_result, "output_tokens", 0),
            }
        }

    def compose_system_message(self) -> str:
        """Compose the chat system message from loaded project context + registries."""
        from .spawner import _compose_system_message
        settings = get_settings()
        return _compose_system_message(
            AgentConfig(
                agent_type="chat",
                task_description="",
                project_context=self.project_context,
                agent_registry=self.agent_registry,
                skill_registry=self.skill_registry,
                is_orchestrator=True,
            ),
            settings,
        )

    def _build_main_agent_config(
        self, task_description: str, verify_command: Optional[str] = None
    ) -> AgentConfig:
        """Build the top-level (orchestrator) agent config: full roster + tools + spawn.

        This is the ONE agent that sees available agents/skills and may delegate.
        A verify_command, when supplied, gates the agent's completion on exit 0.
        """
        return AgentConfig(
            agent_type="main",
            task_description=task_description,
            project_context=self.project_context,
            agent_registry=self.agent_registry,
            skill_registry=self.skill_registry,
            permission_scope=PermissionScope.default_for_project(self.project_context.root),
            is_orchestrator=True,
            verify_command=verify_command,
        )

    async def chat(self, prompt: str, on_text_delta=None):
        """Handle an interactive chat prompt through the main orchestrator agent.

        Routes chat through the same tool-calling agent path as tasks so the model
        can actually read/write/run commands and delegate to sub-agents.
        """
        config = self._build_main_agent_config(prompt)
        return await self.agent_spawner.spawn(config, on_text_delta=on_text_delta)

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

    def register_handlers(self, verify_command: Optional[str] = None) -> None:
        """Register loop handlers for orchestration.

        verify_command, when supplied, gates each iteration's completion on exit 0.
        """

        async def prepare_handler(state: TaskState) -> None:
            """Prepare next iteration."""
            self._log_to_ui(f"Preparing iteration {state.iteration}", "info")
            if self.ui:
                self.ui.main_panel.add_info(f"Iteration {state.iteration}")

        async def execute_handler(state: TaskState) -> None:
            """Execute one iteration: run the main orchestrator agent on the task.

            The main agent sees the full roster and may delegate to sub-agents
            (multiple spawn_agent calls in one turn run concurrently). If a prior
            iteration failed, its error is fed back so the agent fixes it instead
            of starting blind.
            """
            self._log_to_ui(f"Executing iteration {state.iteration}", "info")

            task = state.description
            last_error = state.results.get("last_error")
            if last_error:
                task += (
                    f"\n\nThe previous attempt failed with this error:\n{last_error}\n"
                    "Diagnose the cause, fix it, and continue the task to completion."
                )

            config = self._build_main_agent_config(task, verify_command=verify_command)

            def on_text_delta(text: str) -> None:
                self._log_to_ui(text, "agent_output")

            result = await self.agent_spawner.spawn(config, on_text_delta=on_text_delta)

            if result.success:
                # Compose token-efficient capsule for next iteration
                capsule = self.compose_capsule(result)
                self._log_to_ui(f"Agent result (capsule): {capsule['summary']}", "info")
                state.result = str(capsule["summary"])
                state.results["agent_done"] = True
                state.results["last_error"] = None
            else:
                # Feed the failure into the next iteration instead of aborting.
                error = result.error or "Agent failed without an error message"
                self._log_to_ui(f"Agent failed: {error}", "error")
                state.errors.append(error)
                state.results["agent_done"] = False
                state.results["last_error"] = error

        async def checkpoint_handler(state: TaskState) -> None:
            """Post-checkpoint hook after each iteration."""
            self._log_to_ui(f"Completed iteration {state.iteration}", "info")

        self.loop_controller.register_handler("prepare", prepare_handler)
        self.loop_controller.register_handler("execute", execute_handler)
        self.loop_controller.register_handler("checkpoint", checkpoint_handler)

    async def run_task(
        self,
        task_description: str,
        max_iterations: int = 10,
        verify_command: Optional[str] = None,
    ) -> TaskState:
        """Run a task through the harness: loop until done or errors stop resolving.

        Each iteration runs the main orchestrator agent; failures are fed back into
        the next iteration. The task completes when an iteration finishes cleanly.
        When verify_command is supplied, an iteration only counts as done if that
        command exits 0 — otherwise the failure is fed back and the loop continues.
        """
        self._log_to_ui(f"Starting task: {task_description}", "info")

        state = TaskState(
            description=task_description,
            max_iterations=max_iterations,
            success_criteria={"agent_done": True},
        )
        state.criteria_met = {"agent_done": False}

        completion_checker = CompletionChecker.create_simple({"agent_done": True})
        self.register_handlers(verify_command=verify_command)

        try:
            state = await self.loop_controller.run(state, completion_checker)
            self._log_to_ui(f"Task finished: {state.status.value}", "info")
        except Exception as e:
            self._log_to_ui(f"Task failed: {str(e)}", "error")
            state.status = TaskStatus.FAILED

        return state
