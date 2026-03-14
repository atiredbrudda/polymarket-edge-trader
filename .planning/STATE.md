# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-21)

**Core value:** Surface where smart money is moving in niche prediction markets so the user can see what informed traders are doing and factor that into their own thinking.
**Current focus:** v1.2 — Phase 19 complete, pending review

## Current Position

Phase: 21 (Market Entity Extraction — IN PROGRESS)
Plan: 20-01 + 20-02 complete (merged 2026-03-14), 21-01 pending execution
Status: Phase 20 complete. Starting Phase 21 Plan 01.
Last activity: 2026-03-14 — Phase 21 Plan 01 execution started.

Progress: [█████████░] 90% (v1.2 — phase 21 in progress)

## Performance Metrics

**Velocity (v1.1):**
- Total plans completed: 41 (29 from v1.0 + 12 from v1.1 phases 10-14)
- Codebase: ~32,065 LOC Python (15,400 src + 16,665 tests)
- Timeline: 2026-02-13 → 2026-02-21 (8 days)

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting v1.2:

- Gamma Events API (`gamma-api.polymarket.com/events`) chosen as authoritative source for both market resolution and deep classification
- One-time ~30s download (~10MB) is sufficient; no incremental polling needed for v1.2
- Phase 17 (classification) depends on Phase 15 but not Phase 16 — can potentially parallelize 16+17

### Roadmap Evolution

- v1.0 phases 1-9 completed and archived (milestones/v1.0-ROADMAP.md)
- v1.1 phases 10-14 completed and archived (milestones/v1.1-ROADMAP.md)
- v1.2 phases 15-18 defined: Gamma ingestion → Resolution → Classification → E2E validation
- Phase 19: Self-healing token catalog (auto-patch gaps after backfill)
- Phase 20: eSports token gap recovery (156 null-token markets, 3,633 trades)
- Phase 21 added: Market Entity Extraction — LLM extracts team_a, team_b, tournament, game from market question text during discover
- Phase 22 added: Org-Team Mapping — data model for org→team relationships, cross-game org tracking, normalization layer
- Phase 23 added: Contextual Analyze Command — query-time win rate per dimension per trader, replaces pre-computed scoring

### Known Limitations (carry to v1.2 work)

- `markets.outcome=NULL` for all 117k markets — blocks PnL scoring (fixed by Phase 16)
- `token_catalog.node_path=NULL` — classification stuck at eSports root (fixed by Phase 17)
- Position.resolved=False for all positions — scoring pipeline can't filter (FIXED by 18-01)
- Scoring produces empty leaderboards end-to-end until both gaps are closed (validated in Phase 18)
- Note: E2E leaderboard still empty in practice due to MIN_RESOLVED_MARKETS=5 threshold + Xero100i having 0 positions — data gap, not a code gap

### Pending Todos

None.

### Blockers/Concerns

None — Phase 19 in review, awaiting approval to merge.

## Session Continuity

Last session: 2026-02-27
Stopped at: Phase 19 submitted for review (worker/19-01)
Resume file: None
Next: Awaiting review, then milestone v1.2 complete
