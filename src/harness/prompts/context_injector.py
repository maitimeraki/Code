"""Context injection for prompts - finds relevant prior solutions."""

from typing import List, Optional, Dict, Any
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


# Memory injection functions (used by spawner to augment agent prompts)

async def inject_memory_into_prompt(
    base_prompt: str,
    task_description: str,
    user_id: Optional[str] = None,
    include_prefs: bool = True,
    include_pitfalls: bool = True,
    include_knowledge: bool = True,
) -> str:
    """Augment agent system prompt with memory context.

    Injects:
    - User preferences (customization)
    - Known pitfalls (learn from errors)
    - Relevant knowledge (prior solutions)

    Args:
        base_prompt: Original system prompt
        task_description: Current task (for search)
        user_id: User ID for preference injection
        include_prefs: Include user preferences
        include_pitfalls: Include known pitfalls
        include_knowledge: Include relevant solutions

    Returns:
        Augmented system prompt
    """
    injections = []

    # Phase 5: Inject user preferences
    if include_prefs and user_id:
        try:
            from harness.core.user_preferences import get_all_preferences

            prefs = await get_all_preferences(user_id)
            if prefs:
                prefs_block = _format_preferences_block(prefs)
                injections.append(prefs_block)
        except Exception:
            pass  # Silently skip if unavailable

    # Phase 5: Inject known pitfalls
    if include_pitfalls:
        try:
            from harness.core.error_memory import get_top_pitfalls

            top_errors = await get_top_pitfalls(limit=5)
            if top_errors:
                pitfalls_block = _format_pitfalls_block(top_errors)
                injections.append(pitfalls_block)
        except Exception:
            pass  # Silently skip if unavailable

    # Phase 5: Inject relevant knowledge
    if include_knowledge:
        try:
            from harness.persistence.knowledge_graph import KnowledgeGraph

            kg = KnowledgeGraph()
            await kg.init()
            results = await kg.search(
                query=task_description,
                top_k=3,
                min_quality=0.5,
            )
            if results:
                knowledge_block = _format_knowledge_block(results)
                injections.append(knowledge_block)
        except Exception:
            pass  # Silently skip if unavailable

    # Compose final prompt
    if injections:
        injection_section = "\n\n".join(injections)
        return f"{base_prompt}\n\n{injection_section}"
    else:
        return base_prompt


def _format_preferences_block(prefs: Dict[str, Any]) -> str:
    """Format user preferences as XML block."""
    if not prefs:
        return ""

    lines = ["<user_preferences>"]
    for key, value in prefs.items():
        lines.append(f"  {key}: {value}")
    lines.append("</user_preferences>")

    return "\n".join(lines)


def _humanize_signature(signature: str) -> str:
    """Turn an error signature back into a readable 'Type: message' string.

    Signatures are 'ErrorType_message_with_underscores' (see error_memory).
    e.g. 'ValueError_invalid_json' -> 'ValueError: invalid json'
    """
    if "_" not in signature:
        return signature
    error_type, _, rest = signature.partition("_")
    message = rest.replace("_", " ")
    return f"{error_type}: {message}"


def _format_pitfalls_block(errors: List[Any]) -> str:
    """Format known pitfalls/errors as XML block."""
    if not errors:
        return ""

    lines = ["<known_pitfalls>", "Common errors to avoid (ranked by frequency):"]
    for i, error in enumerate(errors[:5], 1):
        readable = _humanize_signature(error.signature)
        lines.append(
            f"  {i}. {readable} (seen {error.occurrence_count}x)"
        )
        if error.resolution:
            lines.append(f"     → Fix: {error.resolution}")
    lines.append("</known_pitfalls>")

    return "\n".join(lines)


def _format_knowledge_block(entries: List[Any]) -> str:
    """Format relevant knowledge as XML block.

    Accepts both ORM objects (from KnowledgeGraph) and plain dicts (from a
    capsule's relevant_knowledge), so the same block renders in either path.
    """
    if not entries:
        return ""

    def _get(entry, key, default=None):
        if isinstance(entry, dict):
            return entry.get(key, default)
        return getattr(entry, key, default)

    lines = ["<relevant_solutions>", "Prior solutions for similar problems:"]
    for i, entry in enumerate(entries[:3], 1):
        task_type = _get(entry, "task_type", "unknown")
        quality = _get(entry, "quality_score", 0.0) or 0.0
        lines.append(f"  {i}. [{task_type}] Quality: {quality:.1f}")
        solution_preview = str(_get(entry, "solution", ""))[:100].replace("\n", " ")
        lines.append(f"     {solution_preview}...")
        use_count = _get(entry, "use_count", 0) or 0
        if use_count > 0:
            lines.append(f"     (reused {use_count}x)")
    lines.append("</relevant_solutions>")

    return "\n".join(lines)


def format_capsule_with_memory(
    base_prompt: str,
    capsule,
) -> str:
    """Augment capsule system prompt with injected memory (Phase 4+5 integration).

    Args:
        base_prompt: Original system prompt
        capsule: SubAgentCapsule with user_preferences, known_pitfalls, relevant_knowledge

    Returns:
        Augmented prompt with memory blocks
    """
    injections = []

    # Include user preferences from capsule
    if capsule.user_preferences:
        prefs_block = _format_preferences_block(capsule.user_preferences)
        injections.append(prefs_block)

    # Include known pitfalls from capsule
    if capsule.known_pitfalls:
        lines = ["<known_pitfalls>", "Known errors to avoid:"]
        for pitfall in capsule.known_pitfalls:
            lines.append(f"  • {pitfall['error']} (seen {pitfall['frequency']}x)")
            if pitfall.get("resolution"):
                lines.append(f"    → {pitfall['resolution']}")
        lines.append("</known_pitfalls>")
        injections.append("\n".join(lines))

    # Include relevant knowledge from capsule
    if capsule.relevant_knowledge:
        knowledge_block = _format_knowledge_block(capsule.relevant_knowledge)
        injections.append(knowledge_block)

    # Compose final prompt
    if injections:
        injection_section = "\n\n".join(injections)
        return f"{base_prompt}\n\n{injection_section}"
    else:
        return base_prompt
