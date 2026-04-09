"""Checkpointing — save and resume pipeline state between steps.

Saves state to checkpoints/<run_id>.json after each step completes.
On resume, skips completed steps and continues from where it left off.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

CHECKPOINTS_DIR = Path(__file__).parent / "checkpoints"


def generate_run_id() -> str:
    """Generate a new run ID based on current timestamp."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def save_checkpoint(run_id: str, state: dict, completed_steps: list[str], completed_gates: list[str] = None):
    """Save pipeline state after a step completes.

    Args:
        run_id: Unique identifier for this run.
        state: Full pipeline state dict.
        completed_steps: List of step names that have completed.
        completed_gates: List of gate names that have been passed (e.g. ["gate_1"]).
    """
    CHECKPOINTS_DIR.mkdir(exist_ok=True)
    data = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "completed_steps": completed_steps,
        "completed_gates": completed_gates or [],
        "state": state,
    }
    path = CHECKPOINTS_DIR / f"{run_id}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Dual-write to DB — best-effort, never crashes the pipeline
    try:
        import db
        conn = db.get_db(db.DB_PATH)
        db.create_tables(conn)
        db.upsert_application(run_id, state, created_at=data["timestamp"], conn=conn)
        conn.close()
    except Exception as e:
        import sys
        print(f"  [db] Warning: could not write to database: {e}", file=sys.stderr)

    return path


def load_checkpoint(run_id: str) -> Optional[dict]:
    """Load a checkpoint by run ID. Returns None if not found."""
    path = CHECKPOINTS_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_checkpoints() -> list[dict]:
    """List all available checkpoints, newest first."""
    if not CHECKPOINTS_DIR.exists():
        return []
    checkpoints = []
    for path in sorted(CHECKPOINTS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            checkpoints.append({
                "run_id": data["run_id"],
                "timestamp": data["timestamp"],
                "completed_steps": data["completed_steps"],
                "completed_gates": data.get("completed_gates", []),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return checkpoints


def get_latest_checkpoint() -> Optional[dict]:
    """Get the most recent checkpoint. Returns None if none exist."""
    checkpoints = list_checkpoints()
    return checkpoints[0] if checkpoints else None


def is_step_completed(checkpoint: dict, step_name: str) -> bool:
    """Check if a step was already completed in a checkpoint."""
    return step_name in checkpoint.get("completed_steps", [])


def is_gate_completed(checkpoint: dict, gate_name: str) -> bool:
    """Check if a gate was already passed in a checkpoint."""
    return gate_name in checkpoint.get("completed_gates", [])


def delete_checkpoint(run_id: str) -> bool:
    """Delete a checkpoint file. Returns True if deleted."""
    path = CHECKPOINTS_DIR / f"{run_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False
