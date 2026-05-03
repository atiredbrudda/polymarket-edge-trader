#!/usr/bin/env python3
"""Snapshot resolved-market data before deletion (Phase 5 prune, step 1).

Exports to data/audit/resolved_40d_snapshot_<UTC-timestamp>/:
  - targets.csv   — condition_ids that will be deleted
  - summary.json  — per-table counts, pre-flight check outputs, DB size, wall clock

Required by prune_resolved_40d.py --execute.
"""

import csv
import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "analytics.db"
AUDIT_ROOT = Path(__file__).parent.parent / "data" / "audit"

TARGET_SUBQ = (
    "SELECT condition_id FROM markets "
    "WHERE resolved = 1 AND end_date < datetime('now', '-40 days')"
)

TABLES = [
    ("trades",          "market_id"),
    ("positions",       "market_id"),
    ("signals",         "market_id"),
    ("market_entities", "condition_id"),
    ("token_catalog",   "condition_id"),
    ("gamma_events",    "condition_id"),
    ("markets",         "condition_id"),
]


def preflight(db: sqlite3.Connection) -> dict:
    panel_size = db.execute("SELECT COUNT(*) FROM q5_traders").fetchone()[0]
    traders = [
        row[0]
        for row in db.execute(
            "SELECT trader_address FROM q5_traders ORDER BY trader_address"
        ).fetchall()
    ]
    panel_hash = hashlib.sha256("\n".join(traders).encode()).hexdigest()
    top10 = [
        round(row[0], 6)
        for row in db.execute(
            "SELECT composite_score FROM q5_traders ORDER BY composite_score DESC LIMIT 10"
        ).fetchall()
    ]
    signal_count = db.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    return {
        "q5_panel_size": panel_size,
        "q5_panel_hash_sha256": panel_hash,
        "q5_top10_scores": top10,
        "signal_count": signal_count,
    }


def main() -> None:
    if not DB_PATH.exists():
        print(f"ERROR: db not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    t0 = time.time()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = AUDIT_ROOT / f"resolved_40d_snapshot_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(str(DB_PATH))
    try:
        target_ids = [row[0] for row in db.execute(TARGET_SUBQ).fetchall()]
        print(f"Target markets: {len(target_ids):,}")

        with (out_dir / "targets.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["condition_id"])
            w.writerows([[cid] for cid in target_ids])

        target_counts: dict[str, int] = {}
        total_counts: dict[str, int] = {}
        for table, col in TABLES:
            if table == "markets":
                target_counts[table] = len(target_ids)
            else:
                target_counts[table] = db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {col} IN ({TARGET_SUBQ})"
                ).fetchone()[0]
            total_counts[table] = db.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]

        pf = preflight(db)
        db_size = DB_PATH.stat().st_size

        summary = {
            "snapshot_at_utc": datetime.now(timezone.utc).isoformat(),
            "wall_clock_s": round(time.time() - t0, 1),
            "db_path": str(DB_PATH),
            "db_size_bytes": db_size,
            "db_size_gb": round(db_size / 1024**3, 2),
            "target_market_count": len(target_ids),
            "target_counts": target_counts,
            "total_counts": total_counts,
            "preflight": pf,
        }
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    finally:
        db.close()

    elapsed = round(time.time() - t0, 1)
    print(f"Snapshot written to {out_dir}")
    print(f"  targets.csv: {len(target_ids):,} condition_ids")
    print(f"  DB size: {db_size / 1024**3:.2f} GB")
    print(f"  Target counts by table:")
    for table, _ in TABLES:
        n = target_counts[table]
        tot = total_counts[table]
        pct = 100 * n / tot if tot else 0
        print(f"    {table:<20} {n:>10,} / {tot:>10,}  ({pct:.1f}%)")
    print(f"  Pre-flight: Q5 panel={pf['q5_panel_size']}, signals={pf['signal_count']}")
    print(f"  Elapsed: {elapsed}s")
    print(f"\nDated marker for prune --execute: {out_dir.name}")


if __name__ == "__main__":
    main()
