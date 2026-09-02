"""Project detection and multi-project registry for scoped context."""

import hashlib
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any
import structlog
from sqlalchemy import select

logger = structlog.get_logger(__name__)


class ProjectDetector:
    """Stable, reliable project identification using git root + user email."""

    @staticmethod
    def detect_project_id() -> str:
        """Generate stable project ID from git root + user email hash.

        Fallback: sha256(cwd) if not in git repo.
        Returns: str (SHA256[:16])
        """
        try:
            # Get git root
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                raise Exception("Not in git repo")
            repo_root = result.stdout.strip()

            # Get user email
            result = subprocess.run(
                ["git", "config", "user.email"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                user_email = ""
            else:
                user_email = result.stdout.strip()

            # Hash: sha256(repo_root:user_email)[:16]
            key = f"{repo_root}:{user_email}"
            project_id = hashlib.sha256(key.encode()).hexdigest()[:16]
            logger.info("Project ID detected", project_id=project_id, repo=repo_root)
            return project_id

        except Exception as e:
            # Fallback: sha256(cwd)[:16]
            logger.warning("Git detection failed, using cwd fallback", error=str(e))
            cwd = str(Path.cwd())
            project_id = hashlib.sha256(cwd.encode()).hexdigest()[:16]
            logger.info("Project ID from cwd", project_id=project_id, cwd=cwd)
            return project_id

    @staticmethod
    def get_project_metadata() -> Dict[str, Any]:
        """Collect project metadata for registration."""
        try:
            # Get git root
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            repo_root = result.stdout.strip() if result.returncode == 0 else str(Path.cwd())

            # Get project name (basename of root)
            project_name = Path(repo_root).name

            # Get git remote
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            git_remote = result.stdout.strip() if result.returncode == 0 else None

            project_id = ProjectDetector.detect_project_id()

            return {
                "project_id": project_id,
                "project_root": repo_root,
                "project_name": project_name,
                "git_remote": git_remote,
                "created_at": datetime.now(),
            }
        except Exception as e:
            logger.error("Failed to collect project metadata", error=str(e))
            raise


class ProjectRegistry:
    """Singleton registry for multi-project context management."""

    _current_project_id: Optional[str] = None

    @classmethod
    async def register_project(
        cls,
        repo_root: Path,
        project_name: str,
        session
    ) -> str:
        """Register new project, return project_id."""
        from harness.persistence.models import Project

        metadata = ProjectDetector.get_project_metadata()
        project_id = metadata["project_id"]

        try:
            # Check if already registered
            result = await session.execute(
                select(Project).where(Project.project_id == project_id)
            )
            existing = result.scalars().first()

            if existing:
                logger.info("Project already registered", project_id=project_id)
                return project_id

            # Register new project
            project = Project(
                project_id=project_id,
                project_name=project_name,
                project_root=str(repo_root),
                git_remote=metadata.get("git_remote"),
                created_at=datetime.now(),
                last_accessed=datetime.now(),
                metadata_json={},
            )
            session.add(project)
            await session.commit()

            logger.info("Project registered", project_id=project_id, name=project_name)
            return project_id

        except Exception as e:
            logger.error("Project registration failed", error=str(e))
            raise

    @classmethod
    async def get_current_project(cls, session) -> Dict[str, Any]:
        """Get current project metadata."""
        from harness.persistence.models import Project

        if not cls._current_project_id:
            cls._current_project_id = ProjectDetector.detect_project_id()

        result = await session.execute(
            select(Project).where(Project.project_id == cls._current_project_id)
        )
        project = result.scalars().first()

        if not project:
            return {"project_id": cls._current_project_id}

        return {
            "project_id": project.project_id,
            "project_name": project.project_name,
            "project_root": project.project_root,
            "git_remote": project.git_remote,
            "created_at": project.created_at,
            "last_accessed": project.last_accessed,
        }

    @classmethod
    async def list_projects(cls, session) -> List[Dict[str, Any]]:
        """List all registered projects."""
        from harness.persistence.models import Project

        result = await session.execute(select(Project))
        projects = result.scalars().all()

        return [
            {
                "project_id": p.project_id,
                "project_name": p.project_name,
                "project_root": p.project_root,
                "git_remote": p.git_remote,
                "created_at": p.created_at,
                "last_accessed": p.last_accessed,
            }
            for p in projects
        ]

    @classmethod
    def set_current_project(cls, project_id: str) -> None:
        """Set current project for this session."""
        cls._current_project_id = project_id
        logger.info("Current project set", project_id=project_id)
