#!/usr/bin/env python3
"""Python-based chunked migration: trades PK -> (trade_id, trader_address).

Alternative to migrate_trades_composite_pk.sh when that runs too slowly.
Gives per-chunk progress output so you can see it's actually working and
estimate when it'll finish. Safe to Ctrl-C at any point — the live DB is
untouched; only the scratch file is affected.

Strategy (tuned to finish on this size of DB):
  1. Copy analytics.db -> analytics.db.migration-scratch
  2. On scratch: create trades_new with composite PK only (no extra indexes)
  3. Stream rows in chunks of 100k, inserting into trades_new
  4. Drop old trades, rename trades_new -> trades
  5. Build the 7 secondary indexes one at a time (each with progress line)
  6. ANALYZE, restore durability PRAGMAs
  7. Swap files when verification passes

Run only when:
  - monitor and backfill are NOT running (lock contention)
  - cron is unloaded (same reason)
  - you have ~1-2 hours of quiet machine time

Reversal: live DB is untouched until the final swap. To abort: Ctrl-C, then
remove analytics.db.migration-scratch. To roll back after swap:
    mv analytics.db.pre-composite-pk.bak analytics.db
"""

from __future__ import annotations

import os
import shutil
import signal
import sqlite3
import sys
import time
from pathlib import Path

DB_PATH = Path("/Users/macbookair/polymarketv2/data/analytics.db")
BACKUP_PATH = DB_PATH.with_suffix(".db.pre-composite-pk.bak")
SCRATCH_PATH = DB_PATH.with_suffix(".db.migration-scratch")
CHUNK_SIZE = 100_000

SECONDARY_INDEXES = [
    ("idx_trades_token", "(token_id)"),
    ("idx_trades_market", "(market_id)"),
    ("idx_trades_timestamp", "(timestamp)"),
    ("idx_trades_trader_address", "(trader_address)"),
    ("idx_trades_trader_market", "(trader_address, market_id)"),
    ("idx_trades_dedup", "(trader_address, market_id, token_id, side, price, size, timestamp)"),
    ("idx_trades_ts_trader_market", "(timestamp, trader_address, market_id)"),
]


def fail(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def check_no_writers() -> None:
    import subprocess
    for pattern in ("polymarket.*monitor", "polymarket.*backfill"):
        try:
            subprocess.check_output(["pgrep", "-f", pattern], stderr=subprocess.DEVNULL)
            fail(f"{pattern!r} is running. Stop it first.")
        except subprocess.CalledProcessError:
            pass


def check_cron_unloaded() -> None:
    import subprocess
    try:
        out = subprocess.check_output(["launchctl", "list"], text=True)
        if "com.polymarket.cron-pipeline" in out:
            fail("Cron pipeline is loaded. Unload it first:\n"
                 "  launchctl unload ~/Library/LaunchAgents/com.polymarket.cron-pipeline.plist")
    except subprocess.CalledProcessError:
        pass


def copy_with_progress(src: Path, dst: Path) -> None:
    total = src.stat().st_size
    print(f"  Copying {src.name} -> {dst.name} ({total/1e9:.1f} GB)...")
    chunk = 64 * 1024 * 1024  # 64MB reads
    copied = 0
    start = time.time()
    with open(src, "rb") as sf, open(dst, "wb") as df:
        while True:
            buf = sf.read(chunk)
            if not buf:
                break
            df.write(buf)
            copied += len(buf)
            pct = copied / total * 100
            elapsed = time.time() - start
            rate = copied / elapsed / 1e6 if elapsed > 0 else 0
            print(f"    {copied/1e9:.2f}/{total/1e9:.2f} GB ({pct:5.1f}%) @ {rate:.0f} MB/s",
                  end="\r", flush=True)
    print()


def migrate_data(conn: sqlite3.Connection, total_rows: int) -> None:
    """Stream trades -> trades_new in chunks with progress."""
    cur = conn.cursor()
    # Ensure source order uses the PK so the destination PK fills sequentially.
    # Read only columns we're keeping (schema had 8 columns).
    cur.execute(
        """
        SELECT trade_id, trader_address, token_id, timestamp, side, price, size, market_id
        FROM trades
        ORDER BY trade_id, trader_address
        """
    )
    inserter = conn.cursor()
    written = 0
    start = time.time()
    last_print = start
    batch: list[tuple] = []

    for row in cur:
        batch.append(tuple(row))
        if len(batch) >= CHUNK_SIZE:
            inserter.executemany(
                "INSERT INTO trades_new VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                batch,
            )
            written += len(batch)
            batch.clear()
            now = time.time()
            if now - last_print >= 2:
                pct = written / total_rows * 100
                elapsed = now - start
                rate = written / elapsed if elapsed > 0 else 0
                eta = (total_rows - written) / rate if rate > 0 else 0
                print(f"    inserted {written:,}/{total_rows:,} "
                      f"({pct:5.1f}%) @ {rate/1000:.1f}k rows/s  ETA {eta/60:.1f} min",
                      end="\r", flush=True)
                last_print = now

    if batch:
        inserter.executemany(
            "INSERT INTO trades_new VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            batch,
        )
        written += len(batch)

    print(f"    inserted {written:,} rows total in {(time.time()-start)/60:.1f} min       ")
    if written != total_rows:
        fail(f"row count mismatch: inserted {written}, expected {total_rows}")


def build_indexes(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for name, cols in SECONDARY_INDEXES:
        print(f"  CREATE INDEX {name} ON trades{cols} ...")
        t0 = time.time()
        cur.execute(f"CREATE INDEX {name} ON trades{cols}")
        conn.commit()
        print(f"    done in {(time.time()-t0)/60:.1f} min")


def run() -> None:
    print("== preflight ==")
    if not DB_PATH.exists():
        fail(f"DB not found at {DB_PATH}")
    check_no_writers()
    check_cron_unloaded()

    db_bytes = DB_PATH.stat().st_size
    df = shutil.disk_usage(DB_PATH.parent)
    if df.free < db_bytes * 3:
        fail(f"need ~{db_bytes*3/1e9:.0f} GB free, have {df.free/1e9:.0f} GB")
    print(f"  DB size: {db_bytes/1e9:.1f} GB  |  Free: {df.free/1e9:.0f} GB")

    # Pre-snapshot
    print("== pre-migration snapshot ==")
    with sqlite3.connect(DB_PATH) as c:
        pre_count = c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        pre_schema = c.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='trades'"
        ).fetchone()[0]
    print(f"  rows: {pre_count:,}")
    if "PRIMARY KEY (trade_id, trader_address)" in pre_schema:
        print("  Already migrated. Exiting.")
        return

    # Backup
    print("== backup ==")
    if BACKUP_PATH.exists():
        with sqlite3.connect(BACKUP_PATH) as c:
            b = c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        if b != pre_count:
            fail(f"existing backup rows={b} != live {pre_count}; remove {BACKUP_PATH}")
        print(f"  Reusing backup at {BACKUP_PATH}")
    else:
        copy_with_progress(DB_PATH, BACKUP_PATH)

    # Scratch
    print("== scratch copy ==")
    for p in (SCRATCH_PATH, SCRATCH_PATH.with_suffix(".migration-scratch-shm"),
              SCRATCH_PATH.with_suffix(".migration-scratch-wal")):
        p.unlink(missing_ok=True)
    copy_with_progress(DB_PATH, SCRATCH_PATH)

    # Migrate on scratch
    print("== migration on scratch ==")
    conn = sqlite3.connect(str(SCRATCH_PATH), isolation_level=None)  # manual BEGIN/COMMIT
    try:
        cur = conn.cursor()
        # Lightweight pragmas — we have a backup so skipping fsync is safe.
        cur.execute("PRAGMA journal_mode = MEMORY")
        cur.execute("PRAGMA synchronous = OFF")

        cur.execute("BEGIN IMMEDIATE")
        cur.execute("""
            CREATE TABLE trades_new (
                trade_id TEXT,
                trader_address TEXT,
                token_id TEXT REFERENCES token_catalog(token_id),
                timestamp TEXT,
                side TEXT,
                price NUMERIC(10,6),
                size NUMERIC(20,6),
                market_id TEXT,
                PRIMARY KEY (trade_id, trader_address)
            )
        """)
        migrate_data(conn, pre_count)
        cur.execute("DROP TABLE trades")
        cur.execute("ALTER TABLE trades_new RENAME TO trades")
        conn.commit()

        # Indexes (each its own transaction — smaller rollback scope, progress per-index)
        build_indexes(conn)

        # Restore durability mode
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA synchronous = NORMAL")

        cur.execute("ANALYZE trades")
        conn.commit()
    finally:
        conn.close()

    # Verify scratch
    print("== verify scratch ==")
    with sqlite3.connect(SCRATCH_PATH) as c:
        post_count = c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        post_schema = c.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='trades'"
        ).fetchone()[0]
    if post_count != pre_count:
        fail(f"scratch rows {post_count} != pre {pre_count}. Live DB untouched; remove {SCRATCH_PATH}")
    if "PRIMARY KEY (trade_id, trader_address)" not in post_schema:
        fail(f"scratch PK not updated. Live DB untouched; remove {SCRATCH_PATH}")
    print(f"  scratch rows: {post_count:,}  |  PK composite: ok")

    # Swap
    print("== swap ==")
    for sib in (DB_PATH.with_suffix(".db-shm"), DB_PATH.with_suffix(".db-wal")):
        sib.unlink(missing_ok=True)
    old_path = DB_PATH.with_suffix(".db.old-premigration")
    DB_PATH.rename(old_path)
    SCRATCH_PATH.rename(DB_PATH)
    print(f"  Live DB swapped. Old file at {old_path} (delete once verified).")
    print()
    print("Migration complete. Restart monitor and reload cron.")


if __name__ == "__main__":
    # Ctrl-C cleanly — transactions on scratch roll back; live DB untouched.
    def _sigint(_s, _f):
        print("\nInterrupted. Live DB untouched. Remove scratch if present: "
              f"rm {SCRATCH_PATH}")
        sys.exit(130)
    signal.signal(signal.SIGINT, _sigint)
    run()
