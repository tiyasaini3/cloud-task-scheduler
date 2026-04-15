import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import engine, Base, get_db
from app import models, schemas, cache, storage
from app.queue import enqueue_reminder, get_queue_depth, ping_queue

import os
import webbrowser

# -------------------- APP SETUP --------------------

app = FastAPI(
    title="Task Scheduler & Reminder Service",
    description="Cloud-based distributed task scheduling and reminder service.",
    version="1.0.0",
)

# ✅ CORS (fixes OPTIONS 405 errors from dashboard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Static files (dashboard)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Auto-open dashboard (best effort, may not work inside Docker)
@app.on_event("startup")
def open_dashboard():
    try:
        webbrowser.open("http://localhost:8000")
    except Exception:
        pass

# Create DB tables
@app.on_event("startup")
def on_startup():
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables ensured.")
    except Exception as e:
        logger.error(f"Database init failed: {e}")

# -------------------- DASHBOARD --------------------

@app.get("/", include_in_schema=False)
def serve_dashboard():
    path = os.path.join(os.path.dirname(__file__), "static", "dashboard.html")
    return FileResponse(path)

# -------------------- MIDDLEWARE --------------------

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = datetime.utcnow()
    response = await call_next(request)
    ms = (datetime.utcnow() - start).total_seconds() * 1000
    logger.info(f"{request.method} {request.url.path} → {response.status_code} ({ms:.1f}ms)")
    return response

# -------------------- HEALTH --------------------

@app.get("/health", response_model=schemas.HealthResponse, tags=["Health"])
def health_check(db: Session = Depends(get_db)):
    db_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {e}"

    redis_status = "ok" if cache.ping() else "error"
    queue_status = "ok" if ping_queue() else "error"

    overall = "ok" if all(s == "ok" for s in [db_status, redis_status, queue_status]) else "degraded"

    return schemas.HealthResponse(
        status=overall,
        database=db_status,
        redis=redis_status,
        queue=queue_status,
        version="1.0.0",
    )

# -------------------- TASKS --------------------

@app.post("/tasks", response_model=schemas.TaskResponse, status_code=201, tags=["Tasks"])
def create_task(payload: schemas.TaskCreate, db: Session = Depends(get_db)):
    if not cache.check_rate_limit(payload.owner_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")

    task = models.Task(**payload.dict())
    db.add(task)
    db.commit()
    db.refresh(task)

    offsets = [int(x.strip()) for x in task.reminder_minutes_before.split(",")]
    queued = 0

    for minutes in offsets:
        deadline = task.deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)

        remind_at = deadline - timedelta(minutes=minutes)

        if remind_at > datetime.now(timezone.utc):
            ok = enqueue_reminder(
                str(task.id),
                task.title,
                task.owner_id,
                remind_at,
                deadline
            )
            if ok:
                queued += 1
                log = models.ReminderLog(
                    task_id=task.id,
                    task_title=task.title,
                    owner_id=task.owner_id,
                    scheduled_for=remind_at,
                    status="queued",
                    message=f"Reminder for '{task.title}' due {task.deadline}",
                )
                db.add(log)

    if queued > 0:
        task.status = "scheduled"

    db.commit()
    db.refresh(task)

    cache.set_job_state(str(task.id), "scheduled", {"reminders_queued": queued})

    storage.write_audit_log(
        "task_created",
        str(task.id),
        task.owner_id,
        {
            "title": task.title,
            "deadline": str(task.deadline),
            "reminders_queued": queued,
        },
    )

    logger.info(f"[API] Task created id={task.id} reminders_queued={queued}")
    return task


@app.get("/tasks", response_model=schemas.TaskListResponse, tags=["Tasks"])
def list_tasks(
    owner_id: str = Query(...),
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(models.Task).filter(models.Task.owner_id == owner_id)

    if status:
        q = q.filter(models.Task.status == status)
    if priority:
        q = q.filter(models.Task.priority == priority)

    total = q.count()

    tasks = (
        q.order_by(models.Task.deadline.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return schemas.TaskListResponse(
        tasks=tasks,
        total=total,
        page=page,
        page_size=page_size
    )


@app.get("/tasks/{task_id}", response_model=schemas.TaskResponse, tags=["Tasks"])
def get_task(task_id: UUID, db: Session = Depends(get_db)):
    cached = cache.get_cached_task(str(task_id))
    if cached:
        return JSONResponse(content=cached)

    task = _get_or_404(task_id, db)

    cache.cache_task(
        str(task_id),
        {
            "id": str(task.id),
            "title": task.title,
            "description": task.description,
            "owner_id": task.owner_id,
            "status": task.status,
            "deadline": str(task.deadline),
            "reminder_minutes_before": task.reminder_minutes_before,
            "created_at": str(task.created_at),
            "updated_at": str(task.updated_at),
            "completed_at": str(task.completed_at) if task.completed_at else None,
            "tags": task.tags,
            "priority": task.priority,
        },
    )

    return task


@app.patch("/tasks/{task_id}", response_model=schemas.TaskResponse, tags=["Tasks"])
def update_task(task_id: UUID, payload: schemas.TaskUpdate, db: Session = Depends(get_db)):
    task = _get_or_404(task_id, db)

    for field, value in payload.dict(exclude_unset=True).items():
        if isinstance(value, str) or value is None:
            setattr(task, field, value)
        else:
            setattr(task, field, str(value) if hasattr(value, "value") else value)

    task.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(task)

    cache.invalidate_task_cache(str(task_id))
    storage.write_audit_log("task_updated", str(task.id), task.owner_id)

    return task


@app.post("/tasks/{task_id}/complete", response_model=schemas.TaskResponse, tags=["Tasks"])
def complete_task(task_id: UUID, db: Session = Depends(get_db)):
    task = _get_or_404(task_id, db)

    if task.status == "completed":
        raise HTTPException(status_code=400, detail="Task is already completed.")

    task.status = "completed"
    task.completed_at = datetime.utcnow()
    task.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(task)

    cache.set_job_state(str(task_id), "completed")
    cache.invalidate_task_cache(str(task_id))
    storage.write_audit_log("task_completed", str(task.id), task.owner_id)

    return task


@app.delete("/tasks/{task_id}", response_model=schemas.MessageResponse, tags=["Tasks"])
def delete_task(task_id: UUID, db: Session = Depends(get_db)):
    task = _get_or_404(task_id, db)

    storage.write_audit_log(
        "task_deleted",
        str(task.id),
        task.owner_id,
        {"title": task.title},
    )

    db.delete(task)
    db.commit()

    cache.delete_job_state(str(task_id))
    cache.invalidate_task_cache(str(task_id))

    return schemas.MessageResponse(
        message="Task deleted.",
        task_id=str(task_id)
    )

# -------------------- REMINDERS --------------------

@app.get("/tasks/{task_id}/reminders", response_model=list[schemas.ReminderLogResponse], tags=["Reminders"])
def get_reminders(task_id: UUID, db: Session = Depends(get_db)):
    _get_or_404(task_id, db)

    return (
        db.query(models.ReminderLog)
        .filter(models.ReminderLog.task_id == task_id)
        .order_by(models.ReminderLog.scheduled_for.asc())
        .all()
    )

# -------------------- STATE --------------------

@app.get("/tasks/{task_id}/state", tags=["Tasks"])
def get_task_state(task_id: UUID):
    state = cache.get_job_state(str(task_id))
    if not state:
        raise HTTPException(status_code=404, detail="No state found for this task.")
    return state

# -------------------- QUEUE --------------------

@app.get("/queue/depth", tags=["Health"])
def queue_depth():
    return {"queue_depth": get_queue_depth()}

# -------------------- HELPERS --------------------

def _get_or_404(task_id: UUID, db: Session) -> models.Task:
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")
    return task
