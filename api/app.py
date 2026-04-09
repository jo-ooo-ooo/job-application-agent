"""FastAPI application — REST API for application and round management.

Start with:
    uvicorn api.app:app --reload --port 8000

All routes return JSON. CORS is open (local-only tool, no auth needed).
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent))
from db import (
    create_tables,
    get_application,
    list_applications,
    update_application,
    create_round,
    update_round,
    get_rounds,
)

app = FastAPI(title="Job Application Agent", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    create_tables()


# ── Request models ────────────────────────────────────────────

class ApplicationUpdate(BaseModel):
    status: Optional[str] = None     # applied|screening|interview|offer|rejected
    applied_at: Optional[str] = None  # ISO datetime string
    role: Optional[str] = None
    jd_url: Optional[str] = None


class RoundCreate(BaseModel):
    type: str                          # hr|hiring_manager|case_study|panel
    scheduled_at: Optional[str] = None
    notes: Optional[str] = None


class RoundUpdate(BaseModel):
    status: Optional[str] = None       # scheduled|prepped|completed
    prep_content: Optional[str] = None
    audio_path: Optional[str] = None
    transcript: Optional[str] = None
    transcript_analysis: Optional[str] = None
    notes: Optional[str] = None
    completed_at: Optional[str] = None


# ── Application routes ────────────────────────────────────────

@app.get("/applications")
def get_applications() -> list[dict]:
    """List all applications, newest first. Excludes large text fields."""
    apps = list_applications()
    # Strip large text fields from list view — fetch individual app for full detail
    summary_fields = {"id", "company", "role", "status", "score", "recommendation",
                      "created_at", "applied_at", "updated_at", "jd_url"}
    return [{k: v for k, v in a.items() if k in summary_fields} for a in apps]


@app.get("/applications/{app_id}")
def get_application_detail(app_id: str) -> dict:
    """Get full application detail including pipeline outputs and rounds."""
    application = get_application(app_id)
    if not application:
        raise HTTPException(status_code=404, detail=f"Application '{app_id}' not found")
    application["rounds"] = get_rounds(app_id)
    return application


@app.patch("/applications/{app_id}")
def patch_application(app_id: str, body: ApplicationUpdate) -> dict:
    """Update status, applied_at, role, or jd_url on an application."""
    if not get_application(app_id):
        raise HTTPException(status_code=404, detail=f"Application '{app_id}' not found")

    valid_statuses = {"cv_ready", "applied", "screening", "interview", "offer", "rejected"}
    if body.status and body.status not in valid_statuses:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{body.status}'. Valid: {', '.join(sorted(valid_statuses))}",
        )

    updates = {k: v for k, v in body.dict().items() if v is not None}
    if updates:
        update_application(app_id, **updates)
    return get_application(app_id)


# ── Round routes ──────────────────────────────────────────────

@app.post("/applications/{app_id}/rounds", status_code=201)
def post_round(app_id: str, body: RoundCreate) -> dict:
    """Add a new interview round to an application."""
    if not get_application(app_id):
        raise HTTPException(status_code=404, detail=f"Application '{app_id}' not found")

    valid_types = {"hr", "hiring_manager", "case_study", "panel", "other"}
    if body.type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid type '{body.type}'. Valid: {', '.join(sorted(valid_types))}",
        )

    extra = {}
    if body.scheduled_at:
        extra["scheduled_at"] = body.scheduled_at
    if body.notes:
        extra["notes"] = body.notes

    round_id = create_round(app_id, body.type, **extra)
    return {"id": round_id, "application_id": app_id, "type": body.type, "status": "scheduled"}


@app.patch("/applications/{app_id}/rounds/{round_id}")
def patch_round(app_id: str, round_id: str, body: RoundUpdate) -> dict:
    """Update a round — add prep content, transcript, status, etc."""
    rounds = get_rounds(app_id)
    if not any(r["id"] == round_id for r in rounds):
        raise HTTPException(status_code=404, detail=f"Round '{round_id}' not found")

    updates = {k: v for k, v in body.dict().items() if v is not None}
    if updates:
        update_round(round_id, **updates)

    return next(r for r in get_rounds(app_id) if r["id"] == round_id)
