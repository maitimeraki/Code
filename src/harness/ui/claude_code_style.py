"""Claude Code visual style definitions — production-grade terminal UI."""

from rich.style import Style
from rich.console import Console

class Colors:
    """Semantic color palette for production-grade terminal UI."""
    BG = "#0f1117"
    TEXT_PRIMARY = "#e6edf3"
    TEXT_DIM = "#6e7681"
    TEXT_SUBTLE = "#30363d"

    # Semantic colors (vibrant, purpose-driven)
    ASSISTANT_CORAL = "#ff7b72"      # Main LLM responses
    TOOL_CYAN = "#79c0ff"            # Tool calls & execution
    AGENT_GOLD = "#ffa657"           # Agent spawning & status
    SUCCESS_GREEN = "#3fb950"        # Success messages
    WARNING_YELLOW = "#d29922"       # Warnings
    ERROR_RED = "#f85149"            # Errors & critical
    ACCENT_BLUE = "#58a6ff"          # Links & highlights
    ACCENT_PURPLE = "#bc8ef7"        # Special emphasis

    # Visual structure
    BORDER = "#30363d"
    BORDER_ACCENT = "#58a6ff"


class Styles:
    """Text styles for production-grade Claude Code UI."""
    # Headers & titles
    TITLE = Style(color=Colors.ACCENT_BLUE, bold=True)
    HEADER = Style(color=Colors.ACCENT_BLUE, bold=True)
    SECTION_TITLE = Style(color=Colors.TEXT_PRIMARY, bold=True)

    # Status & metadata
    STATUS_BAR = Style(color=Colors.TEXT_DIM, bgcolor="black")
    HINT = Style(color=Colors.TEXT_DIM, italic=False)
    PATH = Style(color=Colors.TEXT_DIM)
    VERSION = Style(color=Colors.WARNING_YELLOW, bold=False)

    # User & system
    PROMPT = Style(color=Colors.TEXT_PRIMARY, bold=True)
    INPUT_TEXT = Style(color=Colors.TEXT_PRIMARY)

    # Semantic
    SUCCESS = Style(color=Colors.SUCCESS_GREEN, bold=True)
    ERROR = Style(color=Colors.ERROR_RED, bold=True)
    WARNING = Style(color=Colors.WARNING_YELLOW, bold=True)
    INFO = Style(color=Colors.ACCENT_BLUE)

    # Block types (block markers)
    ASSISTANT_BLOCK = Style(color=Colors.ASSISTANT_CORAL, bold=True)
    TOOL_BLOCK = Style(color=Colors.TOOL_CYAN, bold=True)
    AGENT_BLOCK = Style(color=Colors.AGENT_GOLD, bold=True)
    SYSTEM_BLOCK = Style(color=Colors.TEXT_DIM)
    SKILL_BLOCK = Style(color=Colors.SUCCESS_GREEN, bold=True)

    # Special
    TOOL_CALL = Style(color=Colors.TOOL_CYAN, bold=True)
    AGENT_THINKING = Style(color=Colors.AGENT_GOLD)
    WELCOME = Style(color=Colors.ACCENT_BLUE, bold=True)
    BORDER = Style(color=Colors.BORDER)  # For panel borders & visual separators


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
    BlockKind.ASSISTANT: Colors.ASSISTANT_CORAL,
    BlockKind.TOOL: Colors.TOOL_CYAN,
    BlockKind.AGENT: Colors.AGENT_GOLD,
    BlockKind.SKILL: Colors.SUCCESS_GREEN,
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
