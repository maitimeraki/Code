"""Stream listener for capturing agent output in real-time."""

import asyncio
from typing import AsyncIterator, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class LogLevel(Enum):
    """Log severity levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogEntry:
    """A single log entry from agent or tool."""
    timestamp: datetime
    level: LogLevel
    source: str
    message: str
    data: Optional[dict] = None


class StreamListener:
    """Listens to agent output streams in real-time."""

    def __init__(self):
        self.log_buffer: asyncio.Queue[LogEntry] = asyncio.Queue(maxsize=1000)
        self.listeners: list[Callable[[LogEntry], None]] = []

    def register_listener(self, callback: Callable[[LogEntry], None]) -> None:
        """Register a callback for log entries."""
        self.listeners.append(callback)

    async def emit(self, entry: LogEntry) -> None:
        """Emit a log entry to all listeners."""
        try:
            self.log_buffer.put_nowait(entry)
        except asyncio.QueueFull:
            try:
                self.log_buffer.get_nowait()
                await self.log_buffer.put(entry)
            except asyncio.QueueEmpty:
                pass

        for callback in self.listeners:
            try:
                callback(entry)
            except Exception:
                pass

    async def log_agent_output(
        self,
        message: str,
        level: LogLevel = LogLevel.INFO,
        data: Optional[dict] = None,
    ) -> None:
        """Log agent output."""
        entry = LogEntry(
            timestamp=datetime.now(),
            level=level,
            source="agent",
            message=message,
            data=data,
        )
        await self.emit(entry)

    async def log_tool_call(
        self,
        tool_name: str,
        args: dict,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Log a tool call."""
        message = f"Tool: {tool_name}"
        level = LogLevel.ERROR if error else LogLevel.INFO
        data = {"tool": tool_name, "args": args, "result": result, "error": error}
        entry = LogEntry(
            timestamp=datetime.now(),
            level=level,
            source="tool",
            message=message,
            data=data,
        )
        await self.emit(entry)

    async def log_skill_call(
        self,
        skill_name: str,
        params: Optional[dict] = None,
    ) -> None:
        """Log a skill invocation."""
        message = f"Skill: {skill_name}"
        data = {"skill": skill_name, "params": params or {}}
        entry = LogEntry(
            timestamp=datetime.now(),
            level=LogLevel.INFO,
            source="skill",
            message=message,
            data=data,
        )
        await self.emit(entry)

    async def log_agent_call(
        self,
        agent_name: str,
        task: str,
        iteration: Optional[int] = None,
    ) -> None:
        """Log an agent spawn."""
        message = f"Agent: {agent_name}"
        data = {"agent": agent_name, "task": task, "iteration": iteration}
        entry = LogEntry(
            timestamp=datetime.now(),
            level=LogLevel.INFO,
            source="agent_call",
            message=message,
            data=data,
        )
        await self.emit(entry)

    async def log_agent_status(
        self,
        agent_name: str,
        status: str,
        detail: Optional[str] = None,
    ) -> None:
        """Log agent status change."""
        message = f"Agent {agent_name}: {status}"
        data = {"agent": agent_name, "status": status, "detail": detail}
        entry = LogEntry(
            timestamp=datetime.now(),
            level=LogLevel.INFO,
            source="agent_status",
            message=message,
            data=data,
        )
        await self.emit(entry)

    async def stream_entries(self) -> AsyncIterator[LogEntry]:
        """Stream log entries as they arrive."""
        while True:
            try:
                entry = await asyncio.wait_for(self.log_buffer.get(), timeout=1.0)
                yield entry
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def get_buffer_snapshot(self) -> list[LogEntry]:
        """Get current buffer contents."""
        return list(self.log_buffer._queue)
