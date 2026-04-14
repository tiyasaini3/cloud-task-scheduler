import os
import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")
LOCAL_LOG_DIR = os.getenv("LOCAL_LOG_DIR", "/tmp/task_logs")
S3_BUCKET = os.getenv("S3_BUCKET", "task-scheduler-logs")


def _ensure_local_dir():
    os.makedirs(LOCAL_LOG_DIR, exist_ok=True)


def _write_local(key: str, data: dict) -> bool:
    _ensure_local_dir()
    filename = key.replace("/", "_") + ".json"
    path = os.path.join(LOCAL_LOG_DIR, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return True


def _write_s3(key: str, data: dict) -> bool:
    import boto3
    s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(data, default=str),
        ContentType="application/json",
    )
    return True


def write_audit_log(event_type: str, task_id: str, owner_id: str,
                    details: Optional[dict] = None) -> bool:
    ts = datetime.utcnow()
    key = f"audit/{ts.strftime('%Y/%m/%d')}/{event_type}_{task_id}_{ts.strftime('%H%M%S%f')}"
    payload = {
        "event_type": event_type,
        "task_id": task_id,
        "owner_id": owner_id,
        "timestamp": ts.isoformat(),
        "details": details or {},
    }
    try:
        if STORAGE_BACKEND == "s3":
            return _write_s3(key, payload)
        return _write_local(key, payload)
    except Exception as e:
        logger.error(f"[STORAGE] Failed to write audit log: {e}")
        return False


def write_reminder_execution_log(task_id: str, owner_id: str, remind_at: str,
                                  status: str, message: Optional[str] = None) -> bool:
    ts = datetime.utcnow()
    key = f"reminders/{ts.strftime('%Y/%m/%d')}/reminder_{task_id}_{ts.strftime('%H%M%S%f')}"
    payload = {
        "task_id": task_id,
        "owner_id": owner_id,
        "remind_at": remind_at,
        "execution_time": ts.isoformat(),
        "status": status,
        "message": message,
    }
    try:
        if STORAGE_BACKEND == "s3":
            return _write_s3(key, payload)
        return _write_local(key, payload)
    except Exception as e:
        logger.error(f"[STORAGE] Failed to write reminder log: {e}")
        return False
