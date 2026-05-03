#!/usr/bin/env python3
"""One-shot prune of bot/MM trader rows from analytics.db.

Removes the ~110 traders matching the bias-conservative bot signature:
  trades > BOT_TRADE_FLOOR
    AND (trades / positions) > BOT_TPR_THRESHOLD
    AND trader NOT IN Q5 panel (composite_score >= -0.10)

Q5 whitelist guarantees zero scored signal traders are touched. Verified by
asserting the Q5 panel SHA256 hash is identical before and after.

Defaults to --dry-run. Requires --execute to delete. Optionally VACUUMs at
the end with --vacuum.

Use case: 1.58M trade rows (~21% of trades table) recovered in one shot.
Stops new bot trades from accumulating: the same filter is applied at
backfill ingest in src/polymarket_analytics/commands/backfill.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from polymarket_analytics.scoring.thresholds import (
    BOT_TPR_THRESHOLD,
    BOT_TRADE_FLOOR,
    Q5_COMPOSITE_THRESHOLD,
)

DB_PATH = REPO / "data" / "analytics.db"
AUDIT_ROOT = REPO / "data" / "audit"
LOCK_PATH = REPO / "data" / ".pipeline.lock"

BOT_SUBQUERY = f"""
    SELECT tt.trader_address
    FROM (SELECT trader_address, COUNT(*) AS n_trades FROM trades GROUP BY trader_address) tt
    JOIN (SELECT trader_address, COUNT(*) AS n_positions FROM positions GROUP BY trader_address) tp
      ON tp.trader_address = tt.trader_address
    LEFT JOIN (
      SELECT trader_address FROM lift_scores
      WHERE composite_score >= {Q5_COMPOSITE_THRESHOLD}
        AND computed_at = (SELECT MAX(computed_at) FROM lift_scores)
    ) q ON q.trader_address = tt.trader_address
    WHERE tt.n_trades > {BOT_TRADE_FLOOR}
      AND tp.n_positions > 0
      AND (1.0 * tt.n_trades / tp.n_positions) > {BOT_TPR_THRESHOLD}
      AND q.trader_address IS NULL
"""

# Deletion order: child tables first, traders last (FK chain).
DELETE_TABLES = [
    ("trades",      "trader_address"),
    ("positions",   "trader_address"),
    ("lift_scores", "trader_address"),
    ("traders",     "address"),
]


def q5_panel_hash(db: sqlite3.Connection) -> tuple[int, str]:
    """SHA256 of the sorted Q5 panel addresses + composite scores.

    Whitelist invariant: hash MUST be identical before and after the prune.
    Any drift means a Q5 trader was incorrectly excluded — bug in BOT_SUBQUERY.
    """
    rows = db.execute(f"""
        SELECT trader_address, ROUND(composite_score, 6)
        FROM lift_scores
        WHERE composite_score >= {Q5_COMPOSITE_THRESHOLD}
          AND computed_at = (SELECT MAX(computed_at) FROM lift_scores)
        ORDER BY trader_address
    """).fetchall()
    if not rows:
        return 0, "empty"
    payload = "\n".join(f"{a}|{s}" for a, s in rows).encode()
    return len(rows), hashlib.sha256(payload).hexdigest()[:16]


def snapshot_state(db: sqlite3.Connection) -> dict:
    """Capture pre/post invariants for verification."""
    n_q5, h_q5 = q5_panel_hash(db)
    return {
        "trades":      db.execute("SELECT COUNT(*) FROM trades").fetchone()[0],
        "positions":   db.execute("SELECT COUNT(*) FROM positions").fetchone()[0],
        "lift_scores": db.execute("SELECT COUNT(*) FROM lift_scores").fetchone()[0],
        "traders":     db.execute("SELECT COUNT(*) FROM traders").fetchone()[0],
        "q5_panel_size": n_q5,
        "q5_panel_hash": h_q5,
        "db_bytes":      DB_PATH.stat().st_size,
    }


def print_state(label: str, s: dict) -> None:
    print(f"\n  {label}:")
    print(f"    trades              {s['trades']:>14,}")
    print(f"    positions           {s['positions']:>14,}")
    print(f"    lift_scores         {s['lift_scores']:>14,}")
    print(f"    traders             {s['traders']:>14,}")
    print(f"    q5_panel_size       {s['q5_panel_size']:>14,}")
    print(f"    q5_panel_hash       {s['q5_panel_hash']:>14}")
    print(f"    db_size_GB          {s['db_bytes'] / 1024**3:>14.2f}")


def count_targets(db: sqlite3.Connection, bot_addrs: list[str]) -> dict[str, int]:
    if not bot_addrs:
        return {t: 0 for t, _ in DELETE_TABLES}
    placeholders = ",".join("?" * len(bot_addrs))
    return {
        table: db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col} IN ({placeholders})",
            bot_addrs,
        ).fetchone()[0]
        for table, col in DELETE_TABLES
    }


def write_snapshot(snap_dir: Path, bot_addrs: list[str], pre: dict, targets: dict) -> None:
    snap_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / "bot_addresses.txt").write_text("\n".join(bot_addrs) + "\n")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "thresholds": {
            "BOT_TRADE_FLOOR": BOT_TRADE_FLOOR,
            "BOT_TPR_THRESHOLD": BOT_TPR_THRESHOLD,
            "Q5_COMPOSITE_THRESHOLD": Q5_COMPOSITE_THRESHOLD,
        },
        "bot_count": len(bot_addrs),
        "pre_state": pre,
        "targets": targets,
    }
    (snap_dir / "snapshot.json").write_text(json.dumps(payload, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="Actually delete (default is dry-run)")
    parser.add_argument("--vacuum", action="store_true",
                        help="Run VACUUM after delete (slow on large DB)")
    parser.add_argument("--limit-sample", type=int, default=15,
                        help="Print this many top bots in dry-run summary")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: db not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    if args.execute and LOCK_PATH.exists():
        print(f"ERROR: pipeline lock at {LOCK_PATH} — pipeline may be running.",
              file=sys.stderr)
        print("  Stop monitor + cron, then retry.", file=sys.stderr)
        sys.exit(1)

    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA foreign_keys = OFF")  # bulk delete, no FK churn

    try:
        # 1. Compute target bot set
        bot_addrs = [r[0] for r in db.execute(BOT_SUBQUERY).fetchall()]
        if not bot_addrs:
            print("No traders match the bot signature — nothing to do.")
            return

        # 2. Pre-state snapshot
        pre = snapshot_state(db)
        targets = count_targets(db, bot_addrs)

        print("=" * 72)
        print(f"BOT/MM PRUNE — {'EXECUTE' if args.execute else 'DRY RUN'}")
        print("=" * 72)
        print(f"\nFilter: trades > {BOT_TRADE_FLOOR} AND tpr > {BOT_TPR_THRESHOLD} "
              f"AND NOT in Q5 (composite >= {Q5_COMPOSITE_THRESHOLD})")
        print(f"Matched: {len(bot_addrs):,} bot/MM addresses")

        # Show top N bots by trade volume so the user can sanity-check
        sample = db.execute(f"""
            SELECT t.trader_address, COUNT(*) AS nt,
                   COALESCE((SELECT COUNT(*) FROM positions WHERE trader_address=t.trader_address), 0) AS np
            FROM trades t
            WHERE t.trader_address IN ({BOT_SUBQUERY})
            GROUP BY t.trader_address
            ORDER BY nt DESC
            LIMIT ?
        """, [args.limit_sample]).fetchall()
        print(f"\n  Top {args.limit_sample} by trade count:")
        for addr, nt, np_ in sample:
            tpr = nt / np_ if np_ else 0
            print(f"    {addr[:10]}  trades={nt:>7,}  positions={np_:>5}  tpr={tpr:>6.1f}")

        print_state("BEFORE (totals)", pre)
        print(f"\n  TO DELETE:")
        for table, _ in DELETE_TABLES:
            print(f"    {table:<20} {targets[table]:>14,}")

        if not args.execute:
            print("\nDry-run only. Re-run with --execute to delete.")
            return

        # 3. Snapshot to disk for audit
        snap_dir = AUDIT_ROOT / f"bot_prune_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        write_snapshot(snap_dir, bot_addrs, pre, targets)
        print(f"\n  Snapshot written to {snap_dir.relative_to(REPO)}")

        # 4. Execute deletes inside a single transaction
        print("\nExecuting 4-step transaction...")
        t0 = time.time()
        placeholders = ",".join("?" * len(bot_addrs))
        deleted: dict[str, int] = {}
        try:
            with db:
                for table, col in DELETE_TABLES:
                    sql = f"DELETE FROM {table} WHERE {col} IN ({placeholders})"
                    deleted[table] = db.execute(sql, bot_addrs).rowcount
                    print(f"  {table:<20} {deleted[table]:>14,} rows deleted")
        except Exception as e:
            print(f"\nFAILED — transaction rolled back: {type(e).__name__}: {e}",
                  file=sys.stderr)
            sys.exit(1)

        elapsed_tx = round(time.time() - t0, 1)
        print(f"\nDelete transaction complete ✓  ({elapsed_tx}s)")

        # 5. Post-state + invariants
        post = snapshot_state(db)
        print_state("AFTER (totals)", post)

        # Row-count math
        ok = True
        for table, _ in DELETE_TABLES:
            expected = pre[table] - deleted[table]
            if post[table] != expected:
                print(f"  MISMATCH {table}: expected {expected:,}, got {post[table]:,}",
                      file=sys.stderr)
                ok = False

        # Q5 invariant (the load-bearing assertion)
        if pre["q5_panel_hash"] != post["q5_panel_hash"]:
            print(f"\n!!! Q5 PANEL HASH DRIFT !!!", file=sys.stderr)
            print(f"  pre:  size={pre['q5_panel_size']}  hash={pre['q5_panel_hash']}",
                  file=sys.stderr)
            print(f"  post: size={post['q5_panel_size']}  hash={post['q5_panel_hash']}",
                  file=sys.stderr)
            print(f"  A scored signal trader was incorrectly excluded.", file=sys.stderr)
            ok = False
        else:
            print(f"\n  Q5 panel invariant ✓  (size={post['q5_panel_size']}, "
                  f"hash={post['q5_panel_hash']})")

        # Residual check — confirm no rows for bot addresses survived
        residual = sum(
            db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} IN ({placeholders})",
                bot_addrs,
            ).fetchone()[0]
            for table, col in DELETE_TABLES
        )
        if residual > 0:
            print(f"  RESIDUAL: {residual} rows still reference bot addresses",
                  file=sys.stderr)
            ok = False
        else:
            print(f"  Residual check ✓  (zero rows reference bot addresses)")

        if not ok:
            print("\nVerification FAILED — investigate before proceeding.", file=sys.stderr)
            sys.exit(1)

    finally:
        db.close()

    if args.vacuum:
        print("\nRunning VACUUM (may take several minutes on a large DB)...")
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
    else:
        print("\nSkipping VACUUM. Re-run with --vacuum to reclaim disk space, or "
              "let the next midnight cron handle it via wal-truncate.")


if __name__ == "__main__":
    main()
