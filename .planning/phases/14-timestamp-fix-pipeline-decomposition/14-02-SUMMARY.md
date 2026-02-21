# Phase 14-02: Pipeline Decomposition

## Summary

Decomposed the `sweep` command into individual, composable pipeline stages. Users can now run scoring, signal detection, and alert delivery independently instead of through one opaque orchestrator.

## Changes

### src/cli/commands.py

1. Added `score` command - computes expertise scores for all traders
2. Added `detect` command - refreshes signal detection (distinct from `signals` viewer)
3. Added `alert` command - delivers pending alerts via Telegram
4. Rewrote `sweep` command as transparent inline orchestrator:
   - Stage 1: Ingest markets
   - Stage 2: Compute scores
   - Stage 3: Detect signals
   - Stage 4 (optional): Deliver alerts
5. Added `--with-alerts` flag to sweep (alerts are opt-in)

## New Commands

```
polymarket score              # Compute expertise scores
polymarket detect             # Refresh signal detection
polymarket detect --window 6  # Custom time window
polymarket alert              # Deliver Telegram alerts
polymarket sweep              # Full pipeline (no alerts)
polymarket sweep --with-alerts # Full pipeline with alerts
```

## Verification

All commands registered and accessible:
- `polymarket score --help` ✓
- `polymarket detect --help` ✓
- `polymarket alert --help` ✓
- `polymarket sweep --help` ✓ (shows --with-alerts flag)

## Notes

- The existing `signals` command is a VIEWER (reads stored signals)
- The new `detect` command COMPUTES signals (refreshes them)
- These are different operations with different names
- `run_sweep` from scheduler.py is no longer called from sweep CLI
