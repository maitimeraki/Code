"""User preferences: customizable behavior per user."""

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4
import structlog
from sqlalchemy import select

from harness.persistence.database import get_session
from harness.persistence.models import UserPreference

logger = structlog.get_logger(__name__)


async def set_preference(
    user_id: str,
    key: str,
    value: Any,
    source: str = "user",
) -> str:
    """Set or update a user preference.

    Args:
        user_id: User identifier
        key: Preference key (e.g., "auto_approve_risk_level")
        value: Preference value (can be any JSON-serializable value)
        source: "user" | "system" | "inferred"

    Returns:
        pref_id
    """
    async with get_session() as db_session:
        # Check if preference exists
        result = await db_session.execute(
            select(UserPreference)
            .where(UserPreference.user_id == user_id)
            .where(UserPreference.key == key)
        )
        existing = result.scalars().first()

        if existing:
            # Update
            existing.value = str(value) if not isinstance(value, str) else value
            existing.source = source
            existing.updated_at = datetime.now()
            pref_id = existing.pref_id
        else:
            # Create
            pref_id = str(uuid4())
            pref = UserPreference(
                pref_id=pref_id,
                user_id=user_id,
                key=key,
                value=str(value) if not isinstance(value, str) else value,
                source=source,
                updated_at=datetime.now(),
            )
            db_session.add(pref)

        await db_session.commit()

    logger.info(
        "User preference set",
        user_id=user_id,
        key=key,
        source=source,
    )

    return pref_id


async def get_preference(
    user_id: str,
    key: str,
    default: Any = None,
) -> Optional[Any]:
    """Get a specific user preference.

    Args:
        user_id: User identifier
        key: Preference key
        default: Default value if not found

    Returns:
        Preference value, or default if not found
    """
    async with get_session() as db_session:
        result = await db_session.execute(
            select(UserPreference)
            .where(UserPreference.user_id == user_id)
            .where(UserPreference.key == key)
        )
        pref = result.scalars().first()

    return pref.value if pref else default


async def get_all_preferences(user_id: str) -> dict[str, Any]:
    """Get all preferences for a user as a dict.

    Args:
        user_id: User identifier

    Returns:
        Dictionary of {key: value}
    """
    async with get_session() as db_session:
        result = await db_session.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        prefs = result.scalars().all()

    return {pref.key: pref.value for pref in prefs}


async def delete_preference(user_id: str, key: str) -> bool:
    """Delete a specific user preference.

    Args:
        user_id: User identifier
        key: Preference key

    Returns:
        True if deleted, False if not found
    """
    async with get_session() as db_session:
        result = await db_session.execute(
            select(UserPreference)
            .where(UserPreference.user_id == user_id)
            .where(UserPreference.key == key)
        )
        pref = result.scalars().first()

        if not pref:
            return False

        await db_session.delete(pref)
        await db_session.commit()

    logger.info(
        "User preference deleted",
        user_id=user_id,
        key=key,
    )

    return True


async def clear_all_preferences(user_id: str) -> int:
    """Delete all preferences for a user.

    Args:
        user_id: User identifier

    Returns:
        Number of preferences deleted
    """
    async with get_session() as db_session:
        result = await db_session.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        prefs = result.scalars().all()
        count = len(prefs)

        for pref in prefs:
            await db_session.delete(pref)

        await db_session.commit()

    logger.info(
        "User preferences cleared",
        user_id=user_id,
        count=count,
    )

    return count
