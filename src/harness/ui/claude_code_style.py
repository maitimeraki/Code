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
    TITLE = Style(color="cyan", bold=True)
    STATUS_BAR = Style(color="white", bgcolor="black")
    PROMPT = Style(color="red", bold=True)
    INPUT_TEXT = Style(color="white", bgcolor="black")
    HINT = Style(color="white", italic=True, bgcolor="black")
    WELCOME = Style(color="yellow", bold=True)
    SUCCESS = Style(color="green", bold=True)
    ERROR = Style(color="red", bold=True)
    INFO = Style(color="blue")
    BORDER = Style(color="red")
    PATH = Style(color="green", dim=True)
    VERSION = Style(color="yellow", bold=True)
    TOOL_CALL = Style(color="cyan", bold=True)
    AGENT_THINKING = Style(color="green", italic=True)


# Block marker glyphs (Claude Code style). "C" replaces the round bullet as the
# per-block leader; the corner joins a tool result under its call.
BLOCK_MARKER = "C"
RESULT_MARKER = "⎿"


class BlockKind:
    """Semantic block types with a leader color each (used by OutputRenderer)."""
    ASSISTANT = "assistant"   # main LLM reply text
    TOOL = "tool"             # tool call
    AGENT = "agent"           # sub-agent spawn / status
    SKILL = "skill"           # skill invocation
    SYSTEM = "system"         # info/system line


BLOCK_MARKER_COLORS = {
    BlockKind.ASSISTANT: Colors.ACCENT_CORAL,
    BlockKind.TOOL: Colors.ACCENT_CYAN,
    BlockKind.AGENT: Colors.ACCENT_GOLD,
    BlockKind.SKILL: Colors.ACCENT_GREEN,
    BlockKind.SYSTEM: Colors.TEXT_DIM,
}


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
