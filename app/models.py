import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
import enum


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ReminderStatus(str, enum.Enum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class Task(Base):
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(String(100), nullable=False)
    status = Column(SAEnum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    deadline = Column(DateTime(timezone=True), nullable=False)
    reminder_minutes_before = Column(String(200), default="30")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    tags = Column(String(500), nullable=True)
    priority = Column(String(20), default="medium")


class ReminderLog(Base):
    __tablename__ = "reminder_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), nullable=False)
    task_title = Column(String(255), nullable=False)
    owner_id = Column(String(100), nullable=False)
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(SAEnum(ReminderStatus), default=ReminderStatus.QUEUED, nullable=False)
    message = Column(Text, nullable=True)
    error_detail = Column(Text, nullable=True)
    attempt_count = Column(String(10), default="1")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
