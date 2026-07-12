"""Structured logging setup with structlog."""

import logging
import logging.handlers
import structlog
from pathlib import Path
from typing import Any


def configure_logging(log_level: str = "info", log_file: Path | None = None) -> None:
    """Configure structlog for JSON structured output to file (not terminal)."""

    # ponytail: file-based logging keeps stdout/stderr clean for Rich Live control
    if log_file is None:
        log_file = Path.home() / ".code" / "data" / "harness.log"

    log_file.parent.mkdir(parents=True, exist_ok=True)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Set root logger to file, no console output
    handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10_000_000,  # 10MB
        backupCount=5,
    )
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
        handlers=[handler],
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a logger instance."""
    return structlog.get_logger(name)
