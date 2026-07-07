"""Render tool output and logs as Rich renderables."""

import json
from typing import Optional, Union
from rich.text import Text
from rich.syntax import Syntax
from rich.table import Table
from .claude_code_style import Styles


class OutputRenderer:
    """Converts various output formats to Rich renderables."""

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
        """Render agent thinking."""
        return Text(text, style="dim italic")

    @staticmethod
    def render_tool_output(tool_name: str, output: str, is_error: bool = False) -> Text:
        """Render tool output."""
        style = Styles.ERROR if is_error else Styles.SUCCESS
        return Text(f"{tool_name}: {output}", style=style)
