"""Agent spawner with multi-LLM fallback support and real tool-calling loop."""

import asyncio
from typing import Optional, Callable, TYPE_CHECKING
from datetime import datetime
import platform
import structlog
import json

from .agent import AgentConfig, AgentResult, AgentStatus, AgentType
from .llm_client import LLMClient, TextDelta, ToolCallsReady, StreamDone
from harness.tools.definitions import get_tools_payload, validate_args, TOOL_REGISTRY
from harness.tools.factory import build_scoped_router
from harness.tools.executor import ToolExecutor
from harness.config import get_settings
from pydantic import ValidationError

if TYPE_CHECKING:
    from harness.ui.stream_listener import StreamListener

logger = structlog.get_logger(__name__)


def _compose_system_message(config: "AgentConfig") -> str:
    """Compose final system message from agent config, project context, registries.

    Assembles: agent instructions, environment info, project memory, available agents/skills.
    """
    parts = []

    if config.system_prompt:
        parts.append(config.system_prompt)

    if config.project_context:
        env_block = f"""<environment>
project_root: {config.project_context.root}
platform: {platform.system()}
date: {datetime.now().strftime('%Y-%m-%d')}
</environment>"""
        parts.append(env_block)

        if config.project_context.memory_text:
            parts.append(f"""<project_memory>
{config.project_context.memory_text}
</project_memory>""")

    if config.agent_registry:
        agents = config.agent_registry.list_agents()
        if agents:
            agent_lines = "\n".join(f"- {a.name}: {a.description}" for a in agents)
            parts.append(f"""<available_agents>
{agent_lines}
</available_agents>""")

    if config.skill_registry:
        skills = config.skill_registry.list_skills()
        if skills:
            skill_lines = "\n".join(f"- {s.name}: {s.description}" for s in skills)
            parts.append(f"""<available_skills>
{skill_lines}
</available_skills>""")

    return "\n\n".join(parts)


class AgentSpawner:
    """Spawn and execute agents with real tool-calling loop and multi-LLM fallback."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        max_parallel_agents: Optional[int] = None,
        tool_timeout_seconds: Optional[int] = None,
        stream_listener: Optional["StreamListener"] = None,
    ):
        self.llm_client = llm_client or LLMClient()
        self.max_parallel_agents = max_parallel_agents or get_settings().max_parallel_agents
        self.tool_timeout_seconds = tool_timeout_seconds or get_settings().tool_timeout_seconds
        self.stream_listener = stream_listener
        self.results = {}

    async def spawn(
        self, config: AgentConfig, on_text_delta: Optional[Callable[[str], None]] = None
    ) -> AgentResult:
        """Spawn agent and execute task with real LLM tool-calling loop.

        Args:
            config: Agent configuration with task description and permissions.
            on_text_delta: Optional callback to stream text deltas to UI.

        Returns:
            AgentResult with status, output, and token usage.
        """
        result = AgentResult(
            agent_type=config.agent_type,
            status=AgentStatus.SPAWNING,
            started_at=datetime.now(),
        )

        try:
            result.status = AgentStatus.RUNNING
            logger.info(
                "Spawning agent",
                agent_name=config.agent_name,
                task=config.task_description[:100],
            )

            # Emit agent start event
            if self.stream_listener:
                from harness.ui.stream_listener import LogLevel
                await self.stream_listener.log_agent_output(
                    f"Agent '{config.agent_name}' spawning...",
                    level=LogLevel.INFO,
                )

            # Build scoped router + executor (fresh per spawn for isolation)
            scope = config.permission_scope
            router = build_scoped_router(
                scope,
                agent_registry=config.agent_registry,
                spawn_fn=self.spawn,
                parent_config=config,
            )
            executor = ToolExecutor(router, tool_timeout_seconds=self.tool_timeout_seconds)

            # Build tools payload for LLM
            tools_payload = get_tools_payload(router, agent_registry=config.agent_registry) if router.handlers else None

            # Initialize messages with optional system prompt and project context
            messages = []
            system_content = _compose_system_message(config)
            if system_content:
                messages.append({"role": "system", "content": system_content})
            messages.append({"role": "user", "content": config.task_description})

            # Tool-calling loop
            for iteration in range(config.max_tool_iterations):
                result.status = AgentStatus.THINKING
                logger.debug(f"Iteration {iteration + 1}/{config.max_tool_iterations}")

                # Get LLM response with tool support (with retries for Tier 5)
                completion = None
                last_llm_error = None
                for retry_attempt in range(config.max_retries + 1):
                    try:
                        # Stream with tools
                        assistant_text = ""
                        tool_calls_this_turn = []

                        async for event in self.llm_client.stream(
                            messages=messages,
                            tools=tools_payload,
                            model=config.model,
                            fallback_models=None,
                        ):
                            if isinstance(event, TextDelta):
                                assistant_text += event.content
                                if on_text_delta:
                                    on_text_delta(event.content)
                                # Emit LLM response to stream listener
                                if self.stream_listener:
                                    from harness.ui.stream_listener import LogLevel
                                    await self.stream_listener.log_agent_output(
                                        event.content,
                                        level=LogLevel.INFO,
                                    )
                            elif isinstance(event, ToolCallsReady):
                                tool_calls_this_turn = event.tool_calls
                            elif isinstance(event, StreamDone):
                                pass

                        completion = (assistant_text, tool_calls_this_turn)
                        break

                    except Exception as e:
                        last_llm_error = e
                        if retry_attempt < config.max_retries:
                            wait_time = 0.5 * (2 ** retry_attempt)
                            logger.warning(
                                f"LLM call failed, retrying (attempt {retry_attempt + 1}/{config.max_retries})",
                                error=str(e),
                                wait_time=wait_time,
                            )
                            await asyncio.sleep(wait_time)
                        else:
                            logger.error(
                                "LLM call failed after all retries",
                                error=str(e),
                            )

                if completion is None:
                    # Tier 5: LLM failure after retries
                    result.status = AgentStatus.FAILED
                    result.error = f"LLM call failed: {str(last_llm_error)}"
                    logger.error(result.error)
                    break

                assistant_text, tool_calls_this_turn = completion

                # Check if tool calls exist
                if tool_calls_this_turn:
                    result.status = AgentStatus.TOOL_CALLING

                    # Append assistant message with tool calls to history
                    messages.append(
                        {
                            "role": "assistant",
                            "content": assistant_text or None,
                            "tool_calls": [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {"name": tc.name, "arguments": tc.arguments},
                                }
                                for tc in tool_calls_this_turn
                            ],
                        }
                    )

                    # Execute each tool call
                    for tool_call in tool_calls_this_turn:
                        tool_error = None
                        tool_result = None

                        # Emit tool call start event
                        if self.stream_listener:
                            from harness.ui.stream_listener import LogLevel
                            try:
                                args = json.loads(tool_call.arguments) if isinstance(tool_call.arguments, str) else tool_call.arguments
                            except (json.JSONDecodeError, TypeError):
                                args = {"raw": tool_call.arguments}

                            await self.stream_listener.log_tool_call(
                                tool_name=tool_call.name,
                                args=args,
                            )

                        try:
                            # Map name to ToolType
                            tool_type = None
                            for tt, defn in TOOL_REGISTRY.items():
                                if defn.name == tool_call.name:
                                    tool_type = tt
                                    break

                            if tool_type is None:
                                raise ValueError(f"Unknown tool: {tool_call.name}")

                            # Tier 0/1: Validate arguments
                            try:
                                validated_args = validate_args(tool_type, tool_call.arguments)
                            except ValidationError as ve:
                                tool_error = f"Invalid arguments for {tool_call.name}: {str(ve)}"
                                logger.warning(tool_error)
                            else:
                                # Tier 2–4: Execute tool (permission/circuit-breaker handled inside)
                                tool_result = await executor.execute(
                                    tool_type, **validated_args.model_dump()
                                )
                                result.tokens_used += tool_result.tool_call.tokens_used

                                if not tool_result.tool_call.success:
                                    tool_error = tool_result.tool_call.error

                        except Exception as e:
                            tool_error = f"Tool execution error: {str(e)}"
                            logger.error(tool_error, tool=tool_call.name)

                        # Emit tool result event
                        if self.stream_listener:
                            await self.stream_listener.log_tool_call(
                                tool_name=tool_call.name,
                                args={},  # Already logged in call start
                                result=tool_result.tool_call.result if tool_result else None,
                                error=tool_error,
                            )

                        # Append tool result to messages
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": tool_error or (tool_result.tool_call.result if tool_result else "No result"),
                            }
                        )

                    result.iterations += 1

                    # Check token budget
                    if config.tool_token_budget and result.tokens_used >= config.tool_token_budget:
                        result.status = AgentStatus.FAILED
                        result.error = f"Tool token budget exhausted: {result.tokens_used} >= {config.tool_token_budget}"
                        break

                else:
                    # No tool calls — this is the final answer
                    result.status = AgentStatus.COMPLETED
                    result.output = assistant_text
                    result.tokens_used += len(assistant_text.split())

                    # Emit completion event
                    if self.stream_listener:
                        from harness.ui.stream_listener import LogLevel
                        await self.stream_listener.log_agent_output(
                            f"Agent '{config.agent_name}' completed in {result.iterations} iteration(s)",
                            level=LogLevel.INFO,
                        )

                    logger.info(
                        "Agent completed",
                        agent_name=config.agent_name,
                        iterations=result.iterations,
                        tokens=result.tokens_used,
                    )
                    break

            # Check if loop exhausted
            if result.status == AgentStatus.TOOL_CALLING:
                # Tier 6: max_tool_iterations exhausted
                result.status = AgentStatus.FAILED
                result.error = f"Max tool iterations ({config.max_tool_iterations}) exhausted"
                logger.warning(result.error)

        except asyncio.CancelledError:
            result.status = AgentStatus.CANCELLED
            logger.info("Agent cancelled", agent_name=config.agent_name)
            raise

        except Exception as e:
            # Tier 7: unexpected crash
            result.status = AgentStatus.FAILED
            result.error = str(e)
            logger.error(
                "Agent failed",
                agent_name=config.agent_name,
                error=str(e),
            )

        finally:
            result.completed_at = datetime.now()

        return result

    async def spawn_parallel(self, configs: list[AgentConfig]) -> list[AgentResult]:
        """Spawn multiple agents in parallel with semaphore."""
        semaphore = asyncio.Semaphore(self.max_parallel_agents)

        async def bounded_spawn(config):
            async with semaphore:
                return await self.spawn(config)

        tasks = [bounded_spawn(cfg) for cfg in configs]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results
