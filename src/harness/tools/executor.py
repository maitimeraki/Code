"""Tool execution with retry and caching logic."""

import asyncio
import hashlib
from typing import Optional, Dict, Any, Callable
import structlog
from datetime import datetime, timedelta

from .models import ToolCall, ToolType, ToolStatus, ToolResult
from .router import ToolRouter
from .permissions import ApprovalRequired
from harness.config import get_settings

logger = structlog.get_logger(__name__)


def _tname(tool_type) -> str:
    """String form of a tool identity — normalizes a ToolType enum to its value
    (str(ToolType.BASH) is "ToolType.BASH", NOT "Bash" — that divergence made
    session-grant keys never match the retry check)."""
    return tool_type.value if isinstance(tool_type, ToolType) else str(tool_type)


# Decisions the approval callback returns once the human decides. The executor
# maps each to an outcome: approve-set → execute the call now; deny-set → fail
# the call; anything else (None, unexpected string) → park as AWAITING_APPROVAL
# so the loop can surface it again on retry.
_APPROVED_DECISIONS = {"approved", "approved_session", "persist"}
_DENIED_DECISIONS = {"denied", "denied_session"}


class ToolExecutor:
    """Execute tools with retry, caching, and circuit breaker."""

    def __init__(
        self,
        router: ToolRouter,
        tool_timeout_seconds: Optional[int] = None,
        approval_callback: Optional[Callable[[ToolType, Dict[str, Any], str], Any]] = None,
        task_id: Optional[str] = None,
    ):
        self.router = router
        self.cache: Dict[str, tuple[Any, datetime]] = {}
        self.cache_ttl = timedelta(hours=1)
        self.tool_timeout_seconds = tool_timeout_seconds or get_settings().tool_timeout_seconds
        self.approval_callback = approval_callback
        self.task_id = task_id
        self.retry_config = {
            ToolType.READ: {"max_retries": 2, "backoff": 0.5},
            ToolType.WRITE: {"max_retries": 1, "backoff": 1.0},
            ToolType.EDIT: {"max_retries": 1, "backoff": 0.5},
            ToolType.BASH: {"max_retries": 3, "backoff": 0.5},
            ToolType.GREP: {"max_retries": 2, "backoff": 0.5},
            ToolType.GLOB: {"max_retries": 1, "backoff": 0.5},
            # A spawned agent is a whole long-running task, not a quick I/O op —
            # never auto-retry one. A failed sub-agent is reported to the parent
            # model, which decides adaptively instead of silently re-launching.
            ToolType.SPAWN_AGENT: {"max_retries": 0, "backoff": 0.5},
        }
        self.circuit_breaker_threshold = 5
        self.circuit_breaker_reset_time = 60
        self.failed_attempts: Dict[ToolType, int] = {}
        self.circuit_opened_at: Dict[ToolType, datetime] = {}

    def _cache_key(self, tool_type: ToolType, **kwargs) -> str:
        """Generate cache key for tool call."""
        key_str = f"{_tname(tool_type)}:{str(sorted(kwargs.items()))}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def _is_cached_valid(self, cached_time: datetime) -> bool:
        """Check if cached result is still valid."""
        return datetime.now() - cached_time < self.cache_ttl

    async def _surface_approval(self, tool_type, kwargs: Dict[str, Any], risk: str = "high") -> Optional[str]:
        """Block on the human's approval decision for this tool call.

        Awaits the UI callback (the Y/N/A/S/P picker) and returns the decision
        the human made: "approved", "approved_session", "persist", "denied", or
        "denied_session". Returns None when no callback is wired (headless) or
        the callback errored — the caller then parks the call as
        AWAITING_APPROVAL so the loop can surface it again on retry.
        """
        if not self.approval_callback:
            return None
        name = _tname(tool_type)  # plain string — the grant keys must match this
        try:
            return await self.approval_callback(
                action={"tool_type": name, "args": kwargs},
                tool=name,
                risk_level=risk,
            )
        except Exception as e:
            logger.warning("Failed to surface approval request", tool=name, error=str(e))
            return None

    async def execute(
        self,
        tool_type: ToolType,
        **kwargs
    ) -> ToolResult:
        """Execute tool with retry and caching."""
        # HITL gate: check if approval is needed (via permissions or risk classification).
        # If needed and not yet granted, return AWAITING_APPROVAL; the loop will park.
        # AskUserQuestion is exempt — it IS the user interaction mechanism.
        if tool_type != ToolType.ASK_USER_QUESTION and get_settings().require_approval:
            needs_approval = False
            try:
                from harness.core.risk import classify_risk
                from harness.tools.permissions import PermissionScope

                risk = classify_risk(tool_type, kwargs, scope=None)
                needs_approval = risk == "high"
            except Exception as e:
                logger.error(f"Risk classification failed: {e}")
                needs_approval = True

            if needs_approval:
                # Check the unified approval state (session grant / one-call grant /
                # session denial) using the same fingerprints the UI grants with.
                from harness.core.approval_policy import is_granted, is_denied
                name = _tname(tool_type)
                resource = kwargs.get("command") or kwargs.get("path") or ""

                if is_denied(name, resource):
                    logger.info("Tool denied for this session", tool_type=name)
                    return ToolResult(
                        tool_call=ToolCall(
                            tool_type=tool_type,
                            args=kwargs,
                            status=ToolStatus.FAILED,
                            error=f"Tool '{name}' was denied for this session.",
                        )
                    )

                if not is_granted(name, resource):
                    # Not granted — BLOCK on the human's decision. Approved →
                    # fall through and execute; denied → fail; no UI → park so
                    # the loop can surface it again on retry.
                    logger.info(
                        "Tool requires approval, awaiting human decision",
                        tool_type=name,
                    )
                    decision = await self._surface_approval(tool_type, kwargs, risk="high")
                    if decision in _DENIED_DECISIONS:
                        return ToolResult(
                            tool_call=ToolCall(
                                tool_type=tool_type,
                                args=kwargs,
                                status=ToolStatus.FAILED,
                                error=f"Tool '{name}' was denied by the user.",
                            )
                        )
                    if decision not in _APPROVED_DECISIONS:
                        # No UI / no decision — park for the loop to re-surface.
                        return ToolResult(
                            tool_call=ToolCall(
                                tool_type=tool_type,
                                args=kwargs,
                                status=ToolStatus.AWAITING_APPROVAL,
                            )
                        )
                    # Approved — the UI handler set the grant before returning, so
                    # the scoped router's gate lets this call run below.

        cache_key = self._cache_key(tool_type, **kwargs)

        # Check circuit breaker (with time-based reset for half-open retry)
        if self.failed_attempts.get(tool_type, 0) >= self.circuit_breaker_threshold:
            opened_at = self.circuit_opened_at.get(tool_type)
            if opened_at and datetime.now() - opened_at > timedelta(seconds=self.circuit_breaker_reset_time):
                logger.info(f"Circuit breaker half-open for {_tname(tool_type)}, attempting reset")
                self.reset_circuit_breaker(tool_type)
            else:
                logger.warning(f"Circuit breaker open for {_tname(tool_type)}")
                result = await self.router.call(tool_type, **kwargs)
                result.tool_call.error = "Circuit breaker open"
                return result

        # Check cache
        if cache_key in self.cache:
            cached_result, cached_time = self.cache[cache_key]
            if self._is_cached_valid(cached_time):
                logger.info(f"Cache hit for {_tname(tool_type)}")
                result = ToolResult(
                    tool_call=ToolCall(
                        tool_type=tool_type,
                        args=kwargs,
                        status=ToolStatus.SUCCESS,
                        result=cached_result,
                    ),
                    cached=True,
                )
                return result
            else:
                del self.cache[cache_key]

        # Get retry config
        config = self.retry_config.get(tool_type, {"max_retries": 1, "backoff": 0.5})
        max_retries = config["max_retries"]
        backoff = config["backoff"]

        # Retry loop
        last_result = None
        for attempt in range(max_retries + 1):
            try:
                # AskUserQuestion and AgentSpawn bypass the executor's per-tool
                # timeout. AskUserQuestion is governed by its own UI timeout; a
                # spawned agent is a long-running task governed by ITS OWN wall-
                # clock budget (AgentConfig.timeout_seconds). Binding it to the
                # tool I/O timeout is what killed legitimate 10-20 min sub-agents
                # and made the parent model re-launch a replacement.
                if _tname(tool_type) in (
                    _tname(ToolType.ASK_USER_QUESTION),
                    _tname(ToolType.SPAWN_AGENT),
                ):
                    result = await self.router.call(tool_type, **kwargs)
                else:
                    result = await asyncio.wait_for(
                        self.router.call(tool_type, **kwargs),
                        timeout=self.tool_timeout_seconds
                    )
                result.retry_count = attempt
                result.total_retries = max_retries

                if result.tool_call.success:
                    # Cache successful result
                    self.cache[cache_key] = (result.tool_call.result, datetime.now())
                    self.failed_attempts[tool_type] = 0
                    logger.info(f"Success on attempt {attempt + 1}", tool=_tname(tool_type))
                    return result

                last_result = result

                if attempt < max_retries:
                    wait_time = backoff * (2 ** attempt)
                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} for {_tname(tool_type)}",
                        wait_time=wait_time,
                    )
                    await asyncio.sleep(wait_time)

            except ApprovalRequired:
                # Permission gate wants human approval — BLOCK on the decision.
                # Approved → the grant is now set, so re-calling runs through the
                # gate; denied → fail; no UI → park for the loop to re-surface.
                logger.info(f"Tool {_tname(tool_type)} requires human approval", tool_type=_tname(tool_type))
                decision = await self._surface_approval(tool_type, kwargs, risk="medium")
                if decision in _DENIED_DECISIONS:
                    return ToolResult(
                        tool_call=ToolCall(
                            tool_type=tool_type,
                            args=kwargs,
                            status=ToolStatus.FAILED,
                            error=f"Tool '{_tname(tool_type)}' was denied by the user.",
                        )
                    )
                if decision not in _APPROVED_DECISIONS:
                    # No UI / no decision — park for the loop to re-surface.
                    return ToolResult(
                        tool_call=ToolCall(
                            tool_type=tool_type,
                            args=kwargs,
                            status=ToolStatus.AWAITING_APPROVAL,
                            error=f"Tool '{_tname(tool_type)}' requires human approval — not executed.",
                        )
                    )
                # Approved — the grant is set, so re-call executes through the gate.
                try:
                    result = await self.router.call(tool_type, **kwargs)
                except ApprovalRequired:
                    # Grant didn't stick (state wiped between surface and here) — park.
                    return ToolResult(
                        tool_call=ToolCall(
                            tool_type=tool_type,
                            args=kwargs,
                            status=ToolStatus.AWAITING_APPROVAL,
                            error=f"Tool '{_tname(tool_type)}' requires human approval — not executed.",
                        )
                    )
                result.retry_count = attempt
                result.total_retries = max_retries
                if result.tool_call.success:
                    self.cache[cache_key] = (result.tool_call.result, datetime.now())
                    self.failed_attempts[tool_type] = 0
                    logger.info(f"Approved tool executed", tool=_tname(tool_type))
                    return result
                last_result = result
            except asyncio.TimeoutError:
                logger.error(f"Tool call timed out after {self.tool_timeout_seconds}s: {_tname(tool_type)}")
                last_result = ToolResult(
                    tool_call=ToolCall(
                        tool_type=tool_type,
                        args=kwargs,
                        status=ToolStatus.TIMEOUT,
                        error=f"Tool execution timed out after {self.tool_timeout_seconds}s",
                    )
                )
            except Exception as e:
                logger.error(f"Unexpected error in execute: {e}")
                last_result = ToolResult(
                    tool_call=ToolCall(
                        tool_type=tool_type,
                        args=kwargs,
                        status=ToolStatus.FAILED,
                        error=str(e),
                    )
                )

        # All retries failed — update circuit breaker tracking
        if last_result:
            failed_count = self.failed_attempts.get(tool_type, 0) + 1
            self.failed_attempts[tool_type] = failed_count
            if failed_count >= self.circuit_breaker_threshold:
                self.circuit_opened_at[tool_type] = datetime.now()
            return last_result

        return ToolResult(
            tool_call=ToolCall(
                tool_type=tool_type,
                args=kwargs,
                status=ToolStatus.FAILED,
                error="All retries exhausted",
            )
        )

    def clear_cache(self) -> None:
        """Clear the entire cache."""
        self.cache.clear()
        logger.info("Cache cleared")

    def reset_circuit_breaker(self, tool_type: Optional[ToolType] = None) -> None:
        """Reset circuit breaker for a tool or all tools."""
        if tool_type:
            self.failed_attempts[tool_type] = 0
            logger.info(f"Circuit breaker reset for {_tname(tool_type)}")
        else:
            self.failed_attempts.clear()
            logger.info("All circuit breakers reset")
