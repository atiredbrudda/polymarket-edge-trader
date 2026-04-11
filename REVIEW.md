# Code Review: Polymarket Analytics Pipeline

**Reviewed:** 2026-04-09
**Updated:** 2026-04-11 (session 2)
**Depth:** deep (cross-file analysis)
**Files Reviewed:** 20
**Status:** mostly_resolved (13 fixed, 3 acceptable, 3 minor open)

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

---

_Reviewed: 2026-04-09_
_Updated: 2026-04-11_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
