"""Stream aggregator that batches and updates UI in real-time."""

import asyncio
from typing import Callable, Awaitable, Optional
from collections import deque
from .stream_listener import StreamListener, LogEntry
from .renderers import OutputRenderer


class StreamAggregator:
    """Batches stream entries and updates UI every 50ms."""

    def __init__(self, stream_listener: StreamListener):
        self.listener = stream_listener
        self.batch_buffer: deque = deque(maxlen=100)
        self.batch_interval = 0.05
        self.on_batch: Optional[Callable[[list[LogEntry]], Awaitable[None]]] = None

    def register_batch_handler(self, handler: Callable[[list[LogEntry]], Awaitable[None]]) -> None:
        """Register handler to process batches."""
        self.on_batch = handler

    async def start(self) -> None:
        """Start the aggregator loop."""
        stream_task = asyncio.create_task(self._consume_stream())
        batch_task = asyncio.create_task(self._batch_loop())

        try:
            await asyncio.gather(stream_task, batch_task, return_exceptions=True)
        except asyncio.CancelledError:
            stream_task.cancel()
            batch_task.cancel()

    async def _consume_stream(self) -> None:
        """Consume entries from stream listener."""
        try:
            async for entry in self.listener.stream_entries():
                self.batch_buffer.append(entry)
        except asyncio.CancelledError:
            pass

    async def _batch_loop(self) -> None:
        """Send batches every 50ms."""
        while True:
            try:
                await asyncio.sleep(self.batch_interval)

                if self.batch_buffer and self.on_batch:
                    batch = list(self.batch_buffer)
                    self.batch_buffer.clear()
                    await self.on_batch(batch)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    def get_formatted_entries(self, entries: list[LogEntry]) -> list:
        """Format entries for display."""
        formatted = []
        for entry in entries:
            rendered = OutputRenderer.render_log_entry(entry)
            formatted.append(rendered)
        return formatted
