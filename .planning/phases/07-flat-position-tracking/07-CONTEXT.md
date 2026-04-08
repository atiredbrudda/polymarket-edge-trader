# Phase 7: FLAT Position Tracking — Context

**Gathered:** 2026-04-05
**Status:** Ready for planning
**Source:** Design session — all decisions locked

<domain>
## Phase Boundary

Fixes a systematic blind spot in the scoring pipeline: traders who enter and exit a position before market resolution are currently invisible to scoring because their net size ≈ 0 and their PnL is set to 0. These are precisely the CLV traders — they spot mispricing, enter, the price corrects, they exit. This phase makes them visible.

Scope: `positions/aggregation.py`, `positions/resolution.py`, `scoring/extraction.py`, `scoring/metrics.py`, `db/schema.py` (migration only). No CLI command changes.

</domain>

<decisions>
## Implementation Decisions

### Schema — positions table
- Add `avg_exit_price NUMERIC(10,6)` column
- Add via `run_migrations()` in `db/schema.py` — same pattern as `event_slug` migration
- NULL for LONG/SHORT positions held to resolution (they don't have a meaningful exit price)
- Populated only for positions that have SELL trades

### build-positions — aggregation.py
- **avg_entry_price**: change from `SUM(size * price) / SUM(size)` (all trades) to BUY-only weighted average:
  `SUM(CASE WHEN side='BUY' THEN size*price ELSE 0 END) / NULLIF(SUM(CASE WHEN side='BUY' THEN size ELSE 0 END), 0)`
- **avg_exit_price**: SELL-only weighted average:
  `SUM(CASE WHEN side='SELL' THEN size*price ELSE 0 END) / NULLIF(SUM(CASE WHEN side='SELL' THEN size ELSE 0 END), 0)`
  — returns NULL when no SELL trades exist (LONG/SHORT with no exits)
- **FLAT position size**: use gross BUY volume, not abs(net_size):
  `SUM(CASE WHEN side='BUY' THEN size ELSE 0 END)` as size when direction=FLAT
  — LONG/SHORT positions keep size = abs(net_size) as before
- Direction detection logic unchanged (net_size > epsilon → LONG, < -epsilon → SHORT, else → FLAT)

### resolve-positions — resolution.py
- FLAT positions with avg_exit_price IS NOT NULL resolve immediately — no market outcome needed
- FLAT PnL formula: `pnl = size * (avg_exit_price - avg_entry_price)`
  - size here is gross BUY volume (stored in positions.size for FLAT)
  - positive = profit (sold higher than bought), negative = loss
- Add a separate UPDATE pass before the existing market-outcome UPDATE:
  ```sql
  UPDATE positions
  SET resolved = 1,
      outcome = CASE WHEN pnl_calc > 0 THEN 'WIN' ELSE CASE WHEN pnl_calc < 0 THEN 'LOSS' ELSE 'FLAT' END END,
      pnl = size * (avg_exit_price - avg_entry_price)
  WHERE direction = 'FLAT'
    AND avg_exit_price IS NOT NULL
    AND resolved = 0
  ```
- Dependency check: relax the "no outcomes found" assertion — FLAT positions don't need it
  (only block if zero positions are resolvable by either path)

### scoring/extraction.py
- Add `p.avg_exit_price`, `p.direction` to SELECT
- No change to WHERE clause — `resolved = 1` already includes FLAT positions resolved by the new path

### scoring/metrics.py — calculate_clv
- For FLAT direction: `resolution_price = avg_exit_price`
- For LONG/SHORT: `resolution_price = outcome.map({YES: 1.0, NO: 0.0})` (unchanged)
- Implementation: after mapping outcome → resolution_price, override for FLAT rows:
  ```python
  df.loc[df["direction"] == "FLAT", "resolution_price"] = df.loc[df["direction"] == "FLAT", "avg_exit_price"]
  ```
- Drop rows where resolution_price is still NULL after both paths (shouldn't happen after resolve-positions, but guard anyway)

### Tests
- `test_build_positions.py`: update avg_entry_price assertions (now BUY-only); add FLAT size test
- `test_resolve_positions.py`: add FLAT PnL tests (bought at 0.40, sold at 0.70 → pnl > 0)
- `test_scoring_metrics.py`: add FLAT CLV test (resolution_price = avg_exit_price)
- `test_integration.py`: add a FLAT trader to fixture (buys then fully sells before resolution) and assert they are scored

### Claude's Discretion
- Exact SQL structure for the two-pass resolve-positions (savepoint vs single transaction)
- Whether to use raw SQL or Python loop for FLAT resolution pass
- Error message wording for edge cases

</decisions>

<specifics>
## Specific Implementation Notes

**Current aggregation SQL (to replace):**
```sql
SUM(size * price) / SUM(size) as avg_entry_price,
```

**New SQL (split BUY/SELL):**
```sql
SUM(CASE WHEN side='BUY' THEN size*price ELSE 0 END) /
    NULLIF(SUM(CASE WHEN side='BUY' THEN size ELSE 0 END), 0) as avg_entry_price,
SUM(CASE WHEN side='SELL' THEN size*price ELSE 0 END) /
    NULLIF(SUM(CASE WHEN side='SELL' THEN size ELSE 0 END), 0) as avg_exit_price,
```

**FLAT size SQL:**
```sql
-- Direction-conditional size:
-- LONG/SHORT: abs(net_size) as before
-- FLAT: gross BUY volume
```
This needs to be handled in Python after fetching the row (direction not known until net_size computed).

**CLV for FLAT (backtested reality):**
Trader buys YES at 0.40, sells at 0.70 before resolution.
- avg_entry_price = 0.40, avg_exit_price = 0.70
- resolution_price = 0.70 (not 1.0)
- CLV = (0.70 - 0.40) / 0.40 = 0.75 ← positive CLV, structural edge captured

**GUIDE.md RSLV-04 conflict:**
GUIDE.md says "FLAT: pnl = 0". This was the old behavior we're fixing. The new behavior supersedes it for FLAT positions with avg_exit_price. Positions that are FLAT with no exit trades (edge case: net cancellation?) stay at pnl=0 but those are genuinely zero-return.

</specifics>

<deferred>
## Deferred Ideas

- Partial-exit tracking (trader bought 100, sold 40, still holds 60): this phase only fixes fully-FLAT positions. Partial exits on LONG/SHORT positions are a separate concern — the entry price split (BUY-only) already improves accuracy for them, but full partial-exit PnL attribution is deferred.
- avg_exit_price on LONG/SHORT positions (partial sell tracking): stored as NULL for now, deferred.

</deferred>

---

*Phase: 07-flat-position-tracking*
*Context gathered: 2026-04-05 via design session*
