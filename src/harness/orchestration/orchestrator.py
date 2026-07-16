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
        )

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

    def _build_main_agent_config(self, task_description: str) -> AgentConfig:
        """Build the top-level (orchestrator) agent config: full roster + tools + spawn.

        This is the ONE agent that sees available agents/skills and may delegate.
        """
        return AgentConfig(
            agent_type="main",
            task_description=task_description,
            project_context=self.project_context,
            agent_registry=self.agent_registry,
            skill_registry=self.skill_registry,
            permission_scope=PermissionScope.default_for_project(self.project_context.root),
            is_orchestrator=True,
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

            agents = {a.name for a in self.agent_registry.list_agents()}
            default_agent = "architect" if "architect" in agents else (
                next(iter(agents)) if agents else None
            )
            if default_agent is None:
                self._log_to_ui("No agents available in registry", "error")
                return

            config = AgentConfig(
                agent_type=default_agent,
                task_description=state.description,
                system_prompt=self.agent_registry.get_full(default_agent),
                project_context=self.project_context,
                agent_registry=self.agent_registry,
                skill_registry=self.skill_registry,
                permission_scope=PermissionScope.default_for_project(self.project_context.root),
                is_orchestrator=True,
            )

            def on_text_delta(text: str) -> None:
                self._log_to_ui(text, "agent_output")

            result = await self.agent_spawner.spawn(config, on_text_delta=on_text_delta)

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
            description=task_description,
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
