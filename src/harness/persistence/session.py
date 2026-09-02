"""Session management with async SQLite persistence."""

import json
import uuid
from datetime import datetime
from typing import Optional, Dict, List, Any
import structlog
from sqlalchemy import select, and_

from harness.core.models import TaskState, TaskStatus
from harness.persistence.database import get_session
from harness.persistence.models import Session, Task, TaskJournal, PendingQuestion
from harness.persistence.project_detector import ProjectDetector

logger = structlog.get_logger(__name__)


class SessionManager:
    """Manage session creation, persistence, and resumption via SQLite."""

    def __init__(self, project_id: Optional[str] = None):
        """Initialize with optional project_id; auto-detect if None."""
        self.project_id = project_id or ProjectDetector.detect_project_id()

    async def create_session(self, user_id: str, metadata: Dict[str, Any] = None) -> str:
        """Create new session in database with project_id auto-set."""
        session_id = str(uuid.uuid4())

        async with get_session() as db_session:
            session = Session(
                session_id=session_id,
                project_id=self.project_id,
                user_id=user_id,
                status="active",
                metadata_json=metadata or {},
            )
            db_session.add(session)
            await db_session.commit()

        logger.info("Session created", session_id=session_id, user_id=user_id, project_id=self.project_id)
        return session_id

    async def create_task(
        self,
        session_id: str,
        description: str,
        max_iterations: int = 10,
    ) -> str:
        """Create task within session (project auto-scoped)."""
        async with get_session() as db_session:
            result = await db_session.execute(
                select(Session).where(
                    and_(
                        Session.project_id == self.project_id,
                        Session.session_id == session_id,
                    )
                )
            )
            existing_session = result.scalars().first()
            if not existing_session:
                raise ValueError(f"Session not found in project {self.project_id}: {session_id}")

            task_id = str(uuid.uuid4())
            task = Task(
                task_id=task_id,
                project_id=self.project_id,
                session_id=session_id,
                description=description,
                status="pending",
                max_iterations=max_iterations,
            )
            db_session.add(task)
            await db_session.commit()

        logger.info("Task created", task_id=task_id, session_id=session_id, project_id=self.project_id)
        return task_id

    async def save_task_state(self, task_id: str, state: TaskState) -> None:
        """Save task state to database."""
        async with get_session() as db_session:
            task = await db_session.get(Task, task_id)
            if not task:
                raise ValueError(f"Task not found: {task_id}")

            if task.project_id != self.project_id:
                raise ValueError(f"Task {task_id} does not belong to project {self.project_id}")

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
                project_id=self.project_id,
                task_id=task_id,
                iteration=iteration,
                message=message,
            )
            db_session.add(entry)
            await db_session.commit()

        logger.debug("Journal entry recorded", task_id=task_id, iteration=iteration)

    async def get_session(self, session_id: str) -> Optional[Session]:
        """Retrieve session from database (project-scoped)."""
        async with get_session() as db_session:
            result = await db_session.execute(
                select(Session).where(
                    and_(
                        Session.project_id == self.project_id,
                        Session.session_id == session_id,
                    )
                )
            )
            return result.scalars().first()

    async def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve task from database (project-scoped)."""
        async with get_session() as db_session:
            result = await db_session.execute(
                select(Task).where(
                    and_(
                        Task.project_id == self.project_id,
                        Task.task_id == task_id,
                    )
                )
            )
            return result.scalars().first()

    async def get_task_journal(self, task_id: str) -> List[TaskJournal]:
        """Get all journal entries for task (project-scoped)."""
        async with get_session() as db_session:
            result = await db_session.execute(
                select(TaskJournal)
                .where(
                    and_(
                        TaskJournal.project_id == self.project_id,
                        TaskJournal.task_id == task_id,
                    )
                )
                .order_by(TaskJournal.created_at)
            )
            return result.scalars().all()

    async def list_tasks(self, session_id: str) -> List[Task]:
        """List all tasks in session (project-scoped)."""
        async with get_session() as db_session:
            result = await db_session.execute(
                select(Task).where(
                    and_(
                        Task.project_id == self.project_id,
                        Task.session_id == session_id,
                    )
                )
            )
            return result.scalars().all()

    async def get_active_sessions(self) -> List[Session]:
        """List active sessions for THIS project only."""
        async with get_session() as db_session:
            result = await db_session.execute(
                select(Session).where(
                    and_(
                        Session.project_id == self.project_id,
                        Session.status == "active",
                    )
                )
            )
            return result.scalars().all()

    async def get_active_tasks(self) -> List[Task]:
        """List running tasks for THIS project only."""
        async with get_session() as db_session:
            result = await db_session.execute(
                select(Task).where(
                    and_(
                        Task.project_id == self.project_id,
                        Task.status == "running",
                    )
                )
            )
            return result.scalars().all()

    async def pause_session(self, session_id: str) -> None:
        """Pause session."""
        async with get_session() as db_session:
            session = await db_session.get(Session, session_id)
            if not session:
                raise ValueError(f"Session not found: {session_id}")

            if session.project_id != self.project_id:
                raise ValueError(f"Session {session_id} does not belong to project {self.project_id}")

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

            if session.project_id != self.project_id:
                raise ValueError(f"Session {session_id} does not belong to project {self.project_id}")

            session.status = "active"
            session.updated_at = datetime.now()
            await db_session.commit()

        logger.info("Session resumed", session_id=session_id)


# ── Pending question persistence ──────────────────────────────────────


async def save_pending_question(session_id: str, question: dict) -> str:
    """Save a pending question to the database."""
    question_id = str(uuid.uuid4())
    project_id = ProjectDetector.detect_project_id()
    async with get_session() as db_session:
        row = PendingQuestion(
            id=question_id,
            project_id=project_id,
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
    """Load the most recent unanswered question for a session."""
    project_id = ProjectDetector.detect_project_id()
    async with get_session() as db_session:
        result = await db_session.execute(
            select(PendingQuestion)
            .where(
                and_(
                    PendingQuestion.project_id == project_id,
                    PendingQuestion.session_id == session_id,
                    PendingQuestion.answer_json.is_(None),
                )
            )
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
