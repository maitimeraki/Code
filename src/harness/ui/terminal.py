"""Main terminal orchestrator for Claude Code-style UI."""

import asyncio
import signal
from typing import Optional
from rich.console import Console
from rich.layout import Layout
from .claude_code_style import create_console
from .statusbar import StatusBar, StatusInfo
from .main_panel import MainPanel
from .input_bar import InputBar
from .state import UIState
from .keybinds import KeybindMap
from .input_handler import InputHandler, KeyEvent
from .command_palette import CommandPalette


class TerminalUI:
    """Claude Code-style terminal UI orchestrator."""

    def __init__(self):
        self.console = create_console()
        self.status_bar = StatusBar(self.console)
        self.main_panel = MainPanel(self.console)
        self.input_bar = InputBar(self.console)
        self.state = UIState()
        self.running = True

        # Phase 2B: Keyboard input
        self.keybinds = KeybindMap()
        self.input_handler = InputHandler(self.keybinds)
        self.command_palette = CommandPalette()

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
            else:
                # Regular prompt
                if text:
                    self.input_bar.add_to_history(text)
                    self.main_panel.add_info(f"Prompt: {text}")
                    self.input_bar.clear()

        async def on_delete_char(event: KeyEvent):
            """Handle Backspace - delete character."""
            self.input_bar.delete_char()

        async def on_history_prev(event: KeyEvent):
            """Handle Up arrow - previous history."""
            prev = self.input_bar.get_previous()
            if prev is not None:
                self.input_bar.set_buffer(prev)

        async def on_history_next(event: KeyEvent):
            """Handle Down arrow - next history."""
            next_input = self.input_bar.get_next()
            if next_input is not None:
                self.input_bar.set_buffer(next_input)

        async def on_open_palette(event: KeyEvent):
            """Handle Ctrl+K - open command palette."""
            self.input_bar.enter_palette_mode()

        async def on_clear_screen(event: KeyEvent):
            """Handle Ctrl+L - clear main panel."""
            self.main_panel.clear()

        async def on_cancel(event: KeyEvent):
            """Handle Ctrl+C - cancel operation."""
            self.state.pause()
            self.main_panel.add_error("Operation cancelled")

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
        self.input_handler.register_handler("quit", on_quit)

    def initialize(self) -> None:
        """Initialize the UI."""
        self._setup_signal_handlers()
        self._setup_input_handlers()

        self.status_bar.update(StatusInfo(
            project_name="Agent Harness",
            branch="main",
            status="ready",
            version="0.1.0",
        ))

        self.main_panel.add_section("Welcome back!", "")
        self.main_panel.add_info("Tips for getting started")
        self.main_panel.add_line("Press Ctrl+K to open command palette")
        self.main_panel.add_line("Use arrow keys for input history")
        self.main_panel.add_line("Type a prompt and press Enter to start")
        self.main_panel.add_line("")
        self.main_panel.add_info("Phase 2B: Keyboard Input Active")

    def render_layout(self) -> Layout:
        """Create layout with status bar, main panel, and input bar."""
        layout = Layout()
        layout.split_column(
            Layout(name="status", size=1),
            Layout(name="main"),
            Layout(name="input", size=3),
        )

        status_text = self.status_bar.render()
        layout["status"].update(self.console.render_str(str(status_text)))

        height = self.console.height - 4 if self.console.height else 20
        main_panel_widget = self.main_panel.render(height)
        layout["main"].update(main_panel_widget)

        input_text = self.input_bar.render()
        hint_text = self.input_bar.render_hint()
        layout["input"].update(self.console.render_str(
            f"{input_text}\n{hint_text}"
        ))

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
        """Main UI display loop."""
        while self.running and self.state.is_running:
            try:
                layout = self.render_layout()
                self.console.clear()
                self.console.print(layout)
                await asyncio.sleep(0.05)  # 20 FPS
            except KeyboardInterrupt:
                self.state.shutdown()
                break
            except Exception:
                await asyncio.sleep(0.05)

    async def run(self) -> None:
        """Run the terminal UI."""
        self.initialize()

        # Run input and display loops concurrently
        try:
            await asyncio.gather(
                self.input_loop(),
                self.display_loop(),
                return_exceptions=True
            )
        except KeyboardInterrupt:
            self.state.shutdown()
        finally:
            self.shutdown()

    def display_once(self) -> None:
        """Render UI once (for testing)."""
        try:
            self.console.clear()
            self.console.print(self.status_bar.render())
            self.console.print()

            height = self.console.height - 4 if self.console.height else 20
            self.console.print(self.main_panel.render(height))
            self.console.print()

            self.console.print(self.input_bar.render())
            self.console.print(self.input_bar.render_hint())
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

    def shutdown(self) -> None:
        """Clean shutdown."""
        self.state.shutdown()
        self.running = False
        self.console.print("[cyan]Goodbye![/cyan]")

