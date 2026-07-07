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
    import sys
    import io

    # Force UTF-8 on Windows - wrap stdout with UTF-8 encoding
    if sys.platform == "win32":
        try:
            # Reconfigure stdout to use UTF-8
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
            else:
                sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

            # Enable VT100 console mode for ANSI colors
            import ctypes
            kernel = ctypes.windll.kernel32
            handle = kernel.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            kernel.GetConsoleMode(handle, ctypes.byref(mode))
            mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            kernel.SetConsoleMode(handle, mode)
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
