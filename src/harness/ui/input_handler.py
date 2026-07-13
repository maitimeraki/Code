"""Raw keyboard event capture and routing."""

import sys
import asyncio
from typing import Optional, Callable, Dict, Awaitable, Literal
from dataclasses import dataclass
from .keybinds import KeybindMap, KeyCode

if sys.platform == "win32":
    from ._win_console_input import ConsoleInputReader


_WINDOWS_EXTENDED_KEY_MAP: Dict[str, str] = {
    "H": KeyCode.UP.value,
    "P": KeyCode.DOWN.value,
    "K": KeyCode.LEFT.value,
    "M": KeyCode.RIGHT.value,
}

# Windows virtual key codes to synthetic key sequences (for console_api reader)
_WINDOWS_VK_MAP: Dict[int, str] = {
    0x26: KeyCode.UP.value,         # VK_UP
    0x28: KeyCode.DOWN.value,       # VK_DOWN
    0x25: KeyCode.LEFT.value,       # VK_LEFT
    0x27: KeyCode.RIGHT.value,      # VK_RIGHT
    0x21: KeyCode.PAGE_UP.value,    # VK_PRIOR (Page Up)
    0x22: KeyCode.PAGE_DOWN.value,  # VK_NEXT (Page Down)
    0x0D: KeyCode.ENTER.value,      # VK_RETURN (Enter)
    0x08: KeyCode.BACKSPACE.value,  # VK_BACK (Backspace)
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
        self._win_tier: Literal["console_api", "msvcrt_legacy", "piped"] = "piped"
        self._console_reader: Optional[ConsoleInputReader] = None

        # Probe Windows input capabilities (3-tier fallback)
        if sys.platform == "win32":
            try:
                self._console_reader = ConsoleInputReader()
                if self._console_reader.available:
                    self._console_reader.enable_mouse_input()
                    self._win_tier = "console_api"
                else:
                    self._console_reader = None
                    self._win_tier = "msvcrt_legacy"
            except Exception:
                self._win_tier = "msvcrt_legacy"

    def shutdown(self) -> None:
        """Clean shutdown - restore console mode if needed."""
        if self._console_reader:
            try:
                self._console_reader.restore_mode()
            except Exception:
                pass

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
        """Read key on Windows via 3-tier fallback: console_api → msvcrt_legacy → piped."""
        if self._win_tier == "console_api":
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._read_key_windows_console)
        elif self._win_tier == "msvcrt_legacy":
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._read_key_windows_msvcrt)
        else:
            return await self._read_key_windows_piped()

    def _read_key_windows_console(self) -> Optional[str]:
        """Read key via Windows console API with mouse support."""
        if not self._console_reader:
            return None

        try:
            record = self._console_reader.poll_event()
            if record is None:
                return None

            if record.EventType == 0x0001:  # KEY_EVENT
                key_event = record.Event.KeyEvent
                vk = key_event.wVirtualKeyCode

                # Check virtual key map first (includes arrows, Enter, Backspace)
                if vk in _WINDOWS_VK_MAP:
                    return _WINDOWS_VK_MAP[vk]

                # Fall back to Unicode character for printable characters
                char_val = str(key_event.uChar) if key_event.uChar else ""
                if char_val and ord(char_val) >= 32:  # Printable
                    return char_val

                return None
            elif record.EventType == 0x0002:  # MOUSE_EVENT
                mouse_event = record.Event.MouseEvent
                # Wheel delta in high 16 bits (signed)
                wheel_delta = (mouse_event.dwButtonState >> 16) & 0xFFFF
                if wheel_delta & 0x8000:
                    wheel_delta = -(0x10000 - wheel_delta)
                if wheel_delta > 0:
                    return KeyCode.MOUSE_WHEEL_UP.value
                elif wheel_delta < 0:
                    return KeyCode.MOUSE_WHEEL_DOWN.value
            return None
        except Exception:
            return None

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
        if not key or len(key) != 1:
            return False
        # Allow all printable ASCII/Unicode characters except control keys
        if not key.isprintable():
            return False
        # Reject if it's a known modifier/control action
        action = self.keybinds.get_action(key)
        if action and action != "text_input":
            return False
        return True
