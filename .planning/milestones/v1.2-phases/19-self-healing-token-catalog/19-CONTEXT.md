# Phase 19: Self-Healing Token Catalog - Context

**Gathered:** 2026-02-27
**Status:** Ready for planning
**Source:** Conversation-derived (diagnostic session)

<domain>
## Phase Boundary

Patch the existing 401-market gap (10,850 unclassifiable trades) and prevent the gap from growing silently after future backfills. The fix must run automatically at the end of every `backfill` command — no manual intervention required.

This phase does NOT change the backfill logic itself, the scoring pipeline, or any existing CLI commands beyond `backfill`.

</domain>

<decisions>
## Implementation Decisions

### Root Cause (Locked)
- `token_catalog` is built exclusively from JBecker's markets parquet
- 401 condition_ids in `trades` have no matching `token_catalog` entry
- These are markets JBecker never indexed (scattered across all dates — not a simple cutoff issue)
- 177 are eSports markets (actively affect classification/scoring)
- 206 are other categories (Sports, Politics, etc. — traders legitimately bet on anything)
- 18 are other categories (Sports, Politics, Crypto, AI, etc.)

### Detection Strategy (Locked)
- After backfill completes, query: `SELECT DISTINCT t.market_id FROM trades t LEFT JOIN token_catalog tc ON t.market_id = tc.condition_id WHERE tc.condition_id IS NULL`
- This finds all condition_ids with trades but no catalog entry
- Must run after every backfill, not just once

### Patch Strategy — 3-tier lookup (Locked)
**Tier 1 (local, free):** Join `markets` table → extract token IDs from `markets.tokens` JSON → look up those token IDs in `gamma_events.clob_token_ids` → extract tags for node_path/depth
**Tier 2 (API, for markets not in gamma_events):** Call Gamma API `/events` endpoint with condition_id or token_id lookup to get tags
**Tier 3 (fallback):** Insert into token_catalog with category from `markets.category` but `node_path=NULL` — at minimum the market is known and categorized

### What Goes into token_catalog (Locked)
- ALL categories (not just eSports) — traders bet on anything, all should be known
- eSports markets: full node_path from gamma_events tags if available
- Non-eSports markets: category populated, node_path=NULL is acceptable
- Idempotent: `INSERT OR IGNORE` or `ON CONFLICT DO NOTHING` — re-runs safe

### Integration Point (Locked)
- Runs automatically at the END of the `backfill` CLI command
- Also available as standalone `patch-catalog` CLI command for manual runs
- Silent when nothing to patch (zero gaps = zero output)
- Reports count of markets patched and source used (local/api/fallback)

### Backlog Fix (Locked)
- First run patches the existing 401-market / 10,850-trade backlog
- No separate one-time script needed — the automatic step handles it on first execution

### Claude's Discretion
- Whether patch logic lives in `src/catalog/` or `src/pipeline/` or a new `src/catalog/patcher.py`
- Exact batch size for Gamma API calls (to avoid rate limiting)
- Whether to log individual markets patched or just summary counts
- Test strategy (unit tests for the patch logic, integration test for the auto-trigger)

</decisions>

<specifics>
## Specific Data Points

From diagnostic queries (2026-02-27):
- `trades` table: 806,483 rows
- Unclassifiable: 10,850 trade rows across 401 distinct condition_ids
- Of 401: 177 eSports, 206 Unknown category, 18 other (Sports/Politics/Crypto/AI/Business/Culture)
- All 401 ARE in the `markets` table (condition_id, question, category known)
- `gamma_events` has 8,864 events covering 96,350 unique token IDs
- 87,190 of those 96,350 are already in `token_catalog` (90.5% coverage)
- The 9,160 gap in gamma tokens vs catalog = different identifier format issue, not directly actionable

Example unclassifiable eSports markets:
- "Counter-Strike: FUZOS vs Nexus - Map 1 Winner" (category=esports)
- "Valorant: FearX vs Mir Gaming - Map 2 Winner" (category=esports)
- "Dota 2: Tundra Esports vs BetBoom Team (BO3) - DreamLeague Stage 2" (category=esports)
- "Total Kills Over/Under 29.5 in Game 1?" (category=esports)

</specifics>

<deferred>
## Deferred Ideas

- Proactive catalog pre-population for new markets before trades arrive — out of scope, reactive is sufficient
- Enriching existing NULL node_path entries not linked to trades — out of scope
- Changing how token_catalog is built from JBecker — out of scope

</deferred>

---

*Phase: 19-self-healing-token-catalog*
*Context gathered: 2026-02-27 via conversation diagnostic session*
