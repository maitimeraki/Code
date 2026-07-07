"""Knowledge graph for storing and retrieving learned patterns."""

from typing import List, Optional, Dict, Any
from datetime import datetime
import structlog
from rank_bm25 import BM25Okapi

from .models import KnowledgeEntry

logger = structlog.get_logger(__name__)


class KnowledgeGraph:
    """Store and search learned solutions for reuse across tasks."""

    def __init__(self):
        self.entries: Dict[str, KnowledgeEntry] = {}
        self.bm25_index: Optional[BM25Okapi] = None

    def add_solution(
        self,
        task_type: str,
        solution: str,
        code_example: Optional[str] = None,
        quality_score: float = 0.5,
        tags: Optional[List[str]] = None,
    ) -> str:
        """Add a learned solution to the knowledge base."""
        entry_id = f"{task_type}_{len(self.entries)}"
        entry = KnowledgeEntry(
            entry_id=entry_id,
            task_type=task_type,
            solution=solution,
            code_example=code_example,
            quality_score=quality_score,
            tags=tags or [],
            created_at=datetime.now(),
        )
        self.entries[entry_id] = entry
        self._rebuild_index()

        logger.info(
            "Solution added",
            entry_id=entry_id,
            task_type=task_type,
            quality=quality_score,
        )
        return entry_id

    def _rebuild_index(self) -> None:
        """Rebuild BM25 index from all entries."""
        if not self.entries:
            self.bm25_index = None
            return

        # Tokenize documents
        corpus = [
            f"{entry.task_type} {entry.solution} {' '.join(entry.tags)}".lower().split()
            for entry in self.entries.values()
        ]

        self.bm25_index = BM25Okapi(corpus)
        logger.debug(f"Rebuilt knowledge graph with {len(self.entries)} entries")

    def search(
        self,
        query: str,
        task_type: Optional[str] = None,
        top_k: int = 5,
        min_quality: float = 0.0,
    ) -> List[KnowledgeEntry]:
        """Search knowledge base for similar solutions."""
        if not self.bm25_index or not self.entries:
            logger.warning("Knowledge graph empty, no results")
            return []

        # Tokenize query
        query_tokens = query.lower().split()

        # Get BM25 scores
        scores = self.bm25_index.get_scores(query_tokens)

        # Rank entries
        ranked = sorted(
            zip(self.entries.values(), scores),
            key=lambda x: x[1],
            reverse=True,
        )

        # Filter and limit
        results = []
        for entry, score in ranked:
            # Apply filters
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

    def mark_used(self, entry_id: str) -> None:
        """Mark entry as used (increment reuse counter)."""
        if entry_id not in self.entries:
            logger.warning(f"Entry not found: {entry_id}")
            return

        entry = self.entries[entry_id]
        entry.use_count += 1
        entry.last_used_at = datetime.now()

        logger.debug(f"Marked as used: {entry_id}", use_count=entry.use_count)

    def get_by_task_type(self, task_type: str) -> List[KnowledgeEntry]:
        """Get all solutions for a task type."""
        return [e for e in self.entries.values() if e.task_type == task_type]

    def get_top_solutions(self, top_k: int = 10) -> List[KnowledgeEntry]:
        """Get highest quality solutions."""
        sorted_entries = sorted(
            self.entries.values(),
            key=lambda e: (e.quality_score, e.use_count),
            reverse=True,
        )
        return sorted_entries[:top_k]

    def get_frequently_used(self, top_k: int = 10) -> List[KnowledgeEntry]:
        """Get most frequently reused solutions."""
        sorted_entries = sorted(
            self.entries.values(),
            key=lambda e: e.use_count,
            reverse=True,
        )
        return sorted_entries[:top_k]

    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge graph statistics."""
        if not self.entries:
            return {
                "total_entries": 0,
                "avg_quality": 0.0,
                "avg_reuse_count": 0,
                "task_types": [],
            }

        qualities = [e.quality_score for e in self.entries.values()]
        reuse_counts = [e.use_count for e in self.entries.values()]
        task_types = list(set(e.task_type for e in self.entries.values()))

        return {
            "total_entries": len(self.entries),
            "avg_quality": sum(qualities) / len(qualities),
            "avg_reuse_count": sum(reuse_counts) / len(reuse_counts),
            "task_types": task_types,
            "total_reuses": sum(reuse_counts),
        }

    def clear(self) -> None:
        """Clear all entries."""
        self.entries.clear()
        self.bm25_index = None
        logger.info("Knowledge graph cleared")
