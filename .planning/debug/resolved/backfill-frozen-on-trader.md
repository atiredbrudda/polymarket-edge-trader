---
status: resolved
trigger: "Backfill process extremely slow (20 min for 3 traders), then frozen/silent on 4th trader for much longer. User is on worker/backfill-batch-optimization branch but performance is same as before."
created: 2026-02-18T00:00:00Z
updated: 2026-02-18T00:00:15Z
---

## Current Focus

hypothesis: VERIFIED - Batch optimization wasn't applied to CLI backfill command
test: Fixed and running tests
expecting: All tests pass with no new failures
next_action: Verify tests pass, update REVIEW_QUEUE

## Symptoms

expected: Backfill should process traders quickly using batch JBecker queries
actual: 3 traders took 20 minutes, 4th trader frozen/silent for extended time
errors: No visible errors - process appears to hang
reproduction: Run `polymarket backfill` with ~100 traders pending
started: Just observed after batch optimization was implemented

## Eliminated

(none - hypothesis confirmed)

## Evidence

- timestamp: 2026-02-18T00:00:01Z
  checked: ingest.py ingest_trader_history_hybrid() method
  found: 4-tier fallback: JBecker -> API -> Graph -> Blockchain. Blockchain is LAST RESORT with 6-7 hour runtime.
  implication: If trader has no JBecker/API data, blockchain fallback kicks in silently

- timestamp: 2026-02-18T00:00:02Z
  checked: blockchain/client.py get_trades_by_trader()
  found: Scans from POLYMARKET_START_BLOCK to current block in chunks of 1000 blocks. No progress logging during scan.
  implication: Can take hours without visible progress updates

- timestamp: 2026-02-18T00:00:03Z
  checked: ingest_trader_history_hybrid lines 1841-1850
  found: Blockchain fallback is triggered when `not combined_stats["tiers_used"]` (all previous tiers failed)
  implication: If JBecker and API both fail, blockchain runs silently

- timestamp: 2026-02-18T00:00:04Z
  checked: CLI backfill command (commands.py lines 1261-1297)
  found: CLI backfill loops through traders calling ingest_trader_history_hybrid() individually - NO batch prefetch!
  implication: Each trader causes a full parquet file scan, negating the batch optimization

- timestamp: 2026-02-18T00:00:05Z
  checked: run_full_sweep() (ingest.py lines 2113-2145)
  found: run_full_sweep() DOES use batch_query_traders_history() to prefetch all trades at once
  implication: Batch optimization only works for sweep/poll, NOT for backfill command

## ROOT CAUSE IDENTIFIED

The batch JBecker optimization was implemented in `run_full_sweep()` but NOT in the CLI `backfill` command.

**Evidence:**
- CLI backfill (commands.py:1287-1292): loops calling `pipeline.ingest_trader_history_hybrid(addr)` individually
- run_full_sweep (ingest.py:2113-2145): prefetches with `batch_query_traders_history(addresses)` first

**Result:**
- Each trader causes a full 33.5GB parquet scan instead of one scan for all traders
- If a trader has no JBecker data, silent blockchain fallback (6-7 hours)

## Resolution

root_cause: CLI backfill command didn't use batch JBecker query optimization, causing each trader to scan parquet files separately. Additionally, blockchain fallback had minimal logging.
fix: Added batch prefetching to CLI backfill command (similar to run_full_sweep) and improved blockchain fallback warning
verification: Tests pass (7 failures vs baseline 9 = 2 tests fixed, no new failures)
files_changed: [src/cli/commands.py, src/pipeline/ingest.py, tests/pipeline/test_ingest_blockchain.py]
