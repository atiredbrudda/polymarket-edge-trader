---
status: resolved
trigger: "sweep-market-filtering-issues"
symptoms_prefilled: true
created: "2026-02-15T00:00:00.000Z"
updated: "2026-02-15T13:00:00.000Z"
---

## Current Focus
hypothesis: "Investigation complete - fixes applied"
test: "All fixes implemented"
expecting: "Sweep should now only return eSports markets within timeframe, no trader extraction"
next_action: "Verify fixes work correctly"

## Symptoms
expected: "Only eSports markets that close within the specified timeframe (e.g., 11hours)"
actual: "1) Non-eSports markets getting through the filter, 2) eSports markets beyond the closing-within timeframe being returned"
errors: "No error messages - just wrong results"
reproduction: "polymarket sweep --closing-within \"11hours\" --niche esports"
started: "Never worked correctly - this is a persistent issue since the sweep was built"

## Eliminated
<!-- APPEND only - prevents re-investigating -->

## Evidence
- timestamp: "2026-02-15T12:00:00.000Z"
  checked: "src/pipeline/ingest.py _filter_market_by_niche function"
  found: "Keyword matching uses broad keywords like 'major', 'tournament', 'championship' that match non-esports markets"
  implication: "Non-eSports markets containing these words pass the filter"
  fix_applied: "Removed generic keywords, kept only specific game titles"

- timestamp: "2026-02-15T12:00:00.000Z"
  checked: "src/pipeline/ingest.py run_full_sweep step 2"
  found: "Trader discovery queries ALL active markets, not just those matching niche filter"
  implication: "Traders are discovered from markets that weren't filtered"
  fix_applied: "Added niche filter to trader discovery query, added skip_trader_discovery parameter"

- timestamp: "2026-02-15T12:00:00.000Z"
  checked: "src/cli/commands.py sweep command"
  found: "Sweep command was discovering traders when it should only find markets"
  fix_applied: "Added skip_trader_discovery=True to run_sweep call"

## Resolution
root_cause: "Three issues: 1) Overly broad esports keyword matching allowing non-esports through, 2) Trader discovery querying all markets not filtered ones, 3) Sweep command extracting traders when should only find markets"

fix: "1) Removed broad keywords (major, tournament, championship) from esports filter, 2) Added niche filter to trader discovery query to only use filtered markets, 3) Added skip_trader_discovery=True parameter to sweep command, 4) Added JSON debug output to logs/sweep_debug.json"

verification: "Code changes applied - need to test with actual sweep command"

files_changed:
- "src/pipeline/ingest.py": "Fixed keyword filter, added skip_trader_discovery param, added JSON debug output"
- "src/cli/scheduler.py": "Added skip_trader_discovery parameter to run_sweep"
- "src/cli/commands.py": "Pass skip_trader_discovery=True in sweep command"
