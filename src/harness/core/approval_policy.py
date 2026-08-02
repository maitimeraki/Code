"""Approval policy: session grants and persisted rules for tool approval decisions."""

import json
from datetime import datetime
from typing import Any, Optional
import structlog

from harness.core.user_preferences import get_preference, set_preference

logger = structlog.get_logger(__name__)


# Session-level grants: set of f"{tool}:{fingerprint}" that have been approved for this session.
_session_grants: set[str] = set()


def grant_session(tool: str, fingerprint: str) -> None:
    """Grant approval for this session (option [A])."""
    key = f"{tool}:{fingerprint}"
    _session_grants.add(key)
    logger.info("Session grant issued", tool=tool, fingerprint=fingerprint)


def is_granted_session(tool: str, fingerprint: str) -> bool:
    """Check if tool+fingerprint is granted for this session."""
    key = f"{tool}:{fingerprint}"
    return key in _session_grants


async def grant_persisted(
    tool: str,
    fingerprint: str,
    decision: str = "allow",
    user_id: str = "local",
) -> None:
    """Save approval rule to user preferences (option [P])."""
    rules = await get_approval_rules(user_id)
    rules.append({
        "tool": tool,
        "pattern": fingerprint,
        "decision": decision,
        "at": datetime.now().isoformat(),
    })
    rule_json = json.dumps(rules)
    await set_preference(user_id, "approval_rules", rule_json, source="user")
    logger.info("Persisted approval rule added", tool=tool, pattern=fingerprint)


async def is_granted_persisted(tool: str, fingerprint: str, user_id: str = "local") -> bool:
    """Check if tool+fingerprint is in persisted rules."""
    rules = await get_approval_rules(user_id)
    for rule in rules:
        if rule.get("tool") == tool and rule.get("pattern") == fingerprint:
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
    """Clear all session grants (e.g., on restart or logout)."""
    global _session_grants
    _session_grants.clear()
    logger.info("Session grants cleared")
