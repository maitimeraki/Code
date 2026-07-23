"""Main terminal orchestrator for Claude Code-style UI."""

import asyncio
import json
import signal
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
from .claude_code_style import create_console
from .statusbar import StatusBar, StatusInfo
from .main_panel import MainPanel
from .input_bar import InputBar
from .header import Header
from .welcome_panel import WelcomePanel
from .state import UIState
from .keybinds import KeybindMap, KeyCode
from .input_handler import InputHandler, KeyEvent
from .command_palette import CommandPalette
from .command_actions import CommandActions
from .stream_listener import StreamListener, LogEntry
from .stream_aggregator import StreamAggregator
from .renderers import OutputRenderer
from .claude_code_style import BlockKind, Colors

if TYPE_CHECKING:
    from harness.orchestration.llm_client import LLMClient, TextDelta


# Per-agent inline gutter: a distinct (glyph, color) pair is assigned to each
# concurrent sub-agent by arrival order, so their interleaved lines in the shared
# main body remain visually separable. Cycles if more agents than pairs appear.
_SUBAGENT_GUTTERS = [
    ("┃", Colors.AGENT_GOLD),
    ("┋", Colors.ACCENT_PURPLE),
    ("┇", Colors.TOOL_CYAN),
    ("╏", Colors.ACCENT_BLUE),
    ("┊", Colors.SUCCESS_GREEN),
    ("╎", Colors.WARNING_YELLOW),
]


class TerminalUI:
    """Claude Code-style terminal UI orchestrator."""

    def __init__(self, llm_client: Optional["LLMClient"] = None):
        self.console = create_console()
        self.header = Header(self.console)
        self.welcome_panel = WelcomePanel(self.console)
        self.status_bar = StatusBar(self.console)
        self.main_panel = MainPanel(self.console)
        self.input_bar = InputBar(self.console)
        self.state = UIState()
        self.running = True
        self._dirty = False
        self.show_welcome = True  # Show welcome panel on first run

        # LLM client for chat input
        self.llm_client = llm_client
        self.current_model = llm_client.settings.model if llm_client else None
        self.system_prompt: Optional[str] = None
        # Orchestrator for routing chat through the main agent (set by HarnessApp).
        # When present, chat gets real tools + delegation; else falls back to raw LLM.
        self.orchestrator = None

        # Active assistant text block: index into main_panel scrollback of the
        # block currently accumulating streamed reply text, plus its raw markdown
        # source. Reset to None whenever a tool/agent/skill event is rendered so
        # the next reply text opens a *new* block below that event — this keeps
        # text/tool/text output in true chronological order.
        self._active_text_idx: Optional[int] = None
        self._active_text_raw: str = ""
        # Set when new tokens have been appended to _active_text_raw but the
        # rendered block has not yet been rebuilt. The markdown re-render is O(n)
        # in the reply length, so rebuilding per token is O(n²) and causes the
        # streaming stutter. Instead we coalesce: append is cheap, and the block
        # is rebuilt at most once per display frame (see _flush_active_text).
        self._text_dirty: bool = False

        # Phase 2B: Keyboard input
        self.keybinds = KeybindMap()
        self.input_handler = InputHandler(self.keybinds)
        self.command_palette = CommandPalette()

        # Phase 2C: Real-time streams
        self.stream_listener = StreamListener()
        self.stream_aggregator = StreamAggregator(self.stream_listener)

        # Parallel sub-agent activity: instead of a separate region, each concurrent
        # delegated agent occupies ONE in-place card line in the main orchestrator
        # body. The card updates in place as events arrive — showing status, a running
        # tool-call count, and the most-recent tool — so 20 tool calls don't produce
        # 20 lines. Keyed by agent_id; each holds its gutter + live state + the
        # scrollback index of its card line.
        self._subagents: dict = {}
        self._next_subagent_gutter = 0

        # Main orchestrator's own tool activity is collapsed the same way sub-agent
        # activity is: ONE in-place card line showing status, a running tool-call
        # count, the most-recent call, and up to two lines of that call's output —
        # instead of a full call block + full output block per call (the flood).
        # None until the orchestrator issues its first tool call in a turn; reset
        # to None whenever assistant prose resumes so the next tool burst opens a
        # fresh card below that prose (chronological order preserved).
        self._orch_card: Optional[dict] = None

        # Phase 2E: Command actions
        self.command_actions = CommandActions(self)
        self._wire_command_handlers()

        # Inline approval: pending approval dict + lock for serial prompts
        self._pending_approval: Optional[dict] = None  # {tool, args, risk, future}
        self._approval_lock = asyncio.Lock()

        # Pending question interactive picker
        self._pending_question: Optional[dict] = None
        self._question_lock = asyncio.Lock()

        # Task board: OrderedDict of task_id -> TaskItem dicts
        self._task_board: OrderedDict = OrderedDict()
        self._task_board_goal: str = ""
        self._task_board_dirty: bool = False
        self._all_done_at: Optional[datetime] = None

        # Processing indicator
        self._is_processing: bool = False
        self._show_indicator: bool = True
        self._spinner_frame: int = 0

        # Token tracking (accumulated from stream tool events)
        self._total_tokens_used: int = 0

        # Task board blinking cursor toggle
        self._task_blink_on: bool = True

    def _wire_command_handlers(self) -> None:
        """Wire command actions to palette commands."""
        handler_map = {
            ":run-task": self.command_actions.run_task,
            ":pause": self.command_actions.pause,
            ":resume": self.command_actions.resume,
            ":cancel": self.command_actions.cancel,
            ":search-logs": self.command_actions.search_logs,
            ":clear": self.command_actions.clear,
            ":export": self.command_actions.export,
            ":help": self.command_actions.help,
            ":quit": self.command_actions.quit,
        }

        for cmd in self.command_palette.commands:
            if cmd.shortcut in handler_map:
                cmd.handler = handler_map[cmd.shortcut]

    async def request_approval(self, tool_type, args: dict, risk: str) -> bool:
        """Request user approval for high-risk tool call. Await user y/n keypress.

        Returns: True if approved, False if denied.
        ponytail: serial approval (one at a time via lock), fine for human-paced input.
        """
        async with self._approval_lock:
            # Create future for y/n response
            future: asyncio.Future[bool] = asyncio.Future()

            # Store pending approval state
            self._pending_approval = {
                "tool": tool_type.value if hasattr(tool_type, "value") else str(tool_type),
                "args": args,
                "risk": risk,
                "future": future,
            }
            self._dirty = True

            # Await the y/n keypress to resolve the future
            try:
                result = await asyncio.wait_for(future, timeout=30)  # 30s timeout
            except asyncio.TimeoutError:
                result = False  # Timeout → deny
            finally:
                self._pending_approval = None
                self._dirty = True

            return result

    # ── AskUserQuestion interactive picker ─────────────────────────────────

    @property
    def ask_user_question_callback(self):
        """Return the handle_ask_user_question coroutine for tool-router wiring.

        The factory passes this as the interactive AskUserQuestion handler so the
        tool call shows a picker card instead of a static JSON stub.
        """
        return self.handle_ask_user_question

    async def handle_ask_user_question(
        self, questions: Optional[list] = None, multi_select: bool = False,
        preview: Optional[dict] = None,
    ) -> str:
        """Handle AskUserQuestion: show picker card, await answer, return JSON.

        Blocks until the user answers or timeout fires. The picker card replaces
        the input bar during this time. Returns a JSON string with answers.
        """
        async with self._question_lock:
            q = questions[0] if questions else {"question": "No question provided", "options": []}
            options = q.get("options", [])

            from harness.config import get_settings
            timeout_seconds = get_settings().ask_question_timeout_seconds
            future: asyncio.Future = asyncio.Future()

            state = {
                "question": q.get("question", ""),
                "header": q.get("header", ""),
                "options": options,
                "multi_select": multi_select,
                "focus_index": 0,
                "selections": set(),
                "mode": "options",
                "other_buffer": "",
                "answers": {},
                "annotations": {},
                "future": future,
                "timeout_seconds": timeout_seconds,
                "timeout_at": (
                    datetime.now() + timedelta(seconds=timeout_seconds)
                    if timeout_seconds > 0 else None
                ),
            }
            self._pending_question = state
            self._dirty = True

            question_text = state["question"]
            try:
                if timeout_seconds > 0:
                    result = await asyncio.wait_for(future, timeout=timeout_seconds)
                else:
                    result = await future
            except asyncio.TimeoutError:
                result = {"answers": {}, "annotations": {"note": "User away, auto-continued"}}
            finally:
                self._pending_question = None
                self._dirty = True

            # Render confirmation in scrollback
            answer_str = json.dumps(result.get("answers", {}))
            self.main_panel.add_text(
                OutputRenderer.render_question_confirmation(question_text, answer_str)
            )
            self._dirty = True

            return json.dumps(result)

    # ── Picker key handlers ────────────────────────────────────────────────

    async def _handle_picker_key(self, key: str) -> bool:
        """Route a key event to the picker action. Returns True if consumed."""
        state = self._pending_question
        if not state:
            return False

        if state["mode"] == "options":
            if key in "123456789":
                idx = int(key) - 1
                if 0 <= idx < len(state["options"]):
                    return await self._picker_select(idx)
            if key in (KeyCode.UP.value, "k"):
                return await self._picker_nav(-1)
            if key in (KeyCode.DOWN.value, "j"):
                return await self._picker_nav(1)
            if key in (KeyCode.ENTER.value, "\r", "\n"):
                return await self._picker_confirm()
            if key in ("\t", "o", "O"):
                return await self._picker_other_mode()
            if key == " " and state.get("multi_select"):
                return await self._picker_toggle()
            if key in (KeyCode.ESCAPE.value, "\x1b"):
                return await self._picker_cancel()
        else:
            # Other text-input mode
            if key in (KeyCode.ENTER.value, "\r", "\n"):
                return await self._picker_confirm_other()
            if key in (KeyCode.ESCAPE.value, "\x1b"):
                state["mode"] = "options"
                self._dirty = True
                return True
            if key in (KeyCode.BACKSPACE.value, "\x7f"):
                state["other_buffer"] = state["other_buffer"][:-1]
                self._dirty = True
                return True
            if key and len(key) == 1 and key.isprintable():
                state["other_buffer"] += key
                self._dirty = True
                return True

        return False

    async def _picker_nav(self, direction: int) -> bool:
        state = self._pending_question
        opts = state["options"]
        if not opts:
            return True
        state["focus_index"] = (state["focus_index"] + direction) % len(opts)
        self._dirty = True
        return True

    async def _picker_select(self, idx: int) -> bool:
        state = self._pending_question
        if not state.get("multi_select"):
            state["answers"] = state["options"][idx].get("label", "")
            if state["future"] and not state["future"].done():
                state["future"].set_result({"answers": state["answers"]})
            return True
        if idx in state["selections"]:
            state["selections"].discard(idx)
        else:
            state["selections"].add(idx)
        state["focus_index"] = idx
        self._dirty = True
        return True

    async def _picker_toggle(self) -> bool:
        state = self._pending_question
        idx = state["focus_index"]
        if idx in state["selections"]:
            state["selections"].discard(idx)
        else:
            state["selections"].add(idx)
        self._dirty = True
        return True

    async def _picker_confirm(self) -> bool:
        state = self._pending_question
        if state.get("multi_select"):
            selected = [state["options"][i] for i in state["selections"]]
            state["answers"] = [s.get("label", "") for s in selected]
        else:
            idx = state["focus_index"]
            if 0 <= idx < len(state["options"]):
                state["answers"] = state["options"][idx].get("label", "")
            else:
                state["answers"] = ""
        if state["future"] and not state["future"].done():
            state["future"].set_result({"answers": state["answers"]})
        return True

    async def _picker_other_mode(self) -> bool:
        state = self._pending_question
        state["mode"] = "other"
        state["other_buffer"] = ""
        self._dirty = True
        return True

    async def _picker_confirm_other(self) -> bool:
        state = self._pending_question
        state["answers"] = state.get("other_buffer", "").strip()
        if state["future"] and not state["future"].done():
            state["future"].set_result({"answers": state["answers"]})
        return True

    async def _picker_cancel(self) -> bool:
        state = self._pending_question
        state["answers"] = {}
        if state["future"] and not state["future"].done():
            state["future"].set_result({"answers": {}, "cancelled": True})
        return True

    # ── Task board helpers ─────────────────────────────────────────────────

    def _ensure_task_board(self, tasks: Optional[list] = None) -> None:
        """Initialize task board from a list of task dicts."""
        if not tasks:
            return
        for t in tasks:
            tid = t.get("id", t.get("task_id", ""))
            if tid and tid not in self._task_board:
                self._task_board[tid] = dict(t)
                self._task_board[tid]["blocked_by"] = set(t.get("blocked_by", []))
        self._task_board_dirty = True
        self._dirty = True

    def _update_task(self, task_data: dict) -> None:
        """Update a task in the board from a TaskUpdate event."""
        tid = task_data.get("task_id", "")
        if not tid:
            return
        if tid not in self._task_board:
            self._task_board[tid] = {
                "id": tid,
                "subject": task_data.get("subject", "Untitled"),
                "status": task_data.get("status", "pending"),
                "owner": task_data.get("owner"),
                "blocked_by": set(task_data.get("blocked_by", [])),
                "active_form": task_data.get("active_form", ""),
            }
        else:
            self._task_board[tid].update(task_data)
            if "blocked_by" in task_data:
                self._task_board[tid]["blocked_by"] = set(task_data["blocked_by"])

        status = task_data.get("status", "")
        if status == "completed":
            self._task_board[tid]["completed_at"] = datetime.now()

        self._task_board_dirty = True
        self._dirty = True

        # Check if all tasks completed → start 2s fade timer
        if self._task_board and all(
            t.get("status") == "completed" for t in self._task_board.values()
        ):
            self._all_done_at = datetime.now()

    def _age_completed_tasks(self) -> None:
        """Collapse the task board 2 seconds after all tasks complete."""
        if self._all_done_at is None:
            return
        if not self._task_board:
            self._all_done_at = None
            return
        elapsed = (datetime.now() - self._all_done_at).total_seconds()
        if elapsed >= 2.0:
            self._task_board.clear()
            self._all_done_at = None
            self._task_board_dirty = True
            self._dirty = True

    def _setup_signal_handlers(self) -> None:
        """Setup terminal signal handlers."""
        def handle_sigint(signum, frame):
            self.state.shutdown()
            self.running = False

        signal.signal(signal.SIGINT, handle_sigint)

    def _setup_input_handlers(self) -> None:
        """Setup keyboard input handlers for actions."""
        async def on_submit_input(event: KeyEvent):
            """Handle Enter key - submit input."""
            text = self.input_bar.get_current_input()

            if self.input_bar.state.in_palette_mode:
                # Execute command
                cmd = self.command_palette.get_command(text)
                if cmd:
                    self.main_panel.add_success(f"Executing: {cmd.description}")
                    if cmd.handler:
                        await cmd.handler()
                self.input_bar.exit_palette_mode()
                self._dirty = True
            else:
                # Regular prompt - check for /model command or send to LLM
                if text:
                    self.input_bar.add_to_history(text)
                    self.input_bar.clear()
                    self.main_panel.state.scroll_position = 0
                    self._dirty = True

                    if text.startswith("/"):
                        if text.startswith("/model"):
                            self._handle_model_command(text)
                        else:
                            self.main_panel.add_error(f"Unknown command: {text}")
                            self.main_panel.add_info("Available commands: /model [name]")
                    elif self.llm_client:
                        self.main_panel.add_info(f"You: {text}")
                        task = asyncio.create_task(self._handle_llm_prompt(text))
                    else:
                        self.main_panel.add_info(f"You: {text}")
                        self.main_panel.add_info("(LLM not configured. Run 'harness init' and set API keys.)")

        async def on_delete_char(event: KeyEvent):
            """Handle Backspace - delete character."""
            self.input_bar.delete_char()
            self._dirty = True

        async def on_history_prev(event: KeyEvent):
            """Handle Up arrow - previous history."""
            prev = self.input_bar.get_previous()
            if prev is not None:
                self.input_bar.set_buffer(prev)
                self._dirty = True

        async def on_history_next(event: KeyEvent):
            """Handle Down arrow - next history."""
            next_input = self.input_bar.get_next()
            if next_input is not None:
                self.input_bar.set_buffer(next_input)
                self._dirty = True

        async def on_open_palette(event: KeyEvent):
            """Handle Ctrl+K - open command palette."""
            self.input_bar.enter_palette_mode()
            self._dirty = True

        async def on_clear_screen(event: KeyEvent):
            """Handle Ctrl+L - clear main panel."""
            self.main_panel.clear()

        async def on_cancel(event: KeyEvent):
            """Handle Ctrl+C - cancel operation."""
            self.state.pause()
            self.add_message("Operation cancelled", level="error")

        async def on_scroll_up(event: KeyEvent):
            """Handle Page Up - scroll conversation up."""
            self.main_panel.state.scroll_up(5)
            self._dirty = True

        async def on_scroll_down(event: KeyEvent):
            """Handle Page Down - scroll conversation down."""
            self.main_panel.state.scroll_down(5)
            self._dirty = True

        async def on_quit(event: KeyEvent):
            """Handle Ctrl+D - quit."""
            self.state.shutdown()
            self.running = False

        # Register handlers
        self.input_handler.register_handler("submit_input", on_submit_input)
        self.input_handler.register_handler("delete_char", on_delete_char)
        self.input_handler.register_handler("history_prev", on_history_prev)
        self.input_handler.register_handler("history_next", on_history_next)
        self.input_handler.register_handler("open_palette", on_open_palette)
        self.input_handler.register_handler("clear_screen", on_clear_screen)
        self.input_handler.register_handler("cancel", on_cancel)
        self.input_handler.register_handler("scroll_up", on_scroll_up)
        self.input_handler.register_handler("scroll_down", on_scroll_down)
        self.input_handler.register_handler("quit", on_quit)

    def _setup_stream_handlers(self) -> None:
        """Setup stream batch handler to update UI with specialized rendering per entry type."""
        async def on_batch(entries: list[LogEntry]):
            """Handle a batch of log entries with type-aware rendering.

            Events are split by depth. Sub-agent events (depth >= 1, produced by
            delegated parallel agents) are rendered inline into the main scrollback
            with a per-agent colored gutter, so concurrent agents stay visually
            distinct while sharing the orchestrator's body. Orchestrator-level
            events (depth 0) render into the main panel as before.

            Each tool/agent/skill event is wrapped with its block marker and
            closes any active assistant text block, so the next streamed reply
            text opens a fresh block *below* the event (chronological order).
            """
            for entry in entries:
                data = entry.data or {}
                depth = data.get("depth", 0) or 0

                # ── Side effects: token tracking + task board updates ──────
                # Accumulate tokens from tool result events (all depths).
                if data.get("tokens"):
                    self._total_tokens_used += data["tokens"]
                    self._dirty = True

                # Populate task board from task management tool events.
                tool_name = data.get("tool", "")
                if tool_name == "TaskCreate" and data.get("args"):
                    args = data["args"]
                    self._update_task({
                        "task_id": f"t{len(self._task_board) + 1}",
                        "subject": args.get("subject", "Untitled"),
                        "status": args.get("status", "pending"),
                        "active_form": args.get("active_form", ""),
                    })
                elif tool_name == "TaskUpdate" and data.get("args"):
                    self._update_task(data["args"])
                elif tool_name == "TaskList" and data.get("result"):
                    try:
                        parsed = json.loads(data["result"])
                        tasks = parsed.get("tasks", []) if isinstance(parsed, dict) else []
                        if tasks:
                            self._ensure_task_board(tasks)
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        pass

                # ---- Sub-agent lane: render inline with a per-agent gutter ----
                if depth >= 1 and entry.source in ("tool", "agent_status", "agent"):
                    self._route_subagent_event(entry, data)
                    self._dirty = True
                    continue

                # ---- Orchestrator lane: existing main-pipeline rendering ----
                # Route to specialized renderer based on entry source and data
                if entry.source == "tool" and entry.data:
                    # Collapse the orchestrator's own tool calls into a single
                    # in-place card (mirrors the sub-agent lane) instead of a full
                    # call block + full output block per call.
                    self._route_orchestrator_tool(entry.data)
                    self._dirty = True
                    continue
                elif entry.source == "skill":
                    # Skill invocation
                    inner = OutputRenderer.render_skill_call(
                        entry.data.get("skill", "unknown"),
                        entry.data.get("params")
                    )
                    rendered = self._wrap_block(BlockKind.SKILL, inner)
                elif entry.source == "agent_call":
                    # Agent spawn
                    inner = OutputRenderer.render_agent_call(
                        entry.data.get("agent", "unknown"),
                        entry.data.get("task", ""),
                        entry.data.get("iteration")
                    )
                    rendered = self._wrap_block(BlockKind.AGENT, inner)
                elif entry.source == "agent_status":
                    # Agent status change
                    inner = OutputRenderer.render_agent_status(
                        entry.data.get("agent", "unknown"),
                        entry.data.get("status", "UNKNOWN"),
                        entry.data.get("detail", "")
                    )
                    rendered = self._wrap_block(BlockKind.AGENT, inner)
                elif entry.source == "agent":
                    # Agent reasoning/thinking (streaming LLM response)
                    inner = OutputRenderer.render_llm_response_stream(
                        entry.message,
                        model="Agent"
                    )
                    rendered = self._wrap_block(BlockKind.AGENT, inner)
                else:
                    # Fallback to generic log entry render for everything else
                    rendered = self._wrap_block(
                        BlockKind.SYSTEM, OutputRenderer.render_log_entry(entry)
                    )

                self.main_panel.add_text(rendered)
            self._dirty = True

        self.stream_aggregator.register_batch_handler(on_batch)

    def initialize(self) -> None:
        """Initialize the UI."""
        self._setup_signal_handlers()
        self._setup_input_handlers()
        self._setup_stream_handlers()

        # Fold welcome panel into scrollback as the first content (scrolls naturally)
        # Render as plain Text (not Panel) so it wraps/scrolls with other content
        left = self.welcome_panel.render_left_column()
        right = self.welcome_panel.render_right_column()
        welcome_text = Text()
        welcome_text.append(left)
        welcome_text.append("\n\n")
        welcome_text.append(right)
        self.main_panel.add_text(welcome_text)

        self.status_bar.update(StatusInfo(
            project_name="Agent Harness",
            branch="main",
            status="ready",
            version="0.1.0",
        ))

        self._dirty = False  # Start clean - CompatibleLive prints initial layout

    def render_layout(self) -> Layout:
        """Create responsive layout: header + main + task_board + picker + input + status.

        Dynamic interleaved regions (only rendered when non-zero height):
          - task_board: between main and picker when tasks exist and not all-done.
          - picker: between task_board/main and input when a question/approval is pending.
        The input region stays at a compact 4 lines (processing indicator + input bar).
        """
        layout = Layout()
        width = self.console.width if self.console.width else 120
        height = self.console.height if self.console.height else 40

        # Pinned heights (always visible)
        header_height = 2
        input_height = 4
        status_height = 1

        # Task board: between main and picker when tasks are live
        task_board_height = 0
        if self._task_board and self._all_done_at is None:
            task_board_height = min(len(self._task_board) + 5, 14)

        # Picker/approval overlay: between task_board and input when pending
        picker_height = 0
        if self._pending_approval:
            picker_height = 12
        elif self._pending_question:
            n_opts = len(self._pending_question.get("options", []))
            picker_height = min(n_opts * 3 + 10, 30)

        # Calculate main height (shrinks as overlays grow)
        total_fixed = header_height + input_height + status_height + task_board_height + picker_height
        main_height = max(10, height - total_fixed)

        parts = [Layout(name="header", size=header_height)]
        parts.append(Layout(name="main", size=main_height))
        if task_board_height > 0:
            parts.append(Layout(name="task_board", size=task_board_height))
        if picker_height > 0:
            parts.append(Layout(name="picker", size=picker_height))
        parts.append(Layout(name="input", size=input_height))
        parts.append(Layout(name="status", size=status_height))
        layout.split_column(*parts)

        # Render header (metadata: branch, version, path)
        header_widget = self.header.render()
        layout["header"].update(header_widget)

        # Render main scrollable panel with row-aware windowing
        main_panel_widget = self.main_panel.render(main_height, width)
        layout["main"].update(main_panel_widget)

        # Render task board between main and picker
        if task_board_height > 0:
            tasks = list(self._task_board.values())
            board = OutputRenderer.render_task_board(
                tasks, self._task_board_goal,
                show_cursor=self._task_blink_on,
                total_tokens=self._total_tokens_used,
            )
            if board:
                layout["task_board"].update(board)

        # Render picker overlay (question card or permission prompt)
        if picker_height > 0:
            if self._pending_approval:
                approval_panel = OutputRenderer.render_permission_prompt(
                    tool=self._pending_approval["tool"],
                    command_str=str(self._pending_approval.get("args", {})),
                    risk=self._pending_approval["risk"],
                    description="",
                )
                layout["picker"].update(approval_panel)
            elif self._pending_question:
                picker = OutputRenderer.render_picker_card(self._pending_question)
                layout["picker"].update(picker)

        # Render input area: processing indicator (when busy) + input bar
        if self._is_processing:
            indicator = OutputRenderer.render_processing_indicator(
                self._is_processing, self._show_indicator, self._spinner_frame
            )
            combined = Text()
            combined.append(indicator)
            combined.append("\n")
            combined.append(self.input_bar.render())
            layout["input"].update(combined)
        else:
            layout["input"].update(self.input_bar.render())

        # Render pinned status bar at absolute bottom
        status_text = self.status_bar.render()
        layout["status"].update(self.console.render_str(str(status_text)))

        return layout

    async def input_loop(self) -> None:
        """Main keyboard input loop."""
        while self.running and self.state.is_running:
            try:
                key = await self.input_handler.read_key()
                if key is None:
                    await asyncio.sleep(0.01)
                    continue

                # Intercept y/n for pending approval before normal input handling
                if self._pending_approval:
                    if key.lower() == "y":
                        self._pending_approval["future"].set_result(True)
                        self._pending_approval = None
                        self._dirty = True
                        await asyncio.sleep(0.001)
                        continue
                    elif key.lower() == "n":
                        self._pending_approval["future"].set_result(False)
                        self._pending_approval = None
                        self._dirty = True
                        await asyncio.sleep(0.001)
                        continue
                    # Ignore all other keys during approval prompt
                    await asyncio.sleep(0.001)
                    continue

                # Intercept picker keys when a question is pending
                if self._pending_question:
                    consumed = await self._handle_picker_key(key)
                    if consumed:
                        await asyncio.sleep(0.001)
                        continue
                    # Fall through: let text keys through for "Other" mode
                    if self._pending_question.get("mode") != "other":
                        await asyncio.sleep(0.001)
                        continue

                # Handle text input
                if self.input_handler.is_text_input(key):
                    if self.input_bar.state.in_palette_mode:
                        self.input_bar.state.palette_buffer += key
                    else:
                        self.input_bar.add_char(key)
                    self._dirty = True
                else:
                    # Handle control keys
                    await self.input_handler.handle_key(key)

                await asyncio.sleep(0.001)
            except KeyboardInterrupt:
                self.state.shutdown()
                break
            except Exception:
                await asyncio.sleep(0.01)

    async def display_loop(self) -> None:
        """Update display on changes + animate processing indicator and task board."""
        last_message_count = 0
        last_size = self.console.size
        while self.running and self.state.is_running:
            try:
                # ── Per-frame animation ─────────────────────────────────────

                # Processing indicator: cycle spinner + blink every 4 frames
                if self._is_processing:
                    self._spinner_frame += 1
                    if self._spinner_frame % 4 == 0:
                        self._show_indicator = not self._show_indicator
                        self._dirty = True

                # Task board blinking cursor: toggle every 6 frames (600ms)
                if self._task_board and self._all_done_at is None:
                    self._task_blink_on = not self._task_blink_on
                    self._dirty = True

                # Task board: collapse 2s after all tasks complete
                self._age_completed_tasks()

                # ── Re-render on changes ────────────────────────────────────
                current_message_count = len(self.main_panel.state.lines)
                current_size = self.console.size

                if self._dirty or current_message_count != last_message_count or current_size != last_size:
                    # Coalesced markdown rebuild: fold any accumulated streamed
                    # tokens into the active block once, here, rather than per token.
                    self._flush_active_text()
                    layout = self.render_layout()
                    self._live.update(layout, refresh=True)
                    self._dirty = False
                    last_message_count = current_message_count
                    last_size = current_size

                await asyncio.sleep(0.1)  # 10fps
            except KeyboardInterrupt:
                self.state.shutdown()
                break
            except Exception:
                await asyncio.sleep(0.1)

    async def run(self) -> None:
        """Run the terminal UI."""
        self.initialize()
        initial_layout = self.render_layout()

        # Use Rich's Live display for proper terminal rendering (no auto_refresh — we drive updates from display_loop)
        self._live = Live(initial_layout, console=self.console, refresh_per_second=10, auto_refresh=False)
        self._live.start(refresh=True)

        # Run input, display, and stream loops concurrently
        try:
            await asyncio.gather(
                self.input_loop(),
                self.display_loop(),
                self.stream_aggregator.start(),
                return_exceptions=True
            )
        except KeyboardInterrupt:
            self.state.shutdown()
        finally:
            self.input_handler.shutdown()
            self._live.stop()

        self.shutdown()

    def display_once(self) -> None:
        """Render UI once (for testing)."""
        try:
            self.console.clear()
            self.console.print(self.header.render())
            self.console.print()

            if self.show_welcome:
                self.console.print(self.welcome_panel.render())
                self.console.print()

            height = max(10, self.console.height - 12 if self.console.height else 20)
            self.console.print(self.main_panel.render(height))
            self.console.print()

            self.console.print(self.input_bar.render())
            self.console.print()

            self.console.print(self.status_bar.render())
        except Exception as e:
            self.console.print(f"[red]Display error: {str(e)}[/red]")

    def add_message(self, text: str, level: str = "info") -> None:
        """Add a message to main panel."""
        if level == "success":
            self.main_panel.add_success(text)
        elif level == "error":
            self.main_panel.add_error(text)
        elif level == "info":
            self.main_panel.add_info(text)
        else:
            self.main_panel.add_line(text)
        self._dirty = True

    def _handle_model_command(self, text: str) -> None:
        """Handle /model command to list or switch models."""
        if not self.llm_client:
            self.main_panel.add_error("LLM not configured")
            return

        parts = text.split(maxsplit=1)
        if len(parts) == 1:
            # /model — list available models
            self.main_panel.add_info("Available models:")
            for m in self.llm_client.settings.models:
                mark = " ← current" if m == self.current_model else ""
                self.main_panel.add_line(f"  {m}{mark}")
            self.main_panel.add_info(f"Subagent model: {self.llm_client.settings.subagent_model}")
        else:
            # /model <name> — switch to model
            model_name = parts[1]
            if model_name in self.llm_client.settings.models:
                self.current_model = model_name
                self.main_panel.add_success(f"Model switched to: {model_name}")
            else:
                self.main_panel.add_error(f"Model '{model_name}' not found. Available: {', '.join(self.llm_client.settings.models)}")
        self._dirty = True

    def _ensure_subagent(self, agent_id: str, name: str) -> dict:
        """Return the live card state for a sub-agent, creating its card line on first sight.

        On creation, a stable (glyph, color) gutter is assigned and a fresh card
        line is appended to the main body; its scrollback index is stored so later
        events can re-render that same line in place instead of appending new ones.
        """
        state = self._subagents.get(agent_id)
        if state is not None:
            return state

        glyph, color = _SUBAGENT_GUTTERS[self._next_subagent_gutter % len(_SUBAGENT_GUTTERS)]
        self._next_subagent_gutter += 1
        state = {
            "name": name,
            "glyph": glyph,
            "color": color,
            "status": "RUNNING",
            "tool_count": 0,
            "current_tool": "",
            "detail": "",
            "line_idx": None,
        }
        self._subagents[agent_id] = state

        # Append this agent's card line and remember where it lives.
        self.main_panel.add_text(self._render_subagent_card(state))
        state["line_idx"] = len(self.main_panel.state.lines) - 1
        # A sub-agent card closes any active assistant text block so reply text
        # opens fresh below the cards (chronology preserved). Flush pending tokens
        # first so nothing streamed just before the card is dropped.
        self._flush_active_text()
        self._active_text_idx = None
        self._active_text_raw = ""
        return state

    def _render_subagent_card(self, state: dict):
        """Build the Rich Text for a sub-agent's card from its current state."""
        return OutputRenderer.render_subagent_card(
            glyph=state["glyph"],
            gutter_color=state["color"],
            agent_name=state["name"],
            status=state["status"],
            tool_count=state["tool_count"],
            current_tool=state["current_tool"],
            detail=state["detail"],
        )

    def _refresh_subagent_card(self, state: dict) -> None:
        """Re-render a sub-agent's card line in place (no new scrollback line)."""
        idx = state.get("line_idx")
        if idx is not None and idx < len(self.main_panel.state.lines):
            self.main_panel.state.lines[idx] = self._render_subagent_card(state)
        else:
            # Card line was scrolled out of the bounded deque; re-append.
            self.main_panel.add_text(self._render_subagent_card(state))
            state["line_idx"] = len(self.main_panel.state.lines) - 1

    def _route_subagent_event(self, entry: LogEntry, data: dict) -> None:
        """Update a depth>=1 sub-agent's in-place card in the main orchestrator body.

        Each concurrent sub-agent owns exactly one card line, updated in place as
        events arrive: a tool call bumps the running count and becomes the card's
        "most-recent tool"; a status change updates the card's status. This keeps
        each agent's activity in its own space and collapses many tool calls into a
        count + latest call, rather than one line per call.
        """
        agent_id = data.get("agent_id") or data.get("agent") or "sub-agent"
        name = data.get("agent") or "sub-agent"
        state = self._ensure_subagent(agent_id, name)

        if entry.source == "agent_status":
            state["status"] = data.get("status", state["status"])
            detail = data.get("detail") or ""
            if detail:
                state["detail"] = detail
        elif entry.source == "tool":
            is_result = data.get("result") is not None or data.get("error") is not None
            if is_result:
                # A result only confirms the in-flight call finished; don't count it.
                return
            state["tool_count"] += 1
            state["status"] = "TOOL_CALLING"
            state["current_tool"] = OutputRenderer.format_tool_compact(
                data.get("tool", "unknown"),
                data.get("args") or {},
            )
        else:
            # source == "agent" (streamed sub-agent prose) is intentionally dropped.
            return

        self._refresh_subagent_card(state)

    # ---- Orchestrator tool card (depth 0) ----------------------------

    def _ensure_orchestrator_card(self) -> dict:
        """Return the orchestrator's live tool card, creating its line on first use.

        Mirrors _ensure_subagent: appends one card line to the main body and
        remembers its scrollback index so later calls re-render in place rather
        than appending a new line per call. Creating a card also closes any active
        assistant text block so prose that preceded this tool burst stays above it.
        """
        if self._orch_card is not None:
            return self._orch_card

        state = {
            "status": "TOOL_CALLING",
            "tool_count": 0,
            "current_tool": "",
            "output_lines": [],
            "is_error": False,
            "line_idx": None,
        }
        self._orch_card = state
        self.main_panel.add_text(self._render_orchestrator_card(state))
        state["line_idx"] = len(self.main_panel.state.lines) - 1
        # Close the active assistant block; flush pending tokens first so nothing
        # streamed just before the card is dropped.
        self._flush_active_text()
        self._active_text_idx = None
        self._active_text_raw = ""
        return state

    def _render_orchestrator_card(self, state: dict):
        """Build the Rich Text for the orchestrator card from its current state."""
        return OutputRenderer.render_orchestrator_card(
            status=state["status"],
            tool_count=state["tool_count"],
            current_tool=state["current_tool"],
            output_lines=state["output_lines"],
            is_error=state["is_error"],
        )

    def _refresh_orchestrator_card(self, state: dict) -> None:
        """Re-render the orchestrator card in place (no new scrollback line)."""
        idx = state.get("line_idx")
        if idx is not None and idx < len(self.main_panel.state.lines):
            self.main_panel.state.lines[idx] = self._render_orchestrator_card(state)
        else:
            # Card line was scrolled out of the bounded deque; re-append.
            self.main_panel.add_text(self._render_orchestrator_card(state))
            state["line_idx"] = len(self.main_panel.state.lines) - 1

    def _route_orchestrator_tool(self, data: dict) -> None:
        """Update the orchestrator's single in-place tool card from a tool event.

        A call (no result/error yet) bumps the running count and becomes the card's
        most-recent tool. A result/error attaches up to two output lines under that
        call — an empty successful result renders as "No output" via the renderer.
        """
        state = self._ensure_orchestrator_card()
        is_result = data.get("result") is not None or data.get("error") is not None

        if not is_result:
            state["tool_count"] += 1
            state["status"] = "TOOL_CALLING"
            state["current_tool"] = OutputRenderer.format_tool_compact(
                data.get("tool", "unknown"),
                data.get("args") or {},
            )
            # New call in flight: clear the prior call's output tail.
            state["output_lines"] = []
            state["is_error"] = False
        else:
            is_error = bool(data.get("error"))
            content = data.get("error") if is_error else data.get("result")
            state["is_error"] = is_error
            state["output_lines"] = str(content or "").splitlines()

        self._refresh_orchestrator_card(state)

    def _wrap_block(self, kind: str, inner):
        """Wrap a Channel-B event render with its 'C' block marker.

        Also closes any active assistant text block so the next streamed reply
        text starts a new block *below* this event (preserves chronology).
        """
        # Fold any pending streamed tokens into the block before closing it,
        # otherwise the last tokens before this event would be dropped.
        self._flush_active_text()
        self._active_text_idx = None
        self._active_text_raw = ""
        return OutputRenderer.render_block(kind, inner)

    def _flush_active_text(self) -> None:
        """Rebuild the active assistant block from accumulated raw markdown.

        Called at most once per display frame (from display_loop) and before any
        event closes the active block. This collapses the per-token markdown
        re-render (O(n²) over the reply) into one rebuild per frame, removing the
        streaming stutter while keeping the block live.
        """
        if not self._text_dirty:
            return
        self._text_dirty = False
        if self._active_text_idx is None or self._active_text_idx >= len(self.main_panel.state.lines):
            return
        self.main_panel.state.lines[self._active_text_idx] = OutputRenderer.render_block(
            BlockKind.ASSISTANT, self._active_text_raw, markdown=True
        )

    async def _handle_llm_prompt(self, prompt: str) -> None:
        """Stream LLM response for a prompt.

        Prefers routing through the orchestrator's main agent (real tools +
        delegation). Falls back to a raw LLM stream if no orchestrator is wired.
        """
        if not self.llm_client and not self.orchestrator:
            self.main_panel.add_error("LLM client not initialized")
            self._dirty = True
            return

        # Reset per-prompt state; signal processing to the user.
        self._is_processing = True
        self._total_tokens_used = 0
        self._active_text_idx = None
        self._active_text_raw = ""
        self._orch_card = None

        def append_chunk(chunk: str) -> None:
            """Append a streamed text chunk to the active assistant block.

            Token arrival is kept cheap: opening a new block renders once, but
            subsequent tokens only accumulate raw markdown and set _text_dirty.
            The actual markdown rebuild is coalesced to one-per-frame in
            display_loop via _flush_active_text, so a long reply no longer
            re-renders its whole body on every token (was O(n²), the stutter).
            """
            if not chunk:
                return

            if self._active_text_idx is None or self._active_text_idx >= len(self.main_panel.state.lines):
                # Open a new assistant block at the tail.
                self._active_text_raw = chunk
                rendered = OutputRenderer.render_block(
                    BlockKind.ASSISTANT, self._active_text_raw, markdown=True
                )
                self.main_panel.add_text(rendered)
                self._active_text_idx = len(self.main_panel.state.lines) - 1
                self._text_dirty = False
                # Prose resumed after a tool burst: retire the current orchestrator
                # card so the next tool call opens a fresh card *below* this text.
                self._orch_card = None
            else:
                # Accumulate only; defer the markdown rebuild to the next frame.
                self._active_text_raw += chunk
                self._text_dirty = True
            self._dirty = True

        try:
            # Preferred path: main agent with tools + delegation.
            if self.orchestrator:
                result = await self.orchestrator.chat(prompt, on_text_delta=append_chunk)
                # If the agent produced output but streamed nothing, render it once.
                if result and result.output and not self._active_text_raw.strip():
                    append_chunk(result.output)
                if result and not result.success and result.error:
                    self.main_panel.add_error(f"Agent error: {result.error}")
                self._dirty = True
                return

            # Fallback path: raw LLM stream (no tools).
            messages = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})
            messages.append({"role": "user", "content": prompt})

            # Import TextDelta at runtime to avoid circular imports in TYPE_CHECKING
            from harness.orchestration.llm_client import TextDelta

            async for event in self.llm_client.stream(messages, model=self.current_model):
                if isinstance(event, TextDelta):
                    append_chunk(event.content)
        except Exception as e:
            self.main_panel.add_error(f"LLM error: {str(e)}")
            self._dirty = True
        finally:
            # Signal idle; reset processing state.
            self._is_processing = False

            # Fold the final streamed tokens into the block once the stream ends,
            # in case no further display frame ticks to flush them.
            self._flush_active_text()
            self._dirty = True

    def shutdown(self) -> None:
        """Clean shutdown."""
        self.state.shutdown()
        self.running = False
        self.console.print("[cyan]Goodbye![/cyan]")

