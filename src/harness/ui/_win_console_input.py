"""Windows console input reader with keyboard and mouse support via ReadConsoleInputW."""

import sys
import ctypes
from ctypes import wintypes
from typing import Optional


if sys.platform == "win32":
    # Verify struct size at import time
    pass  # Will verify after struct definition


# Win32 Constants
ENABLE_MOUSE_INPUT = 0x0010
ENABLE_EXTENDED_FLAGS = 0x0080
ENABLE_QUICK_EDIT_MODE = 0x0040

# Event types
KEY_EVENT = 0x0001
MOUSE_EVENT = 0x0002


class Coord(ctypes.Structure):
    """COORD structure for mouse position."""
    _fields_ = [
        ("X", wintypes.SHORT),
        ("Y", wintypes.SHORT),
    ]


class KeyEventRecord(ctypes.Structure):
    """KEY_EVENT_RECORD from Win32."""
    _fields_ = [
        ("bKeyDown", wintypes.BOOL),
        ("wRepeatCount", wintypes.WORD),
        ("wVirtualKeyCode", wintypes.WORD),
        ("wVirtualScanCode", wintypes.WORD),
        ("uChar", ctypes.c_wchar),
        ("dwControlKeyState", wintypes.DWORD),
    ]


class MouseEventRecord(ctypes.Structure):
    """MOUSE_EVENT_RECORD from Win32."""
    _fields_ = [
        ("dwMousePosition", Coord),
        ("dwButtonState", wintypes.DWORD),
        ("dwControlKeyState", wintypes.DWORD),
        ("dwEventFlags", wintypes.DWORD),
    ]


class InputRecord(ctypes.Structure):
    """INPUT_RECORD from Win32 - union of KEY_EVENT_RECORD and MOUSE_EVENT_RECORD."""
    class Event(ctypes.Union):
        _fields_ = [
            ("KeyEvent", KeyEventRecord),
            ("MouseEvent", MouseEventRecord),
        ]

    _fields_ = [
        ("EventType", wintypes.WORD),
        ("Event", Event),
    ]


if sys.platform == "win32":
    assert ctypes.sizeof(InputRecord) == 20, f"InputRecord size mismatch: {ctypes.sizeof(InputRecord)}"


class ConsoleInputReader:
    """Windows console input reader supporting keyboard and mouse."""

    def __init__(self):
        """Initialize console reader."""
        self.stdin_handle = None
        self.original_mode = None
        self.available = False

        if sys.platform != "win32":
            return

        try:
            # Get STDIN handle
            kernel32 = ctypes.windll.kernel32
            self.stdin_handle = kernel32.GetStdHandle(-11)  # STD_INPUT_HANDLE

            if self.stdin_handle == -1 or not self.stdin_handle:
                return

            # Check if it's a console
            mode = wintypes.DWORD()
            if not kernel32.GetConsoleMode(self.stdin_handle, ctypes.byref(mode)):
                return

            self.original_mode = mode.value
            self.kernel32 = kernel32
            self.available = True
        except Exception:
            pass

    def enable_mouse_input(self) -> bool:
        """Enable mouse input on the console."""
        if not self.available or not self.stdin_handle:
            return False

        try:
            new_mode = self.original_mode | ENABLE_MOUSE_INPUT | ENABLE_EXTENDED_FLAGS
            new_mode &= ~ENABLE_QUICK_EDIT_MODE
            return bool(self.kernel32.SetConsoleMode(self.stdin_handle, new_mode))
        except Exception:
            return False

    def poll_event(self) -> Optional[InputRecord]:
        """Poll and return next actionable event (keyboard or mouse wheel only)."""
        if not self.available or not self.stdin_handle:
            return None

        try:
            # Check how many events are pending
            num_events = wintypes.DWORD()
            if not self.kernel32.GetNumberOfConsoleInputEvents(self.stdin_handle, ctypes.byref(num_events)):
                return None

            if num_events.value == 0:
                return None

            # Read up to 32 events at once to drain the buffer
            records = (InputRecord * min(32, num_events.value))()
            num_read = wintypes.DWORD()

            if not self.kernel32.ReadConsoleInputW(
                self.stdin_handle,
                ctypes.byref(records),
                len(records),
                ctypes.byref(num_read)
            ):
                return None

            # Walk through records looking for actionable events
            for i in range(num_read.value):
                record = records[i]

                if record.EventType == KEY_EVENT:
                    key_event = record.Event.KeyEvent
                    # Only return key-down events
                    if key_event.bKeyDown:
                        return record
                elif record.EventType == MOUSE_EVENT:
                    mouse_event = record.Event.MouseEvent
                    # Check wheel events: wheel delta in high 16 bits of dwButtonState
                    if mouse_event.dwEventFlags & 0x0004:  # MOUSE_WHEELED
                        return record

            # No actionable events found
            return None
        except Exception:
            return None

    def restore_mode(self) -> None:
        """Restore original console mode."""
        if not self.available or not self.stdin_handle or not self.original_mode:
            return

        try:
            self.kernel32.SetConsoleMode(self.stdin_handle, self.original_mode)
        except Exception:
            pass
