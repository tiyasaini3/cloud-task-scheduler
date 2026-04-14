import os
import json
import logging
import redis
from typing import Optional

logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

_client: Optional[redis.Redis] = None


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=True)
    return _client


def ping() -> bool:
    try:
        return get_client().ping()
    except Exception:
        return False


JOB_STATE_TTL = 60 * 60 * 48


def set_job_state(task_id: str, state: str, meta: Optional[dict] = None) -> None:
    key = f"job:state:{task_id}"
    value = {"state": state, "meta": meta or {}}
    get_client().setex(key, JOB_STATE_TTL, json.dumps(value))


def get_job_state(task_id: str) -> Optional[dict]:
    key = f"job:state:{task_id}"
    raw = get_client().get(key)
    return json.loads(raw) if raw else None


def delete_job_state(task_id: str) -> None:
    get_client().delete(f"job:state:{task_id}")


TASK_CACHE_TTL = 60 * 5


def cache_task(task_id: str, task_data: dict) -> None:
    key = f"task:cache:{task_id}"
    get_client().setex(key, TASK_CACHE_TTL, json.dumps(task_data, default=str))


def get_cached_task(task_id: str) -> Optional[dict]:
    key = f"task:cache:{task_id}"
    raw = get_client().get(key)
    return json.loads(raw) if raw else None


def invalidate_task_cache(task_id: str) -> None:
    get_client().delete(f"task:cache:{task_id}")


def check_rate_limit(owner_id: str, limit: int = 100, window_seconds: int = 60) -> bool:
    key = f"ratelimit:{owner_id}"
    client = get_client()
    current = client.incr(key)
    if current == 1:
        client.expire(key, window_seconds)
    return current <= limit
