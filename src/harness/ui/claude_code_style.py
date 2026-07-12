"""Claude Code visual style definitions."""

from rich.style import Style
from rich.console import Console

class Colors:
    """Gruvbox-inspired retro color palette (Claude Code style)."""
    BG = "#1d2021"
    TEXT_PRIMARY = "#ebdbb2"
    TEXT_DIM = "#928374"
    ACCENT_CORAL = "#fb4934"
    ACCENT_GREEN = "#b8bb26"
    ACCENT_GOLD = "#d79921"
    ACCENT_BLUE = "#83a598"
    ACCENT_CYAN = "#8ec07c"
    BORDER_CORAL = "#fb4934"


class Styles:
    """Text styles for Claude Code UI (Gruvbox theme)."""
    TITLE = Style(color=Colors.ACCENT_BLUE, bold=True)
    STATUS_BAR = Style(color=Colors.TEXT_DIM, bgcolor=Colors.BG)
    PROMPT = Style(color=Colors.ACCENT_CORAL, bold=True)
    INPUT_TEXT = Style(color=Colors.TEXT_PRIMARY, bgcolor=Colors.BG)
    HINT = Style(color=Colors.TEXT_DIM, italic=True, bgcolor=Colors.BG)
    WELCOME = Style(color=Colors.ACCENT_GOLD, bold=True)
    SUCCESS = Style(color=Colors.ACCENT_GREEN, bold=True)
    ERROR = Style(color=Colors.ACCENT_CORAL, bold=True)
    INFO = Style(color=Colors.ACCENT_BLUE)
    BORDER = Style(color=Colors.BORDER_CORAL)
    PATH = Style(color=Colors.ACCENT_GREEN, dim=True)
    VERSION = Style(color=Colors.ACCENT_GOLD, bold=True)
    TOOL_CALL = Style(color=Colors.ACCENT_BLUE, bold=True)
    AGENT_THINKING = Style(color=Colors.ACCENT_CYAN, italic=True)


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
        force_interactive=True,
        legacy_windows=False,
        color_system="truecolor",
        width=None,
        height=None,
    )
