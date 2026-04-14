import os
import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

QUEUE_BACKEND = os.getenv("QUEUE_BACKEND", "redis")


def _get_redis_client():
    import redis
    return redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        db=0,
        decode_responses=True,
    )


def _enqueue_redis(task_id, task_title, owner_id, remind_at, deadline) -> bool:
    r = _get_redis_client()
    payload = {
        "task_id": task_id,
        "task_title": task_title,
        "owner_id": owner_id,
        "remind_at": remind_at.isoformat(),
        "deadline": deadline.isoformat(),
        "enqueued_at": datetime.utcnow().isoformat(),
    }
    r.rpush(os.getenv("REDIS_QUEUE_NAME", "reminders"), json.dumps(payload))
    logger.info(f"[QUEUE] Enqueued reminder task={task_id} at {remind_at}")
    return True


def _enqueue_sqs(task_id, task_title, owner_id, remind_at, deadline) -> bool:
    import boto3
    sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION", "us-east-1"))
    queue_url = os.getenv("SQS_QUEUE_URL")
    if not queue_url:
        raise EnvironmentError("SQS_QUEUE_URL is not set")
    payload = {
        "task_id": task_id,
        "task_title": task_title,
        "owner_id": owner_id,
        "remind_at": remind_at.isoformat(),
        "deadline": deadline.isoformat(),
        "enqueued_at": datetime.utcnow().isoformat(),
    }
    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(payload),
        MessageAttributes={
            "task_id": {"StringValue": task_id, "DataType": "String"},
        },
    )
    return True


def enqueue_reminder(task_id, task_title, owner_id, remind_at, deadline) -> bool:
    try:
        if QUEUE_BACKEND == "sqs":
            return _enqueue_sqs(task_id, task_title, owner_id, remind_at, deadline)
        return _enqueue_redis(task_id, task_title, owner_id, remind_at, deadline)
    except Exception as e:
        logger.error(f"[QUEUE] Failed to enqueue task={task_id}: {e}")
        return False


def get_queue_depth() -> Optional[int]:
    try:
        if QUEUE_BACKEND == "sqs":
            import boto3
            sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION", "us-east-1"))
            resp = sqs.get_queue_attributes(
                QueueUrl=os.getenv("SQS_QUEUE_URL", ""),
                AttributeNames=["ApproximateNumberOfMessages"],
            )
            return int(resp["Attributes"].get("ApproximateNumberOfMessages", 0))
        r = _get_redis_client()
        return r.llen(os.getenv("REDIS_QUEUE_NAME", "reminders"))
    except Exception as e:
        logger.warning(f"[QUEUE] Could not fetch queue depth: {e}")
        return None


def ping_queue() -> bool:
    try:
        if QUEUE_BACKEND == "sqs":
            import boto3
            boto3.client("sqs", region_name=os.getenv("AWS_REGION", "us-east-1")).list_queues()
            return True
        r = _get_redis_client()
        return r.ping()
    except Exception:
        return False
