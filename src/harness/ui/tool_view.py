"""Tool execution display component."""

from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum
from rich.table import Table
from .claude_code_style import Styles


class ToolStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class ToolCall:
    tool_name: str
    status: ToolStatus = ToolStatus.PENDING
    args: Dict = None
    result: Optional[str] = None
    error: Optional[str] = None


class ToolView:
    def __init__(self):
        self.tools: Dict[str, ToolCall] = {}

    def start_tool(self, tool_id: str, tool_name: str, args: Dict) -> None:
        self.tools[tool_id] = ToolCall(tool_name=tool_name, args=args or {})

    def finish_tool(self, tool_id: str, result: str) -> None:
        if tool_id in self.tools:
            self.tools[tool_id].result = result
            self.tools[tool_id].status = ToolStatus.DONE

    def error_tool(self, tool_id: str, error: str) -> None:
        if tool_id in self.tools:
            self.tools[tool_id].error = error
            self.tools[tool_id].status = ToolStatus.ERROR

    def render(self) -> Table:
        table = Table(title="Tool Execution", show_header=True, header_style=Styles.TITLE)
        table.add_column("Tool", style=Styles.PROMPT)
        table.add_column("Status", style=Styles.INPUT_TEXT)
        table.add_column("Result/Error", style=Styles.HINT)

        if not self.tools:
            table.add_row("(no tool calls)", "", "")
            return table

        for tool_id, tool in self.tools.items():
            status_icons = {
                ToolStatus.PENDING: "⏳",
                ToolStatus.RUNNING: "▶️",
                ToolStatus.DONE: "✅",
                ToolStatus.ERROR: "❌",
            }
            status_icon = status_icons.get(tool.status, "?")
            status_text = f"{status_icon} {tool.status.value}"
            output = tool.error or tool.result or ""
            table.add_row(tool.tool_name, status_text, output[:50])

        return table
