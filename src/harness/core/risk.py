"""Risk classification for tool calls (used by the opt-in approval gate)."""

import os
import re
import shlex
from pathlib import Path
from typing import Any

from harness.tools.models import ToolType
from harness.tools.permissions import PermissionScope

# Bash commands that indicate high-risk operations.
_HIGH_RISK_BASH_COMMANDS = {
    "rm", "git", "dd", "mkfs", "truncate", "drop", "shutdown", "reboot", "sudo",
}


def classify_risk(
    tool_type: ToolType,
    args: dict[str, Any],
    scope: PermissionScope | None = None,
) -> str:
    """Return a coarse risk level for a tool call: "low" | "high".

    Flags clearly destructive/externally-visible actions (rm -rf, git push, DB drops),
    file operations outside allowed scope, and agent spawning. Deliberately conservative.

    Args:
        tool_type: The type of tool being called.
        args: The arguments passed to the tool.
        scope: Optional PermissionScope for checking file access bounds.

    Returns:
        "low" or "high" risk level.
    """
    try:
        if tool_type == ToolType.BASH:
            command = args.get("command", "").strip()
            if not command:
                return "low"
            try:
                tokens = shlex.split(command)
                if tokens:
                    cmd_name = os.path.basename(tokens[0]).lower()
                    if cmd_name in _HIGH_RISK_BASH_COMMANDS:
                        return "high"
                    command_lower = command.lower()
                    if any(
                        x in command_lower
                        for x in ("rm -rf", "rm -r", "rm -f", "git push",
                                   "git reset --hard", "git clean", "drop table",
                                   "drop database", "> /dev", ":(){")
                    ):
                        return "high"
            except ValueError:
                return "high"

        elif tool_type == ToolType.READ:
            path = args.get("path", "")
            if _is_secret_path(path):
                return "high"

        elif tool_type in (ToolType.WRITE, ToolType.EDIT):
            if scope:
                path = args.get("path", "")
                try:
                    from harness.tools.permissions import PathGuard
                    PathGuard.resolve_and_check(path, scope, "write")
                except PermissionError:
                    return "high"

        elif tool_type == ToolType.SPAWN_AGENT:
            return "high"

    except Exception:
        return "high"

    return "low"


def _is_secret_path(path: str) -> bool:
    """Check if path looks like a secret (.env*, *_rsa, credentials*, etc)."""
    path_lower = path.lower()
    secret_patterns = (r"\.env", r"_rsa$", r"credentials", r"secret", r"token", r"password")
    return any(re.search(p, path_lower) for p in secret_patterns)
