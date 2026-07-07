"""Raw keyboard event capture and routing."""

import sys
import asyncio
from typing import Optional, Callable, Dict, Awaitable
from dataclasses import dataclass
from .keybinds import KeybindMap


@dataclass
class KeyEvent:
    """A keyboard event."""
    key: str
    action: str
    is_text: bool


class InputHandler:
    """Handles raw keyboard input and routes to actions."""

    def __init__(self, keybinds: KeybindMap):
        self.keybinds = keybinds
        self.handlers: Dict[str, Callable[[KeyEvent], Awaitable[None]]] = {}

    def register_handler(
        self, action: str, handler: Callable[[KeyEvent], Awaitable[None]]
    ) -> None:
        """Register a handler for an action."""
        self.handlers[action] = handler

    async def handle_key(self, key: str) -> Optional[KeyEvent]:
        """Handle a single key press and dispatch to registered handler."""
        action = self.keybinds.get_action(key)

        if action is None:
            # Regular text input
            return KeyEvent(key=key, action="text_input", is_text=True)

        event = KeyEvent(key=key, action=action, is_text=False)

        # Dispatch to registered handler
        if action in self.handlers:
            handler = self.handlers[action]
            await handler(event)

        return event

    async def read_key(self) -> Optional[str]:
        """Read a single key from stdin (non-blocking)."""
        if sys.platform == "win32":
            return await self._read_key_windows()
        else:
            return await self._read_key_unix()

    async def _read_key_windows(self) -> Optional[str]:
        """Read key on Windows using msvcrt."""
        try:
            import msvcrt

            if msvcrt.kbhit():
                key = msvcrt.getch()
                # Handle arrow keys
                if key == b"\xe0":
                    next_key = msvcrt.getch()
                    arrow_map = {
                        b"H": "\x1b[A",  # up
                        b"P": "\x1b[B",  # down
                        b"K": "\x1b[D",  # left
                        b"M": "\x1b[C",  # right
                    }
                    return arrow_map.get(next_key)
                return key.decode("utf-8", errors="ignore")
            return None
        except Exception:
            return None

    async def _read_key_unix(self) -> Optional[str]:
        """Read key on Unix/Linux using termios."""
        try:
            import termios
            import tty

            loop = asyncio.get_event_loop()
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)

            try:
                tty.setraw(fd)
                ch = await loop.run_in_executor(None, sys.stdin.read, 1)
                return ch if ch else None
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            return None

    def is_text_input(self, key: str) -> bool:
        """Check if key is regular text (not a control key)."""
        return (
            not self.keybinds.is_modifier_key(key)
            and len(key) == 1
            and key.isprintable()
        )
