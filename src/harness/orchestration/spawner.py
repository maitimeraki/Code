"""Agent spawner with multi-LLM fallback support and real tool-calling loop."""

import asyncio
from typing import Optional, Callable, TYPE_CHECKING
from datetime import datetime
import platform
import structlog
import json
import uuid

from .agent import AgentConfig, AgentResult, AgentStatus, AgentType
from .llm_client import LLMClient, TextDelta, ToolCallsReady, StreamDone
from harness.core.verifier import resolve_verifier
from harness.tools.definitions import get_tools_payload, validate_args, TOOL_REGISTRY
from harness.tools.factory import build_scoped_router
from harness.tools.executor import ToolExecutor
from harness.config import get_settings
from pydantic import ValidationError

if TYPE_CHECKING:
    from harness.ui.stream_listener import StreamListener

logger = structlog.get_logger(__name__)


def _compose_system_message(config: "AgentConfig", settings=None) -> str:
    """Compose the final system message by zone-ordered assembly.

    Layers, in order:
      [1]  static operating manual        — every agent
      [1b] DOCTRINE fragments             — capability-gated (e.g. context-mode)
      [2]  agent persona                  — every agent (config.system_prompt)
      [2b] ROLE fragments                 — capability-gated
      [3]  objective pin                  — SUB-AGENTS ONLY (focused goal + scope)
      [4]  dynamic context                — environment + project memory
      [5]  orchestration context          — MAIN AGENT ONLY (roster of agents/skills)

    The prompt is never fixed: fragments are collected from the process-wide
    FragmentRegistry and rendered only when their gate matches THIS agent. An
    install with no capabilities registered yields an empty doctrine zone — a
    clean, minimal prompt. Sub-agents (is_orchestrator=False) never receive the
    roster (layer 5); the orchestrator never receives the pin (layer 3).
    """
    if settings is None:
        from harness.config import get_settings
        settings = get_settings()

    from harness.prompts.fragments import get_fragment_registry, Zone, render_objective_pin

    registry = get_fragment_registry()
    parts = []

    # [1] Static operating manual — same for every agent.
    from harness.prompts.system import build_operating_prompt
    parts.append(build_operating_prompt(settings))

    # [1b] DOCTRINE fragments — sit right after the manual/tool schemas.
    for frag in registry.collect_zone(config, Zone.DOCTRINE):
        parts.append(frag.render(config))

    # [2] Agent persona.
    if config.system_prompt:
        parts.append(config.system_prompt)

    # [2b] ROLE fragments — alongside the persona.
    for frag in registry.collect_zone(config, Zone.ROLE):
        parts.append(frag.render(config))

    # [3] Objective pin — sub-agents run a pinned, scope-bounded goal. The
    # orchestrator manages its own goals and gets no pin.
    if not config.is_orchestrator and config.task_description:
        parts.append(render_objective_pin(config))

    # [4] Dynamic per-run context.
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

    # [5] Orchestration context — ONLY the main agent may see the roster and delegate.
    if config.is_orchestrator:
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


def _compose_post_task_reassertion(config: "AgentConfig") -> Optional[str]:
    """Render the POST_TASK re-assertion for this agent, or None if none applies.

    Injected as a nudge before the child's final turn to counter goal-drift from
    attention decay over a long run. Capability-gated like any other fragment.
    """
    from harness.prompts.fragments import get_fragment_registry, Zone

    registry = get_fragment_registry()
    blocks = [f.render(config) for f in registry.collect_zone(config, Zone.POST_TASK)]
    return "\n\n".join(blocks) if blocks else None


def _extract_completion_summary(tool_calls) -> Optional[str]:
    """Return the summary from an attempt_completion call this turn, or None if absent."""
    for tc in tool_calls:
        if tc.name == "attempt_completion":
            args = tc.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    args = {}
            return args.get("summary", "") if isinstance(args, dict) else ""
    return None


class AgentSpawner:
    """Spawn and execute agents with real tool-calling loop and multi-LLM fallback."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        max_parallel_agents: Optional[int] = None,
        tool_timeout_seconds: Optional[int] = None,
        stream_listener: Optional["StreamListener"] = None,
        approval_callback: Optional[Callable] = None,
        ask_user_question_callback: Optional[Callable] = None,
    ):
        self.llm_client = llm_client or LLMClient()
        self.max_parallel_agents = max_parallel_agents or get_settings().max_parallel_agents
        self.tool_timeout_seconds = tool_timeout_seconds or get_settings().tool_timeout_seconds
        self.stream_listener = stream_listener
        self.approval_callback = approval_callback
        self.ask_user_question_callback = ask_user_question_callback
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

        # Per-spawn identity so the UI can separate concurrent sub-agents that
        # share the same agent_name. depth 0 = top-level orchestrator; depth >= 1
        # = a delegated sub-agent whose events are routed to the activity panel.
        agent_id = uuid.uuid4().hex[:8]
        depth = config.spawn_depth

        # Resolve this task's completion gate: a verify command → CommandVerifier;
        # else if the critic is enabled → CriticVerifier (LLM judge, fail-open);
        # else SelfReportVerifier. Completion is only accepted when it passes.
        settings = get_settings()
        critic_client = self.llm_client if settings.use_critic_verifier else None
        verifier = resolve_verifier(
            config.verify_command, llm_client=critic_client, model=config.model
        )
        project_root = config.project_context.root if config.project_context else None

        try:
            result.status = AgentStatus.RUNNING
            logger.info(
                "Spawning agent",
                agent_name=config.agent_name,
                task=config.task_description[:100],
            )

            # Emit agent start event (structured, with identity + depth) so the
            # UI can open a live activity card for this specific sub-agent.
            if self.stream_listener:
                await self.stream_listener.log_agent_status(
                    agent_name=config.agent_name,
                    status="RUNNING",
                    detail=config.task_description[:80],
                    agent_id=agent_id,
                    depth=depth,
                )

            # Build scoped router + executor (fresh per spawn for isolation)
            scope = config.permission_scope
            router = build_scoped_router(
                scope,
                agent_registry=config.agent_registry,
                spawn_fn=self.spawn,
                parent_config=config,
                ask_user_question_callback=self.ask_user_question_callback,
            )
            executor = ToolExecutor(
                router,
                tool_timeout_seconds=self.tool_timeout_seconds,
                approval_callback=self.approval_callback,
            )

            # Build tools payload for LLM (normalize empty → None so we never send tools=[])
            tools_payload = None
            if router.handlers:
                tools_payload = get_tools_payload(router, agent_registry=config.agent_registry) or None

            # Initialize messages with optional system prompt and project context
            messages = []
            system_content = _compose_system_message(config)

            # Phase 5: augment the system prompt with persistent memory
            # (user preferences + known pitfalls + relevant prior solutions).
            # Best-effort: never let a memory/DB hiccup break agent spawning.
            if system_content:
                try:
                    from harness.prompts.context_injector import inject_memory_into_prompt

                    user_id = config.context.get("user_id") if config.context else None
                    system_content = await inject_memory_into_prompt(
                        base_prompt=system_content,
                        task_description=config.task_description,
                        user_id=user_id,
                    )
                except Exception as mem_err:
                    logger.debug("Memory injection skipped", error=str(mem_err))

            if system_content:
                messages.append({"role": "system", "content": system_content})
            messages.append({"role": "user", "content": config.task_description})

            # POST_TASK re-assertion: computed once, injected before the child's
            # final allowed turn to counter goal-drift over a long run. Gated like
            # any fragment (sub-agents only, by default).
            reassertion = _compose_post_task_reassertion(config)
            reassertion_injected = False

            # Tool-calling loop
            for iteration in range(config.max_tool_iterations):
                result.status = AgentStatus.THINKING
                logger.debug(f"Iteration {iteration + 1}/{config.max_tool_iterations}")

                # Before the last permitted turn, re-assert the objective once so
                # the model closes on its pinned goal rather than drifting.
                if (
                    reassertion
                    and not reassertion_injected
                    and iteration == config.max_tool_iterations - 1
                ):
                    messages.append({"role": "user", "content": reassertion})
                    reassertion_injected = True

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
                                # Only the top-level orchestrator streams its reply
                                # text to the UI (via on_text_delta → the reply line).
                                # Sub-agents get no callback, so their prose is never
                                # shown — only their tool calls are surfaced below.
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

                    # Execute this turn's tool calls concurrently, preserving order.
                    # Independent reads/searches — and multiple spawn_agent
                    # delegations — thus run in parallel instead of blocking one
                    # another, bounded by max_parallel_agents. Each call reports
                    # its own tool result back to the model, so a single failure
                    # never aborts the turn: the model sees the error and adapts.
                    sem = asyncio.Semaphore(self.max_parallel_agents)

                    async def _bounded(tc):
                        async with sem:
                            return await self._execute_tool_call(
                                tc,
                                executor,
                                agent_name=config.agent_name,
                                agent_id=agent_id,
                                depth=depth,
                            )

                    tool_outcomes = await asyncio.gather(
                        *(_bounded(tc) for tc in tool_calls_this_turn)
                    )

                    # Append results in call order and tally token usage.
                    for message, tokens in tool_outcomes:
                        messages.append(message)
                        result.tokens_used += tokens

                    result.iterations += 1

                    # Check token budget
                    if config.tool_token_budget and result.tokens_used >= config.tool_token_budget:
                        result.status = AgentStatus.FAILED
                        result.error = f"Tool token budget exhausted: {result.tokens_used} >= {config.tool_token_budget}"
                        break

                    # Completion gate: if the agent claimed done this turn, verify before
                    # accepting. On pass → complete; on fail → feed the reason back and
                    # keep looping (history retained) so the agent fixes it in-context.
                    summary = _extract_completion_summary(tool_calls_this_turn)
                    if summary is not None:
                        verdict = await verifier.verify(
                            objective=config.task_description,
                            summary=summary,
                            project_root=project_root,
                        )
                        if verdict.passed:
                            result.status = AgentStatus.COMPLETED
                            result.output = summary
                            logger.info(
                                "Agent completed (verified)",
                                agent_name=config.agent_name,
                                iterations=result.iterations,
                                reason=verdict.reason,
                            )
                            break
                        messages.append({
                            "role": "user",
                            "content": (
                                f"Completion was NOT accepted. {verdict.reason}\n"
                                "Fix the underlying cause and continue; call attempt_completion "
                                "again once it is genuinely done."
                            ),
                        })

                else:
                    # No tool calls — natural stop. Verify before accepting as final.
                    verdict = await verifier.verify(
                        objective=config.task_description,
                        summary=assistant_text,
                        project_root=project_root,
                    )
                    if not verdict.passed:
                        # Not actually done — feed the reason back and keep looping.
                        messages.append({"role": "assistant", "content": assistant_text or None})
                        messages.append({
                            "role": "user",
                            "content": (
                                f"Completion was NOT accepted. {verdict.reason}\n"
                                "Fix the underlying cause and continue until it passes."
                            ),
                        })
                        result.iterations += 1
                        continue

                    result.status = AgentStatus.COMPLETED
                    result.output = assistant_text
                    result.tokens_used += len(assistant_text.split())

                    # Terminal COMPLETED status is emitted once in the finally
                    # block (with agent identity), so no separate event here.

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

            # Always emit a terminal lifecycle status with identity so the UI can
            # close this specific sub-agent's activity card (success or failure).
            if self.stream_listener:
                terminal_status = (
                    "COMPLETED" if result.status == AgentStatus.COMPLETED else
                    "CANCELLED" if result.status == AgentStatus.CANCELLED else
                    "FAILED" if result.status == AgentStatus.FAILED else
                    result.status.value.upper()
                )
                detail = result.error or (f"{result.iterations} iter" if result.iterations else "")
                try:
                    await self.stream_listener.log_agent_status(
                        agent_name=config.agent_name,
                        status=terminal_status,
                        detail=detail[:80] if detail else "",
                        agent_id=agent_id,
                        depth=depth,
                    )
                except Exception:
                    pass

        return result

    async def _execute_tool_call(
        self,
        tool_call,
        executor,
        agent_name: Optional[str] = None,
        agent_id: Optional[str] = None,
        depth: int = 0,
    ) -> tuple[dict, int]:
        """Execute a single tool call and return (tool_result_message, tokens_used).

        Isolated per-call so a turn's calls can run concurrently via asyncio.gather.
        Any failure is captured into the returned tool message (never raised), so one
        failing call cannot abort its siblings or the turn — the model reads the error
        and adapts on the next iteration.

        agent_name/agent_id/depth attribute the call to the issuing agent so the UI
        can show, per parallel sub-agent, its current tool call (the tracker derives
        the step number by counting calls it receives for each agent_id).
        """
        tool_error = None
        tool_result = None
        tokens = 0  # track token cost for this call

        # Emit tool call start event
        if self.stream_listener:
            try:
                args = json.loads(tool_call.arguments) if isinstance(tool_call.arguments, str) else tool_call.arguments
            except (json.JSONDecodeError, TypeError):
                args = {"raw": tool_call.arguments}

            await self.stream_listener.log_tool_call(
                tool_name=tool_call.name,
                args=args,
                agent=agent_name,
                agent_id=agent_id,
                depth=depth,
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
                tokens = tool_result.tool_call.tokens_used

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
                tokens=tokens,
                agent=agent_name,
                agent_id=agent_id,
                depth=depth,
            )

        message = {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": tool_error or (tool_result.tool_call.result if tool_result else "No result"),
        }
        return message, tokens

    async def spawn_parallel(self, configs: list[AgentConfig]) -> list[AgentResult]:
        """Spawn multiple agents in parallel with semaphore."""
        semaphore = asyncio.Semaphore(self.max_parallel_agents)

        async def bounded_spawn(config):
            async with semaphore:
                return await self.spawn(config)

        tasks = [bounded_spawn(cfg) for cfg in configs]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results
