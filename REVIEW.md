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

### H-10: `graph_unservable` traders fall into a backfill coverage hole — **CHEAP FIX SHIPPED 2026-05-02; option #2 (auto-clear) still pending**

**Found:** 2026-05-01. **Trigger:** comparing Polymarket REST `/trades?user=` vs DB for `0x8c0b024c17831a0dde038547b7e791ae6a0d7aa5`.

**File:** `src/polymarket_analytics/commands/backfill.py:709-734`

**Status (2026-05-02):**
- ✅ **Resolved via M-09 expansion (heal Data API path)**, not via lean modification. Initial cheap-fix attempt in lean was reverted in favor of the cleaner architecture: heal owns graph_unservable maintenance, lean stays focused on newly-discovered traders. See M-09 entry below for shipped details.
- The 56 graph_unservable traders that have trapped pairs are now serviced via `heal_one_trader_via_api` in `scripts/heal_trapped_batch.py`, which uses `DataAPIClient` (no Goldsky timeouts) and updates `traders.last_trade_seen_at` / `last_backfilled_at` incrementally each heal pass.
- The remaining 48 graph_unservable traders without trapped pairs continue to be served only by monitor's REST polling — same as before. They have no positions or trapped data so heal has no work for them; this is the expected steady state.
- 🔁 Option #2 (auto-clear flag after N successful Data API heals) still pending. Less urgent now: the Data API path means flag traders aren't dead-ended; they get routine updates every heal pass.
- 📋 Validation: after the next monitor poll cycle that runs heal, re-run the audit query for `0x8c0b024c…` against `data-api.polymarket.com/trades?market=…` for the 04-30 window. Taker-side fills should reconcile; maker-side recovery still requires Goldsky (out of scope here).

**Impact:** 94 traders flagged `graph_unservable=1` are silently excluded from **both** lean and full backfill, so their trade history only gets updated by `monitor` (REST `/trades?user=`, taker-side, partial). Confirmed data loss: for the audit trader (a market-maker, 193 positions, ~20k trades), the DB is missing trades from 2026-04-30 15:31–16:21 in 3 known markets that REST clearly exposes — including 4 large fills in `lol-shft-vit-game1` (~$25k notional). Reproduced via last-15 comparison: 5/15 matched.

**Root cause:** the two backfill SQL queries both filter the trader out:

1. **Full mode** (line 724-735) — `AND COALESCE(graph_unservable, 0) = 0` explicitly skips them. Comment justifies this with the midnight-cron 4h budget.
2. **Lean / `--new-only` mode** (line 712-719) — only picks `last_backfilled_at IS NULL`. The code comment at line 710-711 claims "Lean mode keeps serving graph_unservable traders," but the SQL doesn't match the intent: as soon as a graph_unservable trader is backfilled once, `last_backfilled_at` is set and they fall out of the lean selection forever.

So the steady state for any trader who ever gets `graph_unservable=1` is: full skips them, lean skips them, only monitor's REST polling touches them — and REST `?user=` only exposes one side per fill (the proxyWallet side), giving no maker-side recovery.

**Audit (2026-05-01):**
```sql
SELECT COUNT(*) AS total_unservable,
       SUM(CASE WHEN last_backfilled_at IS NOT NULL THEN 1 ELSE 0 END) AS in_coverage_hole,
       SUM(CASE WHEN last_backfilled_at IS NULL THEN 1 ELSE 0 END) AS never_backfilled
FROM traders WHERE graph_unservable = 1;
-- total_unservable=94, in_coverage_hole=94, never_backfilled=0
```
100 % of graph_unservable traders are in the hole.

**Fix options:**

1. **Cheap fix** — broaden lean selection to actually do what the comment claims:
   ```sql
   WHERE last_backfilled_at IS NULL
      OR (graph_unservable = 1 AND last_backfilled_at < :threshold)
   ```
   Lean re-fetches graph_unservable traders on the same 6h cadence full backfill uses for normal traders. Incremental `since_unix_ts` from `last_trade_seen_at` keeps payloads small per the original design intent.

2. **Proper fix** — make `graph_unservable` recoverable. Auto-clear the flag after N successful Data API fetches in a row, or after a backoff window (e.g. clear if `graph_timeout_streak=0` for 7 days). Re-include in full backfill once cleared. Pair with #1 so they're served while waiting to graduate back.

3. **Out of scope here, but related**: REST `?user=` only returns one row per fill, so even with #1 the maker-side recovery is still subgraph-dependent. Worth re-validating that subgraph timeouts that triggered `graph_unservable` are still a real problem at 2026-05-01 traffic levels — the threshold may be over-tuned.

**Recommended:** ship #1 immediately (one-line SQL change, low blast radius), then #2 to prevent the hole from re-forming.

### H-11: ~27% of resolved markets have zero trades ingested — uncataloged-token silent drop — **FIX #1 SHIPPED 2026-05-02; #2 + #3 still pending**

**Status (2026-05-02):**
- ✅ Fix #1 shipped: backfill self-heals `token_catalog` from `trade["conditionId"]` when the API trade arrives but the catalog row is missing. New stat `self_healed_catalog` counts heals per backfill run. Race-safe via `INSERT ... ignore=True`. FK violations (rare — would need the market itself to also be missing) fall through to the existing skip path.
- 🔁 Fix #2 (discover.py retry on empty `clobTokenIds`) still pending. Without it, new markets with the Gamma race condition still arrive without catalog rows; the backfill self-heal patches them up *if* a trade arrives, but markets with zero post-resolution trade activity stay uncataloged. Low-impact gap.
- 🔁 Fix #3 (`backfill_drops` observability table) still pending. Today the only signal is the new `self_healed_catalog` stat (positive case) and the existing `stats["skipped"]` (negative case, still opaque). For a future audit pass to query "what was dropped and why", the drops table would help.
- 📋 Validation: after monitor runs a few cycles, query `SELECT SUM(...)` on backfill output for non-zero `self_healed_catalog` counts. Re-sample previously-zero-trade resolved markets against the Polymarket API; expect ~15-17% to start populating after subsequent backfill runs touch their tokens.

---

**Found:** 2026-05-01 (audit chain from H-10 sampling).
**Files:** `src/polymarket_analytics/commands/discover.py:279-320`, `src/polymarket_analytics/commands/backfill.py:520-528`

**Symptom:** the `markets` table contains thousands of resolved esports markets that have **zero rows** in the `trades` table — even when those markets had real trade activity that's still visible on the live Polymarket API.

**Audit (2026-05-01):**
```sql
-- Resolved markets that closed in April 2026
total=13351, with_trades=9677, zero_trades=3674   (27.5%)
-- All-time
total=56184, with_trades=18838, zero_trades=37346 (66.5%)
```
Spot-check of 5 random zero-trade April markets against live `data-api.polymarket.com/trades?market=…`: 3 of 5 have real trades on the API right now (`dota2-z10-lynx-2026-04-13`: 4 trades, `lol-me1-phx2-2026-04-16`: 10, `r6siege-sz-dk-2026-04-17`: 6); 2 of 5 are legitimately empty (low-liquidity markets nobody traded). So the bug-affected rate is real but not 100% of the zero-trade pool — adjust the audit number to ~60% × 27.5% ≈ **15–17% of resolved April markets actually have trades that were silently dropped during ingest**.

**Root cause — two-step silent drop:**

1. **`discover.py:279-286` skips `token_catalog` insert when `clobTokenIds` is empty.**
   ```python
   clob_token_ids = m.get("clobTokenIds") or []
   ...
   if not clob_token_ids:
       continue
   ```
   Gamma's response sometimes returns markets without `clobTokenIds` populated (likely race conditions on freshly-deployed markets, or Gamma response inconsistency). The market still gets upserted into `markets` (line 256-269), but `token_catalog` never gets the tokens. Verified: 14 of 15 sampled zero-trade April markets have `markets.tokens = '[]'` AND zero rows in `token_catalog`.

2. **`backfill.py:520-528` silently drops every trade whose token isn't in the catalog.**
   ```python
   if not token_id:
       stats["skipped"] += 1
       continue

   # Token catalog lookup: resolve token_id -> condition_id (from cache)
   condition_id = catalog_cache.get(str(token_id))
   if not condition_id:
       stats["skipped"] += 1
       continue
   ```
   When backfill fetches a trader's API trades and a returned trade's token_id isn't in `token_catalog`, it can't resolve `market_id`, so it skips. The skip is counted as a stat but never logged with which market or token, so the failure is invisible.

**Compounding factor:** `discover.py:546-552` has a fallback path that inserts trades with `token_id_val=None` (bypassing the FK) when the token isn't cataloged. So discover-path inserts can succeed where backfill-path inserts can't. This explains why some markets in the sample have `tokens_in_catalog>0` but still zero trades — different code path, different failure mode (likely _fetch_market_trades timeout or empty response at discover time).

**Why "full backfill" doesn't recover this:** `last_trade_seen_at` is the lower bound for incremental fetch. Once a trader's `last_trade_seen_at` advances past the timestamp of the dropped trades, no future backfill will look that far back. Combined with H-10 (graph_unservable hole), the data loss compounds.

**Fix options:**

1. **Backfill should self-heal the catalog when it sees a new token.** In `backfill.py:524`, if the catalog miss happens, look up the token's `condition_id` from the live Gamma API on the spot (or accept the conditionId from the API trade response — `trade["conditionId"]` is already there) and INSERT a row into `token_catalog`. Only skip if the lookup also fails. This eliminates the silent drop.

2. **Discover should retry markets with empty `clobTokenIds`** rather than just skipping them. Either re-fetch from Gamma with retry/backoff, or fall back to the CLOB API's `/markets/{cid}` endpoint which exposes the token IDs.

3. **Add an observability bridge.** Today, `stats["skipped"]` is opaque. Log the (trader, market, token_id) triple of every skipped trade to a `backfill_drops` table or stage. That makes the next audit pass trivial — query the drops table instead of doing API-vs-DB comparisons by hand.

**Recommended:** ship #1 first (highest leverage, narrowest blast radius — only adds rows when a real token is encountered). Pair with #3 to catch any remaining drop modes. Defer #2 unless #1 doesn't close the gap.

### M-02: Graph side determination wrong for token-for-token swaps

**File:** `src/polymarket_analytics/api/graph.py`
**Impact:** Token-for-token swaps (both assets non-zero) always classified as SELL. Rare edge case on Polymarket esports markets.

### M-07: No alert on Anthropic API insufficient funds

**File:** `src/polymarket_analytics/extraction/llm.py`
**Impact:** When the Anthropic API returns an "insufficient funds" / billing error, the pipeline silently falls back to empty extraction. Should trigger a Telegram alert via `health/notify.py` so the user knows to top up the account before LLM-dependent features degrade.

### M-09: Heal scan returns mostly-noise — irredeemable + no-position-row pairs — **PARTIALLY FIXED 2026-05-02; option 3 still pending**

**Status (2026-05-02):**
- ✅ Heal scan now applies an MM filter (`composite_score < -0.10 AND positions > 100`) — drops 508 known-MM trapped traders per scan (2,520 → 2,012). Conservative thresholds (volume floor of 100 positions) preserve borderline real traders. See `MM_SCORE_CUTOFF`/`MM_POSITION_FLOOR` constants in `scripts/heal_trapped_batch.py`.
- ✅ Heal scope expanded to include `graph_unservable=1` traders, routed to a new Data API path (`heal_one_trader_via_api`) that bypasses Goldsky entirely. **Closes REVIEW.md H-10** for the 56 graph_unservable traders that had trapped pairs (full population: 104). Scan now picks up 2,068 traders, with 56 routed via Data API at ~1s each instead of 5+ min Graph timeouts.
- 🔁 Option 3 (graduate `graph_unservable=1` when 100% of trapped markets are dead-ended) still pending. Less urgent now that graduated traders are still serviceable via the Data API path — the noise reduction is the only remaining win.
- 📋 Wiki updates needed: [[Heal Loop Daemon]] should document the new Data API routing; [[Market Maker Bot Detection]] should mark its proposed filter as shipped.

---

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
