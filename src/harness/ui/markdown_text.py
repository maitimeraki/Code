"""Lightweight markdown-to-Rich-Text renderer for assistant prose.

Scope: assistant reply text only. Converts the common inline/block markdown the
model emits (**bold**, *italic*, `code`, # headings, - bullets) into a single
Rich `Text` object so it flows through MainPanel's existing row-wrap windowing.

Deliberately small: raw tool stdout (git status, file contents) is NOT passed
through here — it must stay verbatim.
"""

import re
from rich.text import Text
from .claude_code_style import Colors

# Inline token: bold (**x**), italic (*x* / _x_), or code (`x`).
# Ordered so ** is matched before single *.
_INLINE = re.compile(
    r"(\*\*(?P<bold>.+?)\*\*)"
    r"|(?<!\*)\*(?P<italic>[^*]+?)\*(?!\*)"
    r"|(?<!_)_(?P<italic2>[^_]+?)_(?!_)"
    r"|(`(?P<code>[^`]+?)`)"
)


def _append_inline(text: Text, line: str) -> None:
    """Append a single line of inline markdown to `text`."""
    pos = 0
    for m in _INLINE.finditer(line):
        if m.start() > pos:
            text.append(line[pos:m.start()])

        if m.group("bold") is not None:
            text.append(m.group("bold"), style="bold")
        elif m.group("italic") is not None:
            text.append(m.group("italic"), style="italic")
        elif m.group("italic2") is not None:
            text.append(m.group("italic2"), style="italic")
        elif m.group("code") is not None:
            text.append(m.group("code"), style=f"bold {Colors.TOOL_CYAN}")

        pos = m.end()

    if pos < len(line):
        text.append(line[pos:])


def _append_inline_styled(text: Text, line: str, base_style: str) -> None:
    """Append inline markdown where the whole line carries a base style (headings)."""
    start = len(text.plain)
    _append_inline(text, line)
    text.stylize(base_style, start, len(text.plain))


def render_markdown(source: str) -> Text:
    """Convert a markdown string to a single Rich `Text`.

    Handles block-level headings and bullets line-by-line, with inline styling
    applied within each line.
    """
    text = Text()
    lines = source.split("\n")

    for i, raw_line in enumerate(lines):
        if i > 0:
            text.append("\n")

        stripped = raw_line.lstrip()
        indent = raw_line[: len(raw_line) - len(stripped)]

        # Headings: # .. ###### → bold gold, hashes dropped.
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            text.append(indent)
            _append_inline_styled(text, heading.group(2), base_style=f"bold {Colors.AGENT_GOLD}")
            continue

        # Bullets: - / * / + → normalized bullet glyph.
        bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
        if bullet:
            text.append(f"{indent}• ", style=Colors.ASSISTANT_CORAL)
            _append_inline(text, bullet.group(1))
            continue

        _append_inline(text, raw_line)

    return text
