"""Database models for state and memory persistence."""

from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import Column, String, Integer, Float, DateTime, Text, Boolean, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Session(Base):
    """User session with full execution context."""
    __tablename__ = "sessions"

    session_id = Column(String(36), primary_key=True, index=True)
    user_id = Column(String(255), index=True)
    status = Column(String(50), default="active")  # active, paused, completed, failed
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    completed_at = Column(DateTime, nullable=True)

    metadata_json = Column(JSON, default={})


class Task(Base):
    """Task execution record."""
    __tablename__ = "tasks"

    task_id = Column(String(36), primary_key=True, index=True)
    session_id = Column(String(36), index=True)
    description = Column(Text)
    status = Column(String(50), default="pending")  # pending, running, completed, failed
    result = Column(Text, nullable=True)
    error = Column(Text, nullable=True)

    iterations = Column(Integer, default=0)
    max_iterations = Column(Integer, default=10)
    tokens_used = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.now, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    metadata_json = Column(JSON, default={})


class AgentExecution(Base):
    """Record of agent spawn and execution."""
    __tablename__ = "agent_executions"

    execution_id = Column(String(36), primary_key=True, index=True)
    task_id = Column(String(36), index=True)
    agent_type = Column(String(100), index=True)
    status = Column(String(50))  # running, completed, failed
    output = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    tokens_used = Column(Integer, default=0)

    started_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    metadata_json = Column(JSON, default={})


class ToolCall(Base):
    """Record of tool invocation."""
    __tablename__ = "tool_calls"

    call_id = Column(String(36), primary_key=True, index=True)
    task_id = Column(String(36), index=True)
    tool_type = Column(String(100), index=True)
    status = Column(String(50))  # success, failed, timeout
    result = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    cached = Column(Boolean, default=False)
    tokens_used = Column(Integer, default=0)

    started_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    metadata_json = Column(JSON, default={})


class KnowledgeEntry(Base):
    """Prior solution or learned pattern for future reuse."""
    __tablename__ = "knowledge_entries"

    entry_id = Column(String(36), primary_key=True, index=True)
    task_type = Column(String(255), index=True)  # "authentication", "api_design", etc.
    solution = Column(Text)  # The solution/pattern description
    code_example = Column(Text, nullable=True)
    quality_score = Column(Float, default=0.0)  # 0.0-1.0 rating
    use_count = Column(Integer, default=0)  # Times reused

    created_at = Column(DateTime, default=datetime.now, index=True)
    last_used_at = Column(DateTime, nullable=True)

    tags = Column(JSON, default=[])  # ["jwt", "security", "auth"]
    metadata_json = Column(JSON, default={})


class TaskJournal(Base):
    """Write-ahead log of all decisions and outputs (crash recovery)."""
    __tablename__ = "task_journals"

    journal_id = Column(String(36), primary_key=True, index=True)
    task_id = Column(String(36), index=True)
    sequence = Column(Integer)  # Order of events
    event_type = Column(String(100))  # "agent_started", "tool_executed", "decision_made", etc.
    event_data = Column(JSON)  # Full event payload

    recorded_at = Column(DateTime, default=datetime.now)


class Analytics(Base):
    """System analytics and learning metrics."""
    __tablename__ = "analytics"

    analytics_id = Column(String(36), primary_key=True, index=True)
    metric_name = Column(String(255), index=True)  # "agent_success_rate", "avg_token_usage", etc.
    metric_value = Column(Float)
    dimension = Column(String(255), nullable=True)  # e.g., "architect", "security_reviewer"

    period_start = Column(DateTime)
    period_end = Column(DateTime)
    recorded_at = Column(DateTime, default=datetime.now)

    metadata_json = Column(JSON, default={})
