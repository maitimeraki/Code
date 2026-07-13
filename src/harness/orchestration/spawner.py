"""Agent spawner with multi-LLM fallback support and real tool-calling loop."""

import asyncio
from typing import Optional, Callable
from datetime import datetime
import structlog

from .agent import AgentConfig, AgentResult, AgentStatus, AgentType
from .llm_client import LLMClient, TextDelta, ToolCallsReady, StreamDone
from harness.tools.definitions import get_tools_payload, validate_args, TOOL_REGISTRY
from harness.tools.factory import build_scoped_router
from harness.tools.executor import ToolExecutor
from harness.config import get_settings
from pydantic import ValidationError

logger = structlog.get_logger(__name__)


class AgentSpawner:
    """Spawn and execute agents with real tool-calling loop and multi-LLM fallback."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        max_parallel_agents: Optional[int] = None,
        tool_timeout_seconds: Optional[int] = None,
    ):
        self.llm_client = llm_client or LLMClient()
        self.max_parallel_agents = max_parallel_agents or get_settings().max_parallel_agents
        self.tool_timeout_seconds = tool_timeout_seconds or get_settings().tool_timeout_seconds
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
                agent_type=config.agent_type.value,
                task=config.task_description[:100],
            )

            # Build scoped router + executor (fresh per spawn for isolation)
            scope = config.permission_scope
            router = build_scoped_router(scope)
            executor = ToolExecutor(router, tool_timeout_seconds=self.tool_timeout_seconds)

            # Build tools payload for LLM
            tools_payload = get_tools_payload(router) if router.handlers else None

            # Initialize messages with user task
            messages = [{"role": "user", "content": config.task_description}]

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

                        async for event in self.llm_client.stream_with_tools(
                            messages=messages,
                            tools=tools_payload,
                            model=config.model,
                            fallback_models=[
                                get_settings().code_standard_model,
                                get_settings().code_pro_model,
                                get_settings().code_max_model,
                            ],
                        ):
                            if isinstance(event, TextDelta):
                                assistant_text += event.content
                                if on_text_delta:
                                    on_text_delta(event.content)
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
                    logger.info(
                        "Agent completed",
                        agent_type=config.agent_type.value,
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
            logger.info("Agent cancelled", agent_type=config.agent_type.value)
            raise

        except Exception as e:
            # Tier 7: unexpected crash
            result.status = AgentStatus.FAILED
            result.error = str(e)
            logger.error(
                "Agent failed",
                agent_type=config.agent_type.value,
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
