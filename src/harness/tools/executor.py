"""Tool execution with retry and caching logic."""

import asyncio
import hashlib
from typing import Optional, Dict, Any
import structlog
from datetime import datetime, timedelta

from .models import ToolCall, ToolType, ToolStatus, ToolResult
from .router import ToolRouter

logger = structlog.get_logger(__name__)


class ToolExecutor:
    """Execute tools with retry, caching, and circuit breaker."""

    def __init__(self, router: ToolRouter):
        self.router = router
        self.cache: Dict[str, tuple[Any, datetime]] = {}
        self.cache_ttl = timedelta(hours=1)
        self.retry_config = {
            ToolType.READ: {"max_retries": 2, "backoff": 0.5},
            ToolType.WRITE: {"max_retries": 1, "backoff": 1.0},
            ToolType.BASH: {"max_retries": 3, "backoff": 0.5},
            ToolType.GREP: {"max_retries": 2, "backoff": 0.5},
            ToolType.GLOB: {"max_retries": 1, "backoff": 0.5},
        }
        self.circuit_breaker_threshold = 5
        self.circuit_breaker_reset_time = 60
        self.failed_attempts = {}

    def _cache_key(self, tool_type: ToolType, **kwargs) -> str:
        """Generate cache key for tool call."""
        key_str = f"{tool_type.value}:{str(sorted(kwargs.items()))}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def _is_cached_valid(self, cached_time: datetime) -> bool:
        """Check if cached result is still valid."""
        return datetime.now() - cached_time < self.cache_ttl

    async def execute(
        self,
        tool_type: ToolType,
        **kwargs
    ) -> ToolResult:
        """Execute tool with retry and caching."""
        cache_key = self._cache_key(tool_type, **kwargs)

        # Check circuit breaker
        if self.failed_attempts.get(tool_type, 0) >= self.circuit_breaker_threshold:
            logger.warning(f"Circuit breaker open for {tool_type.value}")
            result = await self.router.call(tool_type, **kwargs)
            result.tool_call.error = "Circuit breaker open"
            return result

        # Check cache
        if cache_key in self.cache:
            cached_result, cached_time = self.cache[cache_key]
            if self._is_cached_valid(cached_time):
                logger.info(f"Cache hit for {tool_type.value}")
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
                result = await self.router.call(tool_type, **kwargs)
                result.retry_count = attempt
                result.total_retries = max_retries

                if result.tool_call.success:
                    # Cache successful result
                    self.cache[cache_key] = (result.tool_call.result, datetime.now())
                    self.failed_attempts[tool_type] = 0
                    logger.info(f"Success on attempt {attempt + 1}", tool=tool_type.value)
                    return result

                last_result = result

                if attempt < max_retries:
                    wait_time = backoff * (2 ** attempt)
                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} for {tool_type.value}",
                        wait_time=wait_time,
                    )
                    await asyncio.sleep(wait_time)

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

        # All retries failed
        if last_result:
            self.failed_attempts[tool_type] = self.failed_attempts.get(tool_type, 0) + 1
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
            logger.info(f"Circuit breaker reset for {tool_type.value}")
        else:
            self.failed_attempts.clear()
            logger.info("All circuit breakers reset")
