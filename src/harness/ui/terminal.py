"""Main terminal orchestrator for Claude Code-style UI."""

import asyncio
import signal
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
from .keybinds import KeybindMap
from .input_handler import InputHandler, KeyEvent
from .command_palette import CommandPalette
from .command_actions import CommandActions
from .stream_listener import StreamListener, LogEntry
from .stream_aggregator import StreamAggregator
from .renderers import OutputRenderer

if TYPE_CHECKING:
    from harness.orchestration.llm_client import LLMClient


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

        # Phase 2B: Keyboard input
        self.keybinds = KeybindMap()
        self.input_handler = InputHandler(self.keybinds)
        self.command_palette = CommandPalette()

        # Phase 2C: Real-time streams
        self.stream_listener = StreamListener()
        self.stream_aggregator = StreamAggregator(self.stream_listener)

        # Phase 2E: Command actions
        self.command_actions = CommandActions(self)
        self._wire_command_handlers()

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

                    if text.startswith("/model"):
                        self._handle_model_command(text)
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
            """Handle a batch of log entries with type-aware rendering."""
            for entry in entries:
                # Route to specialized renderer based on entry source and data
                if entry.source == "tool" and entry.data:
                    if entry.data.get("result") is None and entry.data.get("error") is None:
                        # Tool call (args but no result yet)
                        rendered = OutputRenderer.render_tool_call(
                            entry.data.get("tool", "unknown"),
                            entry.data.get("args")
                        )
                    else:
                        # Tool output (result or error arrived)
                        rendered = OutputRenderer.render_tool_output(
                            entry.data.get("tool", "unknown"),
                            entry.data.get("result") or entry.data.get("error", ""),
                            is_error=bool(entry.data.get("error"))
                        )
                elif entry.source == "agent":
                    # Agent reasoning/thinking
                    rendered = OutputRenderer.render_agent_thinking(entry.message)
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
        """Create responsive layout: header + main + input (pinned) + status (pinned)."""
        layout = Layout()
        width = self.console.width if self.console.width else 120
        height = self.console.height if self.console.height else 40

        # Pinned heights (always visible)
        header_height = 2
        input_height = 4
        status_height = 1

        # Calculate remaining height for scrollable main panel (fills all available space)
        total_fixed = header_height + input_height + status_height
        main_height = max(10, height - total_fixed)

        # Fixed 4-region layout: header / main (flex) / input (pinned) / status (pinned)
        layout.split_column(
            Layout(name="header", size=header_height),
            Layout(name="main", size=main_height),
            Layout(name="input", size=input_height),
            Layout(name="status", size=status_height),
        )

        # Render header (metadata: branch, version, path)
        header_widget = self.header.render()
        layout["header"].update(header_widget)

        # Render main scrollable panel with row-aware windowing
        main_panel_widget = self.main_panel.render(main_height, width)
        layout["main"].update(main_panel_widget)

        # Render pinned input bar at bottom
        input_widget = self.input_bar.render()
        layout["input"].update(input_widget)

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
        """Update display only on actual changes (message added or input cleared)."""
        last_message_count = 0
        last_size = self.console.size
        while self.running and self.state.is_running:
            try:
                # Update if: _dirty flag set, new messages added, or terminal resized
                current_message_count = len(self.main_panel.state.lines)
                current_size = self.console.size

                if self._dirty or current_message_count != last_message_count or current_size != last_size:
                    layout = self.render_layout()
                    self._live.update(layout, refresh=True)
                    self._dirty = False
                    last_message_count = current_message_count
                    last_size = current_size

                await asyncio.sleep(0.1)  # Check 10x per second, not per keystroke
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

    async def _handle_llm_prompt(self, prompt: str) -> None:
        """Stream LLM response for a prompt."""
        if not self.llm_client:
            self.main_panel.add_error("LLM client not initialized")
            self._dirty = True
            return

        model_label = self.current_model or self.llm_client.settings.model
        self.main_panel.add_line(f"{model_label}: ", style="bold cyan")
        idx = len(self.main_panel.state.lines) - 1

        try:
            async for chunk in self.llm_client.stream(prompt, model=self.current_model):
                # Mutate the last line in place to append streaming chunks
                if idx < len(self.main_panel.state.lines):
                    line_tuple = self.main_panel.state.lines[idx]
                    if isinstance(line_tuple, tuple):
                        existing_text, style = line_tuple
                        self.main_panel.state.lines[idx] = (existing_text + chunk, style)
                    else:
                        # Rich Text object — append to it
                        if hasattr(line_tuple, "append"):
                            line_tuple.append(chunk)
                self._dirty = True
        except Exception as e:
            self.main_panel.add_error(f"LLM error: {str(e)}")
            self._dirty = True

    def shutdown(self) -> None:
        """Clean shutdown."""
        self.state.shutdown()
        self.running = False
        self.console.print("[cyan]Goodbye![/cyan]")

