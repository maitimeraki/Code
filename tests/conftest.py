"""Shared pytest fixtures.

Gives every test a fresh, isolated in-memory database so rows never leak
across tests. Without this, tests share one on-disk harness.db and aggregation
counts accumulate across runs (e.g. clear_all_preferences returns 6 not 3).
"""

import pytest_asyncio

from harness.config import get_settings
from harness.persistence import database


@pytest_asyncio.fixture(autouse=True)
async def fresh_db(monkeypatch):
    """Reset the DB engine before each test and point it at in-memory SQLite.

    - Overrides settings.database_url to an in-memory DB (no disk, no leakage).
    - Disposes any prior engine so init_db() rebuilds cleanly.
    - Disposes again on teardown to release the StaticPool connection.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///:memory:")

    # Ensure a clean slate even if a previous test left an engine around.
    await database.dispose_db()
    await database.init_db()

    yield

    await database.dispose_db()


@pytest_asyncio.fixture
def orchestrator():
    """Fresh orchestrator instance without network/FS setup.

    Uses __new__ to skip __init__ which scans agent/skill directories
    and builds an LLMClient — irrelevant to ledger behavior and slow.
    """
    from harness.orchestration.orchestrator import HarnessOrchestrator
    orch = HarnessOrchestrator.__new__(HarnessOrchestrator)
    orch.turns = []
    return orch
