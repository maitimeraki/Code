"""Tool routing and dispatch system."""

import asyncio
from typing import Callable, Any, Optional, Dict
from datetime import datetime
import structlog

from .models import ToolCall, ToolType, ToolStatus, ToolResult, ToolBudget

logger = structlog.get_logger(__name__)


class ToolRouter:
    """Route tool calls to appropriate handlers."""

    def __init__(self):
        self.budget = ToolBudget()
        self.handlers: Dict[ToolType, Callable] = {}
        self.call_history: list[ToolCall] = []

    def register_handler(self, tool_type: ToolType, handler: Callable) -> None:
        """Register a tool handler."""
        self.handlers[tool_type] = handler
        logger.info(f"Registered handler for {tool_type.value}")

    async def call(
        self,
        tool_type: ToolType,
        **kwargs
    ) -> ToolResult:
        """Execute a tool call."""
        tool_call = ToolCall(
            tool_type=tool_type,
            args=kwargs,
            status=ToolStatus.RUNNING,
            started_at=datetime.now(),
        )

        try:
            # Check budget
            if not self.budget.has_budget:
                raise RuntimeError("Token budget exhausted")

            # Check handler exists
            if tool_type not in self.handlers:
                raise ValueError(f"Unknown tool: {tool_type.value}")

            # Execute tool
            handler = self.handlers[tool_type]
            logger.info(f"Calling {tool_type.value}", args=kwargs)

            result = await handler(**kwargs)

            tool_call.status = ToolStatus.SUCCESS
            tool_call.result = result
            tool_call.tokens_used = len(str(result).split())

        except asyncio.TimeoutError:
            tool_call.status = ToolStatus.TIMEOUT
            tool_call.error = "Tool execution timed out"
            logger.warning(f"Timeout for {tool_type.value}")

        except Exception as e:
            tool_call.status = ToolStatus.FAILED
            tool_call.error = str(e)
            logger.error(f"Tool failed: {tool_type.value}", error=str(e))

        finally:
            tool_call.completed_at = datetime.now()
            self.budget.tokens_used += tool_call.tokens_used
            self.call_history.append(tool_call)

        return ToolResult(tool_call=tool_call)

    def get_stats(self) -> dict:
        """Get tool usage statistics."""
        total_calls = len(self.call_history)
        successful = sum(1 for c in self.call_history if c.success)
        failed = sum(1 for c in self.call_history if c.status == ToolStatus.FAILED)
        total_duration = sum(c.duration_seconds or 0 for c in self.call_history)

        return {
            "total_calls": total_calls,
            "successful": successful,
            "failed": failed,
            "total_duration_seconds": total_duration,
            "tokens_used": self.budget.tokens_used,
            "tokens_remaining": self.budget.remaining_tokens,
        }
