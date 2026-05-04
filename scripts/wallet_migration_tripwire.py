#!/usr/bin/env python3
"""Wallet-migration tripwire: detect Q5 traders who appear to have stopped trading.

Polymarket's deposit-wallet migration (docs.polymarket.com/trading/deposit-wallet-migration)
moves new users to ERC-1967 proxy wallets. Phase 1 is new-users-only — existing
users keep their Safes. But existing users may voluntarily opt into the new
model, which would split their on-chain history across two addresses. The
old address goes silent; a new address starts trading the same markets.

This script flags Q5 traders (composite_score >= Q5_COMPOSITE_THRESHOLD on
the latest lift_scores computation) who:
    - Had >= MIN_PRIOR_TRADES in the [30d, 8d] ago window, AND
    - Had ZERO trades in the last 7 days.

Output is informational. Treat a sudden surge in dropouts as evidence the
migration is reaching existing users, not silently as a code change.

Run: scripts/wallet_migration_tripwire.py
Defaults to data/analytics.db. Override with --db-path.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

DB_DEFAULT = Path(__file__).parent.parent / "data" / "analytics.db"
Q5_THRESHOLD = -0.10
MIN_PRIOR_TRADES = 5  # at least N trades in the prior 23-day window to count as "active"


def find_silent_q5(db: sqlite3.Connection) -> list[tuple]:
    return db.execute(
        f"""
        WITH q5 AS (
            SELECT trader_address, composite_score
            FROM lift_scores
            WHERE composite_score >= {Q5_THRESHOLD}
              AND computed_at = (SELECT MAX(computed_at) FROM lift_scores)
        ),
        prior_active AS (
            SELECT trader_address, COUNT(*) AS n_prior
            FROM trades
            WHERE timestamp >= datetime('now','-30 days')
              AND timestamp <  datetime('now','-7 days')
            GROUP BY trader_address
            HAVING n_prior >= {MIN_PRIOR_TRADES}
        ),
        recent_active AS (
            SELECT DISTINCT trader_address
            FROM trades
            WHERE timestamp >= datetime('now','-7 days')
        )
        SELECT q5.trader_address, q5.composite_score, prior_active.n_prior
        FROM q5
        JOIN prior_active USING (trader_address)
        LEFT JOIN recent_active USING (trader_address)
        WHERE recent_active.trader_address IS NULL
        ORDER BY q5.composite_score DESC
        """
    ).fetchall()


def total_q5_count(db: sqlite3.Connection) -> int:
    return db.execute(
        f"""
        SELECT COUNT(*) FROM lift_scores
        WHERE composite_score >= {Q5_THRESHOLD}
          AND computed_at = (SELECT MAX(computed_at) FROM lift_scores)
        """
    ).fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db-path", default=str(DB_DEFAULT))
    ap.add_argument("--quiet", action="store_true", help="No output if dropout count is unremarkable")
    args = ap.parse_args()

    db = sqlite3.connect(args.db_path)
    silent = find_silent_q5(db)
    total = total_q5_count(db)
    db.close()

    pct = (100.0 * len(silent) / total) if total else 0.0
    # Background rate is ~30% of Q5 quiet on any given week (tournament gaps, etc).
    # Flag if it spikes well above that.
    alarm = pct > 50.0

    if args.quiet and not alarm:
        return 0

    print(f"Q5 traders total:        {total}")
    print(f"Q5 silent in last 7d:    {len(silent)} ({pct:.1f}%)")
    print(f"Threshold for ALARM:     >50% (current: {'ALARM' if alarm else 'normal'})")
    print()
    if silent:
        print("Top 20 silent Q5 (by composite_score) — candidates for wallet migration:")
        for addr, score, n_prior in silent[:20]:
            print(f"  {addr}  score={score:+.3f}  prior_30d_trades={n_prior}")
        if len(silent) > 20:
            print(f"  ... and {len(silent)-20} more")
    return 1 if alarm else 0


if __name__ == "__main__":
    sys.exit(main())
