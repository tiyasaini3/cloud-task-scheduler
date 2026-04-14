import os
import sys
import json
import time
import logging
import signal
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import redis
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app import models, cache, storage

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
QUEUE_NAME = os.getenv("REDIS_QUEUE_NAME", "reminders")
POLL_INTERVAL = float(os.getenv("WORKER_POLL_INTERVAL", "2"))
MAX_RETRIES = int(os.getenv("WORKER_MAX_RETRIES", "3"))
DEAD_LETTER_QUEUE = f"{QUEUE_NAME}:dead"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] WORKER: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("worker")

_running = True


def _handle_signal(signum, frame):
    global _running
    logger.info(f"Signal {signum} received — shutting down gracefully…")
    _running = False


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


def get_redis() -> redis.Redis:
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)


def send_reminder(job: dict) -> bool:
    task_id = job["task_id"]
    message = (
        f"REMINDER | Task: '{job['task_title']}' | "
        f"Owner: {job['owner_id']} | Deadline: {job['deadline']}"
    )
    logger.info(f"FIRING: {message}")

    db: Session = SessionLocal()
    try:
        log = db.query(models.ReminderLog).filter(
            models.ReminderLog.task_id == task_id,
            models.ReminderLog.status == "queued",
        ).order_by(models.ReminderLog.scheduled_for.asc()).first()

        if log:
            log.status = "sent"
            log.sent_at = datetime.utcnow()
            log.message = message
            db.commit()
    except Exception as e:
        logger.error(f"DB update failed for task {task_id}: {e}")
    finally:
        db.close()

    storage.write_reminder_execution_log(
        task_id=task_id,
        owner_id=job["owner_id"],
        remind_at=job["remind_at"],
        status="sent",
        message=message,
    )
    cache.set_job_state(task_id, "reminder_sent", {
        "sent_at": datetime.utcnow().isoformat(),
    })
    return True


def process_job(job_str: str) -> None:
    try:
        job = json.loads(job_str)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON: {e}")
        return

    task_id = job.get("task_id", "unknown")
    remind_at_str = job.get("remind_at")
    if not remind_at_str:
        logger.error(f"Job missing remind_at: {job}")
        return

    try:
        remind_at = datetime.fromisoformat(remind_at_str)
        if remind_at.tzinfo is None:
            remind_at = remind_at.replace(tzinfo=timezone.utc)
    except ValueError as e:
        logger.error(f"Cannot parse remind_at '{remind_at_str}': {e}")
        return

    now = datetime.now(timezone.utc)
    wait_seconds = (remind_at - now).total_seconds()

    if wait_seconds > 0:
        logger.info(f"task={task_id} sleeping {wait_seconds:.1f}s until {remind_at_str}")
        cache.set_job_state(task_id, "pending", {"remind_at": remind_at_str})
        slept = 0.0
        while slept < wait_seconds and _running:
            chunk = min(5.0, wait_seconds - slept)
            time.sleep(chunk)
            slept += chunk
        if not _running:
            logger.info(f"Shutdown — re-queuing task={task_id}")
            get_redis().lpush(QUEUE_NAME, job_str)
            return

    cache.set_job_state(task_id, "running")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if send_reminder(job):
                logger.info(f"Reminder sent task={task_id} attempt={attempt}")
                return
        except Exception as e:
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES} failed task={task_id}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)

    logger.error(f"All retries failed task={task_id} — moving to DLQ")
    get_redis().rpush(DEAD_LETTER_QUEUE, job_str)
    cache.set_job_state(task_id, "failed", {"reason": "max_retries_exceeded"})

    db: Session = SessionLocal()
    try:
        log = db.query(models.ReminderLog).filter(
            models.ReminderLog.task_id == task_id,
            models.ReminderLog.status == "queued",
        ).first()
        if log:
            log.status = "failed"
            log.error_detail = "Max retries exceeded"
            db.commit()
    finally:
        db.close()


def run():
    logger.info(f"Worker starting — queue={QUEUE_NAME} redis={REDIS_HOST}:{REDIS_PORT}")
    r = None
    for _ in range(30):
        try:
            r = get_redis()
            r.ping()
            logger.info("Redis connected ✓")
            break
        except Exception:
            logger.warning("Waiting for Redis…")
            time.sleep(2)
    else:
        logger.error("Cannot connect to Redis. Exiting.")
        sys.exit(1)

    logger.info("Polling for jobs…")
    while _running:
        try:
            result = r.blpop(QUEUE_NAME, timeout=int(POLL_INTERVAL))
            if result:
                _, job_str = result
                logger.info(f"Dequeued job: {job_str[:100]}…")
                process_job(job_str)
        except redis.exceptions.ConnectionError:
            logger.error("Redis connection lost — retrying in 5s…")
            time.sleep(5)
            try:
                r = get_redis()
                r.ping()
                logger.info("Reconnected to Redis ✓")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            time.sleep(1)

    logger.info("Worker stopped.")


if __name__ == "__main__":
    run()
