"""MCP (Model Context Protocol) tool provider.

Lets third-party MCP servers contribute tools at runtime with no code change.
Each server's tools are namespaced ``mcp__<server>__<tool>`` so they never
collide with built-ins (or each other) and so permission rules can target them
by glob (e.g. ``deny: ["mcp__prod_db__*"]``).

Supports two transports: ``stdio`` (command/args/env) and ``streamable-http``
(url/headers), driven by an ``mcpServers`` block in settings.json.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import structlog

from harness.config import get_app_settings
from harness.tools.definitions import ToolDefinition
from harness.tools.models import ToolType

logger = structlog.get_logger(__name__)

NAMESPACE_PREFIX = "mcp__"
# A server that hasn't connected within this budget is marked degraded rather
# than blocking agent startup. One slow server never stalls the grid.
CONNECT_TIMEOUT_SECONDS = 10


class MCPProvider:
    """A single MCP server connection, owned by MCPManager."""

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name = name
        self._config = config
        self._namespace = f"{NAMESPACE_PREFIX}{name}__"
        self._defs: dict[str, ToolDefinition] = {}  # full tool name -> definition
        self._degraded = False
        self._last_error = ""
        self._stack: contextlib.AsyncExitStack | None = None
        self._session: Any = None
        self._lock = asyncio.Lock()

    # ── lifecycle ──────────────────────────────────────────────────────────
    async def start(self) -> None:
        """Connect and cache tools. Any failure marks the server degraded."""
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS):
                await self._connect_and_list()
            self._degraded = False
            self._last_error = ""
            logger.info("mcp server connected", server=self.name, tools=len(self._defs))
        except Exception as exc:  # noqa: BLE001 — degrade, never crash the grid
            self._degraded = True
            self._last_error = str(exc)
            await self._dispose()
            logger.warning("mcp server degraded (offline)", name=self.name, error=str(exc))

    async def stop(self) -> None:
        await self._dispose()

    async def _dispose(self) -> None:
        if self._stack is not None:
            with contextlib.suppress(Exception):
                await self._stack.aclose()
            self._stack = None
        self._session = None

    # ── data exposed to the grid ───────────────────────────────────────────
    @property
    def degraded(self) -> bool:
        return self._degraded

    @property
    def error(self) -> str:
        return self._last_error

    def tool_definitions(self) -> list[ToolDefinition]:
        return list(self._defs.values())

    async def call(self, local_name: str, args: dict[str, Any]) -> str:
        """Invoke a tool on this server. Reconnects on a dropped session."""
        async with self._lock:
            if self._session is None:
                async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS):
                    await self._connect_and_list()
            try:
                result = await self._session.call_tool(local_name, arguments=args)
                return _format_call_result(result)
            except Exception as exc:  # noqa: BLE001 — surface to caller + degrade
                self._degraded = True
                self._last_error = str(exc)
                raise

    # ── internals ──────────────────────────────────────────────────────────
    async def _connect_and_list(self) -> None:
        """(Re)establish a session and refresh the cached tool list."""
        from mcp import ClientSession

        new_stack = contextlib.AsyncExitStack()
        try:
            if "url" in self._config:
                read, write = await new_stack.enter_async_context(self._http_session())
            else:
                read, write = await new_stack.enter_async_context(self._stdio_client())
            session = await new_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            listed = await session.list_tools()
            self._defs = {
                f"{self._namespace}{tool.name}": ToolDefinition(
                    name=f"{self._namespace}{tool.name}",
                    tool_type=ToolType.READ,  # dynamic identity; kind unused for MCP
                    description=tool.description or tool.name,
                    json_schema=tool.inputSchema or {},
                )
                for tool in listed.tools
            }
            # Swap in the new stack only after everything succeeded.
            old, self._stack, self._session = self._stack, new_stack, session
            if old is not None:
                with contextlib.suppress(Exception):
                    await old.aclose()
        except Exception:
            with contextlib.suppress(Exception):
                await new_stack.aclose()
            raise

    @contextlib.asynccontextmanager
    async def _stdio_client(self):
        from mcp.client.stdio import StdioServerParameters, stdio_client

        command = self._config.get("command")
        if not command:
            raise ValueError(f"mcp server '{self.name}' needs a 'command'")
        params = StdioServerParameters(
            command=command,
            args=self._config.get("args") or [],
            env=self._config.get("env"),
        )
        async with stdio_client(params) as streams:
            yield streams  # (read, write)

    @contextlib.asynccontextmanager
    async def _http_session(self):
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        url = self._config["url"]
        headers = self._config.get("headers") or {}
        async with httpx.AsyncClient(headers=headers) as http_client:
            async with streamable_http_client(url, http_client=http_client) as streams:
                # streams = (read, write, get_session_id); unwrap to (read, write).
                yield streams[:2]


def _format_call_result(result) -> str:
    """Flatten an MCP call result into a plain string for the agent."""
    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
        elif (st := getattr(block, "structuredContent", None)) is not None:
            import json as _json

            parts.append(_json.dumps(st, default=str))
    body = "\n".join(p for p in parts if p).strip()
    if getattr(result, "isError", False) or not body:
        return body or f"[mcp tool error: {getattr(result, 'isError', False)}]"
    return body


class MCPManager:
    """Owns all configured MCP servers and exposes their tools to the grid."""

    def __init__(self) -> None:
        self._providers: dict[str, MCPProvider] = {}
        self._started = False

    # ── lifecycle ──────────────────────────────────────────────────────────
    @property
    def started(self) -> bool:
        return self._started

    async def load_from_settings(self) -> None:
        """Read ``mcpServers`` from settings.json and register each server."""
        servers = get_app_settings().get("mcpServers", {}) or {}
        for name, config in servers.items():
            if name in self._providers:
                continue
            self._providers[name] = MCPProvider(name, config)
        self._started = True

    async def add(self, name: str, config: dict[str, Any]) -> MCPProvider:
        """Dynamically add a server at runtime (hot-pluggable)."""
        provider = MCPProvider(name, config)
        self._providers[name] = provider
        await provider.start()
        return provider

    async def remove(self, name: str) -> None:
        provider = self._providers.pop(name, None)
        if provider is not None:
            await provider.stop()

    async def start(self) -> None:
        """Start every registered server concurrently; degraded ones are skipped."""
        if not self._providers:
            return
        await asyncio.gather(*(p.start() for p in self._providers.values()))

    async def stop(self) -> None:
        await asyncio.gather(*(p.stop() for p in self._providers.values()))

    # ── grid-facing helpers ────────────────────────────────────────────────
    def healthy(self) -> list[MCPProvider]:
        return [p for p in self._providers.values() if not p.degraded]

    def all_tools(self) -> list[ToolDefinition]:
        """Tool definitions from every healthy server."""
        out: list[ToolDefinition] = []
        for p in self._providers.values():
            if not p.degraded:
                out.extend(p.tool_definitions())
        return out

    def get(self, name: str) -> MCPProvider | None:
        return self._providers.get(name)

    async def call(self, full_name: str, args: dict[str, Any]) -> str:
        """Route ``mcp__server__tool`` by its namespace prefix."""
        parts = full_name.split("__", 2)
        if len(parts) != 3 or parts[0] != "mcp":
            raise ValueError(f"Not an MCP tool: {full_name}")
        provider = self._providers.get(parts[1])
        if provider is None:
            raise ValueError(f"unknown mcp server: {parts[1]}")
        return await provider.call(parts[2], args)