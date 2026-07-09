"""Raw keyboard event capture and routing."""

import sys
import asyncio
from typing import Optional, Callable, Dict, Awaitable
from dataclasses import dataclass
from .keybinds import KeybindMap, KeyCode


_WINDOWS_EXTENDED_KEY_MAP: Dict[str, str] = {
    "H": KeyCode.UP.value,
    "P": KeyCode.DOWN.value,
    "K": KeyCode.LEFT.value,
    "M": KeyCode.RIGHT.value,
}


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
        # Try to use msvcrt on Windows (works on interactive console)
        self._use_msvcrt = sys.platform == "win32"

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
        """Read key on Windows using msvcrt (no echo, no orphaned threads)."""
        if self._use_msvcrt:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._read_key_windows_msvcrt)
        return await self._read_key_windows_piped()

    def _read_key_windows_msvcrt(self) -> Optional[str]:
        """Non-blocking, no-echo key read via msvcrt (real TTY only)."""
        try:
            import msvcrt
        except ImportError:
            return None

        if not msvcrt.kbhit():
            return None

        ch = msvcrt.getch()

        if ch in (b"\x00", b"\xe0"):
            scan = msvcrt.getch()
            return _WINDOWS_EXTENDED_KEY_MAP.get(chr(scan[0]))

        return ch.decode('utf-8', errors='replace') if isinstance(ch, bytes) else ch

    async def _read_key_windows_piped(self) -> Optional[str]:
        """Executor-based read; used only when stdin is not a TTY."""
        try:
            loop = asyncio.get_event_loop()
            try:
                ch = await asyncio.wait_for(
                    loop.run_in_executor(None, sys.stdin.read, 1),
                    timeout=0.01
                )
                return ch if ch else None
            except asyncio.TimeoutError:
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
