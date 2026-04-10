"""Tests for mcp_db_server.py — calls tool functions directly, no MCP protocol needed."""
import sys
from pathlib import Path
import pytest
import sqlite3

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Redirect all db calls to a fresh tmp DB for each test."""
    import db as db_module
    test_db = tmp_path / "test.db"
    
    # Create test database connection
    test_db.parent.mkdir(exist_ok=True)
    main_conn = sqlite3.connect(str(test_db))
    main_conn.row_factory = sqlite3.Row
    main_conn.execute("PRAGMA foreign_keys = ON")
    
    # Monkeypatch get_db to create new connections to the test database
    original_get_db = db_module.get_db
    
    def mock_get_db(path=None):
        conn = sqlite3.connect(str(test_db))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    
    monkeypatch.setattr(db_module, "get_db", mock_get_db)
    
    # Create tables in test database
    db_module.create_tables(main_conn)
    
    # Upsert test applications
    db_module.upsert_application("run_contentful", {
        "job_description": "PM role at Contentful",
        "company_research": "Company: Contentful, Series D, 500 employees",
        "role_analysis": "Need strong API product experience",
        "gap_analysis": "Gap: no CMS experience. Strength: growth PM background",
    }, conn=main_conn)
    db_module.upsert_application("run_deel", {
        "job_description": "Senior PM at Deel",
        "company_research": "Company: Deel, Series D",
    }, conn=main_conn)
    
    yield
    
    # Cleanup
    main_conn.close()


def test_list_jobs_returns_both_apps():
    from mcp_db_server import list_jobs
    result = list_jobs()
    assert "run_contentful" in result
    assert "run_deel" in result


def test_find_application_by_company():
    from mcp_db_server import find_application
    result = find_application("Contentful")
    assert "run_contentful" in result
    assert "Contentful" in result


def test_find_application_case_insensitive():
    from mcp_db_server import find_application
    result = find_application("contentful")
    assert "run_contentful" in result


def test_find_application_no_match():
    from mcp_db_server import find_application
    result = find_application("Google")
    assert "No applications found" in result


def test_get_application_detail_includes_all_sections():
    from mcp_db_server import get_application_detail
    result = get_application_detail("run_contentful")
    assert "PM role at Contentful" in result
    assert "Gap: no CMS experience" in result
    assert "API product experience" in result


def test_get_application_detail_not_found():
    from mcp_db_server import get_application_detail
    result = get_application_detail("run_nonexistent")
    assert "not found" in result.lower()


def test_get_interview_rounds_empty():
    from mcp_db_server import get_interview_rounds
    result = get_interview_rounds("run_contentful")
    assert "No rounds" in result


def test_save_prep_notes_creates_round():
    import db as db_module
    from mcp_db_server import save_prep_notes
    result = save_prep_notes("run_contentful", "hr", "Q1: Tell me about yourself. Q2: Why Contentful?", notes="Monday 10am")
    assert "round_id=" in result
    assert "Contentful" in result
    rounds = db_module.get_rounds("run_contentful")
    assert len(rounds) == 1
    assert rounds[0]["prep_content"] == "Q1: Tell me about yourself. Q2: Why Contentful?"
    assert rounds[0]["notes"] == "Monday 10am"


def test_save_prep_notes_invalid_type():
    from mcp_db_server import save_prep_notes
    result = save_prep_notes("run_contentful", "phone_screen", "content")
    assert "Invalid round_type" in result


def test_save_prep_notes_app_not_found():
    from mcp_db_server import save_prep_notes
    result = save_prep_notes("run_nonexistent", "hr", "content")
    assert "not found" in result.lower()


def test_get_interview_rounds_with_data():
    from mcp_db_server import save_prep_notes, get_interview_rounds
    save_prep_notes("run_contentful", "hr", "Expected questions list here")
    result = get_interview_rounds("run_contentful")
    assert "hr" in result
    assert "Expected questions list here" in result


def test_update_prep_notes():
    import db as db_module
    from mcp_db_server import save_prep_notes, update_prep_notes
    save_prep_notes("run_contentful", "hr", "Initial prep")
    rounds = db_module.get_rounds("run_contentful")
    round_id = rounds[0]["id"]
    result = update_prep_notes(round_id, notes="They probed compensation twice", transcript_analysis="Strong on motivation, weak on metrics")
    assert "Updated" in result
    rounds = db_module.get_rounds("run_contentful")
    assert rounds[0]["notes"] == "They probed compensation twice"
    assert rounds[0]["transcript_analysis"] == "Strong on motivation, weak on metrics"


def test_update_prep_notes_nothing_to_update():
    import db as db_module
    from mcp_db_server import save_prep_notes, update_prep_notes
    save_prep_notes("run_contentful", "hr", "prep")
    rounds = db_module.get_rounds("run_contentful")
    round_id = rounds[0]["id"]
    result = update_prep_notes(round_id)
    assert "Nothing to update" in result


def test_update_prep_notes_round_not_found():
    from mcp_db_server import update_prep_notes
    result = update_prep_notes("round_nonexistent", notes="some note")
    assert "not found" in result.lower()
