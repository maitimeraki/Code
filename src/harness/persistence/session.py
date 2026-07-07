"""Session management for persistence and resumability."""

import uuid
from datetime import datetime
from typing import Optional, Dict, List, Any
import structlog

from harness.core.models import TaskState
from .models import Session, Task, TaskJournal, Base

logger = structlog.get_logger(__name__)


class SessionManager:
    """Manage session creation, persistence, and resumption."""

    def __init__(self):
        self.sessions: Dict[str, Session] = {}
        self.tasks: Dict[str, Task] = {}
        self.journal: Dict[str, List[TaskJournal]] = {}

    def create_session(self, user_id: str, metadata: Dict[str, Any] = None) -> str:
        """Create new session."""
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            user_id=user_id,
            status="active",
            metadata_json=metadata or {},
        )
        self.sessions[session_id] = session
        logger.info("Session created", session_id=session_id, user_id=user_id)
        return session_id

    def create_task(
        self,
        session_id: str,
        description: str,
        max_iterations: int = 10,
    ) -> str:
        """Create task within session."""
        if session_id not in self.sessions:
            raise ValueError(f"Session not found: {session_id}")

        task_id = str(uuid.uuid4())
        task = Task(
            task_id=task_id,
            session_id=session_id,
            description=description,
            status="pending",
            max_iterations=max_iterations,
        )
        self.tasks[task_id] = task
        self.journal[task_id] = []

        logger.info("Task created", task_id=task_id, session_id=session_id)
        return task_id

    def save_task_state(self, task_id: str, state: TaskState) -> None:
        """Save task state to persistence."""
        if task_id not in self.tasks:
            raise ValueError(f"Task not found: {task_id}")

        task = self.tasks[task_id]
        task.status = state.status.value
        task.iterations = state.iteration
        task.tokens_used = state.tokens_used
        task.result = state.result
        task.error = state.error
        task.updated_at = datetime.now()

        if state.status.value == "running" and task.started_at is None:
            task.started_at = datetime.now()

        if state.status.value in ["completed", "failed"]:
            task.completed_at = datetime.now()

        logger.info("Task state saved", task_id=task_id, status=state.status.value)

    def record_journal_entry(
        self,
        task_id: str,
        event_type: str,
        event_data: Dict[str, Any],
    ) -> None:
        """Record event in task journal (write-ahead log)."""
        if task_id not in self.journal:
            self.journal[task_id] = []

        entry = TaskJournal(
            journal_id=str(uuid.uuid4()),
            task_id=task_id,
            sequence=len(self.journal[task_id]) + 1,
            event_type=event_type,
            event_data=event_data,
        )
        self.journal[task_id].append(entry)
        logger.debug("Journal entry recorded", task_id=task_id, event_type=event_type)

    def get_session(self, session_id: str) -> Optional[Session]:
        """Retrieve session."""
        return self.sessions.get(session_id)

    def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve task."""
        return self.tasks.get(task_id)

    def get_task_journal(self, task_id: str) -> List[TaskJournal]:
        """Get all journal entries for task."""
        return self.journal.get(task_id, [])

    def list_tasks(self, session_id: str) -> List[Task]:
        """List all tasks in session."""
        return [t for t in self.tasks.values() if t.session_id == session_id]

    def pause_session(self, session_id: str) -> None:
        """Pause session (saves checkpoint)."""
        if session_id not in self.sessions:
            raise ValueError(f"Session not found: {session_id}")

        session = self.sessions[session_id]
        session.status = "paused"
        session.updated_at = datetime.now()
        logger.info("Session paused", session_id=session_id)

    def resume_session(self, session_id: str) -> None:
        """Resume paused session."""
        if session_id not in self.sessions:
            raise ValueError(f"Session not found: {session_id}")

        session = self.sessions[session_id]
        session.status = "active"
        session.updated_at = datetime.now()
        logger.info("Session resumed", session_id=session_id)

    def complete_session(self, session_id: str) -> None:
        """Mark session as completed."""
        if session_id not in self.sessions:
            raise ValueError(f"Session not found: {session_id}")

        session = self.sessions[session_id]
        session.status = "completed"
        session.completed_at = datetime.now()
        logger.info("Session completed", session_id=session_id)

    def get_stats(self) -> Dict[str, Any]:
        """Get persistence layer statistics."""
        total_sessions = len(self.sessions)
        total_tasks = len(self.tasks)
        completed_tasks = sum(1 for t in self.tasks.values() if t.status == "completed")
        failed_tasks = sum(1 for t in self.tasks.values() if t.status == "failed")
        total_journal_entries = sum(len(entries) for entries in self.journal.values())

        return {
            "total_sessions": total_sessions,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
            "total_journal_entries": total_journal_entries,
        }
