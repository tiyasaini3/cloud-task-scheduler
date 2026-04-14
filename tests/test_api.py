import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

SQLALCHEMY_TEST_URL = "sqlite:///./test_task_scheduler.db"
test_engine = create_engine(SQLALCHEMY_TEST_URL, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
Base.metadata.create_all(bind=test_engine)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield


def future(minutes=120):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


# ── Health ────────────────────────────────────────────────────────────────────

@patch("app.main.ping_queue", return_value=True)
@patch("app.main.cache.ping", return_value=True)
def test_health(mock_cache, mock_queue, client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["database"] == "ok"


# ── Create ────────────────────────────────────────────────────────────────────

@patch("app.main.enqueue_reminder", return_value=True)
@patch("app.main.cache.check_rate_limit", return_value=True)
@patch("app.main.cache.set_job_state")
@patch("app.main.storage.write_audit_log")
def test_create_task(mock_log, mock_state, mock_rl, mock_eq, client):
    r = client.post("/tasks", json={
        "title": "Submit report",
        "owner_id": "user_001",
        "deadline": future(240),
        "reminder_minutes_before": "60,30",
        "priority": "high",
    })
    assert r.status_code == 201
    d = r.json()
    assert d["title"] == "Submit report"
    assert d["priority"] == "high"


@patch("app.main.cache.check_rate_limit", return_value=True)
def test_create_past_deadline(mock_rl, client):
    r = client.post("/tasks", json={
        "title": "Old", "owner_id": "u1", "deadline": "2020-01-01T00:00:00Z"
    })
    assert r.status_code == 422


@patch("app.main.cache.check_rate_limit", return_value=True)
def test_create_invalid_priority(mock_rl, client):
    r = client.post("/tasks", json={
        "title": "Bad", "owner_id": "u1", "deadline": future(), "priority": "critical"
    })
    assert r.status_code == 422


@patch("app.main.cache.check_rate_limit", return_value=False)
def test_rate_limit(mock_rl, client):
    r = client.post("/tasks", json={"title": "T", "owner_id": "u1", "deadline": future()})
    assert r.status_code == 429


# ── Read ──────────────────────────────────────────────────────────────────────

@patch("app.main.enqueue_reminder", return_value=True)
@patch("app.main.cache.check_rate_limit", return_value=True)
@patch("app.main.cache.set_job_state")
@patch("app.main.storage.write_audit_log")
@patch("app.main.cache.get_cached_task", return_value=None)
@patch("app.main.cache.cache_task")
def test_get_task(mock_ct, mock_gc, mock_log, mock_state, mock_rl, mock_eq, client):
    r = client.post("/tasks", json={"title": "Read me", "owner_id": "u2", "deadline": future()})
    tid = r.json()["id"]
    r2 = client.get(f"/tasks/{tid}")
    assert r2.status_code == 200
    assert r2.json()["id"] == tid


def test_get_task_not_found(client):
    assert client.get(f"/tasks/{uuid4()}").status_code == 404


# ── List ──────────────────────────────────────────────────────────────────────

@patch("app.main.enqueue_reminder", return_value=True)
@patch("app.main.cache.check_rate_limit", return_value=True)
@patch("app.main.cache.set_job_state")
@patch("app.main.storage.write_audit_log")
def test_list_tasks(mock_log, mock_state, mock_rl, mock_eq, client):
    for i in range(3):
        client.post("/tasks", json={"title": f"T{i}", "owner_id": "list_user", "deadline": future(60 + i * 30)})
    r = client.get("/tasks?owner_id=list_user")
    assert r.status_code == 200
    assert r.json()["total"] == 3


@patch("app.main.enqueue_reminder", return_value=True)
@patch("app.main.cache.check_rate_limit", return_value=True)
@patch("app.main.cache.set_job_state")
@patch("app.main.storage.write_audit_log")
def test_list_pagination(mock_log, mock_state, mock_rl, mock_eq, client):
    for i in range(5):
        client.post("/tasks", json={"title": f"P{i}", "owner_id": "page_user", "deadline": future(60 + i * 10)})
    r = client.get("/tasks?owner_id=page_user&page=1&page_size=2")
    assert r.json()["total"] == 5
    assert len(r.json()["tasks"]) == 2


# ── Update ────────────────────────────────────────────────────────────────────

@patch("app.main.enqueue_reminder", return_value=True)
@patch("app.main.cache.check_rate_limit", return_value=True)
@patch("app.main.cache.set_job_state")
@patch("app.main.storage.write_audit_log")
@patch("app.main.cache.invalidate_task_cache")
def test_update_task(mock_inv, mock_log, mock_state, mock_rl, mock_eq, client):
    r = client.post("/tasks", json={"title": "Old", "owner_id": "u3", "deadline": future()})
    tid = r.json()["id"]
    r2 = client.patch(f"/tasks/{tid}", json={"title": "New", "priority": "low"})
    assert r2.status_code == 200
    assert r2.json()["title"] == "New"


# ── Complete ──────────────────────────────────────────────────────────────────

@patch("app.main.enqueue_reminder", return_value=True)
@patch("app.main.cache.check_rate_limit", return_value=True)
@patch("app.main.cache.set_job_state")
@patch("app.main.storage.write_audit_log")
@patch("app.main.cache.invalidate_task_cache")
def test_complete_task(mock_inv, mock_log, mock_state, mock_rl, mock_eq, client):
    r = client.post("/tasks", json={"title": "Do it", "owner_id": "u4", "deadline": future()})
    tid = r.json()["id"]
    r2 = client.post(f"/tasks/{tid}/complete")
    assert r2.status_code == 200
    assert r2.json()["status"] == "completed"
    assert r2.json()["completed_at"] is not None


@patch("app.main.enqueue_reminder", return_value=True)
@patch("app.main.cache.check_rate_limit", return_value=True)
@patch("app.main.cache.set_job_state")
@patch("app.main.storage.write_audit_log")
@patch("app.main.cache.invalidate_task_cache")
def test_complete_twice(mock_inv, mock_log, mock_state, mock_rl, mock_eq, client):
    r = client.post("/tasks", json={"title": "Once", "owner_id": "u4", "deadline": future()})
    tid = r.json()["id"]
    client.post(f"/tasks/{tid}/complete")
    r2 = client.post(f"/tasks/{tid}/complete")
    assert r2.status_code == 400


# ── Delete ────────────────────────────────────────────────────────────────────

@patch("app.main.enqueue_reminder", return_value=True)
@patch("app.main.cache.check_rate_limit", return_value=True)
@patch("app.main.cache.set_job_state")
@patch("app.main.storage.write_audit_log")
@patch("app.main.cache.invalidate_task_cache")
@patch("app.main.cache.delete_job_state")
def test_delete_task(mock_del, mock_inv, mock_log, mock_state, mock_rl, mock_eq, client):
    r = client.post("/tasks", json={"title": "Gone", "owner_id": "u5", "deadline": future()})
    tid = r.json()["id"]
    r2 = client.delete(f"/tasks/{tid}")
    assert r2.status_code == 200
    assert client.get(f"/tasks/{tid}").status_code == 404


# ── Reminders ─────────────────────────────────────────────────────────────────

@patch("app.main.enqueue_reminder", return_value=True)
@patch("app.main.cache.check_rate_limit", return_value=True)
@patch("app.main.cache.set_job_state")
@patch("app.main.storage.write_audit_log")
def test_get_reminders(mock_log, mock_state, mock_rl, mock_eq, client):
    r = client.post("/tasks", json={
        "title": "Remind me", "owner_id": "u6",
        "deadline": future(240), "reminder_minutes_before": "60,30",
    })
    tid = r.json()["id"]
    r2 = client.get(f"/tasks/{tid}/reminders")
    assert r2.status_code == 200
    assert isinstance(r2.json(), list)
