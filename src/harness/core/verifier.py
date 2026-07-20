"""Task completion verifiers.

Completion is a gate, not an event. When the agent believes it is done (via the
`attempt_completion` tool or a natural stop), the spawner runs the task's resolved
verifier before accepting completion:

  - CommandVerifier  — run a shell command; exit 0 = done, else feed stderr back.
  - SelfReportVerifier — no mechanical check exists; accept the agent's word (logged).
  - CriticVerifier   — stub for (LLM-as-judge); currently accepts + notes.

`resolve_verifier` picks the strongest signal available for the task: a verify
command yields a CommandVerifier, otherwise we degrade to self-report.
"""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

import structlog

logger = structlog.get_logger(__name__)

VERIFY_TIMEOUT_SECONDS = 300


@dataclass
class VerifyResult:
    """Outcome of a verification attempt."""
    passed: bool
    reason: str


@runtime_checkable
class Verifier(Protocol):
    """Decides whether a task's claimed completion is real."""

    async def verify(
        self, objective: str, summary: str, project_root: Optional[Path] = None
    ) -> VerifyResult:
        ...


class CommandVerifier:
    """Run a shell command; exit code 0 means the task is verified done."""

    def __init__(self, command: str, timeout: int = VERIFY_TIMEOUT_SECONDS):
        self.command = command
        self.timeout = timeout

    async def verify(
        self, objective: str, summary: str, project_root: Optional[Path] = None
    ) -> VerifyResult:
        cwd = str(project_root) if project_root else None
        try:
            proc = await asyncio.create_subprocess_shell(
                self.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                return VerifyResult(
                    passed=False,
                    reason=f"Verification command timed out after {self.timeout}s: {self.command}",
                )
        except Exception as e:
            return VerifyResult(
                passed=False,
                reason=f"Verification command could not run: {e}",
            )

        if proc.returncode == 0:
            return VerifyResult(passed=True, reason=f"Verification passed: {self.command}")

        err = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
        return VerifyResult(
            passed=False,
            reason=(
                f"Verification failed (exit {proc.returncode}) for `{self.command}`:\n{err}"
            ),
        )


class SelfReportVerifier:
    """No mechanical check exists — accept the agent's explicit completion."""

    async def verify(
        self, objective: str, summary: str, project_root: Optional[Path] = None
    ) -> VerifyResult:
        return VerifyResult(
            passed=True,
            reason="Accepted on agent self-report (no verification command configured).",
        )


class CriticVerifier:
    """An LLM judge reads goal + summary and returns a pass/fail verdict.

    Used when a task has no mechanical check (docs, refactors) but self-report
    is too weak. Fail-open: if the judge errors or returns garbage, accept the
    completion rather than becoming a new hard blocker — that would recreate the
    problem Phase A removed.
    """

    def __init__(self, llm_client: Any, model: str = ""):
        self.llm_client = llm_client
        self.model = model

    async def verify(
        self, objective: str, summary: str, project_root: Optional[Path] = None
    ) -> VerifyResult:
        prompt = (
            "You are a strict completion judge. Decide whether the work described "
            "in the SUMMARY genuinely satisfies the OBJECTIVE.\n\n"
            f"OBJECTIVE:\n{objective}\n\n"
            f"SUMMARY OF WORK DONE:\n{summary}\n\n"
            'Reply with ONLY a JSON object: {"passed": true|false, "reason": "<one sentence>"}. '
            "Pass only if the objective is actually met; fail if it is partial, vague, or unverified."
        )
        try:
            text = ""
            async for event in self.llm_client.stream(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
                model=self.model or None,
            ):
                content = getattr(event, "content", None)
                if content:
                    text += content

            verdict = json.loads(_extract_json(text))
            passed = bool(verdict.get("passed"))
            reason = str(verdict.get("reason") or "critic judged the task")
            return VerifyResult(passed=passed, reason=f"Critic: {reason}")
        except Exception as e:
            logger.warning("Critic verifier failed; accepting (fail-open)", error=str(e))
            return VerifyResult(
                passed=True,
                reason=f"Accepted (critic judge unavailable, fell back to self-report): {e}",
            )


def _extract_json(text: str) -> str:
    """Pull the first {...} block out of an LLM reply (tolerates prose/code fences)."""
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def resolve_verifier(
    verify_command: Optional[str], llm_client: Any = None, model: str = ""
) -> Verifier:
    """Pick the strongest completion signal available for the task.

    command → CommandVerifier (exit 0); else an llm_client → CriticVerifier
    (LLM judge, fail-open); else SelfReportVerifier.
    """
    if verify_command:
        return CommandVerifier(verify_command)
    if llm_client is not None:
        return CriticVerifier(llm_client, model=model)
    return SelfReportVerifier()
