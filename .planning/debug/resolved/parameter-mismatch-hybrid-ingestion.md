---
status: resolved
trigger: "parameter-mismatch-hybrid-ingestion"
created: 2026-02-12T00:00:00Z
updated: 2026-02-12T00:15:00Z
---

## Current Focus

hypothesis: run_full_sweep calls ingest_trader_history_hybrid with prefer_graph parameter but function signature expects prefer_jbecker
test: examine both the caller (run_full_sweep) and callee (ingest_trader_history_hybrid) to confirm parameter name mismatch
expecting: find prefer_graph being passed but prefer_jbecker being expected, confirming the Phase 8→Phase 9 transition gap
next_action: read run_full_sweep implementation and ingest_trader_history_hybrid signature

## Symptoms

expected: ingest_trader_history_hybrid should use JBecker dataset as PRIMARY source with prefer_jbecker=True parameter (4-tier: JBecker → API → Graph → Blockchain)
actual: run_full_sweep is calling it with prefer_graph=use_graph parameter which doesn't exist on the function signature
errors: Error messages appear during polymarket sweep execution
reproduction: Run 'polymarket sweep' command
started: Never worked - just started testing after Phase 9 completion. Code has Phase 9 logic (JBecker-first) but is being called with Phase 8 logic (Graph-first)

## Eliminated

## Evidence

- timestamp: 2026-02-12T00:01:00Z
  checked: ingest_trader_history_hybrid function signature (line 1013)
  found: Parameters are prefer_jbecker, fill_gap_with_api, fallback_to_graph, fallback_to_blockchain
  implication: Function expects prefer_jbecker=True for JBecker-first priority

- timestamp: 2026-02-12T00:02:00Z
  checked: run_full_sweep caller code (lines 1193-1196)
  found: Calling ingest_trader_history_hybrid with prefer_graph=use_graph and fallback_to_blockchain parameters
  implication: Caller using Phase 8 parameter name (prefer_graph) instead of Phase 9 name (prefer_jbecker)

- timestamp: 2026-02-12T00:03:00Z
  checked: Parameter count and meaning
  found: prefer_graph parameter doesn't exist on function signature - will be silently ignored as **kwargs don't exist
  implication: All calls to ingest_trader_history_hybrid currently use default prefer_jbecker=True by accident, but won't receive intended use_graph boolean value

- timestamp: 2026-02-12T00:11:00Z
  checked: Test execution after fix
  found: test_run_full_sweep_with_blockchain PASSED, all 9 scheduler tests PASSED
  implication: Fix is working correctly, parameter passing is now correct

## Resolution

root_cause: run_full_sweep (line 1195) calls ingest_trader_history_hybrid with prefer_graph=use_graph parameter, but function signature (line 1016) expects prefer_jbecker parameter. This is Phase 8→Phase 9 transition gap where caller wasn't updated to match new JBecker-first priority order.
fix: Updated run_full_sweep to pass prefer_jbecker parameter instead of prefer_graph, changed parameter from use_graph to use_jbecker to match Phase 9 cost-optimized hierarchy (JBecker -> API -> Graph -> Blockchain)
verification: ✓ test_run_full_sweep_with_blockchain PASSED, ✓ all 9 scheduler tests PASSED - parameter passing works correctly, no regressions introduced
files_changed:
  - src/pipeline/ingest.py (run_full_sweep signature and call to ingest_trader_history_hybrid)
  - tests/pipeline/test_ingest_blockchain.py (updated test to use new parameter names)
