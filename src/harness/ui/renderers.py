"""Render tool output and logs as Rich renderables in Claude Code style."""

import json
from typing import Optional, Union
from rich.text import Text
from rich.syntax import Syntax
from rich.table import Table
from rich.panel import Panel
from .claude_code_style import (
    Styles,
    BLOCK_MARKER,
    RESULT_MARKER,
    BlockKind,
    BLOCK_MARKER_COLORS,
)
from .markdown_text import render_markdown


class OutputRenderer:
    """Converts various output formats to Rich renderables."""

    @staticmethod
    def _lead(kind: str) -> Text:
        """Build the 'C ' block leader for a given block kind, colored per type."""
        color = BLOCK_MARKER_COLORS.get(kind, BLOCK_MARKER_COLORS[BlockKind.SYSTEM])
        lead = Text()
        lead.append(f"{BLOCK_MARKER} ", style=f"bold {color}")
        return lead

    @staticmethod
    def render_block(kind: str, body: Text, markdown: bool = False) -> Text:
        """Wrap `body` as a top-level block with the 'C' leader.

        If `markdown` is True, `body` is treated as a markdown string (converted
        via render_markdown) rather than a pre-built Text.
        """
        result = OutputRenderer._lead(kind)
        if markdown:
            result.append(render_markdown(str(body)))
        else:
            result.append(body if isinstance(body, Text) else Text(str(body)))
        return result

    @staticmethod
    def render_result_block(body, is_error: bool = False) -> Text:
        """Wrap `body` as a tool result, joined under its call with '⎿'.

        Long results are truncated to keep the scrollback readable.
        """
        result = Text()
        result.append(f"  {RESULT_MARKER} ", style=Styles.HINT)
        content = body if isinstance(body, str) else str(body)
        style = Styles.ERROR if is_error else Styles.INPUT_TEXT
        truncated = content[:500]
        result.append(truncated, style=style)
        if len(content) > 500:
            result.append("… (truncated)", style=Styles.HINT)
        return result

    @staticmethod
    def render_json(data: dict, title: Optional[str] = None) -> Union[Text, Table]:
        """Render JSON data as a table or text."""
        try:
            if isinstance(data, list) and data and isinstance(data[0], dict):
                table = Table(title=title or "Data")
                keys = set()
                for item in data:
                    keys.update(item.keys())

                for key in keys:
                    table.add_column(str(key))

                for item in data:
                    table.add_row(*[str(item.get(k, "")) for k in keys])

                return table

            json_str = json.dumps(data, indent=2)
            return Syntax(json_str, "json", theme="monokai", line_numbers=False)
        except Exception:
            return Text(str(data), style=Styles.INPUT_TEXT)

    @staticmethod
    def render_code(code: str, language: str = "python", title: Optional[str] = None) -> Syntax:
        """Render code block with syntax highlighting."""
        return Syntax(
            code,
            language,
            theme="monokai",
            line_numbers=True,
            title=title,
            background_color="default",
        )

    @staticmethod
    def render_error(message: str) -> Text:
        """Render error message."""
        return Text(f"Error: {message}", style=Styles.ERROR)

    @staticmethod
    def render_success(message: str) -> Text:
        """Render success message."""
        return Text(f"Success: {message}", style=Styles.SUCCESS)

    @staticmethod
    def render_info(message: str) -> Text:
        """Render info message."""
        return Text(f"Info: {message}", style=Styles.INFO)

    @staticmethod
    def render_log_entry(entry) -> Text:
        """Render a log entry with timestamp and styling."""
        timestamp = entry.timestamp.strftime("%H:%M:%S")

        level_styles = {
            "DEBUG": Styles.INPUT_TEXT,
            "INFO": Styles.INFO,
            "WARNING": Styles.INPUT_TEXT,
            "ERROR": Styles.ERROR,
            "CRITICAL": Styles.ERROR,
        }

        style = level_styles.get(entry.level.value, Styles.INPUT_TEXT)

        text = Text()
        text.append(f"[{timestamp}] ", style=Styles.HINT)
        text.append(f"[{entry.source.upper()}] ", style=style)
        text.append(entry.message, style=style)

        return text

    @staticmethod
    def render_agent_thinking(text: str) -> Text:
        """Render agent thinking with icon."""
        result = Text()
        result.append("🧠 ", style=Styles.INFO)
        result.append(text, style=Styles.AGENT_THINKING)
        return result

    @staticmethod
    def render_tool_call(tool_name: str, params: dict = None) -> Text:
        """Render a compact one-line tool call: name(arg=val, …).

        Designed to sit under the 'C' block marker, so it carries no icon.
        """
        result = Text()
        result.append(tool_name, style=Styles.TOOL_CALL)
        if params:
            try:
                arg_str = ", ".join(f"{k}={json.dumps(v)}" for k, v in params.items())
            except (TypeError, ValueError):
                arg_str = str(params)
            if len(arg_str) > 200:
                arg_str = arg_str[:200] + "…"
            result.append(f"({arg_str})", style=Styles.INPUT_TEXT)
        else:
            result.append("()", style=Styles.INPUT_TEXT)
        return result

    @staticmethod
    def render_tool_output(tool_name: str, output: str, is_error: bool = False) -> Text:
        """Render tool output with icon."""
        result = Text()
        result.append("📥 ", style=Styles.INFO)
        style = Styles.ERROR if is_error else Styles.SUCCESS
        result.append(f"{tool_name}: {output}", style=style)
        return result

    @staticmethod
    def render_event_tree(event_name: str, message: str, is_root: bool = True, indent: int = 0) -> Text:
        """Render event in tree hierarchy with L-shaped indicator."""
        indent_str = "  " * indent
        tree_char = "L " if is_root else "├ "
        result = Text()
        result.append(indent_str + tree_char, style=Styles.BORDER)
        result.append(event_name, style=Styles.TOOL_CALL)
        result.append(f": {message}", style=Styles.INPUT_TEXT)
        return result

    @staticmethod
    def render_llm_response_stream(content: str, model: str = "Claude") -> Text:
        """Render streaming LLM response in Claude Code style."""
        result = Text()
        result.append(f"{model}: ", style="bold cyan")
        result.append(content, style=Styles.INPUT_TEXT)
        return result

    @staticmethod
    def render_agent_status(agent_name: str, status: str, detail: str = "") -> Text:
        """Render agent status with icon and styling."""
        status_icons = {
            "SPAWNING": "⚡",
            "RUNNING": "🔄",
            "THINKING": "🧠",
            "TOOL_CALLING": "⚙️",
            "COMPLETED": "✓",
            "FAILED": "✗",
            "CANCELLED": "⊘",
        }
        icon = status_icons.get(status, "→")

        status_styles = {
            "SPAWNING": Styles.INFO,
            "RUNNING": Styles.INFO,
            "THINKING": Styles.AGENT_THINKING,
            "TOOL_CALLING": Styles.TOOL_CALL,
            "COMPLETED": Styles.SUCCESS,
            "FAILED": Styles.ERROR,
            "CANCELLED": Styles.HINT,
        }
        style = status_styles.get(status, Styles.INPUT_TEXT)

        result = Text()
        result.append(f"{icon} ", style=style)
        result.append(f"[{agent_name}] ", style="bold")
        result.append(status, style=style)
        if detail:
            result.append(f" — {detail}", style=Styles.HINT)
        return result

    @staticmethod
    def render_skill_call(skill_name: str, params: Optional[dict] = None) -> Text:
        """Render skill invocation with parameters."""
        result = Text()
        result.append("🎯 ", style=Styles.INFO)
        result.append("Skill: ", style="bold")
        result.append(skill_name, style="cyan")

        if params:
            try:
                params_str = json.dumps(params, indent=0)
                result.append(f" {params_str}", style=Styles.HINT)
            except (TypeError, ValueError):
                result.append(f" {params}", style=Styles.HINT)
        return result

    @staticmethod
    def render_agent_call(agent_name: str, task: str, iteration: Optional[int] = None) -> Text:
        """Render agent spawn event."""
        result = Text()
        result.append("🤖 ", style=Styles.INFO)
        result.append("Agent: ", style="bold")
        result.append(agent_name, style="magenta")

        if iteration:
            result.append(f" (iteration {iteration})", style=Styles.HINT)

        result.append(f"\n  → {task}", style=Styles.INPUT_TEXT)
        return result

    @staticmethod
    def render_tool_call_detailed(tool_name: str, params: dict, tool_id: str = "") -> Union[Text, Panel]:
        """Render detailed tool call with formatted parameters."""
        result = Text()
        result.append("⚙️  Tool: ", style="bold cyan")
        result.append(tool_name, style="cyan")

        if tool_id:
            result.append(f" (id: {tool_id[:8]}...)", style=Styles.HINT)

        # Format parameters
        if params:
            result.append("\n  Parameters:\n", style=Styles.HINT)
            try:
                params_str = json.dumps(params, indent=4)
                # Add to syntax highlighted code block
                syntax = Syntax(
                    params_str,
                    "json",
                    theme="monokai",
                    line_numbers=False,
                    background_color="default",
                )
                return Panel(syntax, title="[cyan]Tool Call[/cyan]", expand=False)
            except (TypeError, ValueError):
                result.append(str(params), style=Styles.INPUT_TEXT)

        return result

    @staticmethod
    def render_tool_result_detailed(tool_name: str, result_content: str, is_error: bool = False) -> Union[Text, Panel]:
        """Render detailed tool result with error handling."""
        style = Styles.ERROR if is_error else Styles.SUCCESS
        icon = "❌" if is_error else "✅"

        # Try to render as JSON if result looks like JSON
        try:
            if isinstance(result_content, str) and result_content.strip().startswith(("{", "[")):
                data = json.loads(result_content)
                syntax = Syntax(
                    json.dumps(data, indent=2),
                    "json",
                    theme="monokai",
                    line_numbers=False,
                    background_color="default",
                )
                title = f"[red]Tool Result (Error)[/red]" if is_error else f"[green]Tool Result[/green]"
                return Panel(syntax, title=title, expand=False)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        # Fallback to plain text
        result = Text()
        result.append(f"{icon} ", style=style)
        result.append(f"{tool_name}: ", style="bold")
        result.append(result_content[:200], style=style)  # Truncate very long outputs
        if len(result_content) > 200:
            result.append("... (truncated)", style=Styles.HINT)
        return result

    @staticmethod
    def render_iteration_separator(iteration: int, total: int) -> Panel:
        """Render iteration separator banner."""
        title = f"[bold cyan]Iteration {iteration}/{total}[/bold cyan]"
        return Panel("", title=title, style=Styles.BORDER)
