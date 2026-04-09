#!/usr/bin/env python3
"""One-time migration: import all existing checkpoint files into applications.db.

Safe to run multiple times — uses ON CONFLICT DO UPDATE (idempotent).

Usage:
    python3 migrate.py
    python3 migrate.py --dry-run    # Print what would be imported, no writes
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from checkpoint import CHECKPOINTS_DIR, list_checkpoints, load_checkpoint
from db import create_tables, upsert_application, DB_PATH


def migrate(dry_run: bool = False) -> None:
    if dry_run:
        print("DRY RUN — no changes will be written.")
    else:
        create_tables()

    checkpoints = list_checkpoints()
    if not checkpoints:
        print("No checkpoints found in", CHECKPOINTS_DIR)
        return

    print(f"Found {len(checkpoints)} checkpoints in {CHECKPOINTS_DIR}")
    print(f"DB target: {DB_PATH}\n")

    ok = skipped = 0
    for meta in checkpoints:
        run_id = meta["run_id"]
        data = load_checkpoint(run_id)
        if not data:
            print(f"  SKIP  {run_id} — failed to load file")
            skipped += 1
            continue

        state = data.get("state", {})
        if not state.get("job_description"):
            print(f"  SKIP  {run_id} — no job_description in state")
            skipped += 1
            continue

        company = ""
        cr = state.get("company_research", "")
        m = re.search(r'Company:\s*\[?([A-Za-z0-9][^,\n\[\]]{1,40})', cr)
        if m:
            company = m.group(1).strip()

        status_line = f"  {'(dry) ' if dry_run else ''}OK    {run_id}  company={company or '(unknown)'}"
        print(status_line)

        if not dry_run:
            upsert_application(run_id, state, created_at=data.get("timestamp"))
        ok += 1

    print(f"\nResult: {ok} imported, {skipped} skipped.")
    if dry_run:
        print("(Dry run — nothing was written.)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate checkpoint files to SQLite DB")
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen without writing")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
