import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock


def make_job(minutes=-1):
    remind_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return json.dumps({
        "task_id": "test-001",
        "task_title": "Test Task",
        "owner_id": "user_test",
        "remind_at": remind_at.isoformat(),
        "deadline": (remind_at + timedelta(hours=1)).isoformat(),
    })


@patch("worker.worker.SessionLocal")
@patch("worker.worker.storage.write_reminder_execution_log")
@patch("worker.worker.cache.set_job_state")
def test_send_reminder_success(mock_state, mock_storage, mock_session):
    from worker.worker import send_reminder
    mock_db = MagicMock()
    mock_session.return_value = mock_db
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    assert send_reminder(json.loads(make_job())) is True
    mock_storage.assert_called_once()


@patch("worker.worker.send_reminder", return_value=True)
@patch("worker.worker.cache.set_job_state")
def test_fires_immediately_for_past_job(mock_state, mock_send):
    from worker.worker import process_job
    process_job(make_job(-5))
    mock_send.assert_called_once()


@patch("worker.worker.send_reminder", return_value=True)
@patch("worker.worker.cache.set_job_state")
def test_invalid_json_skipped(mock_state, mock_send):
    from worker.worker import process_job
    process_job("not json {{")
    mock_send.assert_not_called()


@patch("worker.worker.send_reminder", return_value=True)
@patch("worker.worker.cache.set_job_state")
def test_missing_remind_at_skipped(mock_state, mock_send):
    from worker.worker import process_job
    process_job(json.dumps({"task_id": "abc", "task_title": "No time"}))
    mock_send.assert_not_called()


@patch("worker.worker.get_redis")
@patch("worker.worker.send_reminder", side_effect=Exception("fail"))
@patch("worker.worker.cache.set_job_state")
@patch("worker.worker.storage.write_reminder_execution_log")
@patch("worker.worker.SessionLocal")
def test_retries_then_dlq(mock_session, mock_storage, mock_state, mock_send, mock_redis):
    import worker.worker as w
    w.MAX_RETRIES = 2
    mock_db = MagicMock()
    mock_session.return_value = mock_db
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_r = MagicMock()
    mock_redis.return_value = mock_r
    with patch("time.sleep"):
        w.process_job(make_job(-1))
    mock_r.rpush.assert_called_once()
    assert "dead" in mock_r.rpush.call_args[0][0]
