"""Claude Code visual style definitions."""

from rich.style import Style
from rich.console import Console

class Colors:
    """Color palette matching Claude Code UI."""
    BG = "#1e1e1e"
    TEXT_PRIMARY = "#e0e0e0"
    TEXT_DIM = "#808080"
    ACCENT_YELLOW = "#f5c242"
    ACCENT_BLUE = "#4a9eff"
    ACCENT_GREEN = "#4ade80"
    ACCENT_RED = "#ff6b6b"
    ACCENT_CYAN = "#22d3ee"
    BORDER = "#404040"


class Styles:
    """Text styles for Claude Code UI."""
    TITLE = Style(color=Colors.ACCENT_BLUE, bold=True)
    STATUS_BAR = Style(color=Colors.TEXT_DIM, bgcolor=Colors.BG)
    PROMPT = Style(color=Colors.ACCENT_BLUE, bold=True)
    INPUT_TEXT = Style(color=Colors.TEXT_PRIMARY)
    HINT = Style(color=Colors.TEXT_DIM, italic=True)
    WELCOME = Style(color=Colors.ACCENT_YELLOW, bold=True)
    SUCCESS = Style(color=Colors.ACCENT_GREEN, bold=True)
    ERROR = Style(color=Colors.ACCENT_RED, bold=True)
    INFO = Style(color=Colors.ACCENT_CYAN)
    BORDER = Style(color=Colors.BORDER)


def create_console() -> Console:
    """Create Rich console with Claude Code styling."""
    import os
    import sys

    # Force UTF-8 on Windows
    if sys.platform == "win32":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        try:
            import ctypes
            kernel = ctypes.windll.kernel32
            kernel.SetConsoleMode(kernel.GetStdHandle(-11), 7)
        except Exception:
            pass

    return Console(
        force_terminal=True,
        force_interactive=False,
        legacy_windows=False,
        color_system="truecolor",
        width=None,
        height=None,
    )
