#!/bin/bash
# Polymarket Analytics — 4-hour cron pipeline
#
# Schedule: every 4 hours (crontab -e):
#   Scheduled via launchd: ~/Library/LaunchAgents/com.polymarket.cron-pipeline.plist
#
# Two backfill modes:
#   - Lean (--new-only): Mon-Sat, only never-backfilled traders (~20 min)
#   - Full: Sunday, all ~6,000 active traders (~3h)
#   - Missed-Sunday fallback: auto-upgrades to full if >8 days since last full
#
# Pre-flight: runs health-check --tier cron before pipeline.
# Post-run: runs health-check --tier daily for summary alerts.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"
source .venv/bin/activate

FULL_BACKFILL_MARKER="data/.last_full_backfill"
DOW=$(date +%u)  # 1=Monday, 7=Sunday
MAX_DAYS_WITHOUT_FULL=8
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

echo "$LOG_PREFIX Starting cron pipeline run"

# --- Acquire pipeline lock so the monitor skips its pass while cron is running ---
LOCK_FILE="$PROJECT_DIR/data/.pipeline.lock"
mkdir -p "$(dirname "$LOCK_FILE")"
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

if [ "$DOW" -eq 7 ]; then
    BACKFILL_MODE=""
    echo "$LOG_PREFIX Sunday — full backfill mode"
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

# --- Update full backfill marker ---
if [ -z "$BACKFILL_MODE" ]; then
    date +%s > "$FULL_BACKFILL_MARKER"
    echo "$LOG_PREFIX Updated full backfill marker"
fi

# --- Post-run daily summary ---
echo "$LOG_PREFIX Running daily health summary..."
polymarket --niche esports health-check --tier daily || true

if [ -n "$FAILED_STAGES" ]; then
    echo "$LOG_PREFIX WARNING: Failed stages:$FAILED_STAGES"
fi

echo "$LOG_PREFIX Cron pipeline complete"
