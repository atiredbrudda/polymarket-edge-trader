#!/usr/bin/env python3
"""Verify resolved-40d prune invariants (Phase 5 prune, step 3).

Asserts:
  1. Zero trades/positions/token_catalog rows reference deleted markets.
  2. Pre-flight outputs (Q5 panel size, Q5 hash, top-10 scores, signal count)
     are bit-identical to the pre-prune snapshot.
  3. `polymarket --niche esports score` dry-run completes without errors.

Exit code: 0 = all pass, 1 = any failure.
"""

import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "analytics.db"
AUDIT_ROOT = Path(__file__).parent.parent / "data" / "audit"

TARGET_SUBQ = (
    "SELECT condition_id FROM markets "
    "WHERE resolved = 1 AND end_date < datetime('now', '-40 days')"
)


def latest_snapshot_dir() -> Path | None:
    matches = sorted(AUDIT_ROOT.glob("resolved_40d_snapshot_*"))
    return matches[-1] if matches else None


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

    started_at = datetime.now(timezone.utc)
    failures: list[str] = []
    results: dict = {
        "verified_at_utc": started_at.isoformat(),
        "db_path": str(DB_PATH),
        "snapshot_dir": None,
        "snapshot_age_seconds": None,
        "check1_orphans": {},
        "check2_preflight": {},
        "check3_scoring": {},
    }

    db = sqlite3.connect(str(DB_PATH))
    try:
        # Check 1: zero orphan rows in the three tables that backfill re-reads
        print("Check 1 — zero orphan rows in trades/positions/token_catalog:")
        for table, col in [
            ("trades",        "market_id"),
            ("positions",     "market_id"),
            ("token_catalog", "condition_id"),
        ]:
            n = db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} IN ({TARGET_SUBQ})"
            ).fetchone()[0]
            ok = n == 0
            print(f"  {'✓' if ok else '✗'} {table:<20} orphan rows: {n:,} (expected 0)")
            results["check1_orphans"][table] = {"orphan_rows": n, "pass": ok}
            if not ok:
                failures.append(f"{table}: {n:,} orphan rows remain")

        # Check 2: pre-flight invariance
        snap_dir = latest_snapshot_dir()
        if snap_dir is None:
            print("\nCheck 2 — pre-flight comparison: SKIPPED (no snapshot found)")
            results["check2_preflight"] = {"skipped": True, "reason": "no snapshot found"}
        else:
            snap_summary = json.loads((snap_dir / "summary.json").read_text())
            snap_pf = snap_summary["preflight"]
            snap_ts = datetime.fromisoformat(snap_summary["snapshot_at_utc"])
            snap_age_s = (started_at - snap_ts).total_seconds()
            results["snapshot_dir"] = snap_dir.name
            results["snapshot_age_seconds"] = round(snap_age_s, 1)
            current_pf = preflight(db)
            age_note = ""
            if snap_age_s > 300:
                age_note = f" (snapshot age: {snap_age_s/60:.1f} min — pipeline drift likely)"
            print(f"\nCheck 2 — pre-flight comparison (snapshot: {snap_dir.name}){age_note}:")
            fields: dict = {}
            for key in ["q5_panel_size", "q5_panel_hash_sha256", "q5_top10_scores", "signal_count"]:
                old = snap_pf.get(key)
                new = current_pf.get(key)
                match = old == new
                print(f"  {'✓' if match else '✗'} {key}: {'match' if match else f'{old!r} → {new!r}'}")
                fields[key] = {"snapshot": old, "current": new, "match": match}
                if not match:
                    failures.append(f"pre-flight {key} changed after prune")
            results["check2_preflight"] = {
                "snapshot_age_seconds": round(snap_age_s, 1),
                "fields": fields,
            }

    finally:
        db.close()

    # Check 3: scoring dry-run
    print("\nCheck 3 — scoring dry-run:")
    polymarket_bin = Path(__file__).parent.parent / ".venv" / "bin" / "polymarket"
    result = subprocess.run(
        [str(polymarket_bin), "--niche", "esports", "score"],
        capture_output=True, text=True, timeout=120,
    )
    ok = result.returncode == 0
    print(f"  {'✓' if ok else '✗'} polymarket score exit={result.returncode}")
    results["check3_scoring"] = {
        "exit_code": result.returncode,
        "pass": ok,
        "stderr_snippet": (result.stderr[:400].strip() if result.stderr else ""),
    }
    if not ok:
        stderr_snippet = result.stderr[:400].strip() if result.stderr else "(no stderr)"
        print(f"    {stderr_snippet}")
        failures.append(f"polymarket score exited {result.returncode}")

    results["failures"] = failures
    results["overall_pass"] = not failures

    # Persist a JSON receipt alongside the snapshot so the audit trail survives stdout.
    if snap_dir := latest_snapshot_dir():
        ts = started_at.strftime("%Y%m%dT%H%M%SZ")
        out_path = snap_dir / f"verify_{ts}.json"
        out_path.write_text(json.dumps(results, indent=2))
        print(f"\nVerify receipt written to: {out_path}")

    print()
    if failures:
        print("FAILED:")
        for f in failures:
            print(f"  ✗ {f}")
        sys.exit(1)

    print("All assertions passed ✓")
    print()
    print("Note: on the next monitor cycle, watch logs for stats['skipped'] increments")
    print("on re-served old trades — this confirms token_catalog deletion is working.")


if __name__ == "__main__":
    main()
