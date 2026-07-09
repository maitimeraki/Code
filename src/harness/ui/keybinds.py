"""Vim-style keybindings for terminal UI."""

from enum import Enum
from dataclasses import dataclass
from typing import Callable, Dict, Optional, List


class KeyCode(Enum):
    """Terminal key codes."""
    ENTER = "\r"
    ESCAPE = "\x1b"
    CTRL_C = "\x03"
    CTRL_K = "\x0b"
    CTRL_L = "\x0c"
    CTRL_D = "\x04"
    CTRL_H = "\x08"  # Backspace on Windows
    TAB = "\t"
    BACKSPACE = "\x7f"
    UP = "\x1b[A"
    DOWN = "\x1b[B"
    LEFT = "\x1b[D"
    RIGHT = "\x1b[C"


@dataclass
class KeyBinding:
    """A single key binding."""
    key: str
    action: str
    description: str
    handler: Optional[Callable] = None


class KeybindMap:
    """Vim-style keybindings for the terminal UI."""

    def __init__(self):
        self.bindings: Dict[str, KeyBinding] = {}
        self._init_default_bindings()

    def _init_default_bindings(self) -> None:
        """Initialize default vim-style keybindings."""
        # Navigation
        self.register(KeyCode.TAB.value, "focus_next", "Move focus to next pane")
        self.register("\x1b\t", "focus_prev", "Move focus to previous pane")

        # Input manipulation
        self.register(KeyCode.ENTER.value, "submit_input", "Submit input prompt")
        self.register(KeyCode.BACKSPACE.value, "delete_char", "Delete previous character")
        self.register(KeyCode.CTRL_H.value, "delete_char", "Delete previous character (Windows)")
        self.register(KeyCode.CTRL_C.value, "cancel", "Cancel current operation")

        # Command palette
        self.register(KeyCode.CTRL_K.value, "open_palette", "Open command palette")

        # Screen control
        self.register(KeyCode.CTRL_L.value, "clear_screen", "Clear main panel")

        # History navigation
        self.register(KeyCode.UP.value, "history_prev", "Previous input (arrow up)")
        self.register(KeyCode.DOWN.value, "history_next", "Next input (arrow down)")

        # Quit
        self.register(KeyCode.CTRL_D.value, "quit", "Quit application")

    def register(
        self,
        key: str,
        action: str,
        description: str,
        handler: Optional[Callable] = None,
    ) -> None:
        """Register a new key binding."""
        self.bindings[key] = KeyBinding(
            key=key,
            action=action,
            description=description,
            handler=handler,
        )

    def get_action(self, key: str) -> Optional[str]:
        """Get action for a key."""
        # Handle Enter key - could be \r or \n depending on platform/input method
        if key in ("\r", "\n"):
            key = "\r"  # Normalize to \r

        binding = self.bindings.get(key)
        return binding.action if binding else None

    def get_binding(self, key: str) -> Optional[KeyBinding]:
        """Get binding for a key."""
        return self.bindings.get(key)

    def list_bindings(self) -> List[KeyBinding]:
        """List all bindings."""
        return list(self.bindings.values())

    def is_navigation_key(self, key: str) -> bool:
        """Check if key is a navigation key."""
        nav_actions = {"focus_next", "focus_prev", "scroll_up", "scroll_down"}
        action = self.get_action(key)
        return action in nav_actions if action else False

    def is_modifier_key(self, key: str) -> bool:
        """Check if key is a modifier (doesn't produce text)."""
        modifier_actions = {
            "focus_next",
            "focus_prev",
            "history_prev",
            "history_next",
            "submit_input",
            "delete_char",
            "cancel",
            "open_palette",
            "clear_screen",
            "scroll_up",
            "scroll_down",
            "quit",
        }
        action = self.get_action(key)
        return action in modifier_actions if action else False
