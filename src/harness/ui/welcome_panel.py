"""Welcome announcement panel with ASCII art and tips."""

from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns
from .claude_code_style import Styles, Colors


ASCII_MASCOT = """
  ⌐■-╖
  ║ ▄║
  ║ █║
  ║╔═╝
  ╚╩
"""


class WelcomePanel:
    """Renders welcome announcement panel with mascot and tips."""

    def __init__(self, console: Console):
        self.console = console
        self.billing = "Haiku 4.5 · API Usage Billing"
        self.workspace = r"~\Desktop\Project\Code"

    def render_left_column(self) -> Text:
        """Render left column: welcome header + mascot + metadata."""
        left = Text()

        # Welcome header
        welcome_title = Text("Welcome back!", style=Styles.WELCOME)
        left.append(welcome_title)
        left.append("\n\n")

        # ASCII mascot
        mascot = Text(ASCII_MASCOT, style="dim cyan")
        left.append(mascot)
        left.append("\n")

        # Billing and workspace metadata
        billing_text = Text(self.billing, style=Styles.PATH)
        left.append(billing_text)
        left.append("\n")

        workspace_text = Text(self.workspace, style=Styles.PATH)
        left.append(workspace_text)

        return left

    def render_right_column(self) -> Text:
        """Render right column: tips + changelog."""
        right = Text()

        # Tips section
        tips_title = Text("Tips for getting started", style=Styles.WELCOME)
        right.append(tips_title)
        right.append("\n")

        tips = [
            "Ctrl+K   Open command palette",
            "Ctrl+L   Clear main panel",
            "Ctrl+D   Quit",
            "Up/Down  Navigate history",
        ]

        for tip in tips:
            right.append(f"  {tip}\n", style=Styles.HINT)

        # Divider
        right.append("\n")
        right.append("─" * 40 + "\n", style=Styles.BORDER)
        right.append("\n")

        # What's new section
        whats_new_title = Text("What's new", style=Styles.WELCOME)
        right.append(whats_new_title)
        right.append("\n")

        changelog = [
            "Fixed scroll tracking in main panel",
            "Background agent resurrection support",
            "New /resume command for checkpoints",
        ]

        for item in changelog:
            right.append(f"  • {item}\n", style=Styles.INFO)

        return right

    def render(self, width: int = None) -> Panel:
        """Render welcome panel with responsive two-column layout."""
        if width is None:
            width = self.console.width

        left = self.render_left_column()
        right = self.render_right_column()

        # Create responsive two-column layout
        # If terminal is too narrow, stack vertically
        if width < 100:
            content = Text()
            content.append(left)
            content.append("\n\n")
            content.append(right)
        else:
            content = Columns([left, right], equal=False, expand=False)

        return Panel(
            content,
            title="[bold blue]Claude Code v2.1.191[/bold blue]",
            border_style=Styles.BORDER,
            padding=(1, 2),
        )
