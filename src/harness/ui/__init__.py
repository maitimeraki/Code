"""Terminal UI module for Claude Code-style interface."""

# Phase 2A - Terminal UI Rendering
from .claude_code_style import Colors, Styles, create_console
from .statusbar import StatusBar, StatusInfo
from .main_panel import MainPanel
from .input_bar import InputBar
from .state import UIState
from .terminal import TerminalUI

# Phase 2B - Keyboard Input
from .keybinds import KeybindMap, KeyCode
from .input_handler import InputHandler, KeyEvent
from .command_palette import CommandPalette

# Phase 2C - Real-time Streams
from .stream_listener import StreamListener, LogEntry, LogLevel
from .renderers import OutputRenderer
from .stream_aggregator import StreamAggregator

# Phase 2D - Agent State Display
from .agent_view import AgentView, Agent, AgentStatus
from .tool_view import ToolView, ToolCall, ToolStatus

__all__ = [
    # Phase 2A
    "Colors", "Styles", "create_console",
    "StatusBar", "StatusInfo",
    "MainPanel", "InputBar",
    "UIState", "TerminalUI",
    # Phase 2B
    "KeybindMap", "KeyCode",
    "InputHandler", "KeyEvent",
    "CommandPalette",
    # Phase 2C
    "StreamListener", "LogEntry", "LogLevel",
    "OutputRenderer", "StreamAggregator",
    # Phase 2D
    "AgentView", "Agent", "AgentStatus",
    "ToolView", "ToolCall", "ToolStatus",
]



