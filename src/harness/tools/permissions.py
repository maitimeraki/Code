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


class ApprovalRequired(Exception):
    """Raised when a tool+resource needs human approval but has not been granted.

    The tool executor converts this into an AWAITING_APPROVAL result so the call
    is never executed silently.
    """


@dataclass
class ToolPermission:
    """Single tool's permission state.

    ``patterns`` scopes the tool's mode: for ``ask`` they narrow which resources
    prompt, for ``deny`` which resources are blocked. ``deny_patterns`` carries
    path-scoped deny rules on an otherwise-allowed tool (e.g. Read allowed
    everywhere except ``.env*`` / ``.git/*``).
    """

    tool: str
    mode: Literal["allow", "deny", "ask"]
    patterns: list[str] = field(default_factory=list)       # scopes the mode
    deny_patterns: list[str] = field(default_factory=list)  # path-scoped deny on an allow/ask tool


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

        allow_list = perm_config.get("allow", [])
        deny_list = perm_config.get("deny", [])
        ask_list = perm_config.get("ask", [])
        patterns_config = perm_config.get("patterns", {})

        # Build per-tool permissions with path scoping. Priority: deny > ask >
        # allow — a tool in several lists keeps each concern, instead of the last
        # list silently overwriting the others (which is what blanketed Read in
        # deny and dropped its patterns).
        tools: dict[str, ToolPermission] = {}

        # Deny is strongest: whole-tool, or path-scoped via `patterns`.
        for tool in deny_list:
            tools[tool] = ToolPermission(
                tool=tool, mode="deny", patterns=list(patterns_config.get(tool, []))
            )

        # Ask: prompt on matching paths, or always when the entry has no patterns.
        # A tool already deny-scoped (e.g. Write on .git/*) keeps those hard deny
        # paths while prompting for everything else.
        for tool in ask_list:
            existing = tools.get(tool)
            if existing is not None and existing.mode == "deny":
                tools[tool] = ToolPermission(
                    tool=tool,
                    mode="ask",
                    patterns=[],
                    deny_patterns=list(existing.patterns),
                )
            else:
                tools[tool] = ToolPermission(
                    tool=tool, mode="ask", patterns=list(patterns_config.get(tool, []))
                )

        # Allow is weakest. An allowlisted tool that is also deny-scoped (e.g.
        # Read on .env*/.git/*) keeps those deny paths (hard block) but is allowed
        # everywhere else.
        for tool in allow_list:
            existing = tools.get(tool)
            if existing is not None and existing.mode == "deny":
                tools[tool] = ToolPermission(
                    tool=tool, mode="allow", deny_patterns=list(existing.patterns)
                )
            else:
                tools.setdefault(tool, ToolPermission(tool=tool, mode="allow"))

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

        Rules are evaluated in priority order:
        1. deny — hard block, path-scoped by the tool's patterns (a deny entry
           with no patterns blocks the tool everywhere).
        2. alwaysAsk — always requires approval.
        3. ask — requires approval on matching paths (or always when the entry
           carries no patterns).
        4. allow — allowed without approval.
        5. default — third-party MCP tools ask; strict scope denies; else allowed.

        Returns (allowed, mode) where mode is:
        - None: allowed without approval
        - "requires_approval": allowed but needs user approval
        - caller treats (False, None) as denied
        """
        perm = self.tools.get(tool)

        # 1. Deny first. Path-scoped deny blocks only matching resources.
        if perm and perm.mode == "deny":
            if not perm.patterns or self._matches_patterns(resource, perm.patterns):
                return False, None
        elif perm and perm.deny_patterns and self._matches_patterns(resource, perm.deny_patterns):
            return False, None

        # 2. Always-ask tools require approval
        if tool in self.always_ask:
            return True, "requires_approval"

        # 3. Ask — prompt on matching paths (or always when unpatterned)
        if perm and perm.mode == "ask":
            if not perm.patterns or self._matches_patterns(resource, perm.patterns):
                return True, "requires_approval"
            return True, None

        # 4. Allow
        if perm and perm.mode == "allow":
            return True, None

        # 5. Default for tools with no explicit rule
        if not perm:
            # Third-party MCP tools default to ask (approval) unless the operator
            # explicitly allowlists them (or the scope is permissive).
            if tool.startswith("mcp__") and self.default_mode != "permissive":
                return True, "requires_approval"
            if self.default_mode == "strict":
                return False, None

        return True, None

    @staticmethod
    def _matches_patterns(resource: str, patterns: list[str]) -> bool:
        """Check if resource matches any pattern.

        Accepts both "Tool(glob)" entries (e.g. "Read(.env*)") and the bare globs
        used in settings.json's ``patterns`` block (e.g. ".env*", ".git/*").

        Uses fnmatch semantics so ``*`` never crosses a path separator, preventing
        patterns like ``.env*`` from matching ``/deep/nested/.env``.
        """
        import fnmatch
        from pathlib import PurePosixPath

        for pattern in patterns:
            glob_part = pattern
            if "(" in pattern and ")" in pattern:
                # "Read(.env*)" → ".env*"
                glob_part = pattern.split("(", 1)[1].rstrip(")")

            # Normalise separators so Windows paths work with posix-style globs.
            norm_resource = resource.replace("\\", "/")
            norm_glob = glob_part.replace("\\", "/")

            if "/" in norm_glob:
                # Path-qualified glob (e.g. ".git/*", "src/**/*.py") — use
                # PurePosixPath.match() which handles "**" and keeps "*" within a
                # single segment.
                try:
                    if PurePosixPath(norm_resource).match(norm_glob):
                        return True
                except Exception:
                    pass
            else:
                # Bare filename glob (e.g. ".env*", "*.key") — match against the
                # last path component only so it cannot cross directory boundaries.
                basename = norm_resource.rsplit("/", 1)[-1] if "/" in norm_resource else norm_resource
                if fnmatch.fnmatch(basename, norm_glob):
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
