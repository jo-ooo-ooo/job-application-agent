"""Application database — SQLite-backed storage for Application and Round records.

Checkpoint files (.json) are still written for CLI resume support.
This adds queryable persistent storage alongside them.

DB location: data/applications.db  (gitignored — personal application data)
"""

import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "data" / "applications.db"

_VALID_APP_FIELDS = {"status", "applied_at", "role", "jd_url"}
_VALID_ROUND_FIELDS = {
    "status", "prep_content", "audio_path", "transcript",
    "transcript_analysis", "notes", "scheduled_at", "completed_at",
}


def get_db(path: Path = DB_PATH) -> sqlite3.Connection:
    """Open a DB connection. Row factory enables dict-like access."""
    path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_tables(conn: Optional[sqlite3.Connection] = None) -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    close = conn is None
    if conn is None:
        conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS applications (
            id                   TEXT PRIMARY KEY,
            company              TEXT NOT NULL DEFAULT '',
            role                 TEXT NOT NULL DEFAULT '',
            jd_url               TEXT NOT NULL DEFAULT '',
            status               TEXT NOT NULL DEFAULT 'cv_ready',
            job_description      TEXT NOT NULL DEFAULT '',
            company_research     TEXT NOT NULL DEFAULT '',
            role_analysis        TEXT NOT NULL DEFAULT '',
            gap_analysis         TEXT NOT NULL DEFAULT '',
            project_selection    TEXT NOT NULL DEFAULT '',
            cv_json              TEXT NOT NULL DEFAULT '',
            cover_letter_markdown TEXT NOT NULL DEFAULT '',
            score                REAL,
            recommendation       TEXT NOT NULL DEFAULT '',
            created_at           TEXT NOT NULL,
            applied_at           TEXT,
            updated_at           TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rounds (
            id                   TEXT PRIMARY KEY,
            application_id       TEXT NOT NULL REFERENCES applications(id),
            type                 TEXT NOT NULL,
            status               TEXT NOT NULL DEFAULT 'scheduled',
            prep_content         TEXT NOT NULL DEFAULT '',
            audio_path           TEXT NOT NULL DEFAULT '',
            transcript           TEXT NOT NULL DEFAULT '',
            transcript_analysis  TEXT NOT NULL DEFAULT '',
            notes                TEXT NOT NULL DEFAULT '',
            scheduled_at         TEXT,
            completed_at         TEXT,
            created_at           TEXT NOT NULL
        );
    """)
    conn.commit()
    if close:
        conn.close()


def _extract_company(company_research: str) -> str:
    """Parse company name from the first 'Company: ...' line in company_research."""
    m = re.search(r'Company:\s*\[?([A-Za-z0-9][^,\n\[\]]{1,40})', company_research or "")
    return m.group(1).strip() if m else ""


def upsert_application(
    run_id: str,
    state: dict,
    created_at: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Insert or update an application row from pipeline state.

    Called by save_checkpoint() after each pipeline step completes.
    Safe to call multiple times for the same run_id — uses ON CONFLICT UPDATE.
    Ignores unknown keys in state (e.g. old checkpoints with manager_research).
    """
    close = conn is None
    if conn is None:
        conn = get_db()
    now = datetime.now().isoformat()
    conn.execute(
        """
        INSERT INTO applications (
            id, company, status,
            job_description, company_research, role_analysis, gap_analysis,
            project_selection, cv_json, cover_letter_markdown,
            score, recommendation, created_at, updated_at
        ) VALUES (
            :id, :company, :status,
            :job_description, :company_research, :role_analysis, :gap_analysis,
            :project_selection, :cv_json, :cover_letter_markdown,
            :score, :recommendation, :created_at, :updated_at
        )
        ON CONFLICT(id) DO UPDATE SET
            company              = excluded.company,
            company_research     = excluded.company_research,
            role_analysis        = excluded.role_analysis,
            gap_analysis         = excluded.gap_analysis,
            project_selection    = excluded.project_selection,
            cv_json              = excluded.cv_json,
            cover_letter_markdown = excluded.cover_letter_markdown,
            score                = excluded.score,
            recommendation       = excluded.recommendation,
            updated_at           = excluded.updated_at
        """,
        {
            "id": run_id,
            "company": _extract_company(state.get("company_research", "")),
            "status": "cv_ready",
            "job_description": state.get("job_description", ""),
            "company_research": state.get("company_research", ""),
            "role_analysis": state.get("role_analysis", ""),
            "gap_analysis": state.get("gap_analysis", ""),
            "project_selection": state.get("project_selection", ""),
            "cv_json": state.get("cv_json", ""),
            "cover_letter_markdown": state.get("cover_letter_markdown", ""),
            "score": state.get("final_score"),
            "recommendation": state.get("final_recommendation", ""),
            "created_at": created_at or now,
            "updated_at": now,
        },
    )
    # Note: role and jd_url are not extracted from state here because the pipeline
    # doesn't produce them. They are set later via update_application (e.g. from
    # user input or the web UI).
    conn.commit()
    if close:
        conn.close()


def get_application(run_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    """Fetch one application by run_id. Returns None if not found."""
    close = conn is None
    if conn is None:
        conn = get_db()
    row = conn.execute("SELECT * FROM applications WHERE id = ?", (run_id,)).fetchone()
    if close:
        conn.close()
    return dict(row) if row else None


def list_applications(conn: Optional[sqlite3.Connection] = None) -> list[dict]:
    """Fetch all applications ordered newest first."""
    close = conn is None
    if conn is None:
        conn = get_db()
    rows = conn.execute(
        "SELECT * FROM applications ORDER BY created_at DESC"
    ).fetchall()
    if close:
        conn.close()
    return [dict(r) for r in rows]


def update_application(
    run_id: str,
    conn: Optional[sqlite3.Connection] = None,
    **fields,
) -> None:
    """Update whitelisted fields on an application. Unknown fields are silently ignored."""
    updates = {k: v for k, v in fields.items() if k in _VALID_APP_FIELDS}
    if not updates:
        return
    close = conn is None
    if conn is None:
        conn = get_db()
    updates["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = run_id
    conn.execute(f"UPDATE applications SET {set_clause} WHERE id = :id", updates)
    conn.commit()
    if close:
        conn.close()


def create_round(
    application_id: str,
    round_type: str,
    conn: Optional[sqlite3.Connection] = None,
    **fields,
) -> str:
    """Create a new round. Returns the generated round_id."""
    close = conn is None
    if conn is None:
        conn = get_db()
    round_id = f"round_{uuid.uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    extra = {k: v for k, v in fields.items() if k in _VALID_ROUND_FIELDS}
    columns = ["id", "application_id", "type", "status", "created_at"] + list(extra.keys())
    placeholders = [f":{c}" for c in columns]
    conn.execute(
        f"INSERT INTO rounds ({', '.join(columns)}) VALUES ({', '.join(placeholders)})",
        {"id": round_id, "application_id": application_id, "type": round_type,
         "status": "scheduled", "created_at": now, **extra},
    )
    conn.commit()
    if close:
        conn.close()
    return round_id


def update_round(
    round_id: str,
    conn: Optional[sqlite3.Connection] = None,
    **fields,
) -> None:
    """Update whitelisted fields on a round. Unknown fields silently ignored."""
    updates = {k: v for k, v in fields.items() if k in _VALID_ROUND_FIELDS}
    if not updates:
        return
    close = conn is None
    if conn is None:
        conn = get_db()
    # Note: rounds table has no updated_at column (unlike applications).
    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = round_id
    conn.execute(f"UPDATE rounds SET {set_clause} WHERE id = :id", updates)
    conn.commit()
    if close:
        conn.close()


def get_rounds(
    application_id: str,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Fetch all rounds for an application, in creation order."""
    close = conn is None
    if conn is None:
        conn = get_db()
    rows = conn.execute(
        "SELECT * FROM rounds WHERE application_id = ? ORDER BY created_at ASC",
        (application_id,),
    ).fetchall()
    if close:
        conn.close()
    return [dict(r) for r in rows]
