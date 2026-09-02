"""Production-grade approval system for permission-gated tool execution.

Handles user dialogs for tools marked with "ask" mode. Tracks session-level
approvals so repeated calls don't re-prompt within the same session.

Three approval levels:
- "once": Execute this call only, no caching (user chooses "this time")
- "session": Cache for remainder of session (user chooses "yes for session")
- "denied": Deny and raise PermissionError (user chooses "no")
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Literal, Optional
import structlog

logger = structlog.get_logger(__name__)


class ApprovalChoice(str, Enum):
    """User's approval decision."""
    ONCE = "once"
    SESSION = "session"
    DENIED = "denied"


@dataclass
class ApprovalRequest:
    """Request for user approval."""
    tool: str
    resource: str = ""
    description: str = ""
    timeout_seconds: int = 0


@dataclass
class ApprovalDecision:
    """User's decision on an approval request."""
    choice: ApprovalChoice
    tool: str
    resource: str


class ApprovalUI:
    """Abstract base for approval UI (terminal, dialog, web, etc)."""

    async def prompt(self, request: ApprovalRequest) -> ApprovalChoice:
        """Display approval dialog and return user's choice.

        Raises:
            asyncio.TimeoutError: If user doesn't respond within timeout_seconds.
        """
        raise NotImplementedError


class TerminalApprovalUI(ApprovalUI):
    """Terminal-based approval prompt."""

    async def prompt(self, request: ApprovalRequest) -> ApprovalChoice:
        """Display terminal approval dialog."""
        loop = asyncio.get_event_loop()

        def _prompt_sync() -> ApprovalChoice:
            """Synchronous terminal prompt (runs in thread)."""
            print(f"\n┌─ PERMISSION REQUIRED ─────────────────────┐")
            print(f"│ Tool: {request.tool}")
            if request.resource:
                print(f"│ Resource: {request.resource}")
            if request.description:
                print(f"│ Action: {request.description}")
            print(f"└────────────────────────────────────────────┘")
            print()
            print("  [1] This time only")
            print("  [2] Yes for this session")
            print("  [3] No (deny)")
            print()

            while True:
                try:
                    choice = input("Your choice (1-3): ").strip()
                    if choice == "1":
                        return ApprovalChoice.ONCE
                    elif choice == "2":
                        return ApprovalChoice.SESSION
                    elif choice == "3":
                        return ApprovalChoice.DENIED
                    else:
                        print("Invalid choice. Enter 1, 2, or 3.")
                except KeyboardInterrupt:
                    print("\nApproval cancelled (Ctrl+C).")
                    return ApprovalChoice.DENIED
                except EOFError:
                    print("\nApproval denied (EOF).")
                    return ApprovalChoice.DENIED

        try:
            choice = await asyncio.wait_for(
                loop.run_in_executor(None, _prompt_sync),
                timeout=request.timeout_seconds if request.timeout_seconds > 0 else None
            )
            return choice
        except asyncio.TimeoutError:
            logger.warning(f"Approval timeout for {request.tool}", resource=request.resource)
            raise


class ApprovalHandler:
    """Manages approval requests and session-level caching."""

    def __init__(self, ui: Optional[ApprovalUI] = None):
        self.ui = ui or TerminalApprovalUI()
        self.session_approvals: set[str] = set()
        self.approval_timeout_seconds: int = 0

    def _cache_key(self, tool: str, resource: str = "") -> str:
        """Generate cache key for approval tracking."""
        return f"{tool}::{resource}" if resource else tool

    async def request_approval(
        self,
        tool: str,
        resource: str = "",
        description: str = "",
        timeout_seconds: Optional[int] = None,
    ) -> bool:
        """Request approval for a tool operation.

        Returns True if approved, raises PermissionError if denied.
        """
        cache_key = self._cache_key(tool, resource)

        if cache_key in self.session_approvals:
            logger.debug(f"Approval cached for {tool}", resource=resource)
            return True

        req = ApprovalRequest(
            tool=tool,
            resource=resource,
            description=description,
            timeout_seconds=timeout_seconds or self.approval_timeout_seconds,
        )

        logger.info(f"Requesting approval for {tool}", resource=resource)
        choice = await self.ui.prompt(req)

        if choice == ApprovalChoice.DENIED:
            logger.warning(f"Approval denied for {tool}", resource=resource)
            raise PermissionError(f"Access to {tool} denied by user")

        if choice == ApprovalChoice.SESSION:
            self.session_approvals.add(cache_key)
            logger.info(f"Approval granted for session: {tool}", resource=resource)
            return True

        logger.info(f"Approval granted once: {tool}", resource=resource)
        return True

    def clear_session_approvals(self) -> None:
        """Clear session approval cache."""
        self.session_approvals.clear()
        logger.debug("Cleared session approvals")
