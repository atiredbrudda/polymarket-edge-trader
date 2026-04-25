# Code Review: Polymarket Analytics Pipeline

**Reviewed:** 2026-04-09
**Updated:** 2026-04-21 (session 11: H-09 fixed)
**Depth:** deep (cross-file analysis)
**Files Reviewed:** 20
**Status:** mostly_resolved (19 fixed, 3 acceptable, open: H-04)
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

### N-01: Daily notification metrics wrong — **FIXED 2026-04-21**

**Files:** `scripts/cron_pipeline.sh`, `src/polymarket_analytics/commands/health_check.py`, `src/polymarket_analytics/health/checks.py`

Two bugs found from cron log analysis:

1. **`traders_backfilled` was a 24h rolling DB count**, not a per-run count. A lean run of 248 traders reported "Traders backfilled: 18,616" because the 24h window still included the previous day's 18,456-trader full backfill. The number was technically correct but completely misleading.

2. **Failed stages were silently dropped from the daily notification.** `cron_pipeline.sh` called `health-check --tier daily` with no `--stages-failed` arg. The Apr 21 midnight full backfill exit 137 produced a clean-looking daily summary with no mention of the failure.

**Fix:** `RUN_START` timestamp captured at cron start, passed as `--run-start` to daily health check. `daily_summary()` now uses `last_backfilled_at >= run_start` (this-run window) instead of `>= now-24h`. Notification label shows `"Traders backfilled (this run)"` vs `"(24h)"`. `FAILED_STAGES` (space-separated) converted to CSV and passed as `--stages-failed`.

---

### H-08: Zero-trade traders never get `last_backfilled_at` set — **FIXED 2026-04-21**

**File:** `src/polymarket_analytics/commands/backfill.py:561`

`last_backfilled_at` was only stamped when `stats["ingested"] > 0 or stats["skipped"] > 0`. Traders that returned nothing from both API and Graph stayed `IS NULL` forever and were re-selected on every `--new-only` lean run.

**Fix:** `last_backfilled_at` now stamped unconditionally after every API+Graph attempt. `last_trade_seen_at` and `backfill_complete` remain conditional on actual trades found.

---

### H-09: Full backfill OOM-killed at 19k traders — **FIXED 2026-04-21**

**File:** `src/polymarket_analytics/commands/backfill.py`

Root cause: Phase A gathered all 19k API responses via `asyncio.gather` into `fetch_results` before Phase B began. Peak memory = `n_traders × avg_response_size` (observed ~19k × response → SIGKILL).

**Fix:** Merged Phase A + Phase A.5 + Phase B into a single `_fetch_and_process` coroutine per trader under one `semaphore=10`. Memory now bounded to `CONCURRENT_LIMIT × avg_response_size` (~10 responses at once). Sell-only Graph fallbacks run inline inside `backfill_trader` (unchanged path — `prefetched_graph=None` was already handled). Phase A.5 pre-fetch removed: with concurrent Phase B it provided no wall-clock benefit (same `semaphore=10` throughput either way; the "~10x" claim from commit `e5bf4a2` only applied when Phase B was sequential, before commit `b48528f` made it concurrent).

---

### H-07: `ingest-events --full` OOM hang on memory-constrained runs — **FIXED 2026-04-21**

**Files:** `src/polymarket_analytics/api/gamma.py:67` / `src/polymarket_analytics/commands/ingest_events.py:97`

`fetch_markets(closed=True)` was paginating all ~115k+ closed markets (~575 pages) into memory. Observed 2026-04-20: stuck at page 575 for 40+ min, required manual kill. httpx read timeout was already set (60s). The real problem was fetching all historical closed markets when only the last 7 days are needed for resolution chain freshness.

**Fix:** Added `end_date_min` param to `fetch_markets` in `gamma.py`. `ingest_events.py` closed sweep now passes `end_date_min = now − 7 days` (no `end_date_max`, so voided markets with future endDates are still captured). Probed live: Gamma API confirmed to support both params. Result: ~115k markets / 575 pages → ~10k markets / 52 pages (~91% reduction). Voided/cancelled markets (165 total, 1 page) remain included via the no-max approach.

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

## Session 10 handoff — 2026-04-21

### Done this session
- **H-08 FIXED** — `last_backfilled_at` now stamped unconditionally; zombie traders cleared from lean run queue
- **H-07 FIXED** — `ingest-events --full` closed sweep limited to last 7 days via `end_date_min`; 575 pages → 52 pages. Gamma API date filter confirmed working via live probe.

### Pending next session (priority order)
1. **H-04** — discover sequential HTTP (lower priority)

---

## Session 11 handoff — 2026-04-21

### Done this session
- **H-09 FIXED** — Phase A/A.5/B gather-all replaced with single `_fetch_and_process` coroutine per trader under one `semaphore=10`. Memory bounded to 10 responses at once instead of 19k. Phase A.5 Graph pre-fetch removed (redundant with concurrent Phase B — same throughput math). Sell-only Graph fallbacks run inline in `backfill_trader` (existing `prefetched_graph=None` path).

### Pending next session (priority order)
1. **H-04** — discover sequential HTTP (45 min / 283 markets). Compare full backfill performance against prior OOM run to confirm fix.

---

## Session 9 handoff — 2026-04-21

### Done this session
- **N-01 FIXED** — daily notification metrics corrected: `traders_backfilled` now scoped to current run via `--run-start`, failed stages passed via `--stages-failed`
- **Cron log audit** — reviewed all backfill runs since cron went live; confirmed Apr 21 midnight full OOM-killed (exit 137), marker never updated
- **H-08, H-09 identified and documented** — zombie traders + full backfill OOM

### Pending next session (priority order)
1. **H-09** — full backfill OOM at 19k traders. Discuss chunked approach vs concurrency reduction vs fixing H-07 first
2. **H-07** — `ingest-events --full` 115k closed market pages. Fix: `end_date_min = now − 7 days` + `httpx.Timeout(30.0)`
3. **H-08** — zombie traders never getting `last_backfilled_at` set. Simple one-liner fix
4. **H-04** — discover sequential HTTP (lower priority, prop filter reduced market count)

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

---

## Session 12 handoff — 2026-04-25

### Done this session
- **Heal script patches** (`scripts/heal_trapped_batch.py`):
  - Added `failed` set tracking in progress JSON; skips known-failed traders on `--resume`
  - Added `--retry-failed` flag to opt-in re-attempt
  - Auto-marks irredeemable: `data_incomplete=1, graph_retry_count=3` on positions where Graph fetch succeeded but markets stayed trapped
  - Seeded 21 known-failed addresses into progress file from prior run logs
- **3 heal runs completed:** 2,939 → 2,853 trapped pairs (−74), 37k trades inserted, 76 markets healed across 100 attempted traders
- **Diagnosed 8.7h midnight backfill** (vs 3h target) — caused by 6 whale traders generating 147 Graph pagination fallback events: `0x21ffd2b7`, `0x5df52b96`, `0x7edb8d9e`, `0xa3c2ec15`, `0xe9076a87`, `0xf68a2819`
- **Trapped cohort taxonomy:**
  - `exhausted` (positions row, `data_incomplete=1`) — already excluded from backfill
  - `no_pos` orphans (no positions row, ~3,080 pairs) — caused by old `trade_id` PK collision bug; 1,381 won't ever auto-prune (626 still-open + 755 markets-table-missing)
- **DB-level findings (verified):**
  - `wal_autocheckpoint = 1000 pages = 3.9 MB` on a 14.6 GB DB — too aggressive
  - `cache_size = -2000` (2 MB) — shockingly small; monitor SELECTs hit disk constantly
  - `busy_timeout`: monitor/backfill have 30s ✓; **heal uses 5s default** (bypasses `get_db()`)
- **Latent scoring pollution:** `src/polymarket_analytics/scoring/extraction.py:43-62` does NOT filter `data_incomplete=1`. 1,715 incomplete positions currently feed the 30d esports scoring set (~0.28% pollution). Dashboard (`serve.py:281`) does filter; only scoring path doesn't.

### Plan for next session

**Goals (in priority order):**
1. Full backfill ≤4h (currently 8.7h)
2. Data integrity (no scoring pollution, no real-data loss)
3. Zero monitor stalls
4. Continuous heal alongside cron + monitor

**Implementation order — ship-now items (safe during experiment):**

1. **PRAGMA tune** in `src/polymarket_analytics/db/connection.py`:
   - `PRAGMA wal_autocheckpoint = 10000` (3.9MB → 40MB; 10× fewer checkpoint lock spikes)
   - `PRAGMA cache_size = -200000` (2MB → 200MB; cuts monitor SELECT I/O)
   - Keep `synchronous = 2` (don't trade durability)
   - One PR; pure config; reversible

2. **Heal politeness** (`scripts/heal_trapped_batch.py`):
   - Route through `get_db()` instead of raw `sqlite_utils.Database()` (inherits 30s busy_timeout)
   - Chunk `db["trades"].insert_all` into 500-row pieces with `await asyncio.sleep(0.05)` between chunks
   - Drops max lock-hold from ~1500ms to ~50ms per chunk
   - One PR; local to heal script

3. **`graph_unservable` flag on traders** (~50 lines `src/polymarket_analytics/commands/backfill.py`):
   - New column `graph_unservable INTEGER DEFAULT 0` on `traders`
   - Promote trader to `graph_unservable=1` after 2 consecutive timeouts in full-backfill mode
   - Full backfill `WHERE graph_unservable = 0` to skip them
   - Lean backfill (small deltas) still serves them — incremental fetches typically fit one window
   - Heal script also reads this flag and skips
   - Estimated speedup: midnight cron 8.7h → ~3h
   - One PR

4. **heal_loop daemon** (`scripts/heal_loop.sh` + launchd plist):
   ```
   loop:
     if data/.pipeline.lock exists → sleep 5min, continue   (cron has it)
     if data/.monitor_heartbeat <10s old → sleep 20s, continue   (monitor mid-cycle)
     if heal queue empty → sleep 1h, continue
     run: heal_trapped_batch.py --resume --limit 10 --batch-size 10
     sleep 30min
   ```
   - Monitor must touch `data/.monitor_heartbeat` at the start of each poll cycle (~5 lines in `monitor.py`)
   - One PR

**Deferred items (post-experiment, ~7 days from now ≈ 2026-05-02):**

5. **Patch `scoring/extraction.py`** — add `AND COALESCE(p.data_incomplete, 0) = 0` to the WHERE clause
   - Fixes the 1,715-row latent pollution
   - Will shift z-scores; **DO NOT ship during experiment**
   - Re-run scoring + signal generation after merge

6. **Snapshot + delete `no_pos` orphan SELLs** (mirror `scripts/prune_resolved_40d.py` pattern)
   - Snapshot orphan trades to `data/audit/orphan_sells_<date>/` first
   - Guards: trader must be in `heal_trapped_batch_progress.json` `completed` set; pair must still have `buys=0 sells>0` at delete time
   - Single transaction with verification queries
   - Brings trapped count to ~zero permanently

### Bot vs retail finding (informational, not action item)
Of the 6 whales blocking backfill, only 2 are clear bots/MMs (`0x7edb8d9e` HFT @ 28s IAT, `0xf68a2819` MM batches at 0s IAT). Others are long-lived/wide-spread retail. Operational signal "Graph can't serve them" matters more than identity classification — the `graph_unservable` flag handles all six the same way.

### Operational notes
- Lock file pattern `data/.pipeline.lock` confirmed in both `scripts/cron_pipeline.sh:32` and `monitor.py:677` — heal_loop must respect it
- Heal progress file: `data/audit/heal_trapped_batch_progress.json` (1,150 completed + 21 failed as of session end)
- During experiment (~7 days): pause additional heal runs; each insert changes positions → scoring drift

---

## Session 13 handoff — 2026-04-25

### Done this session — all 4 ship-now items from session 12 plan

1. **PRAGMA tune** (`src/polymarket_analytics/db/connection.py`):
   - `wal_autocheckpoint = 10000` (3.9MB → 40MB)
   - `cache_size = -200000` (2MB → 200MB)
   - Verified live: `(10000,)` and `(-200000,)` round-trip on a fresh `get_db()`.

2. **Heal politeness** (`scripts/heal_trapped_batch.py`):
   - Routed through `get_db()` (inherits 30s busy_timeout + new PRAGMAs)
   - `db["trades"].insert_all` chunked to 500 rows with `await asyncio.sleep(0.05)` between chunks
   - `TRAPPED_TRADERS_SQL` now joins `traders` and excludes `graph_unservable=1`

3. **`graph_unservable` flag** (`db/schema.py` + `commands/backfill.py`):
   - Migration adds `graph_unservable INTEGER DEFAULT 0` and `graph_timeout_streak INTEGER DEFAULT 0` on `traders`
   - `GRAPH_UNSERVABLE_THRESHOLD = 2`. Streak increments on Graph timeout (`httpx.ReadTimeout`/`ConnectTimeout`/`asyncio.TimeoutError`) and resets on success
   - Promotion only happens when caller passes `track_graph_streak=True` (full backfill only — lean leaves it alone)
   - Full backfill query filters `COALESCE(graph_unservable, 0) = 0`; lean keeps serving them
   - Live DB migration verified: 22,980 traders, 0 currently flagged

4. **heal_loop daemon** (`scripts/heal_loop.sh` + `scripts/com.polymarket.heal-loop.plist`):
   - Loop invariant: defer to `data/.pipeline.lock` (5min cooldown), `.monitor_heartbeat <10s` (20s cooldown), heal `--limit 10 --batch-size 10` then sleep 30min, long nap (1h) when queue empty
   - `monitor.py` touches `data/.monitor_heartbeat` at top of every poll cycle
   - Plist not auto-loaded — install via `launchctl load ~/Library/LaunchAgents/com.polymarket.heal-loop.plist`

### Validation
- `pytest`: 165 passed, 8 pre-existing failures (`test_enrichment.py` + `test_graph.py`) — confirmed unrelated by stash + re-run
- `heal_trapped_batch.py --dry-run --resume`: 1,053 servable trapped traders, 1,173 completed, 23 failed
- Live DB schema: both new columns present, defaults correct

### Wiki
- New: [[Graph Unservable Flag]], [[Heal Loop Daemon]], [[SQLite PRAGMA Tune]]
- Cross-refs added: [[Market Maker Bot Detection]], [[Graph Pagination Truncation]], [[index]]

### Pending (deferred to ~2026-05-02 per session 12 plan)
- Patch `scoring/extraction.py` to filter `data_incomplete=1` (would shift z-scores during experiment)
- Snapshot + delete `no_pos` orphan SELLs (audit guard pattern, mirror of `prune_resolved_40d.py`)
- Manual: `launchctl load` the heal-loop plist when ready

---

_Reviewed: 2026-04-09_
_Updated: 2026-04-25 (session 13: PRAGMA tune + heal politeness + graph_unservable + heal_loop)_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
