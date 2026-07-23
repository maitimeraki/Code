"""Permission scope and sandbox enforcement for tool execution.

Aligned with Claude Code's permission model:
- Tool-level permissions (allow/deny/ask)
- Pattern matching for path/command constraints
- Minimal structure, no separate Guard classes
"""

import re
import shlex
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from harness.config import get_app_settings


@dataclass
class ToolPermission:
    """Single tool's permission state."""

    tool: str
    mode: Literal["allow", "deny", "ask"]
    patterns: list[str] = field(default_factory=list)  # e.g., ["Read(.env*)", "Write(.git/*)"]


@dataclass
class PermissionScope:
    """Claude Code-aligned permission model.

    Tools are gated with allow/deny/ask modes. Patterns constrain specific tools
    (e.g., deny Read on .env files). ask mode requires approval when triggered.
    """

    tools: dict[str, ToolPermission] = field(default_factory=dict)
    allowed_paths: list[Path] = field(default_factory=list)  # For backward-compat narrowing
    default_mode: Literal["auto", "strict", "permissive"] = "auto"
    always_ask: list[str] = field(default_factory=list)  # Tools always requiring approval

    @classmethod
    def default_for_project(cls, project_root: Path) -> "PermissionScope":
        """Build a PermissionScope from app settings.

        Reads get_app_settings().get("permissions", {}) with Claude Code format:
        - allow: list of allowed tools
        - deny: list of denied tools
        - ask: list of tools requiring approval
        - patterns: dict mapping tool -> patterns to deny (e.g., {"Read": ["Read(.env*)"]})
        - alwaysAsk: list of tools always requiring approval
        - defaultMode: "auto", "strict", or "permissive"
        """
        app_settings = get_app_settings()
        perm_config = app_settings.get("permissions", {})

        # Build tool permissions from allow/deny/ask lists
        tools = {}
        for tool in perm_config.get("allow", []):
            tools[tool] = ToolPermission(tool=tool, mode="allow")

        for tool in perm_config.get("deny", []):
            tools[tool] = ToolPermission(tool=tool, mode="deny")

        patterns_config = perm_config.get("patterns", {})
        for tool in perm_config.get("ask", []):
            patterns = patterns_config.get(tool, [])
            tools[tool] = ToolPermission(tool=tool, mode="ask", patterns=patterns)

        # If no explicit config, default to allow common tools
        if not tools:
            default_tools = ["Read", "Bash", "Edit", "Glob", "Grep", "Skill",
                             "AskUserQuestion", "TaskCreate", "TaskGet", "TaskList",
                             "TaskOutput", "TaskStop", "TaskUpdate"]
            for tool in default_tools:
                tools[tool] = ToolPermission(tool=tool, mode="allow")

        return cls(
            tools=tools,
            allowed_paths=[project_root.resolve()],
            default_mode=perm_config.get("defaultMode", "auto"),
            always_ask=perm_config.get("alwaysAsk", []),
        )

    def check(self, tool: str, resource: str = "") -> tuple[bool, str | None]:
        """Check if tool+resource is allowed.

        Returns (allowed, mode) where mode is:
        - None: allowed without approval
        - "requires_approval": allowed but needs user approval
        - PermissionError: denied (caller should raise)
        """
        # Always-ask tools require approval
        if tool in self.always_ask:
            return True, "requires_approval"

        perm = self.tools.get(tool)
        if not perm:
            if self.default_mode == "strict":
                return False, None
            return True, None

        if perm.mode == "deny":
            return False, None

        if perm.mode == "ask":
            if self._matches_patterns(resource, perm.patterns):
                return True, "requires_approval"
            return True, None

        return True, None

    @staticmethod
    def _matches_patterns(resource: str, patterns: list[str]) -> bool:
        """Check if resource matches any pattern (e.g., "Read(.env*)" → deny .env files)."""
        for pattern in patterns:
            # Parse "Tool(glob_pattern)" → extract glob and convert to regex
            if "(" in pattern and ")" in pattern:
                _, glob_part = pattern.split("(", 1)
                glob_part = glob_part.rstrip(")")
                regex = glob_part.replace("*", ".*").replace("?", ".")
                if re.match(f"^{regex}$", resource):
                    return True
        return False

    def without_agent_spawn(self) -> "PermissionScope":
        """Return a copy with agent spawning disabled."""
        new_tools = dict(self.tools)
        new_tools["spawn_agent"] = ToolPermission(tool="spawn_agent", mode="deny")
        return replace(self, tools=new_tools)

    def narrowed_to(self, working_dir) -> "PermissionScope":
        """Return a copy whose filesystem access is clamped to working_dir.

        The returned scope's allowed_paths is exactly the given directory (resolved),
        so path checks deny any access resolving outside it.
        """
        if not working_dir:
            return self

        target = Path(working_dir).resolve()
        if not target.is_dir():
            return self

        # Only allow narrowing to a directory already inside an allowed path
        for allowed in self.allowed_paths:
            try:
                target.relative_to(allowed)
                return replace(self, allowed_paths=[target])
            except ValueError:
                continue

        return self


class PathGuard:
    """Guards filesystem access by validating paths are within allowed scope.

    Used by factory.py to enforce allowed_paths constraints.
    """

    @staticmethod
    def resolve_and_check(
        path: str, scope: PermissionScope, mode: Literal["read", "write"]
    ) -> Path:
        """Resolve a path and verify it's within allowed_paths.

        Args:
            path: The filesystem path to check.
            scope: The permission scope defining allowed paths.
            mode: Read or write mode (primarily for error messages).

        Returns:
            The resolved Path if it passes the check.

        Raises:
            PermissionError: If path is outside allowed_paths.
        """
        resolved = Path(path).resolve()

        # Check if resolved path is within any allowed path
        for allowed in scope.allowed_paths:
            try:
                resolved.relative_to(allowed)
                return resolved
            except ValueError:
                continue

        raise PermissionError(
            f"Path access denied ({mode}): {path} -> {resolved} is outside allowed paths: "
            f"{', '.join(str(p) for p in scope.allowed_paths)}"
        )


class CommandGuard:
    """Guards shell command execution by checking against patterns."""

    @staticmethod
    def check(command: str, scope: PermissionScope) -> None:
        """Validate a bash command is allowed.

        Args:
            command: The full bash command to check.
            scope: The permission scope.

        Raises:
            PermissionError: If command violates rules.
        """
        # Check if Bash tool is denied
        bash_perm = scope.tools.get("Bash")
        if bash_perm and bash_perm.mode == "deny":
            raise PermissionError("Bash execution is not allowed in this scope")

        try:
            tokens = shlex.split(command)
        except ValueError as e:
            raise PermissionError(f"Invalid bash command syntax: {str(e)}")

        if not tokens:
            raise PermissionError("Empty bash command")

        first_token = tokens[0]

        # Check deny patterns on Bash tool
        if bash_perm and bash_perm.mode == "ask":
            for pattern in bash_perm.patterns:
                if PermissionScope._matches_patterns(command, [pattern]):
                    raise PermissionError(
                        f"Bash command matches forbidden pattern: '{pattern}' in '{command}'"
                    )
