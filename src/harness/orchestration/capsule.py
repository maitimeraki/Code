"""Sub-agent capsule composition: minimal context slicing."""

from typing import Any, Optional
from harness.orchestration.agent import SubAgentCapsule
from harness.core.models import TaskState
from harness.core.error_memory import get_top_pitfalls
from harness.core.user_preferences import get_all_preferences


async def compose_capsule(
    task_state: TaskState,
    objective: str,
    success_criteria: dict[str, Any],
    inputs: dict[str, Any],
    tool_allowlist: list[str],
    write_scope: Optional[str] = None,
    token_budget: int = 4096,
    time_budget_seconds: int = 300,
    user_id: Optional[str] = None,
) -> SubAgentCapsule:
    """Compose a minimal context capsule for a sub-agent.

    This is the orchestrator's way of handing off work to a sub-agent:
    - Only essential inputs (not full history)
    - Limited tool access (not all tools)
    - Explicit budgets and success criteria
    - Pre-injected context: prefs, pitfalls, relevant knowledge

    Args:
        task_state: Current task (for user_id and context)
        objective: What the sub-agent should do
        success_criteria: How to know when it's done
        inputs: Input data for the sub-agent (e.g., {"file": "..."})
        tool_allowlist: Which tools the sub-agent can use
        write_scope: Where it can write ("temp", "project", None)
        token_budget: Max tokens for the sub-agent
        time_budget_seconds: Max time in seconds
        user_id: User ID for preference injection (defaults to task_state context)

    Returns:
        SubAgentCapsule ready to pass to sub-agent
    """
    # Determine user_id for preference/pitfall injection
    if user_id is None:
        user_id = task_state.task_id  # Fallback: use task_id as user context

    # Phase 5: Inject context (prefs + pitfalls + knowledge)
    user_prefs = None
    known_pitfalls = None
    relevant_knowledge = None

    try:
        # Get user preferences
        user_prefs = await get_all_preferences(user_id)
    except Exception:
        pass  # Preferences optional; don't fail if unavailable

    try:
        # Get top pitfalls (most frequent errors)
        top_errors = await get_top_pitfalls(limit=5)
        known_pitfalls = [
            {
                "error": error.signature,
                "frequency": error.occurrence_count,
                "context": error.context,
                "resolution": error.resolution,
            }
            for error in top_errors
        ]
    except Exception:
        pass  # Pitfalls optional; don't fail if unavailable

    # ponytail: Phase 5 knowledge injection would go here (BM25 search on objective)
    # For now, skip it as it requires KnowledgeGraph.search() and we're in Phase 4

    capsule = SubAgentCapsule(
        objective=objective,
        success_criteria=success_criteria,
        inputs=inputs,
        tool_allowlist=tool_allowlist,
        write_scope=write_scope,
        token_budget=token_budget,
        time_budget_seconds=time_budget_seconds,
        user_preferences=user_prefs,
        known_pitfalls=known_pitfalls,
        relevant_knowledge=relevant_knowledge,
    )

    return capsule


def extract_summary_and_artifacts(agent_result) -> tuple[str, list[str]]:
    """Extract summary and artifact refs from agent result.

    When a sub-agent completes, the orchestrator only brings back:
    - Summary (output message)
    - Artifact references (external resources)

    The full trajectory goes to TaskJournal for audit/learning.

    Args:
        agent_result: AgentResult from sub-agent

    Returns:
        (summary_text, artifact_refs_list)
    """
    summary = agent_result.output or ""
    artifacts = agent_result.artifact_refs or []
    return (summary, artifacts)
