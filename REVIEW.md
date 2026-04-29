# Code Review: Polymarket Analytics Pipeline

**Reviewed:** 2026-04-09
**Updated:** 2026-04-29 (session 17: heal retry escalation; review trimmed to open items only)
**Status:** open items below; resolved findings live in git history + wiki

## Scope

This document tracks **open** review findings only. Resolved items have been pruned — their fix is in `git log` and the lesson, where it generalizes, is in the wiki at `/Users/macbookair/Documents/project/test/rerun7/LLM Wiki/workspaces/polymarket/wiki/`. See `wiki/index.md` for the cross-reference.

If you need a resolved item's context: `git log --oneline --all | grep <topic>` or search the wiki by feature name.

---

## Scheduled — Polymarket CLOB v2 Migration

### S-01: CLOB v2 cutover — **ATTEMPTED 2026-04-28, ROLLED BACK**

**Status:** rolled back. Pipeline running on v1 (`clob.polymarket.com`).

**Wiki:** [[CLOB v2 Cutover (2026-04-28) — Rolled Back]] has the full post-mortem (what broke, why the 04-18 audit was wrong, re-attempt criteria).

**Next probe: 2026-05-05.** Run `curl -I https://clob-v2.polymarket.com/midpoint?token_id=<any>`. If response is `HTTP/2 200` (not 301), check Polymarket's status page and re-attempt the cutover. If still 301, roll the probe forward another 1–2 weeks.

**Re-attempt criteria (don't flip env var until all true):**
- `curl -I https://clob-v2.polymarket.com/midpoint?token_id=<known-good>` returns `HTTP/2 200` (not 301).
- Polymarket announcement that v2 is canonical (not a parking redirect).
- `paper-bridge --dry-run` smoke test against v2 returns real prices.

**Cutover playbook** (run on re-attempt day):

```bash
cd /Users/macbookair/polymarketv2
.venv/bin/pip install --upgrade --force-reinstall \
  "polymarket-paper-trader @ git+https://github.com/atiredbrudda/polymarket-paper-trader.git"
export POLYMARKET_CLOB_URL="https://clob-v2.polymarket.com"
.venv/bin/polymarket --niche esports paper-bridge --dry-run
# rollback: unset POLYMARKET_CLOB_URL
```

Add the export to whatever cron sources its env (crontab wrapper, `.env`, systemd unit).

---

## Open Findings

### H-04: `discover` sequential HTTP — 45 min for 283 markets

**File:** `src/polymarket_analytics/commands/discover.py:57-69`
**Impact:** `_fetch_market_trades()` is synchronous httpx, called once per market in a sequential loop. Each call takes ~9s (network round-trip even for empty markets). 283 markets × 9s = 45 minutes. This is the cron bottleneck.

**Root cause of high market count:** Each BO3 match spawns 23–37 Polymarket markets (winner, map winners, game handicaps, first blood, baron nashor, penta kill, total kills O/U, odd/even kills, etc.). Most are prop markets with zero trades — nobody bets on "Any Player Penta Kill?" — but discover fetches trades for all of them.

**Measured 2026-04-16:** 295 markets in `--closing-within 4` window, 12 cached, 283 processed. Of those, 603 had zero trades. Discover spent 45 min fetching nothing for most of them.

**Fix options (pick one or both):**
1. **Concurrent fetching** — use `asyncio.Semaphore(10)` like monitor does. 283 markets / 10 concurrent = ~4.5 min instead of 45 min. Straightforward refactor of `_fetch_market_trades` → async.
2. **Skip zero-volume markets** — Gamma API response includes `volumeNum`. Skip markets with `volumeNum == 0` before fetching trades. Eliminates ~60% of fetches.

### M-02: Graph side determination wrong for token-for-token swaps

**File:** `src/polymarket_analytics/api/graph.py`
**Impact:** Token-for-token swaps (both assets non-zero) always classified as SELL. Rare edge case on Polymarket esports markets.

### M-07: No alert on Anthropic API insufficient funds

**File:** `src/polymarket_analytics/extraction/llm.py`
**Impact:** When the Anthropic API returns an "insufficient funds" / billing error, the pipeline silently falls back to empty extraction. Should trigger a Telegram alert via `health/notify.py` so the user knows to top up the account before LLM-dependent features degrade.

### M-09: Heal scan returns mostly-noise — irredeemable + no-position-row pairs

**Found:** 2026-04-27 (session 14). **Updated:** 2026-04-29 (auto-retry escalation shipped, but the scan-noise issue remains).
**Files:** `scripts/heal_trapped_batch.py` (TRAPPED_TRADERS_SQL line ~80), `src/polymarket_analytics/positions/aggregation.py`
**Wiki:** [[Heal Loop Daemon]] now documents the heal mechanics + retry escalation; M-09 covers what's still leaky.

**Symptom:** every heal scan reports thousands of trapped pairs but most have no actionable work attached. Latest live count: 1,549 trapped traders / 5,862 trapped pairs. Of those, hundreds are already-irredeemable position rows (`data_incomplete=1, graph_retry_count>=3`) that the scan SQL doesn't filter, plus pairs with no `positions` row at all that heal can't mark.

**Root causes:**

1. **`TRAPPED_TRADERS_SQL` only filters by `traders.graph_unservable`, not by per-pair irredeemable markers.** Heal does mark exhausted pairs (`positions.data_incomplete=1, graph_retry_count=3`), but the next scan still sees them.
2. **`build_positions_from_trades` skips sell-only pairs**, so trapped pairs with no `positions` row exist invisibly. heal can't mark them irredeemable (the UPDATE only touches existing rows).
3. **Auto-retry drains `failed`, but the scan population itself doesn't shrink** because of #1 and #2. The recent retry-escalation feature (2026-04-29) graduates whales to `graph_unservable=1`, which DOES shrink the scan — but only along that axis.

**Three fix options, in order of cleanliness:**

1. **Per-pair attempt tracking.** New `heal_attempts` table or column: `(trader, market, last_attempt_at, status)`. Scan filters out pairs attempted in the last N days. Works whether or not a position row exists. ~2h work.
2. **Always create position rows for sell-only pairs in `build_positions_from_trades`.** Then irredeemable-marking covers everyone. Bigger blast radius — downstream consumers (scoring, paper bridge) may not expect sell-only positions.
3. **Mark `traders.graph_unservable=1` when 100% of their trapped markets are dead-ended.** Simplest. Loses ability to re-attempt later if Goldsky catches up — but Goldsky catching up is rare.

**Recommended:** option 3 if the trapped backlog is predominantly historical; option 1 if new trapped pairs flow in steadily with new market activity. Track the trapped-pair count over the next 1–2 weeks to decide.

### P-04: Price cache across `paper-bridge` + `paper-take-profit`

**Impact:** Both commands run back-to-back in cron and hit the live API independently for overlapping markets. Could share a price snapshot to avoid duplicate API calls for the same tokens.

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

### L-06: Add structured error context to pipeline stages

**Impact:** When errors occur in long-running processes (backfill, cron), debugging requires reading source code to triangulate. Adding stage-tagged logging, error aggregation with categories, and context managers would make failures self-diagnosing. Not urgent — current `✗ addr: error` output works, just lacks stage/category tagging.

---

## Acceptable / By Design

| ID   | Finding                                    | Status                                                                                                                                                                                                  |
|------|--------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| H-02 | `trades.market_id` has no FK to `markets`  | By design — backfill ingests trades for markets not yet discovered. FK on `token_id` enforced; trades without catalog entries are skipped.                                                              |
| M-06 | Resolution UPDATE ordering dependency      | Acceptable — ordering is correct and both UPDATEs run in same transaction. Fragile but functional.                                                                                                       |
| L-02 | `extraction.py` swallows all exceptions    | Acceptable — defensive fallback to empty DataFrame. Low-risk since extraction failures are visible downstream (no scores generated).                                                                     |

---

_Reviewer: Claude (gsd-code-reviewer)_
_Last open-items audit: 2026-04-29_
