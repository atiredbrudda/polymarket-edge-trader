# Code Review: Polymarket Analytics Pipeline

**Reviewed:** 2026-04-09
**Updated:** 2026-04-18 (CLOB v2 migration prep + P-03 confirmed fixed)
**Depth:** deep (cross-file analysis)
**Files Reviewed:** 20
**Status:** mostly_resolved (14 fixed, 3 acceptable, open: paper resolution)
**⚠ Scheduled action:** S-01 CLOB v2 cutover on **2026-04-28 ~11:00 UTC** — see Scheduled section.

## Summary

Deep review of the Polymarket analytics pipeline. All critical and most high/medium findings have been resolved. Remaining items are low-impact edge cases and minor improvements.

---

## Resolved Findings

| ID | Finding | Resolution |
|----|---------|------------|
| C-01 | Sell-only detection query ignores market_id grouping | **FIXED** — query now scoped to current-batch `api_markets` with `graph_retry_count` guard |
| C-02 | Incremental backfill skips Graph fallback | **FIXED** — sell-only detection runs for both full and incremental modes |
| C-03 | Graph API has no retry/backoff for 429/503 | **FIXED** — exponential backoff in `_paginate` for 429/502/503/504 |
| C-04 | `max_trade_timestamp` mixes int vs str types | **FIXED** — all timestamps normalized via `_normalize_ts()` before comparison |
| H-01 | Dedup scan is O(n) full table scan | **FIXED** — composite index `idx_trades_dedup` added in schema.py |
| H-03 | Position upsert is row-by-row | **FIXED** — uses batched `upsert_all()` |
| H-05 | `fetch_trades_with_retry` silently swallows errors | **FIXED** — non-retryable errors now logged before returning empty |
| M-01 | CLV formula wrong for SHORT direction | **FIXED** — SHORT CLV inverted correctly in metrics.py |
| M-03 | `component_timers` bleeds across runs | **FIXED** — each CLI invocation is a separate process; no bleed |
| M-04 | `_normalize_ts` falls back to `datetime.now()` | **FIXED** — function now handles both int and ISO string inputs robustly |
| M-05 | Discover trade_id non-deterministic without txHash | **FIXED** — content-based SHA256 hash implemented |
| X-01 | paper_bridge SKIP_API on head-to-head markets | **FIXED** — `_resolve_token_and_outcome()` fallback via trades+lift_scores DB lookup. 98→2 SKIP_API. |
| X-02 | Monitor triggers Graph fallback on every poll pass | **FIXED** — `_fetch_one` returns `since_ts`, passed to `backfill_trader` as `since_unix_ts`. |
| X-03 | Resolved status overwrite by discover/monitor | **NOT A BUG** — ON CONFLICT SET clause never includes `resolved`. Verified: 101k resolved markets intact. |

## Acceptable / By Design

| ID | Finding | Status |
|----|---------|--------|
| H-02 | `trades.market_id` has no FK to `markets` | **By design** — backfill ingests trades for markets not yet discovered. FK on `token_id` enforced; trades without catalog entries are skipped. |
| M-06 | Resolution UPDATE ordering dependency (FLAT before market-outcome) | **Acceptable** — ordering is correct and both UPDATEs run in same transaction. Fragile but functional. |
| L-02 | `extraction.py` swallows all exceptions | **Acceptable** — defensive fallback to empty DataFrame. Low-risk since extraction failures are visible downstream (no scores generated). |

---

## Scheduled — Polymarket CLOB v2 Migration

### S-01: CLOB v2 cutover — **TRIGGER DATE: 2026-04-28 (~11:00 UTC)**

**Status:** prep complete, awaiting cutover. ~1 hour downtime expected; all open orders cancelled at cutover.

**Migration docs:** https://docs.polymarket.com/v2-migration

**Audit summary (2026-04-18):**
- This pipeline is **read-only** on Polymarket APIs. No on-chain order signing.
- pm_trader (`polymarket-paper-trader` fork) is a pure paper trader — no `py-clob-client` dep, no EIP-712 signing, no hardcoded USDC.e addresses.
- Probed v2 endpoints (`/book`, `/midpoint`, `/fee-rate`, `/tick-size`, `/markets/{cond}`) against `clob-v2.polymarket.com` — **schemas are byte-identical to v1**. No parsing changes needed.
- `getClobMarketInfo` is a JS-SDK helper, not a new REST route. `/fee-rate` and `/tick-size` are NOT being removed.
- Total breakage scope: 1 hardcoded URL.

**Prep already done:**
- Fork patched + pushed: `atiredbrudda/polymarket-paper-trader@eb801f1` adds `POLYMARKET_CLOB_URL` and `POLYMARKET_GAMMA_URL` env-var overrides (defaults unchanged — behavior-neutral until env var is set).

**Cutover playbook (run on 2026-04-28):**
```bash
# 1. Pull latest pm_trader into venv
cd /Users/macbookair/polymarketv2
.venv/bin/pip install --upgrade --force-reinstall \
  "polymarket-paper-trader @ git+https://github.com/atiredbrudda/polymarket-paper-trader.git"

# 2. Flip CLOB endpoint via env var (Gamma stays default unless docs change)
export POLYMARKET_CLOB_URL="https://clob-v2.polymarket.com"

# 3. Smoke test before next cron pass
.venv/bin/polymarket --niche esports paper-bridge --dry-run

# 4. If broken, instant rollback:
unset POLYMARKET_CLOB_URL
```

**Add the export to wherever cron sources its env** (crontab wrapper, .env file, systemd unit — verify before cutover).

**Verification checklist post-cutover:**
- [ ] `paper-bridge --dry-run` returns prices (not SKIP_API)
- [ ] `paper-take-profit --dry-run` returns live prices for open positions
- [ ] Monitor poll cycle completes without API errors
- [ ] One real cron pass (next 4h interval) completes cleanly

**What's NOT affected (verified safe):**
- Gamma API (`gamma-api.polymarket.com`) — no announced changes
- Data API (`data-api.polymarket.com`) — read-only trades/holders
- Graph subgraph — read-only fallback
- Bridge decision logic, scoring formulas, detection — all data-agnostic

---

## Remaining Open

### H-06: Paper trading results monitor/dashboard — **FIXED 2026-04-15**

`polymarket --niche esports paper-dashboard` added. Shows: account summary (cash, deployed, realized P&L), top open positions, bridge decision stats (last N days), recent trades. Includes `--reset` (account wipe + reinit), `--resolve` (settle closed markets), and a low-cash alert that fires when cash < $500 (preventing silent SKIP_SIZE rundown).

---

## Remaining Open (Low Impact)

### H-07: `ingest-events --full` OOM hang on memory-constrained runs

**File:** `src/polymarket_analytics/api/gamma.py:67` / `src/polymarket_analytics/commands/ingest_events.py:97`
**Impact:** `fetch_markets(closed=True)` paginates all ~115k+ closed esports markets into a single in-memory list before any processing begins. On a low-memory machine (e.g. post-VACUUM when the OS has been paging heavily), Python stalls mid-pagination with no timeout on the httpx client. Observed 2026-04-20: stuck at page 575 / 115k markets for 40+ min, required manual kill.

**Root cause:** Two problems compound: (1) no httpx read timeout on the Gamma client, so a stalled response waits forever; (2) fetching all 115k closed markets per run is unnecessary — we only need markets closed within the last ~7 days for resolution chain freshness.

**Fix (implement together):**
1. **Date-filtered closed sweep** — add `end_date_min` param to `fetch_markets`, pass `now − 7 days` for the closed fetch in `ingest-events --full`. Cuts 115k pages to ~50 markets. Also eliminates the memory pressure entirely.
2. **httpx read timeout** — set `timeout=httpx.Timeout(30.0)` on the Gamma client so stalled requests surface as `ReadTimeout` (already retried) rather than hanging forever.

**Note:** `--full` must remain unconditional in cron — incremental mode misses newly-resolved markets and breaks the resolution chain (see Cron Architecture wiki).

---

### H-04: `discover` sequential HTTP — 45 min for 283 markets

**File:** `src/polymarket_analytics/commands/discover.py:57-69`
**Impact:** `_fetch_market_trades()` is synchronous httpx, called once per market in a sequential loop. Each call takes ~9s (network round-trip even for empty markets). 283 markets × 9s = 45 minutes. This is the cron bottleneck.

**Root cause of high market count:** Each BO3 match spawns 23-37 Polymarket markets (winner, map winners, game handicaps, first blood, baron nashor, penta kill, total kills O/U, odd/even kills, etc.). Most are prop markets with zero trades — nobody bets on "Any Player Penta Kill?" — but discover fetches trades for all of them.

**Measured 2026-04-16:** 295 markets in `--closing-within 4` window, 12 cached, 283 processed. Of those, 603 had zero trades. Discover spent 45 min fetching nothing for most of them.

**Fix options (pick one or both):**
1. **Concurrent fetching** — use `asyncio.Semaphore(10)` like monitor does. 283 markets / 10 concurrent = ~4.5 min instead of 45 min. Straightforward refactor of `_fetch_market_trades` → async.
2. **Skip zero-volume markets** — Gamma API response includes `volumeNum`. Skip markets with `volumeNum == 0` before fetching trades. Eliminates ~60% of fetches (the dead prop markets nobody trades).

### M-02: Graph side determination wrong for token-for-token swaps

**File:** `src/polymarket_analytics/api/graph.py`
**Impact:** Token-for-token swaps (both assets non-zero) always classified as SELL. Rare edge case on Polymarket esports markets.

### L-01: Unused `asyncio` import in `score.py` and `detect.py`

**Impact:** Cosmetic. The async wrappers work correctly, just unnecessary.

### L-03: `TEAM_PATTERNS` has overlapping entries across games

**File:** `src/polymarket_analytics/extraction/patterns.py`
**Impact:** Ambiguous team matching when same org plays multiple games (G2, Cloud9). Mitigated by game context in most pipelines.

### L-04: `sanity_check.py` hardcodes 30-day window

**File:** `src/polymarket_analytics/commands/sanity_check.py`
**Impact:** Inconsistent with configurable `scoring_window_days`. Only affects sanity check reporting, not scoring.

### L-05: `LLMFallback.extract` uses blocking `time.sleep()`

**File:** `src/polymarket_analytics/extraction/llm.py`
**Impact:** Blocks event loop when called from async context. Only affects LLM fallback retries (rare path).

### M-07: No alert on Anthropic API insufficient funds

**File:** `src/polymarket_analytics/extraction/llm.py`
**Impact:** When the Anthropic API returns an "insufficient funds" / billing error, the pipeline silently falls back to empty extraction. Should trigger a Telegram alert via `health/notify.py` so the user knows to top up the account before LLM-dependent features degrade.

### M-08: Take profit after 50% move in favoured direction — **FIXED 2026-04-16**

`polymarket --niche esports paper-take-profit` added. Runs in two phases each cron pass:

1. **Check-back** — fills `final_outcome` in `take_profit_log` for previously exited positions whose market has since resolved in analytics.db. Shows counterfactual P&L: `(final_price - exit_price) × shares`. Positive = left gains on table; negative = loss avoided.
2. **Scan** — exits any open position where `live_price >= avg_entry_price * threshold` (default 1.5×). Sells via `engine.sell()`, logs TAKE_PROFIT to both `bridge_decisions` and a new `take_profit_log` table. Supports `--dry-run` and `--threshold`.

Runs in monitor `--chain` (every poll cycle) alongside `paper-bridge`. Removed from cron (session 4).

---

### P-01: Incremental `build-positions` — **FIXED 2026-04-16**

Fixed via dirty_pairs in-memory set (monitor path) and timestamp watermark CTE (cron path). Commit `ff98baf`. Monitor path skips the 7.2M-row dirty scan entirely. Watermark only written on cron path to prevent eclipse (commit `83657fc`).

### P-02: Missing index on `positions.last_trade_timestamp` — **FIXED 2026-04-16**

Added `idx_positions_last_trade_ts` and `idx_trades_ts_trader_market` covering index. Commit `ff98baf`.

### P-03: Monitor lock — **FIXED**

Monitor now acquires the same `.pipeline.lock` cron uses (`src/polymarket_analytics/health/lock.py:91`). Each poll pass wraps in `with pipeline_lock("monitor", lock_path=lock_path)` (`monitor.py:668`); if cron holds the lock, the pass is skipped with `Pipeline locked by {holder} — skipping this pass`. Per-trader transactions release the write lock between traders (`monitor.py:483`) so the lock isn't held continuously. Operational matrix documented in `OPERATIONS.md:124-128`.

### P-04: Price cache across `paper-bridge` + `paper-take-profit`

**Impact:** Both commands run back-to-back in cron and hit the live API independently for overlapping markets. Could share a price snapshot to avoid duplicate API calls for the same tokens.

---

### L-06: Add structured error context to pipeline stages

**Impact:** When errors occur in long-running processes (backfill, cron), debugging requires reading source code to triangulate. Adding stage-tagged logging, error aggregation with categories, and context managers would make failures self-diagnosing. Not urgent — current `✗ addr: error` output works, just lacks stage/category tagging for fast triage.

---

---

## Session 3 handoff — 2026-04-15

### Done this session (commit 956f297)

**analytics.db — 16,013 voided positions resolved**
- Root cause: 1,547 markets are genuinely voided/cancelled (games that never happened). Both Gamma and CLOB return `closed=True` but no outcome data — confirmed by sampling 20 across dates back to July 2025.
- Impact: `detect_convergence` queries `WHERE resolved=0`, so all void positions were generating false paper trading signals.
- Fix: `resolution.py` VOID pass — marks positions where `(m.resolved=1 OR m.active=0) AND m.outcome IS NULL` as `resolved=1, outcome='VOID', pnl=0`. Runs before the outcome/FLAT passes.
- Fix: `extraction.py` adds `AND m.outcome IS NOT NULL` to exclude VOID positions from CLV/ROI/Sharpe scoring.
- State: 16,013 VOID, 109,369 genuinely open.

**paper_dashboard.py — --resolve crash bug fixed**
- Root cause: `engine.resolve_all()` called `api.get_market(slug)` in a loop. First `MarketNotFoundError` (delisted slug) aborted the entire loop — not in the caught `(ApiError, ConnectionError, TimeoutError, OSError)` list.
- Fix: replaced with a per-market loop catching `SimError` (base class of all pm_trader errors) so one bad slug doesn't abort the rest.

### Paper positions not resolving — **FIXED 2026-04-15** (commit 9e913d5)

Bypassed `engine.resolve_market()` entirely. New `_do_resolve()` cross-references `paper.db positions` by `market_condition_id` against `analytics.db markets WHERE active=0 OR resolved=1` — same condition used by `resolve-positions`. Team-name → YES/NO mapping uses the `outcomes[]` array from `paper.db market_cache` (populated at trade time, no live API calls). VOIDs refund stake at break-even. `paper-resolve` step added to `cron_pipeline.sh` after `paper-bridge`.

_Reviewed: 2026-04-09_
_Updated: 2026-04-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
