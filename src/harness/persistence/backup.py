"""Automatic backup management for production reliability."""

import shutil
import structlog
from pathlib import Path
from datetime import datetime, timedelta

logger = structlog.get_logger(__name__)


class DatabaseBackup:
    """Manage automatic backups of ~/.code/harness.db."""

    def __init__(self):
        self.db_path = Path.home() / ".code" / "harness.db"
        self.backup_dir = Path.home() / ".code" / "backups"

    async def create_backup(self) -> Path:
        """Create timestamped backup."""
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.backup_dir / f"harness_{timestamp}.db"

            if self.db_path.exists():
                shutil.copy2(self.db_path, backup_path)
                logger.info("Backup created", path=str(backup_path), size=backup_path.stat().st_size)
            else:
                logger.warning("Database file not found, skipping backup", path=str(self.db_path))

            return backup_path
        except Exception as e:
            logger.error("Backup creation failed", error=str(e))
            raise

    async def cleanup_old_backups(self, keep_days: int = 30) -> None:
        """Remove backups older than keep_days."""
        try:
            if not self.backup_dir.exists():
                return

            cutoff = datetime.now() - timedelta(days=keep_days)
            deleted_count = 0

            for backup_file in self.backup_dir.glob("harness_*.db"):
                mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)
                if mtime < cutoff:
                    backup_file.unlink()
                    deleted_count += 1
                    logger.info("Deleted old backup", path=str(backup_file))

            if deleted_count > 0:
                logger.info("Backup cleanup complete", deleted=deleted_count)
        except Exception as e:
            logger.error("Backup cleanup failed", error=str(e))
            raise

    async def restore_backup(self, backup_path: Path) -> None:
        """Restore database from backup."""
        try:
            if not backup_path.exists():
                raise FileNotFoundError(f"Backup not found: {backup_path}")

            if self.db_path.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_pre_restore")
                pre_restore = self.backup_dir / f"harness_{timestamp}.db"
                shutil.copy2(self.db_path, pre_restore)
                logger.info("Pre-restore backup created", path=str(pre_restore))

            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, self.db_path)
            logger.info("Database restored", from_backup=str(backup_path), to=str(self.db_path))
        except Exception as e:
            logger.error("Backup restore failed", error=str(e))
            raise

    async def list_backups(self) -> list:
        """List all available backups."""
        try:
            if not self.backup_dir.exists():
                return []

            backups = sorted(
                self.backup_dir.glob("harness_*.db"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )

            return [
                {
                    "path": str(p),
                    "size": p.stat().st_size,
                    "created": datetime.fromtimestamp(p.stat().st_mtime),
                }
                for p in backups
            ]
        except Exception as e:
            logger.error("Failed to list backups", error=str(e))
            return []
