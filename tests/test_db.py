"""Unit tests for db.py — all tests use a temporary DB via tmp_path fixture."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from db import (
    create_tables, get_db, upsert_application, get_application,
    list_applications, update_application, create_round, update_round, get_rounds,
)


@pytest.fixture
def db_conn(tmp_path):
    """Isolated DB connection for each test — no shared state."""
    conn = get_db(tmp_path / "test.db")
    create_tables(conn)
    yield conn
    conn.close()


def test_upsert_and_get_application(db_conn):
    state = {
        "job_description": "Senior PM role",
        "company_research": "Company: Acme Corp, Series B, 100 employees",
        "cv_json": '{"name": "Test"}',
    }
    upsert_application("run_20260101_120000", state, conn=db_conn)
    app = get_application("run_20260101_120000", conn=db_conn)
    assert app is not None
    assert app["id"] == "run_20260101_120000"
    assert app["company"] == "Acme Corp"
    assert app["status"] == "cv_ready"


def test_upsert_is_idempotent(db_conn):
    """Calling upsert twice with updated state updates the row, not duplicates it."""
    state = {"job_description": "PM role", "company_research": "Company: Foo"}
    upsert_application("run_1", state, conn=db_conn)
    state["company_research"] = "Company: Bar Inc"
    upsert_application("run_1", state, conn=db_conn)
    app = get_application("run_1", conn=db_conn)
    assert app["company"] == "Bar Inc"
    assert len(list_applications(conn=db_conn)) == 1


def test_list_applications_newest_first(db_conn):
    upsert_application("run_20260101_000000", {"job_description": "A"},
                       created_at="2026-01-01T00:00:00", conn=db_conn)
    upsert_application("run_20260102_000000", {"job_description": "B"},
                       created_at="2026-01-02T00:00:00", conn=db_conn)
    apps = list_applications(conn=db_conn)
    assert apps[0]["id"] == "run_20260102_000000"


def test_update_application_status(db_conn):
    upsert_application("run_2", {"job_description": "PM"}, conn=db_conn)
    update_application("run_2", status="applied", conn=db_conn)
    assert get_application("run_2", conn=db_conn)["status"] == "applied"


def test_update_application_ignores_unknown_fields(db_conn):
    """Should not raise — just silently ignore unrecognised field names."""
    upsert_application("run_3", {"job_description": "PM"}, conn=db_conn)
    update_application("run_3", status="interview", injected="DROP TABLE", conn=db_conn)
    assert get_application("run_3", conn=db_conn)["status"] == "interview"


def test_create_and_get_rounds(db_conn):
    upsert_application("run_4", {"job_description": "PM"}, conn=db_conn)
    round_id = create_round("run_4", "hr", notes="Prepare comp range", conn=db_conn)
    rounds = get_rounds("run_4", conn=db_conn)
    assert len(rounds) == 1
    assert rounds[0]["id"] == round_id
    assert rounds[0]["type"] == "hr"
    assert rounds[0]["status"] == "scheduled"
    assert rounds[0]["notes"] == "Prepare comp range"


def test_update_round(db_conn):
    upsert_application("run_5", {"job_description": "PM"}, conn=db_conn)
    round_id = create_round("run_5", "hr", conn=db_conn)
    update_round(round_id, status="completed", transcript="They asked about salary", conn=db_conn)
    rounds = get_rounds("run_5", conn=db_conn)
    assert rounds[0]["status"] == "completed"
    assert rounds[0]["transcript"] == "They asked about salary"


def test_old_checkpoint_state_keys_ignored(db_conn):
    """Old checkpoints have manager_research, manager_name — must not crash."""
    old_state = {
        "job_description": "PM role",
        "manager_name": "John",
        "company_research": "Company: OldCo",
        "manager_research": "Hired many PMs",
        "cv_markdown": "# CV",
    }
    upsert_application("run_old", old_state, conn=db_conn)
    app = get_application("run_old", conn=db_conn)
    assert app["company"] == "OldCo"
