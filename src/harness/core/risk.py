"""Risk classification for tool calls (used by the opt-in approval gate)."""

from typing import Any

from harness.tools.models import ToolType

# Substrings in a bash command that mark it as destructive/irreversible.
_HIGH_RISK_BASH = (
    "rm -rf", "rm -r", "rm -f", "git push", "git reset --hard", "git clean",
    "drop table", "drop database", "truncate", "shutdown", "reboot", "mkfs",
    "dd ", "> /dev", ":(){", "sudo",
)


def classify_risk(tool_type: ToolType, args: dict[str, Any]) -> str:
    """Return a coarse risk level for a tool call: "low" | "high".

    Deliberately conservative and simple — only flags the clearly destructive or
    externally-visible actions (rm -rf, git push, DB drops). Reads and in-project
    writes are low; the caller decides what to do with a "high" verdict.
    """
    if tool_type == ToolType.BASH:
        command = (args.get("command") or "").lower()
        if any(pat in command for pat in _HIGH_RISK_BASH):
            return "high"
    return "low"
