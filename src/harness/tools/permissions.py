"""Permission scope and sandbox enforcement for tool execution."""

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from harness.config import get_app_settings


@dataclass
class PermissionScope:
    """Defines what a tool-calling agent is allowed to do."""

    allowed_paths: list[Path] = field(default_factory=list)
    allow_write: bool = True
    allow_bash: bool = True
    bash_allowlist: list[str] = field(
        default_factory=lambda: ["git", "pytest", "npm", "ls", "cat", "python", "find", "grep"]
    )
    bash_denylist: list[str] = field(
        default_factory=lambda: ["rm -rf", "sudo", "`", "$(", "curl", "wget"]
    )

    @classmethod
    def default_for_project(cls, project_root: Path) -> "PermissionScope":
        """Build a PermissionScope from project-level settings.

        Reads get_app_settings().get("permissions", {}) for user-defined overrides.
        Defaults to project_root only if no config exists.
        """
        app_settings = get_app_settings()
        perm_config = app_settings.get("permissions", {})

        allowed_paths = [project_root.resolve()]
        if "allowedPaths" in perm_config:
            for extra_path in perm_config["allowedPaths"]:
                allowed_paths.append(Path(extra_path).resolve())

        return cls(
            allowed_paths=allowed_paths,
            allow_write=perm_config.get("allowWrite", True),
            allow_bash=perm_config.get("allowBash", True),
            bash_allowlist=perm_config.get("bashAllowlist", cls().bash_allowlist),
            bash_denylist=perm_config.get("bashDenylist", cls().bash_denylist),
        )


class PathGuard:
    """Guards filesystem access by validating paths are within allowed scope."""

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
    """Guards shell command execution by checking first token against allowlist/denylist."""

    @staticmethod
    def check(command: str, scope: PermissionScope) -> None:
        """Validate a bash command is allowed.

        Args:
            command: The full bash command to check.
            scope: The permission scope defining bash allowlist/denylist.

        Raises:
            PermissionError: If command violates allowlist or denylist rules.
        """
        if not scope.allow_bash:
            raise PermissionError("Bash execution is not allowed in this scope")

        try:
            tokens = shlex.split(command)
        except ValueError as e:
            raise PermissionError(f"Invalid bash command syntax: {str(e)}")

        if not tokens:
            raise PermissionError("Empty bash command")

        first_token = tokens[0]

        # Defense-in-depth: check denylist for forbidden patterns/keywords
        for deny_pattern in scope.bash_denylist:
            if deny_pattern in command:
                raise PermissionError(
                    f"Bash command contains forbidden pattern: '{deny_pattern}' in '{command}'"
                )

        # Primary control: check first token against allowlist
        if scope.bash_allowlist and first_token not in scope.bash_allowlist:
            raise PermissionError(
                f"Command '{first_token}' is not in bash allowlist. Allowed: "
                f"{', '.join(scope.bash_allowlist)}"
            )
