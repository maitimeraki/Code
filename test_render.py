#!/usr/bin/env python3
"""Test what render_layout actually produces."""

from harness.ui.terminal import TerminalUI

ui = TerminalUI()
ui.initialize()

layout = ui.render_layout()
print("[DEBUG] Layout type:", type(layout))
print("[DEBUG] Layout repr:", repr(layout))
print("[DEBUG] Layout str:", str(layout))

print("\n[DEBUG] Console test:")
ui.console.print("Hello, this is a test message")
print("[DEBUG] Console height:", ui.console.height)
print("[DEBUG] Console width:", ui.console.width)
