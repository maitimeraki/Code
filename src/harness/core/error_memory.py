"""Error/pitfall memory: track and learn from failures."""

import hashlib
import re
from datetime import datetime
from typing import Optional
import structlog
from sqlalchemy import select

from harness.persistence.database import get_session
from harness.persistence.models import ErrorMemory

logger = structlog.get_logger(__name__)

# Volatile substrings that make two instances of the SAME error look different:
# hex addresses, line/col numbers, paths, timestamps. Stripping them lets the loop
# recognise "same wall, different pebble" and stop churning.
_HEX = re.compile(r"0x[0-9a-fA-F]+")
_NUM = re.compile(r"\d+")
_PATH = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][\w.\-]+)+")
_WS = re.compile(r"\s+")


def normalize_error(text: str) -> str:
    """Collapse volatile parts of an error string to a stable skeleton.

    Two errors that differ only by address/line-number/path/timestamp normalize
    to the same skeleton, so the loop's same-error guard and the memory key both
    treat them as one recurring failure instead of an endless stream of "new" ones.
    """
    if not text:
        return ""
    s = text.strip()
    s = _HEX.sub("<hex>", s)
    s = _PATH.sub("<path>", s)
    s = _NUM.sub("<n>", s)
    s = _WS.sub(" ", s)
    return s.lower()


def _error_signature(error_type: str, error_message: str) -> str:
    """Generate a stable signature for an error (type + normalized message skeleton).

    Examples:
        ValueError + "invalid input at line 42" → "valueerror_<hash>"
        ConnectionError + "timeout after 30s"   → "connectionerror_<hash>"
    """
    skeleton = normalize_error(error_message)[:200]
    digest = hashlib.md5(skeleton.encode("utf-8")).hexdigest()[:12]
    return f"{error_type.lower()}_{digest}"


async def upsert_error(
    error_type: str,
    error_message: str,
    context: Optional[str] = None,
    root_cause: Optional[str] = None,
    resolution: Optional[str] = None,
) -> str:
    """Record an error in memory: upsert with occurrence_count++.

    Args:
        error_type: Exception class name (e.g., "ValueError", "ConnectionError")
        error_message: Exception message
        context: Where it happened (task type, tool name, etc.)
        root_cause: What caused it (if known)
        resolution: How to fix it (if known)

    Returns:
        signature (for tracking)
    """
    signature = _error_signature(error_type, error_message)

    async with get_session() as db_session:
        # Try to get existing entry
        existing = await db_session.get(ErrorMemory, signature)

        if existing:
            # Increment and update
            existing.occurrence_count = (existing.occurrence_count or 0) + 1
            existing.last_seen = datetime.now()
            # Optionally update root cause/resolution if provided
            if root_cause:
                existing.root_cause = root_cause
            if resolution:
                existing.resolution = resolution
        else:
            # Create new entry
            entry = ErrorMemory(
                signature=signature,
                context=context,
                root_cause=root_cause,
                resolution=resolution,
                occurrence_count=1,
                first_seen=datetime.now(),
                last_seen=datetime.now(),
            )
            db_session.add(entry)

        await db_session.commit()

    logger.info(
        "Error recorded in memory",
        signature=signature,
        error_type=error_type,
        context=context,
    )

    return signature


async def get_top_pitfalls(limit: int = 10) -> list[ErrorMemory]:
    """Get most frequent errors (top pitfalls by occurrence_count).

    Args:
        limit: Number of top errors to return

    Returns:
        List of ErrorMemory entries sorted by occurrence_count descending
    """
    async with get_session() as db_session:
        result = await db_session.execute(
            select(ErrorMemory).order_by(ErrorMemory.occurrence_count.desc()).limit(limit)
        )
        return result.scalars().all()


async def get_error_by_signature(signature: str) -> Optional[ErrorMemory]:
    """Retrieve a specific error entry by signature."""
    async with get_session() as db_session:
        return await db_session.get(ErrorMemory, signature)


async def get_errors_by_type(error_type: str, limit: int = 5) -> list[ErrorMemory]:
    """Get all errors of a specific type (e.g., "ValueError").

    Searches by signature prefix matching error_type.
    """
    async with get_session() as db_session:
        result = await db_session.execute(
            select(ErrorMemory)
            .where(ErrorMemory.signature.startswith(error_type.lower() + "_"))
            .order_by(ErrorMemory.occurrence_count.desc())
            .limit(limit)
        )
        return result.scalars().all()


async def clear_error(signature: str) -> bool:
    """Remove an error from memory (e.g., after it's been fixed).

    Args:
        signature: The error signature to clear

    Returns:
        True if deleted, False if not found
    """
    async with get_session() as db_session:
        entry = await db_session.get(ErrorMemory, signature)
        if not entry:
            return False

        await db_session.delete(entry)
        await db_session.commit()

    logger.info("Error cleared from memory", signature=signature)
    return True
