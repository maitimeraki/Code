"""Bound tool output before it enters the LLM message list."""

MAX_TOOL_OUTPUT_CHARS = 8000
_HEAD_CHARS = 5000
_TAIL_CHARS = 2000


def cap_output(text: str, ref_id: str) -> tuple[str, bool]:
    """Return (text, was_capped). Oversized text keeps its head and tail.

    The middle is replaced by a marker naming the retrieval call, so the model
    knows the output was elided rather than assuming it saw everything.
    """
    if not text:
        return "", False
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= MAX_TOOL_OUTPUT_CHARS:
        return text, False

    omitted = len(text) - _HEAD_CHARS - _TAIL_CHARS
    marker = (
        f"\n\n[... {omitted} characters omitted. Full output stored as "
        f"tool_call_id={ref_id}. Retrieve it with "
        f'MemorySearch(query="{ref_id}", source="tool_output") ...]\n\n'
    )
    return text[:_HEAD_CHARS] + marker + text[-_TAIL_CHARS:], True
