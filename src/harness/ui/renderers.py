"""Render tool output and logs as Rich renderables in Claude Code style."""

import json
from datetime import datetime
from typing import Optional, Union, Any
from rich.text import Text
from rich.syntax import Syntax
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
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
        """Build the 'C ' block leader for a given block kind, colored per type.

        Each block type has distinct color for semantic clarity:
        - Assistant (coral): LLM responses
        - Tool (cyan): Tool calls & execution
        - Agent (gold): Agent spawning & status
        - Skill (green): Skill invocation
        - System (dim): Logs & metadata
        """
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
        Errors use red, success uses muted text.
        """
        result = Text()
        result.append(f"  {RESULT_MARKER} ", style="dim" if not is_error else "bold #f85149")
        content = body if isinstance(body, str) else str(body)
        style = "bold #f85149" if is_error else "dim"  # Red for errors, muted for success
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
        Tool name is bold cyan, params are muted for focus.
        """
        result = Text()
        result.append(tool_name, style="bold cyan")
        if params:
            try:
                arg_str = ", ".join(f"{k}={json.dumps(v)}" for k, v in params.items())
            except (TypeError, ValueError):
                arg_str = str(params)
            if len(arg_str) > 200:
                arg_str = arg_str[:200] + "…"
            result.append(f"({arg_str})", style="dim")
        else:
            result.append("()", style="dim")
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
        """Render agent status with icon and semantic color styling.

        Status indicators:
        - SPAWNING/RUNNING: gold (action in progress)
        - THINKING: gold (internal reasoning)
        - TOOL_CALLING: cyan (external tool use)
        - COMPLETED: green (success)
        - FAILED: red (error)
        - CANCELLED: dim (interrupted)
        """
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
            "SPAWNING": "bold #ffa657",      # gold
            "RUNNING": "bold #ffa657",       # gold
            "THINKING": "#ffa657",           # gold (not bold for subtle)
            "TOOL_CALLING": "bold #79c0ff",  # cyan
            "COMPLETED": "bold #3fb950",     # green
            "FAILED": "bold #f85149",        # red
            "CANCELLED": "dim",              # muted
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
    def format_tool_compact(tool_name: str, args: Optional[dict] = None, max_val: int = 32) -> Text:
        """Compact one-line tool render for a sub-agent card: name(key=val).

        Shows only the single most-informative argument, tightly truncated, so the
        card stays on one line regardless of how many args the tool received.
        """
        result = Text()
        result.append(tool_name, style="bold cyan")
        if not args:
            result.append("()", style="dim")
            return result
        chosen_key = None
        for key in ("path", "pattern", "command", "name", "query", "url",
                     "skill", "subject", "task_id", "taskId", "question"):
            if key in args and args[key]:
                chosen_key = key
                break
        if chosen_key is None:
            chosen_key = next(iter(args))
        val = str(args[chosen_key])
        if len(val) > max_val:
            val = val[:max_val] + "…"
        result.append(f"({chosen_key}={val})", style="dim")
        return result

    @staticmethod
    def render_subagent_card(
        glyph: str,
        gutter_color: str,
        agent_name: str,
        status: str,
        tool_count: int,
        current_tool: Union[Text, str, None] = None,
        detail: str = "",
        name_width: int = 12,
    ) -> Text:
        """Render one sub-agent's in-place card line for the shared main body.

        A single line per agent that is re-rendered in place as events arrive, so
        20 tool calls collapse to a running count plus the most-recent call rather
        than 20 separate lines. Layout:

            <glyph> <name>  <status> · N tools · → <recent tool>

        The gutter glyph+color is stable per agent so concurrent agents' cards stay
        visually distinct within the orchestrator body.
        """
        status_styles = {
            "SPAWNING": ("⚡", "bold #ffa657"),
            "RUNNING": ("🔄", "bold #ffa657"),
            "THINKING": ("🧠", "#ffa657"),
            "TOOL_CALLING": ("⚙", "bold #79c0ff"),
            "COMPLETED": ("✓", "bold #3fb950"),
            "FAILED": ("✗", "bold #f85149"),
            "CANCELLED": ("⊘", "dim"),
        }
        icon, status_style = status_styles.get(status, ("→", Styles.INPUT_TEXT))

        result = Text()
        result.append(f"{glyph} ", style=f"bold {gutter_color}")
        result.append(f"{agent_name[:name_width]:<{name_width}} ", style=f"bold {gutter_color}")
        result.append(f"{icon} ", style=status_style)
        result.append(status.lower(), style=status_style)

        result.append(f" · {tool_count} tool{'s' if tool_count != 1 else ''}", style=Styles.HINT)

        is_terminal = status in ("COMPLETED", "FAILED", "CANCELLED")
        if not is_terminal:
            result.append("  → ", style="bold #79c0ff")
            if current_tool is not None and (not isinstance(current_tool, str) or current_tool):
                result.append(current_tool if isinstance(current_tool, Text) else Text(str(current_tool)))
            else:
                result.append("thinking…", style=Styles.AGENT_THINKING)

        # Task detail is only shown before the agent starts calling tools; once
        # tools flow, the recent-tool tail carries the signal and detail would
        # push the card past one line.
        if detail and tool_count == 0:
            result.append(f"   {detail[:50]}", style=Styles.HINT)
        return result

    @staticmethod
    def render_orchestrator_card(
        status: str,
        tool_count: int,
        current_tool: Union[Text, str, None] = None,
        output_lines: Optional[list] = None,
        is_error: bool = False,
    ) -> Text:
        """Render the main orchestrator's single in-place tool card.

        Like a sub-agent card (status + running tool count + most-recent call),
        but the orchestrator additionally shows up to two lines of the latest
        tool's output beneath the call. A successful call with no output shows
        "No output" instead of an empty tail. Layout:

            ⚙ orchestrator  tool_calling · N tools  → recent(tool)
              ⎿ <first output line>
                <second output line>

        Collapsing every call into this one re-rendered line is what keeps the
        orchestrator from flooding scrollback with a block per call + full output.
        """
        status_styles = {
            "SPAWNING": ("⚡", "bold #ffa657"),
            "RUNNING": ("🔄", "bold #ffa657"),
            "THINKING": ("🧠", "#ffa657"),
            "TOOL_CALLING": ("⚙", "bold #79c0ff"),
            "COMPLETED": ("✓", "bold #3fb950"),
            "FAILED": ("✗", "bold #f85149"),
            "CANCELLED": ("⊘", "dim"),
        }
        icon, status_style = status_styles.get(status, ("→", Styles.INPUT_TEXT))

        result = Text()
        result.append(f"{icon} ", style=status_style)
        result.append("orchestrator ", style="bold #79c0ff")
        result.append(status.lower(), style=status_style)
        result.append(
            f" · {tool_count} tool{'s' if tool_count != 1 else ''}", style=Styles.HINT
        )

        is_terminal = status in ("COMPLETED", "FAILED", "CANCELLED")
        if not is_terminal:
            result.append("  → ", style="bold #79c0ff")
            if current_tool is not None and (not isinstance(current_tool, str) or current_tool):
                result.append(
                    current_tool if isinstance(current_tool, Text) else Text(str(current_tool))
                )
            else:
                result.append("thinking…", style=Styles.AGENT_THINKING)

        # Output tail: up to two lines under the most-recent call, or a "No output"
        # placeholder when the call finished with nothing to show.
        out_style = "bold #f85149" if is_error else "dim"
        lines = [ln for ln in (output_lines or []) if ln.strip()][:2]
        if lines:
            for i, line in enumerate(lines):
                marker = RESULT_MARKER if i == 0 else " "
                trimmed = line[:120]
                result.append(f"\n  {marker} ", style=out_style)
                result.append(trimmed, style=out_style)
        elif tool_count > 0:
            result.append(f"\n  {RESULT_MARKER} ", style=out_style)
            result.append(
                "No output" if not is_error else "failed", style=Styles.HINT
            )
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
    def render_question_card(
        questions: list[dict],
        multi_select: bool = False,
        answers: Optional[dict] = None,
    ) -> Text:
        """Render an AskUserQuestion card with speech-bubble style.

        Shows each question with its options, multi-select indicator, and
        any answers the user has provided. Compact enough for inline display.
        """
        result = Text()
        mode = "multi-select" if multi_select else "single-choice"
        result.append(f"💬 ", style="bold #58a6ff")
        result.append(f"Question ", style="bold #58a6ff")

        if answers:
            result.append(f"✓ ", style="bold #3fb950")
            result.append(f"answered", style="bold #3fb950")
        else:
            result.append(f"· {mode}", style="dim")

        for i, q in enumerate(questions):
            label = q.get("question", q.get("label", f"Question {i + 1}"))
            result.append(f"\n  {i + 1}. ", style="bold")
            result.append(label, style=Styles.INPUT_TEXT)
            options = q.get("options", q.get("answers", []))
            for opt in options[:4]:  # Show first 4 options inline
                opt_label = opt.get("label", opt.get("text", str(opt)[:30]))
                result.append(f"\n     · {opt_label}", style=Styles.HINT)
            if len(options) > 4:
                result.append(f"\n     … +{len(options) - 4} more", style=Styles.HINT)

        if answers:
            result.append(f"\n  → ", style="dim")
            result.append(str(answers), style="bold #3fb950")

        return result

    @staticmethod
    def render_task_card(
        task_id: str,
        subject: str,
        status: str = "pending",
        description: str = "",
    ) -> Text:
        """Render a task card with status indicator.

        Semantic coloring: pending (dim), in_progress (gold), completed (green),
        failed (red).
        """
        status_icons = {
            "pending": "○",
            "in_progress": "◷",
            "completed": "✓",
            "failed": "✗",
            "deleted": "⊘",
            "running": "▶",
            "done": "✓",
        }
        status_styles = {
            "pending": "dim",
            "in_progress": "bold #ffa657",
            "completed": "bold #3fb950",
            "failed": "bold #f85149",
            "deleted": "dim",
            "running": "bold #79c0ff",
            "done": "bold #3fb950",
        }
        icon = status_icons.get(status.lower(), "○")
        style = status_styles.get(status.lower(), "dim")

        result = Text()
        result.append(f"{icon} ", style=style)
        result.append(f"[{task_id[:12]}] ", style=Styles.HINT)
        result.append(subject, style="bold")
        result.append(f" — {status}", style=style)
        if description:
            desc = description[:60] + "…" if len(description) > 60 else description
            result.append(f"\n  {desc}", style=Styles.INPUT_TEXT)
        return result

    @staticmethod
    def render_task_list_panel(
        tasks: list[dict[str, Any]],
        title: str = "Tasks",
    ) -> Union[Panel, Text]:
        """Render a task list as a compact Rich Panel or fallback Text.

        Each task dict expects: id, subject, status. Optional: description.
        Empty lists render as a muted 'no tasks' message.
        """
        if not tasks:
            return Text("No tasks", style=Styles.HINT)

        table = Table(
            title=title,
            title_style="bold blue",
            border_style=Styles.BORDER,
            show_header=True,
            header_style="bold",
            box=None,
            padding=(0, 1),
        )
        table.add_column("", width=2)  # status icon
        table.add_column("ID", style=Styles.HINT, no_wrap=True)
        table.add_column("Subject", style="bold")
        table.add_column("Status")

        status_icons = {
            "pending": ("○", "dim"),
            "in_progress": ("◷", "#ffa657"),
            "completed": ("✓", "#3fb950"),
            "failed": ("✗", "#f85149"),
            "running": ("▶", "#79c0ff"),
        }

        for task in tasks:
            s = task.get("status", "pending").lower()
            icon, icon_style = status_icons.get(s, ("○", "dim"))
            tid = task.get("id", task.get("task_id", ""))[:10]
            subj = task.get("subject", task.get("name", ""))
            table.add_row(
                f"[{icon_style}]{icon}[/{icon_style}]",
                tid,
                subj,
                f"[{icon_style}]{s}[/{icon_style}]",
            )

        return Panel(table, title=f"[bold blue]{title}[/bold blue]", border_style=Styles.BORDER)

    @staticmethod
    def render_iteration_separator(iteration: int, total: int) -> Panel:
        """Render iteration separator banner."""
        title = f"[bold cyan]Iteration {iteration}/{total}[/bold cyan]"
        return Panel("", title=title, style=Styles.BORDER)

    # ── Interactive UI components ──────────────────────────────────────────

    @staticmethod
    def render_processing_indicator(
        is_processing: bool, show_indicator: bool, spinner_frame: int
    ) -> Text:
        """Render the input-bar processing indicator.

        When the system is busy the indicator shows a cycling spinner + "Processing..."
        text that blinks on/off every 4 frames (400ms). When idle only the prompt
        marker ``❯ _`` is shown — no spinner, no text.
        """
        result = Text()
        if is_processing:
            spinner_chars = ["🔄", "🔃", "🔄", "🔃"]
            spinner = spinner_chars[spinner_frame % len(spinner_chars)]
            if show_indicator:
                result.append(f"{spinner} Processing...   ", style="bold #ffa657")
            else:
                result.append(" " * 22, style="dim")
        result.append("❯ ", style="bold #bc8ef7")
        result.append("_", style="#79c0ff")
        return result

    @staticmethod
    def render_picker_card(state: dict) -> Panel:
        """Render the interactive picker card for AskUserQuestion.

        Shows the question, a header chip (if present), numbered options
        with keyboard focus highlighting, an "Other" text-input mode, and
        a timeout countdown when one is active.
        """
        question = state.get("question", "")
        header = state.get("header", "")
        options = state.get("options", [])
        multi_select = state.get("multi_select", False)
        focus_idx = state.get("focus_index", 0)
        selections = state.get("selections", set())
        mode = state.get("mode", "options")

        content = Text()

        # Question
        content.append(f"  {question}", style="bold #e6edf3")
        content.append("\n\n")

        # Header chip
        if header:
            content.append(f"  {header}  ", style="bold #fbbf24 on #27272a")
            content.append("\n\n")

        if mode == "options":
            for i, opt in enumerate(options):
                label = opt.get("label", f"Option {i + 1}")
                desc = opt.get("description", "")
                is_focused = i == focus_idx
                is_selected = i in selections

                sel_mark = "◉" if is_selected else "○"
                if multi_select:
                    prefix = f"❯ {sel_mark}" if is_focused else f"  {sel_mark}"
                else:
                    prefix = "❯" if is_focused else " "

                if is_focused:
                    content.append(f"  {prefix} {i + 1}. {label}", style="bold #fbbf24")
                    content.append("\n")
                    if desc:
                        content.append(f"     {desc}", style="#8b949e")
                        content.append("\n")
                else:
                    content.append(f"  {prefix} {i + 1}. {label}", style="#8b949e")
                    content.append("\n")
                    if desc:
                        content.append(f"     {desc}", style="#484f58")
                        content.append("\n")
                content.append("\n")

            # Other option row
            content.append("  ───────────────────────────────────", style="dim")
            content.append("\n")
            content.append("  [Other] Type your own answer...", style="#58a6ff")
            content.append("\n")
        else:
            content.append("  Other: ", style="bold #e6edf3")
            content.append("\n")
            other_buf = state.get("other_buffer", "")
            content.append(f"  {other_buf}_", style="#79c0ff")
            content.append("\n")

        # Timeout countdown (last 20 seconds)
        timeout_at = state.get("timeout_at")
        if timeout_at:
            remaining = max(0, int((timeout_at - datetime.now()).total_seconds()))
            if remaining <= 20:
                content.append(f"  ⏱ Auto-continue in {remaining}s...", style="bold #f85149")
                content.append("\n")

        # Keyboard hints
        n = len(options)
        if mode == "options":
            if multi_select:
                content.append(
                    f"  ↑↓ navigate · 1-{n} select · Space toggle · Tab Other · Enter confirm",
                    style="dim",
                )
            else:
                content.append(
                    f"  ↑↓ navigate · 1-{n} select · Tab Other · Enter confirm",
                    style="dim",
                )
        else:
            content.append("  Enter submit · Esc cancel", style="dim")

        return Panel(
            content,
            title="📋 Question",
            title_align="left",
            border_style="#58a6ff",
            padding=(0, 1),
        )

    @staticmethod
    def render_task_board(
        tasks: list,
        goal: str = "",
        show_cursor: bool = False,
        total_tokens: int = 0,
    ) -> Optional[Panel]:
        """Render the live task board with status icons and progress bar.

        Each task item dict expects: id, subject, status. Optional:
        owner, blocked_by, active_form.  Completed tasks are shown
        with strikethrough. A progress bar at the bottom shows the
        completion ratio. Returns None when the task list is empty.

        When show_cursor is True a blinking heartbeat cursor appears;
        total_tokens shows accumulated token usage below the bar.
        """
        if not tasks:
            return None

        status_icons = {
            "pending": "○",
            "in_progress": "🔄",
            "completed": "✅",
            "blocked": "⏸️",
            "deleted": "🗑️",
        }
        status_colors = {
            "pending": "#71717a",
            "in_progress": "#fbbf24",
            "completed": "#10b981",
            "blocked": "#71717a",
            "deleted": "#ef4444",
        }

        content = Text()
        completed = 0
        total = len(tasks)

        for i, t in enumerate(tasks):
            status = t.get("status", "pending")
            subject = t.get("subject", "Untitled")
            icon = status_icons.get(status, "○")
            color = status_colors.get(status, "#71717a")

            if status == "completed":
                completed += 1
                content.append(f"  {icon} {i + 1}. {subject}", style=f"strikethrough {color}")
            else:
                content.append(f"  {icon} {i + 1}. {subject}", style="bold #e6edf3")

            # Annotations
            if status == "in_progress":
                owner = t.get("owner") or t.get("active_form", "")
                if owner:
                    content.append(f"  [{owner}]", style="dim")
            elif status == "blocked":
                blocked_by = t.get("blocked_by", set())
                if blocked_by:
                    refs = ", ".join(f"#{b}" for b in list(blocked_by)[:3])
                    content.append(f"  [blocked by: {refs}]", style="dim")

            content.append("\n")

        # Progress bar
        pct = (completed / total * 100) if total > 0 else 0
        bar_width = 20
        filled = int(bar_width * completed / total) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_width - filled)
        content.append(f"  {'─' * 40}", style="dim")
        content.append("\n")
        content.append(f"  {completed} of {total}  {bar}  {int(pct)}%", style="dim")

        # Blinking heartbeat cursor + token count
        if total_tokens:
            content.append("\n")
            content.append(f"  ⚡ {total_tokens}", style="#58a6ff")
        if show_cursor:
            content.append("  ▎", style="#58a6ff")
        else:
            content.append("   ", style="dim")

        title = f"{'✅ All done!' if completed == total else f'📋 {total - completed} tasks remaining'}"
        return Panel(
            content,
            title=title,
            title_align="left",
            border_style="#30363d",
            padding=(0, 1),
        )

    @staticmethod
    def render_permission_prompt(
        tool: str, command_str: str, risk: str, description: str = ""
    ) -> Panel:
        """Render a permission prompt with amber border and command block."""
        content = Text()
        content.append(f"  Tool: ", style="bold #e6edf3")
        content.append(tool, style="bold cyan")
        content.append("\n\n")

        # Code-style command block
        cmd_trimmed = command_str[:80]
        content.append(f"  ┌─{'─' * min(len(cmd_trimmed), 60)}─┐", style="dim")
        content.append("\n")
        content.append(f"  │ {cmd_trimmed}", style="#e6edf3")
        content.append("\n")
        content.append(f"  └─{'─' * min(len(cmd_trimmed), 60)}─┘", style="dim")
        content.append("\n\n")

        if description:
            content.append(f"  {description}", style="#8b949e")
            content.append("\n\n")

        risk_color = "#f59e0b" if risk in ("high", "critical") else "#8b949e"
        content.append(f"  Risk: {risk}", style=risk_color)
        content.append("\n\n")
        content.append("  [Y] Yes      [N] No      [A] Always      [S] Skip", style="bold cyan")
        content.append("\n\n")
        content.append("  ⚠ This action is destructive and cannot be undone.", style="bold #f85149")

        return Panel(
            content,
            title="⚠ Permission Required",
            title_align="left",
            border_style="#f59e0b",
            padding=(0, 1),
        )

    @staticmethod
    def render_question_confirmation(question: str, answer: str) -> Text:
        """Render a question confirmation for the scrollback (after answering).

        Appends to the conversation history so the user can see what was asked
        and what they answered. Format:
            C 📋 <question>
               → <answer>
        """
        result = OutputRenderer._lead(BlockKind.SYSTEM)
        result.append("📋 ", style="#58a6ff")
        result.append(question, style="bold")
        result.append("\n")
        result.append("  → ", style="dim")
        result.append(answer, style="bold #3fb950")
        return result
