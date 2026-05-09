#!/usr/bin/env python3
"""Q5 panel tripwire monitor (Tier 2 monitoring).

Reads the current Q5 panel state from analytics.db and fires alerts if any
of the three sentinel tripwires are crossed:

  1. panel_size < 150      (floor of acceptable contraction; deploy=335, current=205)
  2. survival_rate < 0.25  (within quintile-5 pool; deploy=38%, current=32%)
  3. day_over_day_delta > 0.20  (sudden churn — Δ in panel size vs prior run)

Writes each firing to analytics.db.tripwire_log (created on first run).
Idempotent: multiple runs on the same day each write their own row.
Cron-friendly: exits 0 on clean, exits 1 if any tripwire fired.

Usage:
    python3 scripts/q5_panel_tripwire.py [--db-path PATH] [--niche esports]
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

NICHE_DEFAULT = "esports"
DB_DEFAULT = Path(__file__).parent.parent / "data" / "analytics.db"

# Composite score floor (must stay in sync with scoring/thresholds.py)
Q5_COMPOSITE_THRESHOLD = -0.10

# Baseline at 2026-04-19 deploy (post-floor panel)
BASELINE_PANEL_SIZE = 335
BASELINE_SURVIVAL_RATE = 0.38  # 335 / 882

# Tripwire thresholds
TRIPWIRE_PANEL_FLOOR = 150       # panel_size below this
TRIPWIRE_SURVIVAL_FLOOR = 0.25   # survival_rate below this
TRIPWIRE_DOD_DELTA = 0.20        # day-over-day panel_size change above this

CREATE_TRIPWIRE_LOG = """
CREATE TABLE IF NOT EXISTS tripwire_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fired_at TIMESTAMP NOT NULL DEFAULT (datetime('now')),
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    threshold REAL NOT NULL,
    direction TEXT NOT NULL
)
"""


def _current_panel(conn: sqlite3.Connection, niche: str) -> tuple[int, int]:
    """Return (panel_size, total_q5) for the most recent scoring run."""
    row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN composite_score >= :floor THEN 1 ELSE 0 END),
            COUNT(*)
        FROM lift_scores
        WHERE quintile = 5
          AND category = :niche
          AND computed_at = (
              SELECT MAX(computed_at) FROM lift_scores WHERE category = :niche
          )
        """,
        {"floor": Q5_COMPOSITE_THRESHOLD, "niche": niche},
    ).fetchone()
    panel = row[0] or 0
    total = row[1] or 0
    return panel, total


def _prior_panel_from_log(conn: sqlite3.Connection) -> int | None:
    """Return the panel_size recorded in the most recent prior tripwire_log entry."""
    row = conn.execute(
        """
        SELECT value FROM tripwire_log
        WHERE metric = 'panel_size'
        ORDER BY fired_at DESC LIMIT 1
        """
    ).fetchone()
    return int(row[0]) if row else None


def _fire(conn: sqlite3.Connection, metric: str, value: float, threshold: float, direction: str) -> None:
    fired_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO tripwire_log (fired_at, metric, value, threshold, direction) VALUES (?,?,?,?,?)",
        (fired_at, metric, value, threshold, direction),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DB_DEFAULT)
    parser.add_argument("--niche", default=NICHE_DEFAULT)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    conn.execute(CREATE_TRIPWIRE_LOG)

    panel, total = _current_panel(conn, args.niche)
    survival = (panel / total) if total > 0 else 0.0

    fired: list[str] = []

    # Tripwire 1: panel size floor
    if panel < TRIPWIRE_PANEL_FLOOR:
        _fire(conn, "panel_size", panel, TRIPWIRE_PANEL_FLOOR, "below")
        fired.append(f"PANEL_SIZE={panel} < {TRIPWIRE_PANEL_FLOOR}")

    # Tripwire 2: survival rate floor
    if survival < TRIPWIRE_SURVIVAL_FLOOR:
        _fire(conn, "survival_rate", survival, TRIPWIRE_SURVIVAL_FLOOR, "below")
        fired.append(f"SURVIVAL={survival:.1%} < {TRIPWIRE_SURVIVAL_FLOOR:.0%}")

    # Tripwire 3: day-over-day delta (skip if no prior log entry)
    prior = _prior_panel_from_log(conn)
    if prior is not None and prior > 0:
        dod = abs(panel - prior) / prior
        if dod > TRIPWIRE_DOD_DELTA:
            _fire(conn, "day_over_day_delta", dod, TRIPWIRE_DOD_DELTA, "above")
            fired.append(f"DOD_DELTA={dod:.1%} > {TRIPWIRE_DOD_DELTA:.0%} (prior={prior})")

    # Always log current panel_size so the next run can compute day-over-day
    _fire(conn, "panel_size", panel, TRIPWIRE_PANEL_FLOOR, "snapshot")

    conn.commit()
    conn.close()

    if fired:
        print(f"[q5-tripwire] ALERT — {len(fired)} tripwire(s) fired:")
        for msg in fired:
            print(f"  ✗ {msg}")
        raise SystemExit(1)
    else:
        print(
            f"[q5-tripwire] clean — panel {panel} / total_q5 {total} / "
            f"survival {survival:.1%} "
            f"(baseline {BASELINE_PANEL_SIZE} / {BASELINE_SURVIVAL_RATE:.0%})"
        )


if __name__ == "__main__":
    main()
