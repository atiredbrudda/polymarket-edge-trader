#!/bin/bash
# Migrate trades table PK from (trade_id) to (trade_id, trader_address).
#
# Root cause: a CLOB fill is ONE on-chain event with TWO traders. Graph returns
# the same event when querying maker-role AND taker-role, producing identical
# trade_ids for both sides. The single-column PK + INSERT OR IGNORE silently
# drops the second-arrived trader's view of the fill, leaving them sell-only on
# that market.
#
# Strategy: do the migration on a scratch copy of the DB with aggressive pragmas
# (memory-backed sort, synchronous=OFF, large cache), then swap the file. Much
# faster than in-place because it avoids WAL fsync overhead and can keep the
# PK sort in RAM.
#
# Safety:
#   - refuses to run if monitor or backfill is active
#   - takes a full DB backup first (untouched if scratch migration succeeds)
#   - runs the migration on a SCRATCH copy; live DB untouched until final swap
#   - verifies row count before swap; won't swap if mismatch
#
# Reversal if anything goes wrong: `mv analytics.db.pre-composite-pk.bak analytics.db`

set -euo pipefail

DB="/Users/macbookair/polymarketv2/data/analytics.db"
BACKUP="${DB}.pre-composite-pk.bak"
SCRATCH="${DB}.migration-scratch"

echo "== preflight =="

if pgrep -f "polymarket.*monitor" >/dev/null || pgrep -f "polymarket.*backfill" >/dev/null; then
  echo "ERROR: polymarket monitor or backfill is running. Stop it first."
  pgrep -fa "polymarket" | head -5
  exit 1
fi

if [ ! -f "$DB" ]; then
  echo "ERROR: DB not found at $DB"
  exit 1
fi

# Disk space: need ~3x DB size (live + backup + scratch)
db_bytes=$(stat -f %z "$DB")
avail_bytes=$(df "$DB" | tail -1 | awk '{print $4 * 512}')
need_bytes=$(( db_bytes * 4 ))
if [ "$avail_bytes" -lt "$need_bytes" ]; then
  echo "ERROR: need ~${need_bytes} bytes free, have ${avail_bytes}"
  exit 1
fi

echo "  DB size: $(du -h "$DB" | awk '{print $1}')"
echo "  Free:    $(df -h "$DB" | tail -1 | awk '{print $4}')"

echo "== pre-migration snapshot =="
pre_count=$(sqlite3 "$DB" "SELECT COUNT(*) FROM trades;")
pre_schema=$(sqlite3 "$DB" "SELECT sql FROM sqlite_master WHERE type='table' AND name='trades';")
pre_indexes=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND tbl_name='trades';")
echo "  trades rows:    $pre_count"
echo "  indexes:        $pre_indexes"

if echo "$pre_schema" | grep -q "PRIMARY KEY (trade_id, trader_address)"; then
  echo "  Already migrated. Exiting."
  exit 0
fi

# Backup (only if it doesn't already exist — the prior failed migration made one)
echo "== backup =="
if [ -f "$BACKUP" ]; then
  backup_count=$(sqlite3 "$BACKUP" "SELECT COUNT(*) FROM trades;")
  if [ "$backup_count" -eq "$pre_count" ]; then
    echo "  Reusing existing backup at $BACKUP ($backup_count rows, matches live)"
  else
    echo "ERROR: existing backup row count ($backup_count) differs from live ($pre_count)."
    echo "Move or delete $BACKUP, then retry."
    exit 1
  fi
else
  echo "  Copying $DB -> $BACKUP..."
  cp "$DB" "$BACKUP"
  backup_count=$(sqlite3 "$BACKUP" "SELECT COUNT(*) FROM trades;")
  [ "$backup_count" -eq "$pre_count" ] || { echo "ERROR: backup count mismatch"; exit 1; }
  echo "  Backup verified: $backup_count rows"
fi

# Build scratch copy (separate file — live DB untouched during migration)
echo "== scratch copy =="
rm -f "$SCRATCH" "${SCRATCH}-shm" "${SCRATCH}-wal"
echo "  Copying $DB -> $SCRATCH..."
cp "$DB" "$SCRATCH"
echo "  Scratch ready: $(du -h "$SCRATCH" | awk '{print $1}')"

echo "== migration on scratch =="
# PRAGMA notes (minimal, low-memory):
#   journal_mode=MEMORY   — skip WAL fsync (we have a full backup for safety)
#   synchronous=OFF       — skip fsync, safe because we swap atomically
#   Default cache + default temp_store: lets SQLite use disk for sort scratch
#   without starving other processes for RAM. Prior attempt with cache=1GB +
#   temp_store=MEMORY caused swap thrashing.
sqlite3 "$SCRATCH" <<'SQL'
PRAGMA journal_mode = MEMORY;
PRAGMA synchronous = OFF;

BEGIN;

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
);

-- ORDER BY makes PK btree fill sequentially (sorted inserts into empty b-tree)
-- instead of random insertions which cause page splits.
INSERT INTO trades_new (trade_id, trader_address, token_id, timestamp, side, price, size, market_id)
SELECT trade_id, trader_address, token_id, timestamp, side, price, size, market_id
FROM trades
ORDER BY trade_id, trader_address;

DROP TABLE trades;
ALTER TABLE trades_new RENAME TO trades;

CREATE INDEX idx_trades_token ON trades(token_id);
CREATE INDEX idx_trades_market ON trades(market_id);
CREATE INDEX idx_trades_timestamp ON trades(timestamp);
CREATE INDEX idx_trades_trader_address ON trades(trader_address);
CREATE INDEX idx_trades_trader_market ON trades(trader_address, market_id);
CREATE INDEX idx_trades_dedup ON trades(trader_address, market_id, token_id, side, price, size, timestamp);
CREATE INDEX idx_trades_ts_trader_market ON trades(timestamp, trader_address, market_id);

COMMIT;

-- Restore durability mode before anything uses the DB again
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

ANALYZE trades;
SQL

echo "  Scratch migration committed."

echo "== verify scratch =="
post_count=$(sqlite3 "$SCRATCH" "SELECT COUNT(*) FROM trades;")
post_schema=$(sqlite3 "$SCRATCH" "SELECT sql FROM sqlite_master WHERE type='table' AND name='trades';")
post_indexes=$(sqlite3 "$SCRATCH" "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND tbl_name='trades';")
echo "  scratch rows:    $post_count (pre: $pre_count)"
echo "  indexes:         $post_indexes"

if [ "$post_count" -ne "$pre_count" ]; then
  echo "ERROR: row count changed in scratch. Live DB is untouched; remove $SCRATCH and investigate."
  exit 1
fi

if ! echo "$post_schema" | grep -q "PRIMARY KEY (trade_id, trader_address)"; then
  echo "ERROR: scratch PK not updated. Live DB untouched; remove $SCRATCH and investigate."
  exit 1
fi

echo "  PK verified: composite (trade_id, trader_address)"

echo "== swap =="
# Atomic-ish swap. We delete the WAL/shm siblings because they're tied to the old DB's inode.
rm -f "${DB}-shm" "${DB}-wal"
mv "$DB" "${DB}.old-premigration"
mv "$SCRATCH" "$DB"
echo "  Live DB now has composite PK."
echo "  Old DB moved to ${DB}.old-premigration (delete once verified)"

echo
echo "Migration complete."
echo "Backup retained at: $BACKUP"
echo
echo "Next steps:"
echo "  1. Restart monitor"
echo "  2. Run: scripts/recover_trapped_traders.sh --sample 5  (verify fix on a small batch)"
echo "  3. If the sample recovers cleanly, run without --sample for the full 2,005 traders"
