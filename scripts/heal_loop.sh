#!/bin/bash
# Polymarket Analytics — heal_loop daemon
#
# Runs heal_trapped_batch.py continuously in the background, deferring whenever
# cron or monitor is mid-cycle. Sleeps long enough between heal passes to keep
# the write lock idle for monitor SELECTs and cron writes.
#
# Loop invariant per pass:
#   - if data/.pipeline.lock exists (cron mid-run)        → sleep 5min, restart
#   - if data/.monitor_heartbeat <10s old (monitor mid-cycle) → sleep 20s, restart
#   - if heal queue is empty                              → sleep 1h, restart
#   - else: heal up to --limit 10 traders, then sleep 30min
#
# Started via launchd: ~/Library/LaunchAgents/com.polymarket.heal-loop.plist
# stdout/stderr → /tmp/polymarket-heal.log

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"
# shellcheck disable=SC1091
source .venv/bin/activate

LOCK_FILE="$PROJECT_DIR/data/.pipeline.lock"
HEARTBEAT_FILE="$PROJECT_DIR/data/.monitor_heartbeat"
HEAL_SCRIPT="$PROJECT_DIR/scripts/heal_trapped_batch.py"

# Cooldowns (seconds)
COOLDOWN_CRON_LOCKED=300   # 5 min — cron typically finishes in <30 min
COOLDOWN_MONITOR_BUSY=20   # 20s — monitor cycles ~1 min
COOLDOWN_QUEUE_EMPTY=3600  # 1 hour — nothing trapped to heal
COOLDOWN_AFTER_PASS=1800   # 30 min — between successful heal passes

heartbeat_age_s() {
    if [ ! -f "$HEARTBEAT_FILE" ]; then
        echo 999999
        return
    fi
    local mtime
    mtime=$(stat -f %m "$HEARTBEAT_FILE" 2>/dev/null || echo 0)
    local now
    now=$(date +%s)
    echo $((now - mtime))
}

queue_empty() {
    # Returns 0 (true) when no trapped traders exist (filtered by graph_unservable).
    .venv/bin/python -c "
import sys
from pathlib import Path
sys.path.insert(0, '$PROJECT_DIR/src')
from polymarket_analytics.db.connection import get_db
db = get_db(Path('$PROJECT_DIR/data/analytics.db'))
row = db.execute('''
WITH pairs AS (
  SELECT trader_address, market_id,
         SUM(CASE WHEN side=\"BUY\" THEN 1 ELSE 0 END) AS buys,
         SUM(CASE WHEN side=\"SELL\" THEN 1 ELSE 0 END) AS sells
  FROM trades GROUP BY trader_address, market_id
)
SELECT COUNT(DISTINCT p.trader_address)
FROM pairs p
LEFT JOIN traders t ON t.address = p.trader_address
WHERE p.buys = 0 AND p.sells > 0
  AND COALESCE(t.graph_unservable, 0) = 0
''').fetchone()
sys.exit(0 if (row[0] or 0) == 0 else 1)
" 2>/dev/null
}

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] heal_loop: $*"
}

trap 'log "shutdown signal received — exiting"; exit 0' SIGINT SIGTERM

log "starting heal_loop daemon (pid=$$)"

while true; do
    # 1) Cron has the pipeline lock — back off generously
    if [ -f "$LOCK_FILE" ]; then
        log "pipeline.lock present — sleeping ${COOLDOWN_CRON_LOCKED}s"
        sleep "$COOLDOWN_CRON_LOCKED"
        continue
    fi

    # 2) Monitor recently touched its heartbeat — defer briefly
    age=$(heartbeat_age_s)
    if [ "$age" -lt 10 ]; then
        log "monitor heartbeat ${age}s old — sleeping ${COOLDOWN_MONITOR_BUSY}s"
        sleep "$COOLDOWN_MONITOR_BUSY"
        continue
    fi

    # 3) Nothing to heal — long nap
    if queue_empty; then
        log "trapped queue empty — sleeping ${COOLDOWN_QUEUE_EMPTY}s"
        sleep "$COOLDOWN_QUEUE_EMPTY"
        continue
    fi

    # 4) Run a small heal pass
    log "running heal pass (--resume --limit 10 --batch-size 10)"
    if ! .venv/bin/python "$HEAL_SCRIPT" --resume --limit 10 --batch-size 10; then
        log "heal pass exited non-zero — backing off ${COOLDOWN_AFTER_PASS}s anyway"
    fi

    log "heal pass done — sleeping ${COOLDOWN_AFTER_PASS}s"
    sleep "$COOLDOWN_AFTER_PASS"
done
