"""Claude Code visual style definitions — exact color palette from the spec."""

from rich.style import Style
from rich.console import Console


class Colors:
    """Exact color palette for Claude Code-style terminal UI.

    Design philosophy:
    - NO bright colors except pink logo
    - NO card borders, NO background panels
    - Everything muted and subtle
    - Pink logo is the ONLY eye-catching element
    """
    BG = "#1a1a1a"

    # Brand (bright)
    LOGO_PINK = "#ff6b9d"       # Pink — ONLY bright element

    # Header
    HEADER_TITLE = "#e4e4e7"    # Soft white
    HEADER_META = "#71717a"     # Dim gray

    # System messages
    SYSTEM_TEXT = "#71717a"     # Dim gray
    SYSTEM_COMMAND = "#a1a1aa"  # Light gray (backticks)
    LINK_BLUE = "#60a5fa"       # Soft blue, underlined

    # User input
    USER_PROMPT = "#e4e4e7"     # Soft white ">"
    USER_TEXT = "#ffffff"        # White

    # AI response
    AI_TEXT = "#a1a1aa"         # Light gray

    # Tool calls
    TOOL_NAME = "#a1a1aa"       # Light gray
    TOOL_PATH = "#a1a1aa"       # Light gray
    TOOL_COUNT = "#52525b"      # Dark gray

    # Working indicator
    WORKING_DOT = "#fbbf24"     # Yellow — ONLY while running
    DONE_TEXT = "#a1a1aa"       # Light gray, NO dot
    WORKING_BLINK = "#888888"   # Dim gray — for blinking o when in-progress
    WORKING_SOLID = "#ffffff"   # Bright white — for solid o when complete

    # Tool status dots (colored big dots)
    TOOL_SUCCESS = "#4ade80"    # Green — tool executed successfully
    TOOL_ERROR = "#f87171"      # Red — tool errored/failed

    # Picker
    PICKER_FOCUS = "#fbbf24"    # Yellow — highlighted option in picker
    PICKER_NORMAL = "#71717a"   # Dim gray — normal (unfocused) option

    # Spec-aligned grays for new components
    TEXT_SECONDARY = "#6b7280"      # --text-secondary
    TEXT_TERTIARY = "#9ca3af"       # --text-tertiary
    TEXT_QUATERNARY = "#d1d5db"     # --text-quaternary
    SURFACE_MUTED = "#1f2937"       # --surface-muted (dark)
    BORDER = "#374151"              # --border (dark)
    QUESTION_TAB_ACTIVE = "#ffffff" # Active tab text

    # Diff
    DIFF_REMOVED = "#f87171"    # Subtle red
    DIFF_ADDED = "#4ade80"      # Subtle green

    # Input bar
    INPUT_LINE = "#3f3f46"      # Subtle gray

    # Status bar
    STATUS_TEXT = "#71717a"     # Dim gray
    STATUS_HINT = "#52525b"     # Dark gray


class Styles:
    """Text styles using exact spec colors."""
    HEADER_TITLE = Style(color=Colors.HEADER_TITLE)
    HEADER_META = Style(color=Colors.HEADER_META)
    HEADER_META_LINK = Style(color=Colors.LINK_BLUE)
    SYSTEM = Style(color=Colors.SYSTEM_TEXT)
    SYSTEM_COMMAND = Style(color=Colors.SYSTEM_COMMAND)
    SYSTEM_LINK = Style(color=Colors.LINK_BLUE, underline=True)
    USER_PROMPT = Style(color=Colors.USER_PROMPT)
    USER_TEXT = Style(color=Colors.USER_TEXT)
    AI = Style(color=Colors.AI_TEXT)
    TOOL = Style(color=Colors.TOOL_NAME)
    TOOL_COUNT = Style(color=Colors.TOOL_COUNT)
    WORKING = Style(color=Colors.WORKING_DOT)
    WORKING_BLINK = Style(color=Colors.WORKING_BLINK)
    WORKING_SOLID = Style(color=Colors.WORKING_SOLID)
    TOOL_DOT_SUCCESS = Style(color=Colors.TOOL_SUCCESS)  # Green dot for success
    TOOL_DOT_ERROR = Style(color=Colors.TOOL_ERROR)      # Red dot for error
    DIFF_REMOVED = Style(color=Colors.DIFF_REMOVED)
    DIFF_ADDED = Style(color=Colors.DIFF_ADDED)
    INPUT_LINE = Style(color=Colors.INPUT_LINE)
    STATUS = Style(color=Colors.STATUS_TEXT)
    STATUS_HINT = Style(color=Colors.STATUS_HINT)
    LOGO = Style(color=Colors.LOGO_PINK, bold=True)

    # Picker
    PICKER_FOCUS = Style(color=Colors.PICKER_FOCUS, bold=True)
    PICKER_NORMAL = Style(color=Colors.PICKER_NORMAL)

    # Task creation
    TASK_DOT_BLINK = Style(color=Colors.WORKING_BLINK)
    TASK_DOT_SOLID = Style(color=Colors.AI_TEXT)
    TASK_DOT_BROWN = Style(color="#cd853f", bold=True)
    TASK_BOX_PENDING = Style(color=Colors.TEXT_TERTIARY)
    TASK_BOX_RUNNING = Style(color=Colors.AI_TEXT)
    TASK_BOX_DONE = Style(color=Colors.TEXT_QUATERNARY)
    TASK_TEXT_DONE = Style(color=Colors.TEXT_QUATERNARY, strike=True)
    TASK_META = Style(color=Colors.TEXT_SECONDARY)

    # Question UI
    TAB_ACTIVE = Style(color=Colors.QUESTION_TAB_ACTIVE)
    TAB_INACTIVE = Style(color=Colors.TEXT_SECONDARY)
    OPTION_FOCUS = Style(color=Colors.AI_TEXT, bold=True)
    OPTION_NORMAL = Style(color=Colors.AI_TEXT)
    OPTION_DETAIL = Style(color=Colors.TEXT_SECONDARY)
    CURSOR_BLINK = Style(color=Colors.AI_TEXT)
    INPUT_FIELD = Style(color=Colors.AI_TEXT)
    INPUT_PLACEHOLDER = Style(color=Colors.TEXT_TERTIARY)
    KEYBAR_BG = Style(color=Colors.TEXT_TERTIARY)
    DIVIDER = Style(color=Colors.AI_TEXT)
    SUBMIT_HEADING = Style(color=Colors.AI_TEXT, bold=True)
    SUBMIT_DESC = Style(color=Colors.TEXT_SECONDARY)
    SUBMIT_HINT = Style(color=Colors.TEXT_TERTIARY)
    REVIEW_TITLE = Style(color=Colors.TEXT_SECONDARY)
    REVIEW_Q = Style(color=Colors.AI_TEXT, bold=True)
    REVIEW_A = Style(color=Colors.TEXT_SECONDARY)


def create_console() -> Console:
    """Create Rich console with truecolor support and Windows UTF-8."""
    import sys
    import io

    if sys.platform == "win32":
        try:
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
            else:
                sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

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
