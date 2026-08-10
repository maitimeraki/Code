"""Tool routing and dispatch system."""

import asyncio
from typing import Callable, Any, Optional, Dict
from datetime import datetime
import structlog

from .models import ToolCall, ToolType, ToolStatus, ToolResult, ToolBudget
from .permissions import ApprovalRequired

logger = structlog.get_logger(__name__)


class ToolRouter:
    """Route tool calls to appropriate handlers."""

    def __init__(self):
        self.budget = ToolBudget()
        self.handlers: Dict[str, Callable] = {}
        # Dynamically registered (MCP) tool definitions, keyed by LLM name.
        self.mcp_tools: Dict[str, Any] = {}
        self.call_history: list[ToolCall] = []

    def register_handler(self, tool_type: str, handler: Callable) -> None:
        """Register a tool handler keyed by its LLM-facing name."""
        self.handlers[tool_type] = handler
        logger.info(f"Registered handler for {getattr(tool_type, 'value', tool_type)}")

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

            tool_name = tool_type if isinstance(tool_type, str) else getattr(tool_type, "value", str(tool_type))

            # Unified dispatch: built-in and MCP tools (mcp__server__tool) are both
            # registered in self.handlers by factory.build_scoped_router().
            if tool_type not in self.handlers:
                raise ValueError(f"Unknown tool: {tool_name}")

            handler = self.handlers[tool_type]
            logger.info(f"Calling {tool_name}", args=kwargs)
            result = await handler(**kwargs)

            tool_call.status = ToolStatus.SUCCESS
            tool_call.result = result
            tool_call.tokens_used = len(str(result).split())

        except ApprovalRequired:
            # Not an execution failure — permission gate wants human approval.
            # Re-raise so the executor parks the call as AWAITING_APPROVAL.
            raise

        except asyncio.TimeoutError:
            tool_call.status = ToolStatus.TIMEOUT
            tool_call.error = "Tool execution timed out"
            logger.warning(f"Timeout for {getattr(tool_type, 'value', tool_type)}")

        except Exception as e:
            tool_call.status = ToolStatus.FAILED
            tool_call.error = str(e)
            logger.error(f"Tool failed: {getattr(tool_type, 'value', tool_type)}", error=str(e))

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
