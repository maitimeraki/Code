"""Session management with async SQLite persistence."""

import json
import uuid
from datetime import datetime
from typing import Optional, Dict, List, Any
import structlog
from sqlalchemy import select

from harness.core.models import TaskState, TaskStatus
from harness.persistence.database import get_session
from harness.persistence.models import Session, Task, TaskJournal, PendingQuestion

logger = structlog.get_logger(__name__)


class SessionManager:
    """Manage session creation, persistence, and resumption via SQLite."""

    async def create_session(self, user_id: str, metadata: Dict[str, Any] = None) -> str:
        """Create new session in database."""
        session_id = str(uuid.uuid4())

        async with get_session() as db_session:
            session = Session(
                session_id=session_id,
                user_id=user_id,
                status="active",
                metadata_json=metadata or {},
            )
            db_session.add(session)
            await db_session.commit()

        logger.info("Session created", session_id=session_id, user_id=user_id)
        return session_id

    async def create_task(
        self,
        session_id: str,
        description: str,
        max_iterations: int = 10,
    ) -> str:
        """Create task within session."""
        async with get_session() as db_session:
            # Verify session exists
            result = await db_session.execute(
                select(Session).where(Session.session_id == session_id)
            )
            existing_session = result.scalars().first()
            if not existing_session:
                raise ValueError(f"Session not found: {session_id}")

            task_id = str(uuid.uuid4())
            task = Task(
                task_id=task_id,
                session_id=session_id,
                description=description,
                status="pending",
                max_iterations=max_iterations,
            )
            db_session.add(task)
            await db_session.commit()

        logger.info("Task created", task_id=task_id, session_id=session_id)
        return task_id

    async def save_task_state(self, task_id: str, state: TaskState) -> None:
        """Save task state to database."""
        async with get_session() as db_session:
            task = await db_session.get(Task, task_id)
            if not task:
                raise ValueError(f"Task not found: {task_id}")

            task.status = state.status.value
            task.iterations = state.iteration
            task.tokens_used = state.tokens_used
            task.result = state.result
            task.error = state.error
            task.updated_at = datetime.now()

            if state.status == TaskStatus.RUNNING and task.started_at is None:
                task.started_at = datetime.now()

            if state.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                task.completed_at = datetime.now()

            await db_session.commit()

        logger.info("Task state saved", task_id=task_id, status=state.status.value)

    async def record_journal_entry(
        self,
        task_id: str,
        iteration: int,
        message: str,
    ) -> None:
        """Record event in task journal (write-ahead log)."""
        async with get_session() as db_session:
            entry = TaskJournal(
                journal_id=str(uuid.uuid4()),
                task_id=task_id,
                iteration=iteration,
                message=message,
            )
            db_session.add(entry)
            await db_session.commit()

        logger.debug("Journal entry recorded", task_id=task_id, iteration=iteration)

    async def get_session(self, session_id: str) -> Optional[Session]:
        """Retrieve session from database."""
        async with get_session() as db_session:
            return await db_session.get(Session, session_id)

    async def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve task from database."""
        async with get_session() as db_session:
            return await db_session.get(Task, task_id)

    async def get_task_journal(self, task_id: str) -> List[TaskJournal]:
        """Get all journal entries for task."""
        async with get_session() as db_session:
            result = await db_session.execute(
                select(TaskJournal)
                .where(TaskJournal.task_id == task_id)
                .order_by(TaskJournal.created_at)
            )
            return result.scalars().all()

    async def list_tasks(self, session_id: str) -> List[Task]:
        """List all tasks in session."""
        async with get_session() as db_session:
            result = await db_session.execute(
                select(Task).where(Task.session_id == session_id)
            )
            return result.scalars().all()

    async def pause_session(self, session_id: str) -> None:
        """Pause session."""
        async with get_session() as db_session:
            session = await db_session.get(Session, session_id)
            if not session:
                raise ValueError(f"Session not found: {session_id}")

            session.status = "paused"
            session.updated_at = datetime.now()
            await db_session.commit()

        logger.info("Session paused", session_id=session_id)

    async def resume_session(self, session_id: str) -> None:
        """Resume paused session."""
        async with get_session() as db_session:
            session = await db_session.get(Session, session_id)
            if not session:
                raise ValueError(f"Session not found: {session_id}")

            session.status = "active"
            session.updated_at = datetime.now()
            await db_session.commit()

        logger.info("Session resumed", session_id=session_id)


# ── Pending question persistence ──────────────────────────────────────


async def save_pending_question(session_id: str, question: dict) -> str:
    """Save a pending question to the database.

    The question dict mirrors the terminal's _pending_question state:
        {question, header, options, multi_select, timeout_seconds, ...}
    """
    import uuid
    question_id = str(uuid.uuid4())
    async with get_session() as db_session:
        row = PendingQuestion(
            id=question_id,
            session_id=session_id,
            question_text=question.get("question", ""),
            header=question.get("header", ""),
            options_json=json.dumps(question.get("options", [])),
            multi_select=question.get("multi_select", False),
            timeout_seconds=question.get("timeout_seconds", 0),
        )
        db_session.add(row)
        await db_session.commit()
    logger.info("Pending question saved", question_id=question_id)
    return question_id


async def load_pending_question(session_id: str) -> Optional[dict]:
    """Load the most recent unanswered (answer_json IS NULL) question for a session."""
    async with get_session() as db_session:
        result = await db_session.execute(
            select(PendingQuestion)
            .where(PendingQuestion.session_id == session_id)
            .where(PendingQuestion.answer_json.is_(None))
            .order_by(PendingQuestion.created_at.desc())
            .limit(1)
        )
        row = result.scalars().first()
        if row is None:
            return None
        return {
            "id": row.id,
            "question": row.question_text,
            "header": row.header,
            "options": json.loads(row.options_json),
            "multi_select": row.multi_select,
            "timeout_seconds": row.timeout_seconds,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


async def clear_pending_question(question_id: str, answers: dict) -> None:
    """Mark a pending question as answered."""
    async with get_session() as db_session:
        row = await db_session.get(PendingQuestion, question_id)
        if row is not None:
            row.answer_json = json.dumps(answers)
            row.answered_at = datetime.utcnow()
            await db_session.commit()
            logger.info("Pending question cleared", question_id=question_id)
