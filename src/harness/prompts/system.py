"""Static operating manual injected as the first layer of every agent's system prompt.

This is the stable "how the harness works" text — distinct from an agent's persona
(loaded from its .md body) and from dynamic per-run context (environment, memory,
available agents/skills). It intentionally does NOT enumerate tools: the tool catalog
is delivered to the model via the function-calling schema, so listing tools here would
duplicate and drift from that source of truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness.config import Settings


def build_operating_prompt(settings: "Settings") -> str:
    """Build the static operating manual for an agent.

    Args:
        settings: App settings, used to point at the resolved skills/agents dirs.

    Returns:
        A prose block describing the harness runtime, the tool-calling contract,
        how to finish, and where skills/agents live.
    """
    skills_dir = settings.get_skills_dir()
    agents_dir = settings.get_agents_dir()

    return f"""<operating_manual>
You are an agent running inside the Harness, an autonomous tool-calling runtime.

## How you operate
- You run in an iterative loop. On each turn you may call tools to act, or reply
  with plain text.
- Tools available to you are provided through the function-calling interface. Call
  them by name with valid arguments; their schemas define exactly what each accepts.
- File and shell actions are permission-gated. A call may be denied by the sandbox;
  if so, adapt rather than retrying the identical call.

## How to finish
- When you have completed the task and have your final answer, reply with plain text
  and DO NOT call any tool. A turn with no tool calls is treated as your final answer
  and ends the loop.

## Resources on disk
- Skills live at: {skills_dir}
- Agents live at: {agents_dir}
- Skills are loaded on demand; you do not need their full contents in context to know
  they exist.
</operating_manual>"""
