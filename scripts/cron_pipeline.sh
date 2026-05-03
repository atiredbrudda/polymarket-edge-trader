#!/bin/bash
# Polymarket Analytics — 4-hour cron pipeline
#
# Schedule: every 4 hours (crontab -e):
#   Scheduled via launchd: ~/Library/LaunchAgents/com.polymarket.cron-pipeline.plist
#
# Two backfill modes:
#   - Lean (--new-only): all non-midnight passes, only never-backfilled traders (~20 min)
#   - Full: midnight run (00:xx), all ~6,000 active traders (~3h)
#   - Missed-midnight fallback: auto-upgrades to full if >2 days since last full
#
# Pre-flight: runs health-check --tier cron before pipeline.
# Post-run: runs health-check --tier daily for summary alerts.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"
source .venv/bin/activate

FULL_BACKFILL_MARKER="data/.last_full_backfill"
HOUR=$(date +%H)  # 00-23
MAX_DAYS_WITHOUT_FULL=2
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"
RUN_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)

echo "$LOG_PREFIX Starting cron pipeline run"

# --- Acquire pipeline lock so the monitor skips its pass while cron is running ---
LOCK_FILE="$PROJECT_DIR/data/.pipeline.lock"
mkdir -p "$(dirname "$LOCK_FILE")"
if [ -f "$LOCK_FILE" ]; then
    LOCK_INFO=$(python3 -c "import json; d=json.load(open('$LOCK_FILE')); print(d.get('pid',''),d.get('process_type','unknown'))" 2>/dev/null)
    EXISTING_PID="${LOCK_INFO% *}"
    EXISTING_TYPE="${LOCK_INFO#* }"
    if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
        if [ "$EXISTING_TYPE" = "cron" ]; then
            echo "$LOG_PREFIX Lock held by another cron (PID $EXISTING_PID) — skipping run"
            exit 0
        elif [ "$EXISTING_TYPE" = "monitor" ]; then
            # Wait for monitor to finish its pass (max 3 min) rather than
            # preempting — preempting causes concurrent DB writes and "database
            # is locked" errors because monitor keeps writing until its with-block exits.
            echo "$LOG_PREFIX Lock held by monitor (PID $EXISTING_PID) — waiting up to 3 min for it to finish"
            WAIT=0
            while [ $WAIT -lt 180 ] && kill -0 "$EXISTING_PID" 2>/dev/null && [ -f "$LOCK_FILE" ]; do
                sleep 10
                WAIT=$((WAIT + 10))
            done
            if kill -0 "$EXISTING_PID" 2>/dev/null && [ -f "$LOCK_FILE" ]; then
                echo "$LOG_PREFIX Monitor still running after 3 min — proceeding anyway (monitor will see cron lock and stop chain)"
            else
                echo "$LOG_PREFIX Monitor finished — proceeding"
            fi
        fi
    else
        echo "$LOG_PREFIX Stale lock (PID ${EXISTING_PID:-unknown} is gone) — overwriting"
    fi
fi
LOCK_JSON="{\"pid\":$$,\"process_type\":\"cron\",\"started_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
echo "$LOCK_JSON" > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

# --- Pre-flight health check (lock, memory, disk) ---
echo "$LOG_PREFIX Running pre-flight health check..."
if ! polymarket --niche esports health-check --tier cron; then
    echo "$LOG_PREFIX PRE-FLIGHT FAILED — aborting pipeline"
    exit 1
fi

# --- Determine backfill mode ---
BACKFILL_MODE="--new-only"

if [ "$HOUR" -eq 0 ]; then
    BACKFILL_MODE=""
    echo "$LOG_PREFIX Midnight run — full backfill mode"
elif [ -f "$FULL_BACKFILL_MARKER" ]; then
    LAST_FULL=$(cat "$FULL_BACKFILL_MARKER")
    DAYS_SINCE=$(( ($(date +%s) - LAST_FULL) / 86400 ))
    if [ "$DAYS_SINCE" -ge "$MAX_DAYS_WITHOUT_FULL" ]; then
        echo "$LOG_PREFIX WARNING: Last full backfill was ${DAYS_SINCE} days ago. Upgrading to full."
        BACKFILL_MODE=""
    fi
else
    # No marker file = never ran full. Do it now.
    echo "$LOG_PREFIX No full backfill marker found — running full backfill"
    BACKFILL_MODE=""
fi

if [ -n "$BACKFILL_MODE" ]; then
    echo "$LOG_PREFIX Lean backfill mode (--new-only)"
fi

# --- Pipeline stages ---
# Individual stage failures are logged but do NOT abort the pipeline.
# Downstream stages often still produce useful results (e.g. score can
# run even if resolve-positions found nothing new to resolve).
FAILED_STAGES=""

run_stage() {
    local stage_name="$1"
    shift
    echo "$LOG_PREFIX Running: $stage_name"
    if "$@"; then
        return 0
    else
        echo "$LOG_PREFIX FAILED: $stage_name (exit $?)"
        FAILED_STAGES="$FAILED_STAGES $stage_name"
        return 0  # don't trigger set -e — let the pipeline continue
    fi
}

run_stage "discover" polymarket --niche esports discover --closing-within 4
run_stage "backfill" polymarket --niche esports backfill $BACKFILL_MODE
run_stage "retry-incomplete" polymarket --niche esports retry-incomplete
run_stage "ingest-events" polymarket --niche esports ingest-events --full
run_stage "resolve-outcomes" polymarket --niche esports resolve-outcomes
run_stage "sanity-check" polymarket --niche esports sanity-check
run_stage "build-positions" polymarket --niche esports build-positions
run_stage "resolve-positions" polymarket --niche esports resolve-positions
run_stage "score" polymarket --niche esports score
run_stage "detect" polymarket --niche esports detect
# paper-bridge and paper-take-profit are handled by monitor --chain on every
# poll cycle for faster signal-to-trade latency. Cron only resolves closed
# markets (depends on ingest-events --full + resolve-outcomes above).
run_stage "paper-resolve" polymarket --niche esports paper-dashboard --resolve

# --- Daily DB maintenance (midnight only) ---
# Prunes resolved markets older than 40d + their dependents, deletes orphans,
# truncates the WAL high-water mark. Runs after all upstream data-consuming
# stages so they see complete data before deletion.
#
# Each step is independently failable (run_stage continues on error).
# prune_resolved_40d.py runs VACUUM internally; the WAL truncate at the end
# drains both the prune's freelist work AND the orphan-delete WAL bloat.
if [ -z "$BACKFILL_MODE" ]; then
    echo "$LOG_PREFIX Daily DB maintenance starting"
    run_stage "snapshot-40d"   .venv/bin/python scripts/snapshot_resolved_40d.py
    run_stage "prune-40d"      .venv/bin/python scripts/prune_resolved_40d.py --execute --no-lock-check
    run_stage "prune-orphans"  sqlite3 data/analytics.db "BEGIN; DELETE FROM trades WHERE NOT EXISTS (SELECT 1 FROM markets m WHERE m.condition_id = trades.market_id); DELETE FROM positions WHERE NOT EXISTS (SELECT 1 FROM markets m WHERE m.condition_id = positions.market_id); COMMIT;"
    # backfill_drops 30d retention (REVIEW.md H-11 #3 observability table).
    run_stage "prune-drops"    sqlite3 data/analytics.db "DELETE FROM backfill_drops WHERE dropped_at < datetime('now', '-30 days');"
    run_stage "wal-truncate"   sqlite3 data/analytics.db "PRAGMA wal_checkpoint(TRUNCATE);"
    echo "$LOG_PREFIX Daily DB maintenance complete"
fi

# --- Update full backfill marker ---
if [ -z "$BACKFILL_MODE" ]; then
    date +%s > "$FULL_BACKFILL_MARKER"
    echo "$LOG_PREFIX Updated full backfill marker"
fi

# --- Post-run daily summary ---
echo "$LOG_PREFIX Running daily health summary..."
STAGES_CSV=$(echo "$FAILED_STAGES" | xargs | tr ' ' ',')
polymarket --niche esports health-check --tier daily \
    --run-start "$RUN_START" \
    --stages-failed "$STAGES_CSV" || true

if [ -n "$FAILED_STAGES" ]; then
    echo "$LOG_PREFIX WARNING: Failed stages:$FAILED_STAGES"
fi

echo "$LOG_PREFIX Cron pipeline complete"
