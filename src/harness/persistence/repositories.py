"""Repository pattern for project-scoped data access."""

from typing import List, Optional, Dict, Any
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from harness.persistence.models import (
    Session,
    Task,
    AgentExecution,
    ToolCall,
    KnowledgeEntry,
    TaskJournal,
    ApprovalRequest,
    ExecutedAction,
    ErrorMemory,
    UserPreference,
    PendingQuestion,
    Analytics,
)


class BaseRepository:
    """Base class: all queries auto-filter by project_id."""

    def __init__(self, session: AsyncSession, project_id: str):
        self.session = session
        self.project_id = project_id


class SessionRepository(BaseRepository):
    """Project-scoped session queries."""

    async def create(self, session_id: str, user_id: str, metadata: Dict[str, Any]) -> Session:
        """Create session with project_id set."""
        session = Session(
            session_id=session_id,
            project_id=self.project_id,
            user_id=user_id,
            metadata_json=metadata,
        )
        self.session.add(session)
        await self.session.commit()
        return session

    async def get(self, session_id: str) -> Optional[Session]:
        """Query: WHERE project_id == self.project_id AND session_id == session_id."""
        result = await self.session.execute(
            select(Session).where(
                and_(
                    Session.project_id == self.project_id,
                    Session.session_id == session_id,
                )
            )
        )
        return result.scalars().first()

    async def list_active(self) -> List[Session]:
        """Query: WHERE project_id == self.project_id AND status == 'active'."""
        result = await self.session.execute(
            select(Session).where(
                and_(
                    Session.project_id == self.project_id,
                    Session.status == "active",
                )
            )
        )
        return result.scalars().all()


class TaskRepository(BaseRepository):
    """Project-scoped task queries."""

    async def create(self, task_id: str, session_id: str, description: str) -> Task:
        """Create task with project_id set."""
        task = Task(
            task_id=task_id,
            project_id=self.project_id,
            session_id=session_id,
            description=description,
        )
        self.session.add(task)
        await self.session.commit()
        return task

    async def get(self, task_id: str) -> Optional[Task]:
        """Get task."""
        result = await self.session.execute(
            select(Task).where(
                and_(
                    Task.project_id == self.project_id,
                    Task.task_id == task_id,
                )
            )
        )
        return result.scalars().first()

    async def get_by_session(self, session_id: str) -> List[Task]:
        """Query: WHERE project_id == self.project_id AND session_id == session_id."""
        result = await self.session.execute(
            select(Task).where(
                and_(
                    Task.project_id == self.project_id,
                    Task.session_id == session_id,
                )
            )
        )
        return result.scalars().all()

    async def get_by_status(self, status: str) -> List[Task]:
        """Query: WHERE project_id == self.project_id AND status == status."""
        result = await self.session.execute(
            select(Task).where(
                and_(
                    Task.project_id == self.project_id,
                    Task.status == status,
                )
            )
        )
        return result.scalars().all()


class AgentExecutionRepository(BaseRepository):
    """Project-scoped agent execution queries."""

    async def get_by_task(self, task_id: str) -> List[AgentExecution]:
        """Query: WHERE project_id == self.project_id AND task_id == task_id."""
        result = await self.session.execute(
            select(AgentExecution).where(
                and_(
                    AgentExecution.project_id == self.project_id,
                    AgentExecution.task_id == task_id,
                )
            )
        )
        return result.scalars().all()


class ToolCallRepository(BaseRepository):
    """Project-scoped tool call queries."""

    async def get_by_task(self, task_id: str) -> List[ToolCall]:
        """Query: WHERE project_id == self.project_id AND task_id == task_id."""
        result = await self.session.execute(
            select(ToolCall).where(
                and_(
                    ToolCall.project_id == self.project_id,
                    ToolCall.task_id == task_id,
                )
            )
        )
        return result.scalars().all()


class KnowledgeRepository(BaseRepository):
    """Project-scoped knowledge entry queries."""

    async def list_by_type(self, task_type: str) -> List[KnowledgeEntry]:
        """Query: WHERE project_id == self.project_id AND task_type == task_type."""
        result = await self.session.execute(
            select(KnowledgeEntry).where(
                and_(
                    KnowledgeEntry.project_id == self.project_id,
                    KnowledgeEntry.task_type == task_type,
                )
            )
        )
        return result.scalars().all()

    async def list_all(self) -> List[KnowledgeEntry]:
        """Query: WHERE project_id == self.project_id."""
        result = await self.session.execute(
            select(KnowledgeEntry).where(
                KnowledgeEntry.project_id == self.project_id
            )
        )
        return result.scalars().all()


class TaskJournalRepository(BaseRepository):
    """Project-scoped task journal queries."""

    async def get_by_task(self, task_id: str) -> List[TaskJournal]:
        """Query: WHERE project_id == self.project_id AND task_id == task_id."""
        result = await self.session.execute(
            select(TaskJournal).where(
                and_(
                    TaskJournal.project_id == self.project_id,
                    TaskJournal.task_id == task_id,
                )
            )
        )
        return result.scalars().all()


class RepositoryFactory:
    """Factory: returns project-scoped repositories."""

    @staticmethod
    async def create_repositories(session: AsyncSession, project_id: str) -> Dict[str, BaseRepository]:
        """Returns dict of all repositories for a project."""
        return {
            "sessions": SessionRepository(session, project_id),
            "tasks": TaskRepository(session, project_id),
            "agents": AgentExecutionRepository(session, project_id),
            "tools": ToolCallRepository(session, project_id),
            "knowledge": KnowledgeRepository(session, project_id),
            "journals": TaskJournalRepository(session, project_id),
        }
