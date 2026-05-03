#!/usr/bin/env python3
"""Delete resolved-market data from analytics.db (Phase 5 prune, step 2).

Defaults to --dry-run. Requires --execute to delete.
--execute refuses to run unless a same-day snapshot from snapshot_resolved_40d.py exists.

7-step deletion in dependency order (single transaction):
  trades → positions → signals → market_entities → token_catalog → gamma_events → markets

VACUUM runs in a separate connection after commit.
"""

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "analytics.db"
AUDIT_ROOT = Path(__file__).parent.parent / "data" / "audit"
LOCK_PATH = Path(__file__).parent.parent / "data" / ".pipeline.lock"

TARGET_SUBQ = (
    "SELECT condition_id FROM markets "
    "WHERE resolved = 1 AND end_date < datetime('now', '-40 days')"
)

# Deletion order: children before parents, subqueries against markets before markets DELETE.
STEPS = [
    ("trades",          "market_id"),
    ("positions",       "market_id"),
    ("signals",         "market_id"),
    ("market_entities", "condition_id"),
    ("token_catalog",   "condition_id"),
    ("gamma_events",    "condition_id"),
    ("markets",         None),           # last — uses inline filter, not subquery
]

MARKETS_FILTER = "resolved = 1 AND end_date < datetime('now', '-40 days')"


def todays_snapshot_dir() -> Path | None:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    matches = sorted(AUDIT_ROOT.glob(f"resolved_40d_snapshot_{today}T*"))
    return matches[-1] if matches else None


def count_targets(db: sqlite3.Connection) -> dict[str, int]:
    result = {}
    for table, col in STEPS:
        if col is None:
            result[table] = db.execute(
                f"SELECT COUNT(*) FROM markets WHERE {MARKETS_FILTER}"
            ).fetchone()[0]
        else:
            result[table] = db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} IN ({TARGET_SUBQ})"
            ).fetchone()[0]
    return result


def count_totals(db: sqlite3.Connection) -> dict[str, int]:
    return {
        table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table, _ in STEPS
    }


def print_counts(label: str, counts: dict) -> None:
    print(f"\n  {label}:")
    for table, _ in STEPS:
        print(f"    {table:<20} {counts.get(table, 0):>12,}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="Actually delete (default is dry-run)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: db not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    if LOCK_PATH.exists():
        print(f"ERROR: pipeline lock at {LOCK_PATH} — pipeline may be running.", file=sys.stderr)
        print("  Wait for it to clear or remove manually if stale.", file=sys.stderr)
        sys.exit(1)

    if args.execute:
        snap = todays_snapshot_dir()
        if snap is None:
            print("ERROR: --execute requires a same-day snapshot.", file=sys.stderr)
            print("  Run: .venv/bin/python scripts/snapshot_resolved_40d.py", file=sys.stderr)
            sys.exit(1)
        print(f"Snapshot found: {snap.name}")

    db = sqlite3.connect(str(DB_PATH))
    try:
        targets = count_targets(db)
        before = count_totals(db)

        print("=" * 72)
        print(f"RESOLVED-40D PRUNE — {'EXECUTE' if args.execute else 'DRY RUN'}")
        print("=" * 72)
        print_counts("BEFORE (totals)", before)
        print_counts("TO DELETE", targets)

        if not args.execute:
            print("\nDry-run only. Re-run with --execute to delete.")
            return

        print("\nExecuting 7-step transaction...")
        t0 = time.time()
        deleted: dict[str, int] = {}
        try:
            with db:
                for table, col in STEPS:
                    if col is None:
                        sql = f"DELETE FROM markets WHERE {MARKETS_FILTER}"
                    else:
                        sql = f"DELETE FROM {table} WHERE {col} IN ({TARGET_SUBQ})"
                    deleted[table] = db.execute(sql).rowcount
                    print(f"  {table:<20} {deleted[table]:>10,} rows deleted")
        except Exception as e:
            print(f"\nFAILED — transaction rolled back: {type(e).__name__}: {e}", file=sys.stderr)
            sys.exit(1)

        after = count_totals(db)
        print_counts("AFTER (totals)", after)

        all_ok = True
        for table, _ in STEPS:
            expected = before[table] - deleted[table]
            if after[table] != expected:
                print(
                    f"  MISMATCH {table}: expected {expected:,}, got {after[table]:,}",
                    file=sys.stderr,
                )
                all_ok = False
        if not all_ok:
            print("Row-count assertions FAILED — investigate before proceeding.", file=sys.stderr)
            sys.exit(1)

        elapsed_tx = round(time.time() - t0, 1)
        print(f"\nRow-count math checks out ✓  ({elapsed_tx}s)")
        print("Running VACUUM (may take several minutes on a large DB)...")

    finally:
        db.close()

    t_vac = time.time()
    vac_db = sqlite3.connect(str(DB_PATH))
    try:
        vac_db.execute("VACUUM")
    finally:
        vac_db.close()

    elapsed_vac = round(time.time() - t_vac, 1)
    size_after = DB_PATH.stat().st_size
    print(f"VACUUM complete ✓  ({elapsed_vac}s)")
    print(f"DB size after VACUUM: {size_after / 1024**3:.2f} GB")
    print("\nRun scripts/verify_prune_resolved_40d.py to assert post-deletion invariants.")


if __name__ == "__main__":
    main()
