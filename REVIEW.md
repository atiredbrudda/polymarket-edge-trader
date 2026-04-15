# Code Review: Polymarket Analytics Pipeline

**Reviewed:** 2026-04-09
**Updated:** 2026-04-15 (session 3)
**Depth:** deep (cross-file analysis)
**Files Reviewed:** 20
**Status:** mostly_resolved (14 fixed, 3 acceptable, open: paper resolution)

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

## Remaining Open

### H-06: Paper trading results monitor/dashboard — **FIXED 2026-04-15**

`polymarket --niche esports paper-dashboard` added. Shows: account summary (cash, deployed, realized P&L), top open positions, bridge decision stats (last N days), recent trades. Includes `--reset` (account wipe + reinit), `--resolve` (settle closed markets), and a low-cash alert that fires when cash < $500 (preventing silent SKIP_SIZE rundown).

---

## Remaining Open (Low Impact)

### H-04: `discover` uses synchronous HTTP for trade fetching

**File:** `src/polymarket_analytics/commands/discover.py`
**Impact:** Performance bottleneck when discovering many markets. Not a correctness issue.
**Note:** Low priority — discover runs infrequently and processes fewer markets than backfill.

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

### M-08: paper-bridge shows ERR for current price on some markets, silently skips

**Observed:** 2026-04-13, multiple cron runs. Several signals show `ERR` in the current price column and get skipped at trade time. Affects markets where live price fetch fails (API unavailable, token not found, etc.).
**Impact:** Silent missed trades — the signal is valid but never executed. No alert is raised, no count of ERR-skipped trades appears in the daily summary.
**Fix direction:** Count ERR skips separately from intentional SKIP_API/SKIP_CONF skips in the paper-bridge summary. Optionally alert if ERR rate exceeds a threshold.

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

### Still broken — paper positions not resolving (next session)

After fixing the crash, `--resolve` says "No closed markets to resolve" for all 195 positions. Root cause: `engine.resolve_market()` depends on the **live Gamma API** to determine `market.closed` and `outcomePrices >= 0.99`. The Gamma API is unreliable for this — returns `closed=False` or `active=True` for many resolved markets, 404 for delisted slugs.

**The fix:** bypass `engine.resolve_market()` entirely. Resolve paper positions from analytics.db directly:

1. Read `paper_bridge.py` first — understand what `outcome` string is stored when a paper buy is placed (team name like "invictus gaming" vs YES/NO). This determines how to map to analytics.db `markets.outcome`.
2. In `_do_resolve()`, cross-reference `paper.db positions.market_condition_id` → `analytics.db markets` where `resolved=1 AND outcome IS NOT NULL`.
3. Determine payout: if position outcome maps to winning side → `shares * 1.0`, else `0.0`.
4. Write directly to paper.db: `UPDATE positions SET is_resolved=1, realized_pnl=payout, resolved_at=...` + update account cash.
5. Add this step to the launchd cron (after `paper-bridge`) so it runs every 4h automatically.

**Key state:** Paper account has $49.19 cash (LOW CASH), 195 open positions, 0 resolved, 655 total trades. All 195 stuck because the crash has been silently failing since 2026-04-11.

_Reviewed: 2026-04-09_
_Updated: 2026-04-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
