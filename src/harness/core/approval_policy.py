"""Approval policy: session grants, session denials, and persisted allow rules.

Single source of truth for the human-in-the-loop decision state. Every grant,
deny and check routes through ``_toolkey`` so a ``ToolType`` enum member and its
plain string (e.g. ``ToolType.BASH`` and ``"Bash"``) always produce the same
key — otherwise ``str(ToolType.BASH) == "ToolType.BASH"`` silently diverges and
an approval can never be matched again.
"""

import json
from enum import Enum
from datetime import datetime
from typing import Any, Optional
import structlog

from harness.core.user_preferences import get_preference, set_preference

logger = structlog.get_logger(__name__)


def _toolkey(tool) -> str:
    """Normalize a tool identity to its plain string (enum -> value)."""
    return tool.value if isinstance(tool, Enum) else str(tool)


# Session-level grants: set of f"{tool}:{fingerprint}" approved for this session.
_session_grants: set[str] = set()
# Session-level denials: set of f"{tool}:{fingerprint}" denied for this session.
_session_denials: set[str] = set()
# One-call grants/denials: f"{tool}:{exact_fingerprint}" — match only the exact call.
_once_grants: set[str] = set()
_once_denials: set[str] = set()


# ── Fingerprints (single source of truth, used by gates AND grant handlers) ──

def coarse_fingerprint(tool: str, resource: str = "") -> str:
    """Session-level fingerprint: Bash by first token, file tools by parent dir,
    everything else (Skill, Task*, MCP, ...) whole-tool ("")."""
    t = _toolkey(tool)
    if t == "Bash":
        return fingerprint_bash(resource)
    if t in ("Read", "Write", "Update", "Edit", "Grep", "Glob"):
        return fingerprint_file(resource)
    return ""


def exact_fingerprint(tool: str, resource: str = "") -> str:
    """One-call fingerprint: the exact command/path, whole-tool otherwise."""
    t = _toolkey(tool)
    if t == "Bash":
        return (resource or "").strip()
    if t in ("Read", "Write", "Update", "Edit", "Grep", "Glob"):
        return resource or ""
    return ""


# ── Grant / deny actions ────────────────────────────────────────────────────

def grant_session(tool: str, fingerprint: str) -> None:
    """Grant approval for this session (option [A])."""
    _session_grants.add(f"{_toolkey(tool)}:{fingerprint}")
    logger.info("Session grant issued", tool=_toolkey(tool), fingerprint=fingerprint)


def grant_once(tool: str, resource: str) -> None:
    """Approve exactly this one call (option [Y])."""
    _once_grants.add(f"{_toolkey(tool)}:{exact_fingerprint(tool, resource)}")
    logger.info("One-call grant issued", tool=_toolkey(tool), resource=resource)


def deny_session(tool: str, resource: str) -> None:
    """Deny for this session (option [S]) — suppress further prompts."""
    _session_denials.add(f"{_toolkey(tool)}:{coarse_fingerprint(tool, resource)}")
    logger.info("Session denial issued", tool=_toolkey(tool), resource=resource)


def deny_once(tool: str, resource: str) -> None:
    """Deny exactly this one call (option [N])."""
    _once_denials.add(f"{_toolkey(tool)}:{exact_fingerprint(tool, resource)}")
    logger.info("One-call denial issued", tool=_toolkey(tool), resource=resource)


def persist_allow(tool: str) -> None:
    """Persist a tool as allowed in the project-level .code/settings.json
    (option [P]) so future sessions in this project stop prompting for it."""
    from harness.config import add_permission_allow
    add_permission_allow(_toolkey(tool))


# ── Checks ──────────────────────────────────────────────────────────────────

def is_granted_session(tool: str, fingerprint: str) -> bool:
    """Check if tool+fingerprint is granted for this session."""
    return f"{_toolkey(tool)}:{fingerprint}" in _session_grants


def is_granted(tool: str, resource: str = "") -> bool:
    """True if this tool+resource was approved (session-wide or for this exact call)."""
    t = _toolkey(tool)
    return (
        f"{t}:{coarse_fingerprint(t, resource)}" in _session_grants
        or f"{t}:{exact_fingerprint(t, resource)}" in _once_grants
    )


def is_denied(tool: str, resource: str = "") -> bool:
    """True if this tool+resource was denied (session-wide or for this exact call)."""
    t = _toolkey(tool)
    return (
        f"{t}:{coarse_fingerprint(t, resource)}" in _session_denials
        or f"{t}:{exact_fingerprint(t, resource)}" in _once_denials
    )


# ── Persisted rules (DB-backed, kept for compatibility; UI uses settings.json) ──

async def grant_persisted(
    tool: str,
    fingerprint: str,
    decision: str = "allow",
    user_id: str = "local",
) -> None:
    """Save approval rule to user preferences (legacy path)."""
    rules = await get_approval_rules(user_id)
    rules.append({
        "tool": _toolkey(tool),
        "pattern": fingerprint,
        "decision": decision,
        "at": datetime.now().isoformat(),
    })
    rule_json = json.dumps(rules)
    await set_preference(user_id, "approval_rules", rule_json, source="user")
    logger.info("Persisted approval rule added", tool=_toolkey(tool), pattern=fingerprint)


async def is_granted_persisted(tool: str, fingerprint: str, user_id: str = "local") -> bool:
    """Check if tool+fingerprint is in persisted rules (legacy path)."""
    rules = await get_approval_rules(user_id)
    t = _toolkey(tool)
    for rule in rules:
        if rule.get("tool") == t and rule.get("pattern") == fingerprint:
            return rule.get("decision") == "allow"
    return False


async def get_approval_rules(user_id: str = "local") -> list[dict[str, Any]]:
    """Get all approval rules for a user."""
    raw_value = await get_preference(user_id, "approval_rules")
    if not raw_value:
        return []
    try:
        return json.loads(raw_value)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse approval_rules", user_id=user_id)
        return []


def fingerprint_bash(command: str) -> str:
    """Fingerprint a Bash command (first token)."""
    try:
        import shlex
        tokens = shlex.split(command)
        return tokens[0] if tokens else ""
    except ValueError:
        return ""


def fingerprint_file(path: str) -> str:
    """Fingerprint a file path (parent directory)."""
    from pathlib import Path
    try:
        p = Path(path).resolve()
        return str(p.parent)
    except Exception:
        return ""


def clear_session_grants() -> None:
    """Clear all session grants/denials (e.g., on restart or logout)."""
    global _session_grants, _session_denials, _once_grants, _once_denials
    _session_grants.clear()
    _session_denials.clear()
    _once_grants.clear()
    _once_denials.clear()
    logger.info("Session approval state cleared")
