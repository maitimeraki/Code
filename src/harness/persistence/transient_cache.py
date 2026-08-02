"""Transient memory: Redis-backed hot cache for active execution."""

import json
from typing import Optional, Dict, Any
import structlog

logger = structlog.get_logger(__name__)


class TransientMemory:
    """Fast in-memory cache for active task context.

    Provides <10ms lookup for task state during execution.
    Falls back gracefully if Redis is unavailable.
    """

    CONTEXT_TTL = 3600  # 1 hour expiry
    STREAM_TTL = 86400  # 24-hour event stream retention

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self.client: Optional[Any] = None
        self.enabled = False

    async def connect(self) -> None:
        """Initialize Redis connection with graceful degradation."""
        try:
            import redis.asyncio as redis
            self.client = await redis.from_url(self.redis_url, decode_responses=True)
            await self.client.ping()
            self.enabled = True
            logger.info("Connected to Redis", url=self.redis_url)
        except ImportError:
            logger.warning("redis package not installed, transient memory disabled")
            self.enabled = False
        except Exception as e:
            logger.warning("Redis connection failed, transient memory disabled", error=str(e))
            self.enabled = False

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self.client:
            try:
                await self.client.close()
            except Exception as e:
                logger.warning("Error closing Redis connection", error=str(e))

    async def set_context(self, task_id: str, context: Dict[str, Any]) -> None:
        """Store active task context with 1-hour TTL."""
        if not self.enabled or not self.client:
            return

        key = f"task:{task_id}:context"
        try:
            await self.client.setex(
                key,
                self.CONTEXT_TTL,
                json.dumps(context)
            )
            logger.debug("Context cached", task_id=task_id, key=key)
        except Exception as e:
            logger.warning("Failed to cache context", task_id=task_id, error=str(e))

    async def get_context(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve active context (<10ms lookup)."""
        if not self.enabled or not self.client:
            return None

        key = f"task:{task_id}:context"
        try:
            data = await self.client.get(key)
            if not data:
                logger.debug("Context miss", task_id=task_id)
                return None

            context = json.loads(data)
            logger.debug("Context hit", task_id=task_id)
            return context
        except Exception as e:
            logger.warning("Failed to retrieve context", task_id=task_id, error=str(e))
            return None

    async def append_event(self, task_id: str, event: Dict[str, Any]) -> None:
        """Append event to real-time stream."""
        if not self.enabled or not self.client:
            return

        key = f"task:{task_id}:events"
        try:
            event_json = json.dumps(event)
            await self.client.xadd(key, {"event": event_json})
            await self.client.expire(key, self.STREAM_TTL)
            logger.debug("Event streamed", task_id=task_id)
        except Exception as e:
            logger.warning("Failed to stream event", task_id=task_id, error=str(e))

    async def clear_context(self, task_id: str) -> None:
        """Clear context on task completion."""
        if not self.enabled or not self.client:
            return

        key = f"task:{task_id}:context"
        try:
            await self.client.delete(key)
            logger.info("Context cleared", task_id=task_id)
        except Exception as e:
            logger.warning("Failed to clear context", task_id=task_id, error=str(e))
