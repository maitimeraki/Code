"""Knowledge graph for storing and retrieving learned patterns with SQLite persistence."""

from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import uuid4
import structlog
from sqlalchemy import select
from rank_bm25 import BM25Okapi

from harness.persistence.database import get_session
from harness.persistence.models import KnowledgeEntry

logger = structlog.get_logger(__name__)


class KnowledgeGraph:
    """Store and search learned solutions for reuse across tasks via SQLite."""

    def __init__(self):
        self.bm25_index: Optional[BM25Okapi] = None
        self._cache: Dict[str, KnowledgeEntry] = {}

    async def init(self) -> None:
        """Initialize: load all entries from DB and rebuild index."""
        async with get_session() as db_session:
            result = await db_session.execute(select(KnowledgeEntry))
            entries = result.scalars().all()
            for entry in entries:
                self._cache[entry.entry_id] = entry
        self._rebuild_index()
        logger.info(f"Knowledge graph initialized with {len(self._cache)} entries")

    async def add_solution(
        self,
        task_type: str,
        solution: str,
        code_example: Optional[str] = None,
        quality_score: float = 0.5,
    ) -> str:
        """Add a learned solution to the knowledge base and persist to DB."""
        entry_id = str(uuid4())

        async with get_session() as db_session:
            entry = KnowledgeEntry(
                entry_id=entry_id,
                task_type=task_type,
                solution=solution,
                code_example=code_example,
                quality_score=quality_score,
                use_count=0,
                created_at=datetime.now(),
            )
            db_session.add(entry)
            await db_session.commit()

        # Update cache
        self._cache[entry_id] = entry
        self._rebuild_index()

        logger.info(
            "Solution added",
            entry_id=entry_id,
            task_type=task_type,
            quality=quality_score,
        )
        return entry_id

    def _rebuild_index(self) -> None:
        """Rebuild BM25 index from cached entries."""
        if not self._cache:
            self.bm25_index = None
            return

        # Tokenize documents
        corpus = [
            f"{entry.task_type} {entry.solution}".lower().split()
            for entry in self._cache.values()
        ]
        entry_ids = list(self._cache.keys())

        self.bm25_index = BM25Okapi(corpus)
        self._entry_order = entry_ids  # Track order for scoring
        logger.debug(f"Rebuilt knowledge graph with {len(self._cache)} entries")

    async def search(
        self,
        query: str,
        task_type: Optional[str] = None,
        top_k: int = 5,
        min_quality: float = 0.0,
    ) -> List[KnowledgeEntry]:
        """Search knowledge base for similar solutions."""
        if not self.bm25_index or not self._cache:
            logger.warning("Knowledge graph empty, no results")
            return []

        # Tokenize query
        query_tokens = query.lower().split()

        # Get BM25 scores
        scores = self.bm25_index.get_scores(query_tokens)

        # Rank entries
        ranked = []
        for idx, (entry_id, entry) in enumerate(self._cache.items()):
            score = scores[self._entry_order.index(entry_id)]
            ranked.append((entry, score))

        ranked.sort(key=lambda x: x[1], reverse=True)

        # Filter and limit
        results = []
        for entry, score in ranked:
            if score < 0:
                continue
            if entry.quality_score < min_quality:
                continue
            if task_type and entry.task_type != task_type:
                continue
            if len(results) >= top_k:
                break
            results.append(entry)

        logger.info(
            "Knowledge search completed",
            query=query[:50],
            results=len(results),
            task_type=task_type,
        )

        return results

    async def mark_used(self, entry_id: str) -> None:
        """Mark entry as used (increment reuse counter) and persist."""
        async with get_session() as db_session:
            entry = await db_session.get(KnowledgeEntry, entry_id)
            if not entry:
                logger.warning(f"Entry not found: {entry_id}")
                return

            entry.use_count = (entry.use_count or 0) + 1
            entry.last_used_at = datetime.now()
            await db_session.commit()

        # Update cache
        if entry_id in self._cache:
            self._cache[entry_id].use_count = entry.use_count
            self._cache[entry_id].last_used_at = entry.last_used_at

        logger.debug(f"Marked entry as used: {entry_id}")

    async def get_entry(self, entry_id: str) -> Optional[KnowledgeEntry]:
        """Retrieve a specific entry by ID."""
        return self._cache.get(entry_id)

    async def list_by_type(self, task_type: str) -> List[KnowledgeEntry]:
        """List all entries for a task type."""
        return [
            entry
            for entry in self._cache.values()
            if entry.task_type == task_type
        ]
