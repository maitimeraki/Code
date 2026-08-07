"""Permission scope and sandbox enforcement for tool execution.

Aligned with Claude Code's permission model:
- Tool-level permissions (allow/deny/ask)
- Pattern matching for path/command constraints
- Minimal structure, no separate Guard classes
"""

import fnmatch
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
        - allow: list of allowed tools (no pattern checking)
        - ask: list of tools requiring approval (no pattern checking)
        - deny: list of tools with specific path patterns to block
        - patterns: dict mapping tool -> glob patterns to deny (e.g., {"Read": [".env*", ".git/*"]})
        - alwaysAsk: list of tools always requiring approval
        - defaultMode: "auto", "strict", or "permissive"
        """
        app_settings = get_app_settings()
        perm_config = app_settings.get("permissions", {})

        tools = {}

        # Allow tools - no patterns, always allowed
        for tool in perm_config.get("allow", []):
            tools[tool] = ToolPermission(tool=tool, mode="allow")

        # Ask tools - no patterns, always require approval
        for tool in perm_config.get("ask", []):
            tools[tool] = ToolPermission(tool=tool, mode="ask")

        # Deny tools - WITH patterns to block specific paths
        # Support both new format (deny as tool names, patterns separate)
        # and legacy format (deny as "Tool(pattern)" strings)
        # Deny OVERRIDES any prior mode (allow/ask) for the same tool
        patterns_config = perm_config.get("patterns", {})
        for tool_entry in perm_config.get("deny", []):
            tool_name = tool_entry
            patterns = []

            # Legacy format: "Tool(pattern)" → extract both
            if "(" in tool_entry and ")" in tool_entry:
                tool_name, pattern_part = tool_entry.split("(", 1)
                pattern_part = pattern_part.rstrip(")")
                patterns = [pattern_part] if pattern_part else []

            # New format: get patterns from patterns dict
            patterns_from_config = patterns_config.get(tool_name, [])
            if patterns_from_config:
                patterns = patterns_from_config

            tools[tool_name] = ToolPermission(tool=tool_name, mode="deny", patterns=patterns)

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
        - None (with False): denied (caller should raise PermissionError)
        """
        perm = self.tools.get(tool)

        # Deny mode: blocks when pattern matches; allows when pattern doesn't match
        if perm and perm.mode == "deny":
            if self._matches_patterns(resource, perm.patterns):
                return False, None  # Pattern matched → BLOCK access
            # Pattern didn't match → tool is allowed
            return True, None

        # Always-ask tools require approval
        if tool in self.always_ask:
            return True, "requires_approval"

        if not perm:
            if self.default_mode == "strict":
                return False, None
            return True, None

        # Ask mode: require approval for all operations
        if perm.mode == "ask":
            return True, "requires_approval"

        # Allow mode: always permitted
        return True, None

    @staticmethod
    def _matches_patterns(resource: str, patterns: list[str]) -> bool:
        """Check if resource matches any pattern.

        Patterns can be:
        - Simple glob: ".env*" (matches filename)
        - Path glob: ".git/*" (matches path components)
        - Legacy format: "Tool(.env*)" → extracted as ".env*"
        """
        if not resource:
            return False

        resource_path = Path(resource)
        filename = resource_path.name

        for pattern in patterns:
            glob_part = pattern

            # Handle legacy format: "Tool(glob_pattern)"
            if "(" in pattern and ")" in pattern:
                _, glob_part = pattern.split("(", 1)
                glob_part = glob_part.rstrip(")")

            # Use fnmatch for filename matching (handles ".env*")
            # Use Path.match() for glob patterns with path separators (handles ".git/*")
            if fnmatch.fnmatch(filename, glob_part):
                return True

            # For patterns with path separators, use pathlib's glob matching
            if "/" in glob_part or "\\" in glob_part:
                try:
                    if resource_path.match(glob_part):
                        return True
                except (ValueError, TypeError):
                    pass

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
