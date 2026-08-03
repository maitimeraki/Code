"""Inline renderers for terminal UI — ● is the universal progress indicator."""

import json
from typing import Optional, Any
from rich.text import Text
from .claude_code_style import Styles, Colors
from .markdown_text import render_markdown


def _format_args_compact(args: Optional[dict] = None, max_val: int = 40) -> str:
    """Format tool arguments as a compact display string."""
    if not args:
        return ""

    if "file_count" in args:
        return f"({args['file_count']} files)"
    paths = args.get("paths", [])
    if isinstance(paths, list) and len(paths) > 1:
        return f"({len(paths)} files)"
    if isinstance(paths, list) and len(paths) == 1:
        return paths[0]

    for key in ("path", "pattern", "command", "name", "query", "url",
                 "skill", "subject", "task_id", "taskId", "question", "file_path"):
        val = args.get(key)
        if val and isinstance(val, str):
            s = str(val)
            if len(s) > max_val:
                s = s[:max_val] + "…"
            return s

    for v in args.values():
        if isinstance(v, str):
            s = v
            if len(s) > max_val:
                s = s[:max_val] + "…"
            return s
    return ""


def _split_path(path: str) -> tuple[str, str]:
    """Split a path into (dirname, basename) for styled display.

    Returns ("", path) when there's no directory component.
    """
    import os.path
    dirname = os.path.dirname(path)
    basename = os.path.basename(path)
    if not dirname:
        return ("", basename)
    return (dirname + "/", basename)


def _truncate_front(path: str, max_len: int = 50) -> str:
    """Truncate a path from the front, preserving the tail.

    Returns "...eply/nested/path/file.py" when path exceeds max_len.
    """
    if len(path) <= max_len:
        return path
    return "…" + path[-(max_len - 1):]


def _format_tool_args(tool: str, args: Optional[dict]) -> str:
    """Format tool name + args as a plain string for display."""
    arg_str = _format_args_compact(args)
    if arg_str:
        return f"{tool} {arg_str}"
    return tool


class OutputRenderer:
    """Inline renderer — everything returns Rich Text, no panels or cards.

    '●' is the universal progress indicator:
      - Blinking ● → in progress (dim #888888)
      - Green ●    → completed successfully (#4ade80)
      - Red ●      → completed with error (#f87171)
    """

    # ── Block rendering ──────────────────────────────────────────

    @staticmethod
    def render_block(kind: str, body, markdown: bool = False) -> Text:
        """Render a block as inline text.

        When ``kind == "assistant"`` and markdown is ``True``, prepends
        ``● `` (bold white big dot) before the rendered markdown so each
        LLM output block is visually identified in the scrollback.
        """
        if markdown:
            rendered = render_markdown(str(body))
            if kind == "assistant":
                prefix = Text("● ", style="bold white")
                return prefix + rendered
            return rendered
        if isinstance(body, Text):
            return body
        return Text(str(body), style=Styles.AI)

    # ── Tool display ─────────────────────────────────────────────

    @staticmethod
    def render_tool_call_line(tool: str, args: Optional[dict] = None,
                               is_working: bool = False,
                               is_error: bool = False,
                               concurrent_count: int = 0) -> Text:
        """Render a tool call line with leading colored dot indicator and path highlighting.

        The dot shows tool status at a glance:
          ● (blinking gray) → in progress
          ● (green)         → completed successfully
          ● (red)           → completed with error

        For file-reading tools (Read/Glob/Grep) the path is split into a dimmed
        directory portion and a highlighted filename. Concurrent calls (multiple
        reads in one LLM turn) show a count badge.

        Working:  ● Read .../ui/terminal.py +2    ← blinking dot in progress
        Success:  ● Read .../ui/terminal.py        ← green dot
        Error:    ● Read .../ui/terminal.py         ← red dot
        """
        result = Text()
        if is_working:
            dot_style = Styles.WORKING_BLINK
        elif is_error:
            dot_style = Styles.TOOL_DOT_ERROR
        else:
            dot_style = Styles.TOOL_DOT_SUCCESS
        result.append("● ", style=dot_style)  # ● big dot

        # Show tool name
        result.append(tool, style=Styles.TOOL)

        # Path-aware formatting for file-reading tools
        read_tools = {"Read", "Grep", "Glob", "read", "grep", "glob"}
        if tool in read_tools and args:
            path_val = args.get("path") or args.get("pattern") or ""
            if path_val and isinstance(path_val, str):
                result.append(" ", style=Styles.TOOL)
                dir_part, file_part = _split_path(path_val)
                # Dir part: dimmed, front-truncated if long
                dir_display = _truncate_front(dir_part, 45)
                result.append(dir_display, style=Styles.TOOL_COUNT)
                # File/basename part: brighter
                result.append(file_part, style=Styles.TOOL)
            else:
                # Pattern-based (grep) — show pattern compactly
                arg_str = _format_args_compact(args, max_val=50)
                if arg_str:
                    result.append(" ", style=Styles.TOOL)
                    result.append(arg_str, style=Styles.TOOL)
        else:
            arg_str = _format_args_compact(args, max_val=50)
            if arg_str:
                result.append(" ", style=Styles.TOOL)
                result.append(arg_str, style=Styles.TOOL)

        # Concurrent count badge
        if concurrent_count > 0:
            result.append(f" +{concurrent_count}", style=Styles.WORKING)

        return result

    @staticmethod
    def render_tool_call(tool_name: str, params: dict = None) -> Text:
        """Render a compact one-line tool call (backward compat)."""
        return OutputRenderer.render_tool_call_line(tool_name, params, is_working=False)

    @staticmethod
    def render_tool_output(tool_name: str, output: str, is_error: bool = False) -> Text:
        """Render tool output as inline text."""
        return Text(output, style=Styles.STATUS if is_error else Styles.AI)

    @staticmethod
    def format_tool_compact(tool_name: str, args: Optional[dict] = None) -> Text:
        """Compact one-line tool render with path highlighting."""
        result = Text()
        result.append(tool_name, style=Styles.TOOL)

        # Path-aware formatting for file-reading tools
        read_tools = {"Read", "Grep", "Glob", "read", "grep", "glob"}
        if tool_name in read_tools and args:
            path_val = args.get("path") or args.get("pattern") or ""
            if path_val and isinstance(path_val, str):
                result.append(" ", style=Styles.TOOL)
                dir_part, file_part = _split_path(path_val)
                dir_display = _truncate_front(dir_part, 35)
                result.append(dir_display, style=Styles.TOOL_COUNT)
                result.append(file_part, style=Styles.TOOL)
                return result

        arg_str = _format_args_compact(args)
        if arg_str:
            result.append(f" {arg_str}", style=Styles.TOOL)
        return result

    # ── Edit diff display (with line numbers) ────────────────────

    @staticmethod
    def render_edit_diff(diff_lines: list) -> Text:
        """Render edit diff with line numbers.

          - 23. throw new Error('Invalid credentials');
          + 35. return null;
        """
        result = Text()
        for line in diff_lines:
            if line.startswith("+"):
                result.append(f"  {line}\n", style=Styles.DIFF_ADDED)
            elif line.startswith("-"):
                result.append(f"  {line}\n", style=Styles.DIFF_REMOVED)
            else:
                result.append(f"  {line}\n", style=Styles.TOOL_COUNT)
        return result

    # ── Bash output ──────────────────────────────────────────────

    @staticmethod
    def render_bash_output(output_lines: list, is_error: bool = False) -> Text:
        """Render bash command output with indentation.

        Indented 11 spaces to align just past the 'o ' prefix.
        """
        result = Text()
        style = Styles.STATUS if is_error else Styles.TOOL_COUNT
        indent = "           "  # 11 spaces
        for line in output_lines[:8]:
            result.append(f"{indent}{line}\n", style=style)
        if len(output_lines) > 8:
            result.append(f"{indent}… ({len(output_lines) - 8} more lines)", style=Styles.TOOL_COUNT)
        return result

    # ── Agent tree view ──────────────────────────────────────────

    @staticmethod
    def render_agent_tree(
        agents: list[dict],
        blink_on: bool = False,
    ) -> Text:
        """Render parallel agents as a tree with box-drawing characters.

        ● Running 2 agents
        │
        ├─ ● code-reviewer(Checking patterns..)
        │               Read path + 21 tools
        │
        └─ ● security-scan(Scanning for vulns..)
                         Read path + 10 tools
        """
        if not agents:
            return Text("")

        result = Text()
        _TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
        running = sum(1 for a in agents if a.get("status") not in _TERMINAL)

        # Header
        header_dot_style = Styles.TOOL_DOT_SUCCESS if running == 0 else (
            Styles.WORKING_BLINK if blink_on else Styles.TOOL_DOT_SUCCESS
        )
        result.append(f"● Running {len(agents)} agent{'s' if len(agents) != 1 else ''}\n",
                       style=Styles.TOOL_COUNT if running == 0 else Styles.TOOL)

        for i, agent in enumerate(agents):
            name = agent.get("name", "agent")
            status = agent.get("status", "RUNNING")
            desc = agent.get("description", agent.get("detail", agent.get("task", "")))
            tool_count = agent.get("tool_count", 0)
            current_tool = agent.get("current_tool", "")
            is_terminal = status in _TERMINAL
            is_last = i == len(agents) - 1

            connector = "└─" if is_last else "├─"
            if status in ("COMPLETED",):
                dot_style = Styles.TOOL_DOT_SUCCESS
            elif status in ("FAILED", "CANCELLED"):
                dot_style = Styles.TOOL_DOT_ERROR
            elif blink_on:
                dot_style = Styles.WORKING_BLINK
            else:
                dot_style = Styles.TOOL_DOT_SUCCESS

            result.append("│\n", style=Styles.TOOL_COUNT)
            result.append(f"{connector} ", style=Styles.TOOL_COUNT)
            result.append("● ", style=dot_style)
            result.append(name, style=Styles.TOOL)
            if desc:
                d = desc[:40] + "…" if len(desc) > 40 else desc
                result.append(f"({d})", style=Styles.TOOL_COUNT)

            if is_terminal:
                result.append(" Done", style=Styles.WORKING_SOLID)
            result.append("\n")

            # Second line: tool info under agent name
            tool_info = ""
            if current_tool:
                tool_info += str(current_tool) + " "
            if tool_count > 0:
                tool_info += f"+ {tool_count} tool{'s' if tool_count != 1 else ''}"
            if tool_info:
                indent_width = 2 + 1 + len(name)
                if is_last:
                    result.append(" " * indent_width, style=Styles.TOOL_COUNT)
                else:
                    result.append("│" + " " * (indent_width - 1), style=Styles.TOOL_COUNT)
                result.append(f" {tool_info}\n", style=Styles.TOOL_COUNT)

        return result

    # ── Processing indicator ─────────────────────────────────────

    @staticmethod
    def render_processing_indicator(
        is_processing: bool,
        show_indicator: bool,
        tasks: Optional[list] = None,
    ) -> Text:
        """Render * Blinking... + |_ + task list in processing area when tasks exist.

        When tasks exist and is_processing:
          - * Blinking... header toggles on/off with show_indicator (both blink together)
          - |_ tree connector always visible
          - Task checkboxes: □ pending, ■ running, ■ strikethrough done
        When no tasks or not processing: returns empty Text.
        """
        result = Text()
        if not is_processing:
            return result
        if not tasks:
            return result

        # Header: * Blinking... (both toggle with show_indicator for blink effect)
        if show_indicator:
            result.append("* ", style=Styles.TASK_DOT_BROWN)
            result.append("Blinking...", style=Styles.WORKING_BLINK)
        result.append("\n")

        # Tree connector
        result.append("|_\n", style=Styles.OPTION_DETAIL)

        # Task list
        for task in tasks:
            status = task.get("status", "pending")
            subject = task.get("subject", task.get("name", "Untitled"))
            if len(subject) > 55:
                subject = subject[:55] + "…"
            result.append("  ", style=Styles.OPTION_DETAIL)
            if status == "completed":
                result.append("■ ", style=Styles.TASK_BOX_DONE)
                result.append(subject, style=Styles.TASK_TEXT_DONE)
            elif status == "in_progress":
                result.append("■ ", style=Styles.TASK_BOX_RUNNING)
                result.append(subject, style=Styles.USER_TEXT)
            else:
                result.append("□ ", style=Styles.TASK_BOX_PENDING)
                result.append(subject, style=Styles.TASK_META)
            result.append("\n")

        return result

    # ── Sub-agent card (legacy) ──────────────────────────────────

    @staticmethod
    def render_subagent_card(
        glyph: str,
        gutter_color: str,
        agent_name: str,
        status: str,
        tool_count: int,
        current_tool=None,
        detail: str = "",
        name_width: int = 12,
    ) -> Text:
        """Render a sub-agent status line inline (legacy, kept for compat)."""
        status_icons = {
            "SPAWNING": "⚡", "RUNNING": "🔄", "THINKING": "🧠",
            "TOOL_CALLING": "⚙", "COMPLETED": "✓", "FAILED": "✗",
            "CANCELLED": "⊘",
        }
        icon = status_icons.get(status, "→")

        result = Text()
        result.append(f"{glyph} ", style=f"bold {gutter_color}")
        result.append(f"{agent_name[:name_width]:<{name_width}} ", style=f"bold {gutter_color}")
        result.append(f"{icon} ", style=Styles.TOOL)
        result.append(status.lower(), style=Styles.TOOL)
        result.append(f" · {tool_count} tool{'s' if tool_count != 1 else ''}",
                       style=Styles.TOOL_COUNT)

        is_terminal = status in ("COMPLETED", "FAILED", "CANCELLED")
        if not is_terminal:
            result.append("  → ", style=Styles.TOOL)
            if current_tool:
                result.append(current_tool if isinstance(current_tool, Text) else Text(str(current_tool)))
            else:
                result.append("thinking…", style=Styles.TOOL_COUNT)

        if detail and tool_count == 0:
            result.append(f"   {detail[:50]}", style=Styles.TOOL_COUNT)
        return result

    # ── Task Creation (polished task board) ─────────────────────

    @staticmethod
    def render_task_creation(
        tasks: list,
        goal: str = "",
        total_tokens: int = 0,
        active_form: str = "",
        blink_on: bool = True,
    ) -> Text:
        """Render * Blinking... header + |_ tree + task checkboxes.

        * Blinking... is the system-busy header.
        |_ tree connector with task list underneath.
        Each task: □ pending, ■ running, ■ strikethrough done.
        Vanishes entirely when all tasks are done.
        """
        if not tasks:
            return Text("")

        # When all tasks complete the ENTIRE block vanishes
        all_done = all(t.get("status") == "completed" for t in tasks)
        if all_done:
            return Text("")

        result = Text()

        # ── System indicator * Blinking... ────────────────────
        result.append("* ", style=Styles.TASK_DOT_BROWN)
        if blink_on:
            result.append("Blinking...", style=Styles.WORKING_BLINK)
        result.append("\n")

        # ── Tree connector |_ ─────────────────────────────────
        result.append("|_\n", style=Styles.OPTION_DETAIL)

        # ── Task list under _ branch ──────────────────────────
        for task in tasks:
            status = task.get("status", "pending")
            subject = task.get("subject", task.get("name", "Untitled"))
            if len(subject) > 55:
                subject = subject[:55] + "…"

            result.append("  ", style=Styles.OPTION_DETAIL)

            if status == "completed":
                result.append("■ ", style=Styles.TASK_BOX_DONE)
                result.append(subject, style=Styles.TASK_TEXT_DONE)
            elif status == "in_progress":
                result.append("■ ", style=Styles.TASK_BOX_RUNNING)
                result.append(subject, style=Styles.USER_TEXT)
            else:
                result.append("□ ", style=Styles.TASK_BOX_PENDING)
                result.append(subject, style=Styles.TASK_META)
            result.append("\n")

        return result

    # ── Ask User Questions (tabbed form with keyboard nav) ─────

    @staticmethod
    def render_ask_user_questions(state: dict, width: int = 80) -> Text:
        """Render a tabbed question form matching the Claude Code spec.

        Layout:
          ═════ thick divider
          Overview text
          [Tab 1] [Tab 2] [Submit]
          active question panel
          keybar
          ═════ thick divider

        Tab 0..N-1 = questions, Tab N = Submit.
        Post-submit shows review block.
        """
        questions = state.get("questions", [])
        current_tab = state.get("current_tab_index", 0)
        focus_idx = state.get("current_focus_index", 0)
        selections = state.get("selections", {})
        custom_values = state.get("custom_values", {})
        custom_focus = state.get("custom_focus")
        submitted = state.get("submitted", False)
        answers = state.get("answers", {})
        overview = state.get("overview", "")
        has_multi = state.get("multi_select", False)

        result = Text()

        # ── Thick top divider ──────────────────────────────────
        divider = "═" * min(width, 80)
        result.append(divider + "\n\n", style=Styles.DIVIDER)

        # ── Overview text ──────────────────────────────────────
        if overview:
            result.append(overview + "\n\n", style=Styles.TOOL)

        # ── Tabs row ────────────────────────────────────────────
        if not submitted:
            tab_labels = [q.get("label", f"Question {i+1}")
                          for i, q in enumerate(questions)]
            tab_labels.append("Submit")
            for ti, label in enumerate(tab_labels):
                if ti == current_tab:
                    result.append(f" [{label}] ", style=Styles.TAB_ACTIVE)
                else:
                    result.append(f" {label} ", style=Styles.TAB_INACTIVE)
            result.append("\n\n")

        # ── Panel body ─────────────────────────────────────────
        if submitted:
            # Review block
            result.append("── Answers submitted ──\n\n", style=Styles.REVIEW_TITLE)
            for qi, q in enumerate(questions):
                qtext = q.get("question", f"Question {qi+1}")
                ans = answers.get(str(qi)) if isinstance(answers.get(str(qi)), str) else answers.get(qi, "")
                display = str(ans) if ans else "(not answered)"
                result.append(qtext + "\n", style=Styles.REVIEW_Q)
                result.append(f"  → {display}\n", style=Styles.REVIEW_A)
            result.append("\n")
        elif current_tab < len(questions):
            q = questions[current_tab]
            qtext = q.get("question", "Question")
            opts = q.get("options", [])

            result.append(f"Q. {qtext}\n", style=Styles.AI)

            for oi, opt in enumerate(opts):
                is_focused = oi == focus_idx
                is_selected = selections.get(current_tab) == oi or \
                    (has_multi and oi in selections.get(current_tab, set()))
                is_custom = opt.get("isCustom", False)

                if is_focused:
                    result.append("▸ ", style=Styles.CURSOR_BLINK)
                else:
                    result.append("  ", style=Styles.CURSOR_BLINK)

                num = opt.get("num", oi + 1)
                title = opt.get("title") or opt.get("label") or opt.get("text") or opt.get("option") or f"Option {num}"
                cstyle = Styles.OPTION_FOCUS if (is_focused or is_selected) else Styles.OPTION_NORMAL

                result.append(f"{num}. ", style=Styles.TASK_BOX_PENDING)
                result.append(title + "\n", style=cstyle)

                detail = opt.get("detail") or opt.get("description") or opt.get("help") or opt.get("hint") or ""
                if detail:
                    ds = Styles.OPTION_DETAIL if is_focused else Styles.INPUT_PLACEHOLDER
                    result.append(f"   {detail}\n", style=ds)

                if is_custom and is_focused:
                    cv = custom_values.get(current_tab, "")
                    if custom_focus == current_tab:
                        result.append(f"   > {cv}█\n", style=Styles.INPUT_FIELD)
                    else:
                        result.append(f"   > {cv}\n", style=Styles.INPUT_FIELD)

            result.append("\n")
            result.append(" ↑↓ navigate  ←→ switch section  Enter select/submit\n",
                          style=Styles.KEYBAR_BG)
        else:
            result.append("Confirm your answers\n", style=Styles.SUBMIT_HEADING)
            result.append("Review your selections above before submitting.\n",
                          style=Styles.SUBMIT_DESC)
            result.append("\n")
            result.append("Press Enter to confirm and send\n", style=Styles.SUBMIT_HINT)

        # ── Thick bottom divider ───────────────────────────────
        result.append(divider + "\n", style=Styles.DIVIDER)

        return result

    @staticmethod
    def render_user_input(text: str) -> Text:
        """Render user input with '>' prefix (ONLY place > is used)."""
        result = Text()
        result.append("> ", style=Styles.USER_PROMPT)
        result.append(text, style=Styles.USER_TEXT)
        return result

    # ── AI response ─────────────────────────────────────────────

    @staticmethod
    def render_ai_response(text: str) -> Text:
        """Render AI response text in light gray."""
        return Text(text, style=Styles.AI)

    # ── Agent/skill events ──────────────────────────────────────

    @staticmethod
    def render_skill_call(skill_name: str, params: Optional[dict] = None) -> Text:
        """Render skill invocation inline."""
        result = Text()
        result.append(f"Skill: {skill_name}", style=Styles.TOOL)
        if params:
            try:
                result.append(f" {json.dumps(params)}", style=Styles.TOOL_COUNT)
            except (TypeError, ValueError):
                result.append(f" {params}", style=Styles.TOOL_COUNT)
        return result

    @staticmethod
    def render_agent_call(agent_name: str, task: str, iteration: Optional[int] = None) -> Text:
        """Render agent spawn inline."""
        result = Text()
        result.append(f"Agent \"{task}\"", style=Styles.TOOL)
        result.append(f"  [agent: {agent_name}]", style=Styles.TOOL_COUNT)
        if iteration:
            result.append(f"  (iteration {iteration})", style=Styles.TOOL_COUNT)
        return result

    @staticmethod
    def render_agent_status(agent_name: str, status: str, detail: str = "") -> Text:
        """Render agent status inline."""
        status_icons = {
            "SPAWNING": "⚡", "RUNNING": "🔄", "THINKING": "🧠",
            "TOOL_CALLING": "⚙", "COMPLETED": "✓", "FAILED": "✗",
            "CANCELLED": "⊘",
        }
        result = Text()
        result.append(f"{status_icons.get(status, '→')} ", style=Styles.TOOL)
        result.append(f"[{agent_name}] ", style=Styles.TOOL)
        result.append(status, style=Styles.TOOL)
        if detail:
            result.append(f" — {detail}", style=Styles.TOOL_COUNT)
        return result

    @staticmethod
    def render_llm_response_stream(content: str, model: str = "Claude") -> Text:
        """Render streaming LLM response inline."""
        return Text(content, style=Styles.AI)

    @staticmethod
    def render_agent_thinking(text: str) -> Text:
        """Render agent thinking."""
        return Text(text, style=Styles.TOOL_COUNT)

    # ── Initial system messages ─────────────────────────────────

    @staticmethod
    def render_initial_system_messages() -> Text:
        """Render the system messages that appear before first input."""
        result = Text()
        result.append("SessionStart:clear says: # claude-mem status\n\n", style=Styles.SYSTEM)
        result.append(
            "This project has no memory yet. The current session will seed it; "
            "subsequent sessions will receive auto-injected context for relevant past work.\n\n",
            style=Styles.SYSTEM)
        result.append("Memory injection starts on your second session in a project.\n\n",
                       style=Styles.SYSTEM)
        result.append(
            "'/learn-codebase' is available if the user wants to front-load the "
            "entire repo into memory in a single pass (~5 minutes on a typical repo, "
            "optional). Otherwise memory builds passively as work happens.\n\n",
            style=Styles.SYSTEM)
        result.append("Live activity: ", style=Styles.SYSTEM)
        result.append("http://localhost:37777", style=Styles.SYSTEM_LINK)
        result.append("\n")
        result.append("How it works: ", style=Styles.SYSTEM)
        result.append("/how-it-works", style=Styles.SYSTEM_COMMAND)
        result.append("\n\n")
        result.append("This message disappears once the first observation lands.\n\n",
                       style=Styles.SYSTEM)
        result.append("View Observations Live @ ", style=Styles.SYSTEM)
        result.append("http://localhost:37777", style=Styles.SYSTEM_LINK)
        return result

    # ── Log entry ───────────────────────────────────────────────

    @staticmethod
    def render_log_entry(entry) -> Text:
        """Render a log entry inline."""
        result = Text()
        result.append(f"[{entry.source}] ", style=Styles.TOOL_COUNT)
        result.append(entry.message, style=Styles.AI)
        return result

    # ── Error / success / info ──────────────────────────────────

    @staticmethod
    def render_error(message: str) -> Text:
        """Render error message."""
        return Text(f"Error: {message}", style=Styles.STATUS)

    @staticmethod
    def render_success(message: str) -> Text:
        """Render success message."""
        return Text(f"Success: {message}", style=Styles.STATUS)

    @staticmethod
    def render_info(message: str) -> Text:
        """Render info message."""
        return Text(message, style=Styles.AI)

    # ── JSON / code ─────────────────────────────────────────────

    @staticmethod
    def render_json(data: dict, title: Optional[str] = None) -> Text:
        """Render JSON data inline."""
        try:
            s = json.dumps(data, indent=2)
            lines = s.splitlines()[:10]
            if len(s.splitlines()) > 10:
                lines.append("…")
            return Text("\n".join(lines), style=Styles.AI)
        except Exception:
            return Text(str(data), style=Styles.AI)

    @staticmethod
    def render_code(code: str, language: str = "python",
                     title: Optional[str] = None) -> Text:
        """Render code without syntax highlighting."""
        lines = code.splitlines()
        display = "\n".join(lines[:10])
        if len(lines) > 10:
            display += "\n… (truncated)"
        return Text(display, style=Styles.AI)

    # ── Task cards ──────────────────────────────────────────────

    @staticmethod
    def render_task_card(task_id: str, subject: str, status: str = "pending",
                           description: str = "") -> Text:
        """Render a task status card inline."""
        status_icons = {
            "pending": "○", "in_progress": "◷", "completed": "✓",
            "failed": "✗", "deleted": "⊘",
        }
        result = Text()
        result.append(f"{status_icons.get(status.lower(), '○')} ", style=Styles.TOOL)
        result.append(f"[{task_id[:12]}] ", style=Styles.TOOL_COUNT)
        result.append(subject, style=Styles.AI)
        result.append(f" — {status}", style=Styles.TOOL_COUNT)
        if description:
            result.append(f"\n  {description[:80]}{'…' if len(description) > 80 else ''}",
                          style=Styles.AI)
        return result

    @staticmethod
    def render_task_list_panel(tasks: list[dict[str, Any]], title: str = "Tasks") -> Text:
        """Render a task list inline."""
        if not tasks:
            return Text("No tasks", style=Styles.TOOL_COUNT)
        result = Text()
        for task in tasks:
            result.append(
                f"  {task.get('status', 'pending')} "
                f"{task.get('id', task.get('task_id', ''))[:10]} "
                f"{task.get('subject', task.get('name', ''))}\n",
                style=Styles.AI)
        return result

    @staticmethod
    def render_iteration_separator(iteration: int, total: int) -> Text:
        """Render iteration separator inline."""
        return Text(f"── Iteration {iteration}/{total} ──", style=Styles.TOOL_COUNT)

    # ── Interactive UI components (replaced by render_ask_user_questions) --


    @staticmethod
    def render_task_board(tasks: list, goal: str = "",
                           show_cursor: bool = False,
                           total_tokens: int = 0) -> Optional[Text]:
        """Render task board as inline text."""
        if not tasks:
            return None

        status_icons = {"pending": "○", "in_progress": "🔄", "completed": "✅",
                         "blocked": "⏸", "deleted": "🗑"}
        result = Text()
        completed = 0
        total = len(tasks)

        for i, t in enumerate(tasks):
            status = t.get("status", "pending")
            subject = t.get("subject", "Untitled")
            icon = status_icons.get(status, "○")
            if status == "completed":
                completed += 1
                result.append(f"  {icon} {i + 1}. {subject}\n", style=Styles.TOOL_COUNT)
            else:
                result.append(f"  {icon} {i + 1}. {subject}\n", style=Styles.AI)
            if status == "in_progress":
                owner = t.get("owner") or t.get("active_form", "")
                if owner:
                    result.append(f"       [{owner}]\n", style=Styles.TOOL_COUNT)

        pct = (completed / total * 100) if total > 0 else 0
        bar_width = 20
        filled = int(bar_width * completed / total) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_width - filled)
        result.append(f"  {'─' * 40}\n", style=Styles.TOOL_COUNT)
        result.append(f"  {completed} of {total}  {bar}  {int(pct)}%\n", style=Styles.TOOL_COUNT)
        if total_tokens:
            result.append(f"  ⚡ {total_tokens}", style=Styles.SYSTEM_LINK)
        if show_cursor:
            result.append("  ▎", style=Styles.SYSTEM_LINK)
        return result

    @staticmethod
    def render_permission_prompt(tool: str, command_str: str, risk: str,
                                   description: str = "") -> Text:
        """Render permission prompt as inline text."""
        result = Text()
        result.append(f"  Tool: {tool}\n", style=Styles.USER_TEXT)
        result.append(f"  Command: {command_str[:80]}\n", style=Styles.AI)
        if description:
            result.append(f"  {description}\n", style=Styles.AI)
        risk_color = Styles.WORKING if risk in ("high", "critical") else Styles.TOOL_COUNT
        result.append(f"  Risk: {risk}\n", style=risk_color)
        result.append("\n  [Y] Yes   [N] No   [A] Always   [S] Skip", style=Styles.USER_TEXT)
        return result

    @staticmethod
    def render_question_confirmation(questions: list, answers: dict,
                                     overview: str = "") -> Text:
        """Render Q&A summary receipt after all sections answered.

        Shows overview text (if provided) then each question with its answer.
        """
        result = Text()
        if overview:
            result.append(f"  {overview}\n\n", style=Styles.USER_TEXT)
        for qi, q in enumerate(questions):
            qtext = q.get("question", f"Question {qi + 1}")
            ans = answers.get(qi, "")
            display = ans
            if isinstance(ans, list):
                display = ", ".join(ans)
            result.append(f"  Q{qi + 1}. {qtext}\n", style=Styles.USER_TEXT)
            result.append(f"       → {display}\n", style=Styles.PICKER_FOCUS)
        return result