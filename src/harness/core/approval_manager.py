"""Human-in-the-loop approval gate management.

Protocol:
1. park_for_approval(): Save request, set WAITING_APPROVAL, return immediately (never block)
2. apply_decision(): Check ledger for idempotency, execute once, record result
3. Resume flow: Check status on loop resume, continue if approved
"""

import json
from uuid import uuid4
from datetime import datetime
from typing import Any, Optional
import structlog
from sqlalchemy import select

from harness.core.models import TaskState, TaskStatus
from harness.persistence.database import get_session
from harness.persistence.models import ApprovalRequest, ExecutedAction

logger = structlog.get_logger(__name__)


async def park_for_approval(
    state: TaskState,
    tool_call: dict[str, Any],
    risk_level: str = "medium",
    summary: str = "",
) -> str:
    """Park task for approval: save request, set WAITING_APPROVAL, return immediately.

    Protocol 1: Never blocks. Just saves state and returns approval_id.

    Args:
        state: Current TaskState
        tool_call: Tool call details {tool_type, args, ...}
        risk_level: "low" | "medium" | "high" | "critical"
        summary: Human-readable summary of what will happen

    Returns:
        approval_id (so caller can track the approval)
    """
    approval_id = str(uuid4())
    idempotency_key = str(uuid4())  # Unique key for this action

    async with get_session() as db_session:
        # Create approval request
        request = ApprovalRequest(
            approval_id=approval_id,
            task_id=state.task_id,
            proposed_action=tool_call,
            status="pending",
            idempotency_key=idempotency_key,
            risk_level=risk_level,
            summary=summary or f"Execute tool: {tool_call.get('tool_type', 'unknown')}",
            created_at=datetime.now(),
        )
        db_session.add(request)

        # Update task state to WAITING_APPROVAL
        from harness.persistence.models import Task
        task_record = await db_session.get(Task, state.task_id)
        if task_record:
            task_record.status = TaskStatus.WAITING_APPROVAL.value
            task_record.updated_at = datetime.now()

        await db_session.commit()

    # Update in-memory state
    state.status = TaskStatus.WAITING_APPROVAL
    state.waiting_on = approval_id

    logger.info(
        "Task parked for approval",
        approval_id=approval_id,
        task_id=state.task_id,
        risk_level=risk_level,
        idempotency_key=idempotency_key,
    )

    return approval_id


async def apply_decision(
    approval_id: str,
    decision: str,  # "approved" or "rejected"
    decided_by: str = "system",
    notes: str = "",
) -> bool:
    """Apply approval decision and update status (does NOT execute the tool).

    Protocol 2: Atomically record decision. The loop will check status and execute.

    Args:
        approval_id: The approval request ID
        decision: "approved" or "rejected"
        decided_by: Who made the decision
        notes: Optional notes

    Returns:
        True if decision was recorded, False if approval not found
    """
    async with get_session() as db_session:
        request = await db_session.get(ApprovalRequest, approval_id)
        if not request:
            logger.warning("Approval request not found", approval_id=approval_id)
            return False

        if decision.lower() not in ["approved", "rejected"]:
            raise ValueError(f"Invalid decision: {decision}. Must be 'approved' or 'rejected'")

        request.status = decision.lower()
        request.decided_at = datetime.now()
        request.decided_by = decided_by
        request.decision_notes = notes
        await db_session.commit()

    logger.info(
        "Approval decision recorded",
        approval_id=approval_id,
        decision=decision,
        decided_by=decided_by,
    )

    return True


async def check_and_execute_once(
    approval_id: str,
    executor_fn,
) -> tuple[bool, Optional[Any], Optional[str]]:
    """Check approval status and execute tool exactly once (via idempotency ledger).

    This is called by the loop on resume. It:
    1. Checks if approval is approved
    2. Checks if already executed (idempotency ledger)
    3. If not executed, calls executor_fn and records result
    4. Returns (success, result, error)

    Args:
        approval_id: The approval request ID
        executor_fn: Async function to execute the tool. Receives idempotency_key.

    Returns:
        (success: bool, result: Any, error: Optional[str])
    """
    async with get_session() as db_session:
        request = await db_session.get(ApprovalRequest, approval_id)
        if not request:
            return (False, None, f"Approval not found: {approval_id}")

        if request.status != "approved":
            return (False, None, f"Approval not approved: {request.status}")

        idempotency_key = request.idempotency_key

        # Check if already executed
        executed = await db_session.get(ExecutedAction, idempotency_key)
        if executed:
            logger.info(
                "Action already executed (idempotency)",
                idempotency_key=idempotency_key,
                approval_id=approval_id,
            )
            return (True, executed.result_json, executed.error)

    # Execute the tool
    try:
        result = await executor_fn(idempotency_key)

        # Record execution in ledger
        async with get_session() as db_session:
            executed_action = ExecutedAction(
                idempotency_key=idempotency_key,
                task_id=request.task_id,
                result_json=result if isinstance(result, dict) else {"result": str(result)},
                executed_at=datetime.now(),
            )
            db_session.add(executed_action)
            await db_session.commit()

        logger.info(
            "Action executed and recorded",
            idempotency_key=idempotency_key,
            approval_id=approval_id,
        )
        return (True, result, None)

    except Exception as e:
        error_msg = str(e)

        # Record failure in ledger
        async with get_session() as db_session:
            executed_action = ExecutedAction(
                idempotency_key=idempotency_key,
                task_id=request.task_id,
                error=error_msg,
                executed_at=datetime.now(),
            )
            db_session.add(executed_action)
            await db_session.commit()

        logger.error(
            "Action execution failed",
            idempotency_key=idempotency_key,
            approval_id=approval_id,
            error=error_msg,
        )
        return (False, None, error_msg)


async def get_pending_approvals(task_id: str) -> list[ApprovalRequest]:
    """List all pending approval requests for a task."""
    async with get_session() as db_session:
        result = await db_session.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.task_id == task_id)
            .where(ApprovalRequest.status == "pending")
        )
        return result.scalars().all()
