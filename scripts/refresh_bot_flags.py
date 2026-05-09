#!/usr/bin/env python3
"""
refresh_bot_flags.py — Materialize the bot/MM denylist into traders.is_bot.

Run after `score` in the cron pipeline. Two modes:

  --populate   First-run only: mark all current behavioral matches as is_bot=1,
               no rate limit. Run once after deploying materialization.

  (default)    Ongoing refresh: promote new matches, demote stale ones after
               3 consecutive non-matches. Rate-limited to 20 changes per run
               to catch buggy threshold changes early.

Usage:
  .venv/bin/python scripts/refresh_bot_flags.py [--db data/analytics.db] [--populate] [--dry-run]
"""
import sqlite3
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from polymarket_analytics.scoring.thresholds import (
    BOT_EXCLUSION_SQL,
    BOT_TRADE_FLOOR,
    BOT_TPR_THRESHOLD,
)

MAX_CHANGES_PER_RUN = 20
DEMOTE_STREAK_THRESHOLD = 3


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {r[1] for r in conn.execute("PRAGMA table_info(traders)").fetchall()}
    for col, defn in [
        ("is_bot",             "INTEGER DEFAULT 0"),
        ("bot_flagged_at",     "TEXT"),
        ("flag_trade_floor",   "INTEGER"),
        ("flag_tpr_threshold", "INTEGER"),
        ("bot_demote_streak",  "INTEGER DEFAULT 0"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE traders ADD COLUMN {col} {defn}")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_flag_log (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            address            TEXT,
            old_state          INTEGER,
            new_state          INTEGER,
            reason             TEXT,
            flag_trade_floor   INTEGER,
            flag_tpr_threshold INTEGER,
            changed_at         TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_traders_is_bot ON traders(is_bot)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bot_flag_log_addr ON bot_flag_log(address, changed_at)")
    conn.commit()


def _log_change(conn, address, old_state, new_state, reason, now):
    conn.execute(
        """INSERT INTO bot_flag_log
           (address, old_state, new_state, reason, flag_trade_floor, flag_tpr_threshold, changed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [address, old_state, new_state, reason, BOT_TRADE_FLOOR, BOT_TPR_THRESHOLD, now],
    )


def populate(conn: sqlite3.Connection, dry_run: bool) -> None:
    """Initial population: mark every current behavioral match as is_bot=1."""
    now = datetime.now(timezone.utc).isoformat()
    matches = frozenset(
        r[0].lower() for r in conn.execute(BOT_EXCLUSION_SQL).fetchall() if r[0]
    )
    already_flagged = frozenset(
        r[0].lower()
        for r in conn.execute(
            "SELECT address FROM traders WHERE COALESCE(is_bot,0)=1"
        ).fetchall()
    )
    to_flag = matches - already_flagged
    print(f"[bot-flags:populate] behavioral_matches={len(matches)}  already_flagged={len(already_flagged)}  to_flag={len(to_flag)}")
    if not dry_run:
        for addr in to_flag:
            conn.execute(
                """UPDATE traders
                   SET is_bot=1, bot_flagged_at=?, flag_trade_floor=?, flag_tpr_threshold=?, bot_demote_streak=0
                   WHERE LOWER(address)=?""",
                [now, BOT_TRADE_FLOOR, BOT_TPR_THRESHOLD, addr],
            )
            _log_change(conn, addr, 0, 1, "initial_populate", now)
        conn.commit()
        print(f"[bot-flags:populate] flagged {len(to_flag)} traders")
    else:
        print(f"[bot-flags:populate] (dry-run) would flag {len(to_flag)} traders")


def refresh(conn: sqlite3.Connection, dry_run: bool) -> None:
    """Ongoing refresh: promote new matches, demote stale ones."""
    now = datetime.now(timezone.utc).isoformat()

    current_bots = frozenset(
        r[0].lower() for r in conn.execute(BOT_EXCLUSION_SQL).fetchall() if r[0]
    )

    # Traders currently flagged or mid-demotion
    db_rows = {
        r[0].lower(): {"is_bot": r[1], "streak": r[2] or 0}
        for r in conn.execute(
            "SELECT address, is_bot, bot_demote_streak FROM traders "
            "WHERE COALESCE(is_bot,0)=1 OR COALESCE(bot_demote_streak,0)>0"
        ).fetchall()
    }

    promoted, demoted, streak_incr, streak_reset, prune_skipped = [], [], [], [], []

    # Trade counts for flagged traders — used to detect prune artifacts below.
    trade_counts = {
        r[0].lower(): r[1]
        for r in conn.execute(
            "SELECT trader_address, COUNT(*) FROM trades "
            "WHERE trader_address IN (SELECT address FROM traders WHERE COALESCE(is_bot,0)=1) "
            "GROUP BY trader_address"
        ).fetchall()
    }

    # Promote: matches filter but not yet flagged
    for r in conn.execute("SELECT address FROM traders WHERE COALESCE(is_bot,0)=0").fetchall():
        addr = (r[0] or "").lower()
        if addr in current_bots:
            promoted.append(addr)

    # Demotion tracking for currently-flagged traders
    for addr, row in db_rows.items():
        if row["is_bot"] == 1:
            if addr not in current_bots:
                n_trades = trade_counts.get(addr, 0)
                if n_trades < BOT_TRADE_FLOOR:
                    # Trade count below floor — likely a prune artifact, not a
                    # behavior change. Don't penalise the streak; keep flagged.
                    prune_skipped.append(addr)
                else:
                    new_streak = row["streak"] + 1
                    if new_streak >= DEMOTE_STREAK_THRESHOLD:
                        demoted.append(addr)
                    else:
                        streak_incr.append((addr, new_streak))
            elif row["streak"] > 0:
                streak_reset.append(addr)

    total_changes = len(promoted) + len(demoted)
    print(
        f"[bot-flags] current_bots={len(current_bots)}  "
        f"to_promote={len(promoted)}  to_demote={len(demoted)}  "
        f"streak_incr={len(streak_incr)}  streak_reset={len(streak_reset)}  "
        f"prune_skipped={len(prune_skipped)}"
    )

    if total_changes > MAX_CHANGES_PER_RUN:
        print(
            f"[bot-flags] RATE LIMIT: {total_changes} changes exceeds {MAX_CHANGES_PER_RUN} — aborting. "
            "Investigate threshold change before proceeding."
        )
        sys.exit(1)

    if dry_run:
        print("[bot-flags] (dry-run) no writes")
        return

    for addr in promoted:
        conn.execute(
            """UPDATE traders
               SET is_bot=1, bot_flagged_at=?, flag_trade_floor=?, flag_tpr_threshold=?, bot_demote_streak=0
               WHERE LOWER(address)=?""",
            [now, BOT_TRADE_FLOOR, BOT_TPR_THRESHOLD, addr],
        )
        _log_change(conn, addr, 0, 1, "behavioral_match", now)

    for addr in demoted:
        conn.execute(
            "UPDATE traders SET is_bot=0, bot_demote_streak=0 WHERE LOWER(address)=?",
            [addr],
        )
        _log_change(conn, addr, 1, 0, "demoted_after_3_non_matches", now)

    for addr, streak in streak_incr:
        conn.execute(
            "UPDATE traders SET bot_demote_streak=? WHERE LOWER(address)=?",
            [streak, addr],
        )

    for addr in streak_reset:
        conn.execute(
            "UPDATE traders SET bot_demote_streak=0 WHERE LOWER(address)=?",
            [addr],
        )

    # Reset any prior streak accumulated before this guard was added.
    for addr in prune_skipped:
        conn.execute(
            "UPDATE traders SET bot_demote_streak=0 WHERE LOWER(address)=?",
            [addr],
        )

    conn.commit()
    print(f"[bot-flags] done — promoted={len(promoted)}  demoted={len(demoted)}")


def main():
    parser = argparse.ArgumentParser(description="Refresh traders.is_bot materialized column")
    parser.add_argument("--db", default="data/analytics.db")
    parser.add_argument("--populate", action="store_true", help="Initial population run (no rate limit)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    _migrate(conn)

    if args.populate:
        populate(conn, args.dry_run)
    else:
        refresh(conn, args.dry_run)

    conn.close()


if __name__ == "__main__":
    main()
