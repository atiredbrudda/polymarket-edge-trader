# Phase 20: eSports Token Gap Recovery - Context

**Gathered:** 2026-02-27
**Status:** Ready for planning
**Source:** Diagnostic investigation (live DB + API probing session)

<domain>
## Phase Boundary

Recover the 156 null-token eSports markets (156/158 total null-token gap markets are eSports) so that 3,633 currently unclassifiable trades from 1,451 unique traders get proper eSports classification — and fix the root cause so the gap cannot recur.

This phase does NOT change the scoring algorithm, the patcher tier logic, or any CLI commands beyond what is strictly needed for recovery.

</domain>

<decisions>
## Implementation Decisions

### Root Cause (Locked)
- `ingest_trader_history_jbecker` hit markets without `tokens` data in the `markets` table
- The populate-tokens block (~line 1777 in `ingest.py`) called `GET /markets?conditionId=X` on the Gamma API
- The Gamma API **ignores** the `conditionId` query param and returns random unrelated markets
- No token data was found for those random markets, so `markets.tokens` stayed NULL
- With `tokens=NULL`, Tier 1 patcher (needs token_ids) and Tier 2 patcher (also needs token_ids) both skip the market → it gets only a Tier 3 category-only entry or nothing

### Fix Strategy — Events API (Locked)
- The Gamma Events API (`GET /events?tag={slug}&limit=N`) returns events with nested `markets[]`
- Each nested market has both `conditionId` AND `clobTokenIds` — exactly what we need
- Scan all eSports events by tag (counter-strike, valorant, dota-2, league-of-legends, etc.)
- For each nested market: if `conditionId` matches one of the 156 gap markets → extract `clobTokenIds`
- Store as JSON in `markets.tokens` for that condition_id
- Then re-run the patcher — Tier 1 will now find these markets in `gamma_events` and populate `token_catalog` with correct `node_path`

### What the Recovery Does NOT Need (Locked)
- Does NOT need to insert into `gamma_events` — we already have eSports events there from Phase 15
- Does NOT need to call CLOB API — `GET /markets/{conditionId}` returned "market not found" for these old markets
- Does NOT need to scan JBecker markets parquet — checked and 0/156 gap markets are in JBecker markets data
- Does NOT need a new API endpoint — the existing events scan pattern from Phase 15 is sufficient

### ingest.py Fix (Locked)
- The populate-tokens block at ~line 1777 must be replaced with an events-based lookup
- Instead of `GET /markets?conditionId=X`, use: fetch events by tag → match conditionId in nested markets → extract clobTokenIds
- This is the same events API used by the recovery step — one reusable function
- The fix prevents any future backfill from creating new null-token gaps for eSports markets

### Re-scoring (Locked)
- After token_catalog is populated for the 156 markets, the scoring pipeline must be re-run
- Affected traders: up to 1,451 unique traders who had trades on these markets
- Re-scoring is done via the existing `score` CLI command — no new logic needed
- The leaderboard should be re-run after scoring to reflect updated specialization scores

### Token Format (Locked)
- `markets.tokens` stores a JSON string matching the format used by JBecker markets parquet: `["token_id_1", "token_id_2"]`
- Gamma Events API returns `clobTokenIds` as a JSON array — store directly after parsing
- Patcher Tier 1 reads `markets.tokens` via `json.loads()` — same format required

### Scope Boundary (Locked)
- The 2 remaining non-eSports null-token markets (158 total - 156 eSports = 2 other) are out of scope
- They will be handled by Tier 3 (category-only) as before — no node_path needed

### Claude's Discretion
- Whether recovery logic lives in `src/catalog/patcher.py` as a pre-pass, in `src/ingest.py`, or a new `src/catalog/recovery.py`
- Whether to expose a `recover-catalog` CLI command or run recovery as part of `patch-catalog`
- Exact eSports tag slugs to scan (need to enumerate all: counter-strike, valorant, dota-2, league-of-legends, overwatch, etc.)
- Batch size for events API calls (pagination)
- Whether to re-score inline or instruct user to run `score` manually after
- Test strategy: mock events API responses, assert markets.tokens updated, assert token_catalog populated

</decisions>

<specifics>
## Specific Data Points

- **156** eSports markets with `tokens=NULL` and active trades but no `token_catalog` entry
- **3,633** trades affected
- **1,451** unique trader addresses affected
- **8,864** existing `gamma_events` rows (already fetched eSports events from Phase 15)
- Gamma Events API example: `GET https://gamma-api.polymarket.com/events?tag=counter-strike&limit=100`
  - Returns events with `markets[]` array
  - Each market: `{"conditionId": "0x...", "clobTokenIds": "[\"token1\", \"token2\"]", ...}`
- CLOB API confirmed non-viable: `GET /markets/{conditionId}` returns `{"error": "market not found"}` for these old markets
- JBecker markets parquet confirmed non-viable: 0/156 gap condition_ids found in all 41 parquet files
- ingest.py broken block: `GET /markets?conditionId=X` — returns 20 random unrelated markets (ignores param)

</specifics>

<deferred>
## Deferred Ideas

- Generalizing the events-based token recovery to non-eSports categories (Sports, Politics, etc.)
- Making recovery incremental (only scan tags for markets that are missing)
- Adding a monitoring alert when null-token count exceeds a threshold after backfill

</deferred>

---

*Phase: 20-esports-token-gap-recovery*
*Context gathered: 2026-02-27 via diagnostic investigation*
