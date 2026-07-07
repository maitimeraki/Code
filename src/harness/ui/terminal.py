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


class TerminalUI:
    """Claude Code-style terminal UI orchestrator."""

    def __init__(self):
        self.console = create_console()
        self.status_bar = StatusBar(self.console)
        self.main_panel = MainPanel(self.console)
        self.input_bar = InputBar(self.console)
        self.state = UIState()
        self.running = True

    def _setup_signal_handlers(self) -> None:
        """Setup terminal signal handlers."""
        def handle_sigint(signum, frame):
            self.state.shutdown()
            self.running = False

        signal.signal(signal.SIGINT, handle_sigint)

    def initialize(self) -> None:
        """Initialize the UI."""
        self._setup_signal_handlers()

        self.status_bar.update(StatusInfo(
            project_name="Agent Harness",
            branch="main",
            status="ready",
            version="0.1.0",
        ))

        self.main_panel.add_section(
            "Welcome back!",
            ""
        )

        self.main_panel.add_info("Tips for getting started")
        self.main_panel.add_line("Run /init to create a CLAUDE.md file with instructions for Claude")
        self.main_panel.add_line("What's new: Phase 2A - Claude Code-style Terminal UI")
        self.main_panel.add_line("")

        self.main_panel.add_info("Live activity: http://localhost:37777")
        self.main_panel.add_info("How it works: Type a prompt and press Enter")

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

    async def display_loop(self) -> None:
        """Main UI display loop."""
        while self.running and self.state.is_running:
            try:
                layout = self.render_layout()
                self.console.clear()
                self.console.print(layout)
                await asyncio.sleep(0.1)
            except KeyboardInterrupt:
                self.state.shutdown()
                break
            except Exception as e:
                self.main_panel.add_error(f"Error: {str(e)}")

    async def get_user_input(self) -> Optional[str]:
        """Get user input (Phase 2B will enhance)."""
        try:
            text = await self.input_bar.get_input()
            if text:
                self.input_bar.add_to_history(text)
                self.input_bar.clear()
            return text
        except EOFError:
            return None

    async def run(self) -> None:
        """Run the terminal UI."""
        self.initialize()
        await self.display_loop()

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
