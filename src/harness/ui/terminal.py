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
from .state import UIState
from .keybinds import KeybindMap, KeyCode
from .input_handler import InputHandler, KeyEvent
from .command_palette import CommandPalette
from .command_actions import CommandActions
from .stream_listener import StreamListener, LogEntry
from .stream_aggregator import StreamAggregator
from .renderers import OutputRenderer
from .claude_code_style import Styles

if TYPE_CHECKING:
    from harness.orchestration.llm_client import LLMClient, TextDelta


# Per-agent inline gutter: a distinct (glyph, color) pair is assigned to each
# concurrent sub-agent by arrival order, so their interleaved lines in the shared
# main body remain visually separable. Cycles if more agents than pairs appear.
_SUBAGENT_GUTTERS = [
    ("┃", "#ffa657"),   # warm orange
    ("┋", "#bc8ef7"),   # soft purple
    ("┇", "#79c0ff"),   # light blue
    ("╏", "#60a5fa"),   # soft blue
    ("┊", "#4ade80"),   # soft green
    ("╎", "#fbbf24"),   # amber
]


class TerminalUI:
    """Claude Code-style terminal UI orchestrator."""

    def __init__(self, llm_client: Optional["LLMClient"] = None):
        self.console = create_console()
        self.header = Header(self.console)
        self.status_bar = StatusBar(self.console)
        self.main_panel = MainPanel(self.console)
        self.input_bar = InputBar(self.console)
        self.state = UIState()
        self.running = True
        self._dirty = False
        self._show_system_messages = True  # Show system messages on first run

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

        # Main orchestrator's tool calls: each tool gets its OWN line in the
        # scrollback, not a collapsed card. Maps tool_id → {tool, args, status,
        # line_idx, output_lines}. active_tool_ids tracks which are still running
        # (for o-blink animation).
        self._tool_states: dict[str, dict] = {}
        self._active_tool_ids: set[str] = set()
        self._next_tool_id = 0

        # Concurrent read/glob/grep batch merging: when the LLM fires multiple
        # file-reading tools in one turn, they're merged into ONE line showing
        # the latest path + total count. Keyed by tool name (e.g. "Read").
        # ponytail: merges by tool type name — separate lines for mixed types.
        self._concurrent_batches: dict[str, dict] = {}

        # Agent tree: when sub-agents run, they're shown as a tree block
        # (o Running N agents / ├─ o name / └─ o name) instead of individual
        # subagent cards. _agent_tree_idx is the scrollback index of the tree;
        # None when no agents are active.
        self._agent_tree_idx: Optional[int] = None
        self._agent_states: dict[str, dict] = {}

        # Blink toggle: alternates each frame so o/* indicators blink in-place.
        self._blink_on: bool = True

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
        self._task_board_idx: Optional[int] = None  # scrollback line of task board
        self._task_board_active_form: str = ""
        self._all_done_at: Optional[datetime] = None

        # Processing indicator
        self._is_processing: bool = False
        self._show_indicator: bool = True
        self._spinner_frame: int = 0

        # Hidden tools — never rendered in the terminal UI.
        self._hidden_tools: set[str] = {
            "TaskCreate", "TaskUpdate", "TaskList",
            "TaskGet", "TaskOutput", "TaskStop",
            "AskUserQuestion",
        }

        # Token tracking (accumulated from stream tool events)
        self._total_tokens_used: int = 0


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
                result = await asyncio.wait_for(future, timeout=300)  # 5min timeout for human response
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
        """Handle AskUserQuestion: show tabbed question form, await all answers.

        Tab-based with keyboard navigation:
          ← → switch tabs  ↑ ↓ navigate options  Enter select/submit
        The future resolves when the user presses Enter on the Submit tab.
        """
        async with self._question_lock:
            qs = questions or [{"question": "No question provided", "options": []}]

            from harness.config import get_settings
            timeout_seconds = get_settings().ask_question_timeout_seconds
            future: asyncio.Future = asyncio.Future()

            overview = qs[0].get("overview", "") if qs else ""

            state = {
                "questions": qs,
                "multi_select": multi_select,
                "current_tab_index": 0,          # 0=Q1, 1=Q2, N=Submit
                "current_focus_index": 0,         # option focus within question
                "selections": {},                 # {qi: int} selected option index
                "custom_focus": None,             # qi with custom input focused
                "custom_values": {},              # {qi: str} custom input text
                "submitted": False,               # True after submit
                "answers": {},                    # {qi: str} final answers
                "overview": overview,
                "future": future,
                "timeout_seconds": timeout_seconds,
                "timeout_at": (
                    datetime.now() + timedelta(seconds=timeout_seconds)
                    if timeout_seconds > 0 else None
                ),
            }
            self._pending_question = state
            self._dirty = True

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

            # Pick up answers — the LLM will respond incorporating them naturally
            ans = result.get("answers", {})
            self._dirty = True

            return json.dumps(result)

    # ── Picker key handlers ────────────────────────────────────────────────

    async def _handle_picker_key(self, key: str) -> bool:
        """Route keys to the tabbed question picker. Returns True if consumed."""
        state = self._pending_question
        if not state:
            return False

        tab = state.get("current_tab_index", 0)
        qs = state.get("questions", [])
        submitted = state.get("submitted", False)
        focus_idx = state.get("current_focus_index", 0)
        custom_focus = state.get("custom_focus")

        if submitted or not qs:
            return True  # consume all keys after submit / when idle

        # ── Escape: blur custom input / cancel ──────────────
        if key in (KeyCode.ESCAPE.value, "\x1b"):
            if custom_focus is not None:
                state["custom_focus"] = None
                self._dirty = True
                return True
            state["answers"] = {}
            if state["future"] and not state["future"].done():
                state["future"].set_result({"answers": {}, "cancelled": True})
            return True

        # ── Tab: cycle tabs ──────────────────────────────────
        if key == "\t":
            total = len(qs) + 1
            state["current_tab_index"] = (tab + 1) % total
            state["current_focus_index"] = 0
            state["custom_focus"] = None
            self._dirty = True
            return True

        # ── ArrowLeft: previous tab ─────────────────────────
        if key in (KeyCode.LEFT.value, "h"):
            state["current_tab_index"] = max(0, tab - 1)
            state["current_focus_index"] = 0
            state["custom_focus"] = None
            self._dirty = True
            return True

        # ── ArrowRight: next tab ────────────────────────────
        if key in (KeyCode.RIGHT.value, "l"):
            total = len(qs) + 1
            state["current_tab_index"] = min(total - 1, tab + 1)
            state["current_focus_index"] = 0
            state["custom_focus"] = None
            self._dirty = True
            return True

        # ── Submit tab: Enter to submit ─────────────────────
        if tab == len(qs):
            if key in (KeyCode.ENTER.value, "\r", "\n"):
                state["submitted"] = True
                collected = {}
                for qi in range(len(qs)):
                    cv = state["custom_values"].get(qi, "").strip()
                    if cv:
                        collected[str(qi)] = cv
                    else:
                        sel = state["selections"].get(qi)
                        if sel is not None:
                            opts = qs[qi].get("options", [])
                            if 0 <= sel < len(opts):
                                collected[str(qi)] = opts[sel].get("title", "")
                state["answers"] = collected
                if state["future"] and not state["future"].done():
                    state["future"].set_result({"answers": collected})
                self._dirty = True
            return True  # consume all keys on submit tab

        # ── Question tab actions ────────────────────────────
        if tab < len(qs):
            opts = qs[tab].get("options", [])

            # Up/Down: navigate options
            if key in (KeyCode.UP.value, "k"):
                state["current_focus_index"] = (focus_idx - 1) % max(1, len(opts) or 1)
                self._dirty = True
                return True
            if key in (KeyCode.DOWN.value, "j"):
                state["current_focus_index"] = (focus_idx + 1) % max(1, len(opts) or 1)
                self._dirty = True
                return True

            # Enter: select option or toggle custom input
            if key in (KeyCode.ENTER.value, "\r", "\n"):
                if not opts or focus_idx >= len(opts):
                    return True
                opt = opts[focus_idx]
                if opt.get("isCustom"):
                    if custom_focus == tab:
                        cv = state["custom_values"].get(tab, "").strip()
                        if cv:
                            state["selections"][tab] = focus_idx
                            total_n = len(qs)
                            state["current_tab_index"] = min(tab + 1, total_n)
                            state["current_focus_index"] = 0
                            state["custom_focus"] = None
                            self._dirty = True
                        return True
                    state["custom_focus"] = tab
                    self._dirty = True
                    return True
                # Regular option: select + advance
                state["selections"][tab] = focus_idx
                total_n = len(qs)
                state["current_tab_index"] = min(tab + 1, total_n)
                state["current_focus_index"] = 0
                state["custom_focus"] = None
                self._dirty = True
                return True

            # Text input for custom values
            if custom_focus == tab:
                if key in (KeyCode.BACKSPACE.value, "\x7f"):
                    buf = state["custom_values"].get(tab, "")
                    state["custom_values"][tab] = buf[:-1]
                    self._dirty = True
                    return True
                if key and len(key) == 1 and key.isprintable():
                    buf = state["custom_values"].get(tab, "")
                    state["custom_values"][tab] = buf + key
                    self._dirty = True
                    return True

            # Number keys for direct option selection
            if key in "123456789" and opts:
                idx = int(key) - 1
                if 0 <= idx < len(opts):
                    opt = opts[idx]
                    if not opt.get("isCustom"):
                        state["selections"][tab] = idx
                        state["current_focus_index"] = idx
                        total_n = len(qs)
                        state["current_tab_index"] = min(tab + 1, total_n)
                        state["current_focus_index"] = 0
                        state["custom_focus"] = None
                        self._dirty = True
                        return True

        return False

    # (old picker helpers removed — replaced by tab-based _handle_picker_key)

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
                if t.get("active_form"):
                    self._task_board_active_form = t["active_form"]
        self._task_board_dirty = True
        self._dirty = True
        self._refresh_task_board()

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

        if task_data.get("active_form"):
            self._task_board_active_form = task_data["active_form"]

        self._task_board_dirty = True
        self._dirty = True
        self._refresh_task_board()

        # Check if all tasks completed → start 2s fade timer
        if self._task_board and all(
            t.get("status") == "completed" for t in self._task_board.values()
        ):
            self._all_done_at = datetime.now()

    def _age_completed_tasks(self) -> None:
        """Vanish the task board immediately when all tasks complete."""
        if self._all_done_at is None:
            return
        if not self._task_board:
            self._all_done_at = None
            return
        self._task_board.clear()
        self._all_done_at = None
        self._task_board_dirty = True
        self._dirty = True
        self._refresh_task_board()

    def _refresh_task_board(self) -> None:
        """Clear any previously rendered task board from scrollback (now renders in processing area only)."""
        if self._task_board_idx is not None:
            idx = self._task_board_idx
            if idx is not None and idx < len(self.main_panel.state.lines):
                self.main_panel.state.lines[idx] = Text("")
            self._task_board_idx = None

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

            # Regular prompt
            if text:
                self.input_bar.add_to_history(text)
                self.input_bar.clear()
                self.main_panel.state.scroll_position = 0
                self._dirty = True

                # First input: system messages disappear
                if self._show_system_messages:
                    # Don't clear on /clear (it handles that itself)
                    if not text.startswith("/clear"):
                        self.main_panel.clear()
                    self._show_system_messages = False

                if text.startswith("/"):
                    if text.startswith("/clear"):
                        self.main_panel.clear()
                        self.main_panel.add_text(
                            OutputRenderer.render_user_input(text)
                        )
                        self._show_system_messages = False
                    elif text.startswith("/model"):
                        self._handle_model_command(text)
                    else:
                        self.main_panel.add_text(
                            OutputRenderer.render_user_input(text)
                        )
                elif self.llm_client:
                    self.main_panel.add_text(
                        OutputRenderer.render_user_input(text)
                    )
                    task = asyncio.create_task(self._handle_llm_prompt(text))
                else:
                    self.main_panel.add_text(
                        OutputRenderer.render_user_input(text)
                    )
                    self.main_panel.add_text(
                        Text("(LLM not configured. Run 'harness init' and set API keys.)",
                             style=Styles.AI)
                    )

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

                # ---- Sub-agent lane: update agent tree ────────────────
                if depth >= 1 and entry.source in ("tool", "agent_status", "agent"):
                    self._update_agent_state(entry, data)
                    self._refresh_agent_tree()
                    self._dirty = True
                    continue

                # ---- Orchestrator lane: per-tool lines ─────────────────
                if entry.source == "tool" and entry.data:
                    tool_name = data.get("tool", "")
                    # Hidden tools (AskUserQuestion, TaskCreate, etc.) are
                    # never rendered — they are interaction/task-management
                    # tools whose results produce picker cards or task boards.
                    if tool_name in self._hidden_tools:
                        continue
                    # Each orchestrator tool renders as its own "o Read ..." line,
                    # NOT a collapsed card.
                    self._handle_orchestrator_tool_event(entry.data)
                    self._dirty = True
                    continue

                # ---- Other events (skill, agent_call, etc.) ────────────
                if entry.source == "skill":
                    rendered = OutputRenderer.render_skill_call(
                        entry.data.get("skill", "unknown"),
                        entry.data.get("params")
                    )
                elif entry.source == "agent_call":
                    # Agent spawn
                    rendered = OutputRenderer.render_agent_call(
                        entry.data.get("agent", "unknown"),
                        entry.data.get("task", ""),
                        entry.data.get("iteration")
                    )
                elif entry.source == "agent_status":
                    # Agent status change
                    rendered = OutputRenderer.render_agent_status(
                        entry.data.get("agent", "unknown"),
                        entry.data.get("status", "UNKNOWN"),
                        entry.data.get("detail", "")
                    )
                elif entry.source == "agent":
                    # Agent reasoning/thinking (streaming LLM response)
                    rendered = OutputRenderer.render_llm_response_stream(
                        entry.message,
                        model="Agent"
                    )
                else:
                    # Fallback to generic log entry render for everything else
                    rendered = OutputRenderer.render_log_entry(entry)

                self.main_panel.add_text(rendered)
            self._dirty = True

        self.stream_aggregator.register_batch_handler(on_batch)

    def initialize(self) -> None:
        """Initialize the UI."""
        self._setup_signal_handlers()
        self._setup_input_handlers()
        self._setup_stream_handlers()

        # Show initial system messages (disappear after first input)
        sys_msg = OutputRenderer.render_initial_system_messages()
        self.main_panel.add_text(sys_msg)

        self.status_bar.update(StatusInfo(
            permission_mode="accept edits on",
            current_file="",
        ))

        self._dirty = False  # Start clean - CompatibleLive prints initial layout

    def _calc_processing_height(self) -> int:
        """Calculate dynamic height of the processing/task-board area.

        Mirrors render_processing_indicator output shape:
          - 1 line for header (* Blinking... or blank)
          - 1 line for |_ tree connector
          - 1 line per visible task

        Returns 0 when no processing area is needed.
        """
        if not self._is_processing or not self._task_board:
            return 0
        return 2 + len(self._task_board)

    def render_layout(self) -> Layout:
        """Create responsive layout: header -> main -> processing_area -> picker -> input -> status.

        Processing area dynamically sizes based on task count. Input bar is
        always in its own fixed 3-line section at the bottom (never crammed).
        Main fills remaining space, capped at 6-line minimum.
        """
        layout = Layout()
        width = self.console.width if self.console.width else 120
        height = self.console.height if self.console.height else 40

        # Pinned heights
        header_height = 3
        input_height = 3
        status_height = 1

        # Picker overlay: dynamic height based on content when pending
        picker_height = 0
        if self._pending_approval:
            picker_height = 8
        elif self._pending_question:
            qs = self._pending_question.get("questions", [])
            tab = self._pending_question.get("current_tab_index", 0)
            submitted = self._pending_question.get("submitted", False)
            if submitted:
                estimated = 6 + len(qs) * 3  # review block
            elif tab >= len(qs):
                estimated = 10  # submit tab
            else:
                n_opts = len(qs[tab].get("options", []))
                estimated = 9 + n_opts * 2  # active question
            picker_height = min(estimated, max(8, height - 20))

        # Dynamic heights: processing_area + picker
        processing_height = self._calc_processing_height()

        # Fixed mandatory areas
        fixed_total = header_height + input_height + status_height

        # Remaining space for main + processing_area + picker
        remaining = height - fixed_total

        # Main panel must stay at least 6 rows visible
        main_min = 6
        available_for_overlays = remaining - main_min

        # If processing + picker exceed available space, reduce picker first
        if processing_height + picker_height > available_for_overlays:
            overflow = (processing_height + picker_height) - available_for_overlays
            picker_height = max(0, picker_height - overflow)
            # If picker is gone and processing still overflows, cap processing
            if processing_height + picker_height > available_for_overlays:
                processing_height = max(0, available_for_overlays - picker_height)

        main_height = remaining - processing_height - picker_height
        main_height = max(main_min, main_height)

        # ── Build sections ────────────────────────────────────────────────
        parts = [Layout(name="header", size=header_height)]
        parts.append(Layout(name="main", size=main_height))
        if processing_height > 0:
            parts.append(Layout(name="processing_area", size=processing_height))
        if picker_height > 0:
            parts.append(Layout(name="picker", size=picker_height))
        parts.append(Layout(name="input", size=input_height))
        parts.append(Layout(name="status", size=status_height))
        layout.split_column(*parts)

        # ── Render header ─────────────────────────────────────────────────
        layout["header"].update(self.header.render())

        # ── Render main scrollable content ────────────────────────────────
        main_content = self.main_panel.render(main_height, width)
        layout["main"].update(main_content)

        # ── Render processing area (task board, blinking indicator) ───────
        if processing_height > 0:
            tasks = list(self._task_board.values()) if self._task_board else None
            proc = OutputRenderer.render_processing_indicator(
                self._is_processing, self._show_indicator, tasks=tasks
            )
            layout["processing_area"].update(proc)

        # ── Render picker overlay ─────────────────────────────────────────
        if picker_height > 0:
            if self._pending_approval:
                picker_widget = OutputRenderer.render_permission_prompt(
                    tool=self._pending_approval["tool"],
                    command_str=str(self._pending_approval.get("args", {})),
                    risk=self._pending_approval["risk"],
                    description="",
                )
                layout["picker"].update(picker_widget)
            elif self._pending_question:
                picker_widget = OutputRenderer.render_ask_user_questions(
                    self._pending_question, width
                )
                layout["picker"].update(picker_widget)

        # ── Render input area (pure input bar, always fixed at bottom) ────
        layout["input"].update(self.input_bar.render())

        # ── Render pinned status bar ──────────────────────────────────────
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
                    # When a question is pending, ALL keys go to the picker.
                    # Never fall through to the input bar.
                    await asyncio.sleep(0.001)
                    continue

                # Handle text input
                if self.input_handler.is_text_input(key):
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

                # o blink: toggle every 4 frames. When blink_on changes,
                # re-render active tool lines and agent tree in-place.
                self._spinner_frame += 1
                new_blink = (self._spinner_frame // 4) % 2 == 0
                if new_blink != self._blink_on:
                    self._blink_on = new_blink
                    if self._active_tool_ids:
                        self._refresh_blinking_tool_lines()
                    if self._agent_states and self._agent_tree_idx is not None:
                        self._refresh_agent_tree()
                    self._dirty = True

                # Processing indicator + task board blink: toggle every 4 frames
                if self._is_processing:
                    new_show = (self._spinner_frame // 4) % 2 == 0
                    if new_show != self._show_indicator:
                        self._show_indicator = new_show
                        if self._task_board:
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

            height = max(10, self.console.height - 12 if self.console.height else 20)
            self.console.print(self.main_panel.render(height, self.console.width or 80))
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

    # ---- Agent tree (replaces individual subagent cards) ─────────────

    def _update_agent_state(self, entry: LogEntry, data: dict) -> None:
        """Update the shared agent state dict for the agent tree.

        Each concurrent sub-agent is tracked in a shared dict. A tool call bumps
        its running count and becomes the agent's "most-recent tool". A status
        change updates the agent's status. The whole tree is re-rendered as one
        block via _refresh_agent_tree.
        """
        agent_id = data.get("agent_id") or data.get("agent") or "sub-agent"
        name = data.get("agent") or "sub-agent"
        state = self._agent_states.setdefault(agent_id, {
            "name": name,
            "status": "RUNNING",
            "description": "",
            "tool_count": 0,
            "current_tool": "",
        })

        if entry.source == "agent_status":
            state["status"] = data.get("status", state["status"])
            detail = data.get("detail") or ""
            if detail:
                state["description"] = detail
        elif entry.source == "tool":
            is_result = data.get("result") is not None or data.get("error") is not None
            if is_result:
                return
            state["tool_count"] += 1
            state["status"] = "TOOL_CALLING"
            state["current_tool"] = str(OutputRenderer.format_tool_compact(
                data.get("tool", "unknown"),
                data.get("args") or {},
            ))
        # source == "agent" (streamed sub-agent prose) is intentionally dropped.

    def _ensure_agent_tree(self) -> None:
        """Create the agent tree block in the scrollback if not already present."""
        if self._agent_tree_idx is not None:
            return
        rendered = OutputRenderer.render_agent_tree(
            list(self._agent_states.values()),
            blink_on=self._blink_on,
        )
        self.main_panel.add_text(rendered)
        self._agent_tree_idx = len(self.main_panel.state.lines) - 1
        self._flush_active_text()
        self._active_text_idx = None
        self._active_text_raw = ""

    def _refresh_agent_tree(self) -> None:
        """Re-render the agent tree block in-place (no new scrollback line)."""
        self._ensure_agent_tree()
        rendered = OutputRenderer.render_agent_tree(
            list(self._agent_states.values()),
            blink_on=self._blink_on,
        )
        idx = self._agent_tree_idx
        if idx is not None and idx < len(self.main_panel.state.lines):
            self.main_panel.state.lines[idx] = rendered
        else:
            self._agent_tree_idx = None
            self._ensure_agent_tree()

    def _refresh_blinking_tool_lines(self) -> None:
        """Re-render active tool lines with the current blink state.

        Alternates between dim (working) and bright (done-style) based on
        blink_on toggle, creating the visual blinking effect for running tools.
        """
        for tid in list(self._active_tool_ids):
            state = self._tool_states.get(tid)
            if not state or state.get("status") != "running":
                continue
            # Check if this is a batched tool and pass concurrent count
            is_batch = state.get("is_batch", False)
            batch_count = 0
            if is_batch:
                tool_name = state["tool"]
                batch = self._concurrent_batches.get(tool_name)
                if batch:
                    batch_count = len(batch.get("paths", []))
            rendered = OutputRenderer.render_tool_call_line(
                state["tool"], state["args"], is_working=self._blink_on,
                concurrent_count=batch_count if batch_count > 1 else 0,
            )
            idx = state.get("line_idx")
            if idx is not None and idx < len(self.main_panel.state.lines):
                self.main_panel.state.lines[idx] = rendered

    # ---- Per-tool lines (depth 0, replaces collapsed orchestrator card) -

    def _get_read_tools(self) -> set:
        """File-reading tools whose output is hidden (not shown in terminal)."""
        return {"Read", "Grep", "Glob", "read", "grep", "glob"}

    def _handle_orchestrator_tool_event(self, data: dict) -> None:
        """Handle an orchestrator tool event as a standalone '●' line.

        A call (no result/error) creates a new "● tool args" line with a
        blinking dot. Multiple concurrent Read/Glob/Grep calls are merged
        into ONE batch line showing the latest path and a total count.
        A result updates the line to solid green ●. An error updates to red ●.
        Output is suppressed for file-reading tools (Read, Glob, Grep — their
        output is too long for inline display).
        """
        is_result = data.get("result") is not None or data.get("error") is not None
        tool_name = data.get("tool", "unknown")
        args = data.get("args") or {}
        read_tools = self._get_read_tools()

        if not is_result:
            # ── New tool call start ──────────────────────────────────────

            # Merge concurrent Read/Glob/Grep calls into one batch line.
            if tool_name in read_tools:
                batch = self._concurrent_batches.get(tool_name)
                if batch and batch.get("line_idx") is not None:
                    # Append to existing batch — update in place with latest path + count
                    batch["paths"].append(args.get("path", "") or args.get("pattern", ""))
                    batch["pending"] += 1
                    batch["latest_args"] = args
                    rendered = OutputRenderer.render_tool_call_line(
                        tool_name, batch["latest_args"],
                        is_working=True,
                        concurrent_count=len(batch["paths"]),
                    )
                    idx = batch["line_idx"]
                    if idx is not None and idx < len(self.main_panel.state.lines):
                        self.main_panel.state.lines[idx] = rendered
                    return

                # First tool in batch — create new line
                batch = {
                    "tool": tool_name,
                    "paths": [args.get("path", "") or args.get("pattern", "")],
                    "pending": 1,
                    "latest_args": args,
                    "line_idx": None,
                }
                self._concurrent_batches[tool_name] = batch
                tool_id = f"batch_{tool_name}"
                state = {
                    "tool": tool_name,
                    "args": args,
                    "status": "running",
                    "line_idx": None,
                    "output_lines": [],
                    "is_error": False,
                    "tool_id": tool_id,
                    "is_batch": True,
                }
                self._tool_states[tool_id] = state
                self._active_tool_ids.add(tool_id)

                rendered = OutputRenderer.render_tool_call_line(
                    tool_name, args, is_working=True, concurrent_count=1
                )
                self.main_panel.add_text(rendered)
                state["line_idx"] = len(self.main_panel.state.lines) - 1
                batch["line_idx"] = state["line_idx"]
            else:
                # Non-read tools: standard single-call line
                tool_id = f"t{self._next_tool_id}"
                self._next_tool_id += 1

                state = {
                    "tool": tool_name,
                    "args": args,
                    "status": "running",
                    "line_idx": None,
                    "output_lines": [],
                    "is_error": False,
                    "tool_id": tool_id,
                    "is_batch": False,
                }
                self._tool_states[tool_id] = state
                self._active_tool_ids.add(tool_id)

                rendered = OutputRenderer.render_tool_call_line(
                    tool_name, args, is_working=True
                )
                self.main_panel.add_text(rendered)
                state["line_idx"] = len(self.main_panel.state.lines) - 1

            # Close active text block so prose below the tool stays below it
            self._flush_active_text()
            self._active_text_idx = None
            self._active_text_raw = ""
        else:
            # ── Tool result/error ────────────────────────────────────────
            matched_id = None
            total_paths = 0  # used by batch completion rendering

            # Check if this is a batched read tool first
            if tool_name in read_tools:
                batch = self._concurrent_batches.get(tool_name)
                if batch:
                    batch["pending"] = max(0, batch["pending"] - 1)
                    if batch["pending"] > 0:
                        # Still pending results — update count, keep blinking
                        tid = f"batch_{tool_name}"
                        state = self._tool_states.get(tid)
                        if state:
                            rendered = OutputRenderer.render_tool_call_line(
                                tool_name, batch["latest_args"],
                                is_working=True,
                                concurrent_count=len(batch["paths"]),
                            )
                            idx = state.get("line_idx")
                            if idx is not None and idx < len(self.main_panel.state.lines):
                                self.main_panel.state.lines[idx] = rendered
                        return

                    # All results received — save path count and mark as done
                    total_paths = len(batch["paths"])
                    del self._concurrent_batches[tool_name]
                    matched_id = f"batch_{tool_name}"

            if matched_id is None:
                # Standard match
                for tid, s in reversed(list(self._tool_states.items())):
                    if s["tool"] == tool_name and s["status"] == "running":
                        matched_id = tid
                        break

            if matched_id is None:
                return

            state = self._tool_states[matched_id]
            state["status"] = "done"
            state["is_error"] = bool(data.get("error"))
            self._active_tool_ids.discard(matched_id)

            # Re-render with colored dot (green success / red error) and final count for batches
            is_batch = state.get("is_batch", False)
            final_count = total_paths if is_batch and total_paths > 1 else 0

            rendered = OutputRenderer.render_tool_call_line(
                state["tool"], state["args"], is_working=False,
                is_error=state["is_error"],
                concurrent_count=final_count,
            )
            idx = state.get("line_idx")
            if idx is not None and idx < len(self.main_panel.state.lines):
                self.main_panel.state.lines[idx] = rendered

            # Append output below the tool line if not a file-reading tool
            if tool_name in read_tools:
                pass  # Output suppressed for Read/Glob/Grep
            else:
                is_error = state["is_error"]
                content = data.get("error") if is_error else data.get("result")
                output_lines = str(content or "").splitlines()
                if output_lines and any(l.strip() for l in output_lines):
                    self.main_panel.add_text(
                        OutputRenderer.render_bash_output(output_lines, is_error)
                    )

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
            "assistant", self._active_text_raw, markdown=True
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
        self._tool_states.clear()
        self._active_tool_ids.clear()
        self._agent_states.clear()
        self._agent_tree_idx = None

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
                # Blank line separator between tool events and subsequent LLM output
                self.main_panel.add_text(Text(""))
                rendered = OutputRenderer.render_block(
                    "assistant", self._active_text_raw, markdown=True
                )
                self.main_panel.add_text(rendered)
                self._active_text_idx = len(self.main_panel.state.lines) - 1
                self._text_dirty = False
                # Prose resumed after a tool burst: retire tracked tool state so
                # the next tool call opens a fresh line *below* this text.
                self._tool_states.clear()
                self._active_tool_ids.clear()
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

