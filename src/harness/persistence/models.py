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
    args_json = Column(JSON, default={})

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


class TaskJournal(Base):
    """Episodic log: iteration history for a task."""
    __tablename__ = "task_journals"

    journal_id = Column(String(36), primary_key=True, index=True)
    task_id = Column(String(36), index=True)  # Foreign key to Task
    iteration = Column(Integer, index=True)  # Which iteration this log belongs to
    message = Column(Text)  # What happened in this iteration
    created_at = Column(DateTime, default=datetime.now, index=True)


class ApprovalRequest(Base):
    """Human-in-the-loop approval request."""
    __tablename__ = "approval_requests"

    approval_id = Column(String(36), primary_key=True, index=True)
    task_id = Column(String(36), index=True)
    proposed_action = Column(JSON)  # Tool call details: {tool_type, args, ...}
    status = Column(String(50), default="pending")  # pending, approved, rejected
    idempotency_key = Column(String(36), unique=True, index=True)  # Crash-safety
    risk_level = Column(String(50), default="medium")  # low, medium, high, critical
    summary = Column(Text)  # Human-readable summary of what will happen

    created_at = Column(DateTime, default=datetime.now, index=True)
    decided_at = Column(DateTime, nullable=True)
    decided_by = Column(String(255), nullable=True)  # User/system that approved/rejected
    decision_notes = Column(Text, nullable=True)  # Why approved/rejected


class ExecutedAction(Base):
    """Idempotency ledger: tracks executed actions for crash-safety."""
    __tablename__ = "executed_actions"

    idempotency_key = Column(String(36), primary_key=True, index=True)
    task_id = Column(String(36), index=True)
    result_json = Column(JSON, nullable=True)  # Result of execution
    error = Column(Text, nullable=True)  # Error if execution failed
    executed_at = Column(DateTime, default=datetime.now, index=True)


class ErrorMemory(Base):
    """Track errors and failures for learning and recovery."""
    __tablename__ = "error_memory"

    signature = Column(String(255), primary_key=True, index=True)  # Hash of error type + message
    context = Column(Text, nullable=True)  # Where it happened (task type, tool, etc.)
    root_cause = Column(Text, nullable=True)  # What caused it (if known)
    resolution = Column(Text, nullable=True)  # How to fix it (if known)

    occurrence_count = Column(Integer, default=1)  # How many times we've seen this
    first_seen = Column(DateTime, default=datetime.now, index=True)
    last_seen = Column(DateTime, default=datetime.now, index=True)


class UserPreference(Base):
    """User preferences for behavior customization."""
    __tablename__ = "user_preferences"

    pref_id = Column(String(36), primary_key=True, index=True)
    user_id = Column(String(255), index=True)  # FK to user
    key = Column(String(255), index=True)  # Preference name (e.g., "auto_approve_risk_level")
    value = Column(Text)  # Preference value (JSON serializable)
    source = Column(String(100), default="user")  # "user" | "system" | "inferred"

    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, index=True)

    tags = Column(JSON, default=[])  # ["jwt", "security", "auth"]
    metadata_json = Column(JSON, default={})


class PendingQuestion(Base):
    """Persisted pending question for session resume."""
    __tablename__ = "pending_questions"

    id = Column(String(36), primary_key=True, index=True)
    session_id = Column(String(36), nullable=False, index=True)
    question_text = Column(Text, nullable=False)
    header = Column(String(255), default="")
    options_json = Column(Text, nullable=False)
    multi_select = Column(Boolean, default=False)
    timeout_seconds = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    answer_json = Column(Text, nullable=True)
    answered_at = Column(DateTime, nullable=True)


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
