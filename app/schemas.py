from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime, timezone
from uuid import UUID
from app.models import TaskStatus, ReminderStatus


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    owner_id: str = Field(..., min_length=1, max_length=100)
    deadline: datetime = Field(...)
    reminder_minutes_before: Optional[str] = Field("30")
    tags: Optional[str] = None
    priority: Optional[str] = Field("medium")

    @validator("priority")
    def validate_priority(cls, v):
        if v not in {"low", "medium", "high"}:
            raise ValueError("priority must be low, medium, or high")
        return v

    @validator("deadline")
    def validate_deadline(cls, v):
        now = datetime.now(timezone.utc)
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        if v <= now:
            raise ValueError("deadline must be in the future")
        return v

    @validator("reminder_minutes_before")
    def validate_reminder_minutes(cls, v):
        if v:
            try:
                parts = [int(x.strip()) for x in v.split(",")]
                for p in parts:
                    if p < 1:
                        raise ValueError
            except ValueError:
                raise ValueError("reminder_minutes_before must be comma-separated positive integers e.g. '60,30,10'")
        return v


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    deadline: Optional[datetime] = None
    reminder_minutes_before: Optional[str] = None
    tags: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[TaskStatus] = None

    @validator("priority")
    def validate_priority(cls, v):
        if v is not None and v not in {"low", "medium", "high"}:
            raise ValueError("priority must be low, medium, or high")
        return v


class TaskResponse(BaseModel):
    id: UUID
    title: str
    description: Optional[str]
    owner_id: str
    status: TaskStatus
    deadline: datetime
    reminder_minutes_before: str
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    tags: Optional[str]
    priority: str

    class Config:
        orm_mode = True


class TaskListResponse(BaseModel):
    tasks: List[TaskResponse]
    total: int
    page: int
    page_size: int


class ReminderLogResponse(BaseModel):
    id: UUID
    task_id: UUID
    task_title: str
    owner_id: str
    scheduled_for: datetime
    sent_at: Optional[datetime]
    status: ReminderStatus
    message: Optional[str]
    error_detail: Optional[str]
    attempt_count: str
    created_at: datetime

    class Config:
        orm_mode = True


class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str
    queue: str
    version: str


class MessageResponse(BaseModel):
    message: str
    task_id: Optional[str] = None
