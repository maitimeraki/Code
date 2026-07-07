"""Context injection for prompts - finds relevant prior solutions."""

from typing import List, Optional
import structlog
from rank_bm25 import BM25Okapi

from .models import ContextEntry, PromptContext, AgentRole

logger = structlog.get_logger(__name__)


class ContextInjector:
    """Inject relevant context into prompts using BM25 search."""

    def __init__(self):
        self.documents: List[ContextEntry] = []
        self.bm25_index: Optional[BM25Okapi] = None

    def add_document(self, entry: ContextEntry) -> None:
        """Add a document to the knowledge base."""
        self.documents.append(entry)
        self._rebuild_index()
        logger.info(f"Added document: {entry.title}")

    def add_documents(self, entries: List[ContextEntry]) -> None:
        """Add multiple documents."""
        self.documents.extend(entries)
        self._rebuild_index()
        logger.info(f"Added {len(entries)} documents")

    def _rebuild_index(self) -> None:
        """Rebuild BM25 index from current documents."""
        if not self.documents:
            self.bm25_index = None
            return

        # Tokenize documents
        corpus = [
            f"{doc.title} {doc.content} {doc.source}".lower().split()
            for doc in self.documents
        ]

        self.bm25_index = BM25Okapi(corpus)
        logger.debug(f"Rebuilt BM25 index with {len(self.documents)} documents")

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[ContextEntry]:
        """Search for relevant documents using BM25."""
        if not self.bm25_index or not self.documents:
            logger.warning("No documents in index, returning empty results")
            return []

        # Tokenize query
        query_tokens = query.lower().split()

        # Get BM25 scores
        scores = self.bm25_index.get_scores(query_tokens)

        # Rank documents
        ranked = sorted(
            zip(self.documents, scores),
            key=lambda x: x[1],
            reverse=True,
        )

        # Filter and limit results
        results = []
        top_score = 0.0
        for doc, score in ranked:
            if score >= min_score and len(results) < top_k:
                doc.relevance_score = score
                results.append(doc)
                if not top_score:
                    top_score = score

        logger.info(
            "Search completed",
            query=query[:50],
            results=len(results),
            top_score=top_score,
        )

        return results

    async def inject_context(
        self,
        task: str,
        role: AgentRole,
        top_k: int = 5,
    ) -> PromptContext:
        """Inject context for a given task and role."""
        context = PromptContext(task_description=task)

        if not self.documents:
            logger.info("No documents available for context injection")
            return context

        # Search for prior solutions
        query = f"{task} {role.value}"
        results = self.search(query, top_k=top_k)

        # Categorize results
        for entry in results:
            if "solution" in entry.source.lower() or "prior" in entry.source.lower():
                context.prior_solutions.append(entry)
            elif "code" in entry.source.lower() or "example" in entry.source.lower():
                context.code_examples.append(entry)
            elif "tool" in entry.source.lower():
                context.tool_examples.append(entry)
            else:
                context.prior_solutions.append(entry)

        logger.info(
            "Context injected",
            task=task[:50],
            role=role.value,
            solutions=len(context.prior_solutions),
            examples=len(context.code_examples),
        )

        return context

    def clear(self) -> None:
        """Clear all documents."""
        self.documents.clear()
        self.bm25_index = None
        logger.info("Context index cleared")

    def get_stats(self) -> dict:
        """Get statistics about the index."""
        return {
            "total_documents": len(self.documents),
            "indexed": self.bm25_index is not None,
        }
