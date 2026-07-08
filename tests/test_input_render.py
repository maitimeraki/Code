#!/usr/bin/env python3
"""Test what input bar renders."""

from harness.ui.input_bar import InputBar
from harness.ui.claude_code_style import create_console

console = create_console()
input_bar = InputBar(console)

render_result = input_bar.render()
print("[DEBUG] Input bar render type:", type(render_result))
print("[DEBUG] Input bar render:", repr(render_result))

# Try to print it
console.print(render_result)
