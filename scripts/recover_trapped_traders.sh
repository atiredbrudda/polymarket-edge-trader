#!/bin/bash
# One-time recovery: reset last_trade_seen_at for trapped traders so the next
# backfill re-fetches their Graph history. Under the new composite-PK schema,
# BUYs that previously collided with other traders' SELLs now persist.
#
# Safety:
#   - requires the composite-PK migration to have already run
#   - dry-run mode lists affected traders without modifying DB
#   - --sample N resets only the first N traders (handy for testing)
#
# Usage:
#   scripts/recover_trapped_traders.sh --dry-run
#   scripts/recover_trapped_traders.sh --sample 5
#   scripts/recover_trapped_traders.sh              # full reset

set -euo pipefail

DB="/Users/macbookair/polymarketv2/data/analytics.db"
MODE="${1:-}"
SAMPLE_N="${2:-}"

# 1. Require composite PK already in place
schema=$(sqlite3 "$DB" "SELECT sql FROM sqlite_master WHERE type='table' AND name='trades';")
if ! echo "$schema" | grep -q "PRIMARY KEY (trade_id, trader_address)"; then
  echo "ERROR: trades table still has single-column PK."
  echo "Run scripts/migrate_trades_composite_pk.sh first."
  exit 1
fi

# 2. Compute trapped-trader set (same definition used to identify the 9,130 pairs)
TRAPPED_CTE="
WITH pairs AS (SELECT DISTINCT trader_address, market_id FROM trades),
no_pos AS (
  SELECT p.trader_address, p.market_id FROM pairs p
  WHERE NOT EXISTS (SELECT 1 FROM positions ps
    WHERE ps.trader_address=p.trader_address AND ps.market_id=p.market_id)
),
trapped AS (
  SELECT DISTINCT np.trader_address FROM no_pos np
  JOIN trades t ON t.trader_address=np.trader_address AND t.market_id=np.market_id
  GROUP BY np.trader_address, np.market_id
  HAVING SUM(CASE WHEN t.side='BUY' THEN 1 ELSE 0 END) = 0
     AND SUM(CASE WHEN t.side='SELL' THEN 1 ELSE 0 END) > 0
)
"

echo "Computing affected-trader set (this may take a minute over 10GB)..."
count=$(sqlite3 "$DB" "${TRAPPED_CTE} SELECT COUNT(DISTINCT trader_address) FROM trapped;")
echo "  Trapped traders: $count"

if [ "$MODE" = "--dry-run" ]; then
  echo "Dry-run — first 10 addresses:"
  sqlite3 "$DB" "${TRAPPED_CTE} SELECT DISTINCT trader_address FROM trapped LIMIT 10;" | sed 's/^/  /'
  exit 0
fi

# 3. Build target list (optionally capped to sample)
if [ "$MODE" = "--sample" ]; then
  if [ -z "$SAMPLE_N" ]; then
    echo "ERROR: --sample requires a count, e.g. --sample 5"
    exit 1
  fi
  LIMIT_CLAUSE="LIMIT $SAMPLE_N"
  echo "Sample mode: only $SAMPLE_N traders will be reset"
else
  LIMIT_CLAUSE=""
fi

# 4. Confirm before bulk update
echo
if [ -n "$LIMIT_CLAUSE" ]; then
  echo "About to reset last_trade_seen_at = NULL for $SAMPLE_N traders (sample)."
else
  echo "About to reset last_trade_seen_at = NULL for $count traders."
fi
echo "This triggers full-history re-backfill on their next cycle."
read -p "Proceed? [yes/no] " confirm
if [ "$confirm" != "yes" ]; then
  echo "Aborted."
  exit 0
fi

# 5. Reset in one atomic UPDATE
sqlite3 "$DB" <<SQL
BEGIN IMMEDIATE;
${TRAPPED_CTE}
UPDATE traders
SET last_trade_seen_at = NULL
WHERE address IN (
  SELECT DISTINCT trader_address FROM trapped ${LIMIT_CLAUSE}
);
SELECT changes() AS traders_reset;
COMMIT;
SQL

echo
echo "Done. Next backfill cycle will refetch full Graph history for these traders."
echo
echo "To trigger immediately (instead of waiting for cron):"
echo "  /Users/macbookair/polymarketv2/.venv/bin/polymarket --niche esports backfill"
echo
echo "To verify recovery worked, after the backfill completes:"
echo "  sqlite3 $DB \"\\"
echo "     WITH pairs AS (SELECT DISTINCT trader_address, market_id FROM trades), \\"
echo "     no_pos AS (SELECT p.trader_address, p.market_id FROM pairs p \\"
echo "       WHERE NOT EXISTS (SELECT 1 FROM positions ps \\"
echo "         WHERE ps.trader_address=p.trader_address AND ps.market_id=p.market_id)) \\"
echo "     SELECT COUNT(*) AS still_trapped FROM no_pos np \\"
echo "     JOIN trades t ON t.trader_address=np.trader_address AND t.market_id=np.market_id \\"
echo "     GROUP BY np.trader_address, np.market_id \\"
echo "     HAVING SUM(CASE WHEN t.side='BUY' THEN 1 ELSE 0 END) = 0 \\"
echo "        AND SUM(CASE WHEN t.side='SELL' THEN 1 ELSE 0 END) > 0;\""
echo "  # count should drop substantially from 9,130"
