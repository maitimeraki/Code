"""Agent spawner with multi-LLM fallback support."""

import asyncio
from typing import Optional
import structlog

from .agent import AgentConfig, AgentResult, AgentStatus, AgentType

logger = structlog.get_logger(__name__)


class AgentSpawner:
    """Spawn and execute agents with multi-LLM fallback."""

    def __init__(self):
        self.results = {}

    async def spawn(self, config: AgentConfig) -> AgentResult:
        """Spawn agent and execute task."""
        result = AgentResult(
            agent_type=config.agent_type,
            status=AgentStatus.SPAWNING,
        )

        try:
            result.status = AgentStatus.RUNNING
            logger.info(
                "Spawning agent",
                agent_type=config.agent_type.value,
                task=config.task_description[:100],
            )

            # Mock execution - in full Phase 2, this calls litellm
            # For now, simulate agent work
            await asyncio.sleep(0.5)

            result.status = AgentStatus.COMPLETED
            result.output = f"Agent {config.agent_type.value} completed: {config.task_description[:50]}..."
            result.tokens_used = 150

            logger.info(
                "Agent completed",
                agent_type=config.agent_type.value,
                tokens=result.tokens_used,
            )

        except asyncio.CancelledError:
            result.status = AgentStatus.CANCELLED
            logger.info("Agent cancelled", agent_type=config.agent_type.value)
            raise

        except Exception as e:
            result.status = AgentStatus.FAILED
            result.error = str(e)
            logger.error(
                "Agent failed",
                agent_type=config.agent_type.value,
                error=str(e),
            )

        return result

    async def spawn_parallel(self, configs: list[AgentConfig]) -> list[AgentResult]:
        """Spawn multiple agents in parallel with semaphore."""
        semaphore = asyncio.Semaphore(4)  # Max 4 concurrent agents

        async def bounded_spawn(config):
            async with semaphore:
                return await self.spawn(config)

        tasks = [bounded_spawn(cfg) for cfg in configs]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results
