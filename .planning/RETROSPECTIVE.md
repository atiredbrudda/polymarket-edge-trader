# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.2 — Market Resolution & Deep Classification

**Shipped:** 2026-03-22
**Phases:** 11 | **Plans:** 21

### What Was Built
- Gamma Events API integration: bulk download, market resolution, deep token classification
- Self-healing token catalog with 3-tier auto-patcher (local join → API → category-only)
- eSports token gap recovery: 156 null-token markets + ingest.py fix
- Entity-level intelligence: LLM extraction of teams/tournaments, per-team win rates
- Lift-based scoring v2: z(CLV)+z(ROI)+z(Sharpe) formula validated through 348-experiment backtest
- Signal detection rewired to Q5 filtering with price-context enrichment

### What Worked
- **Scope expansion was natural:** Original 4-phase goal (15-18) grew to 11 phases as each phase revealed the next logical gap. The pipeline is genuinely end-to-end now.
- **Pattern-match-first gate:** Adding regex extraction before LLM fallback reduced API costs significantly without losing coverage.
- **Backtest-driven scoring:** 348-experiment backtest proved equal-weight formula needs no tuning — removed subjective parameter choices entirely.
- **Incremental architecture:** Each phase built cleanly on the previous one. No major rewrites needed within the milestone (Phase 25 replaced Phase 23's analyze, but that was a planned evolution).

### What Was Inefficient
- **Missing VERIFICATION.md files:** 8 of 11 phases shipped without formal verification. Code works (integration tests pass), but Nyquist compliance is 0%. This is a process gap, not a quality gap.
- **Dead code accumulation:** Phase 23 EntityAlpha model became dead code when Phase 25 rewrote analyze. Should have deferred Phase 23 implementation knowing scoring was about to change.
- **Old scoring functions preserved:** `compute_game_scores` etc. still in codebase but uncalled. Cleanup deferred.
- **Phase numbering in ROADMAP.md progress table:** The progress table had stale "Planned" / "Not started" statuses for completed phases. ROADMAP wasn't updated as phases completed.

### Patterns Established
- **Pattern-match-first, LLM-fallback:** For entity extraction, try cheap regex before expensive API call
- **DELETE-then-INSERT for snapshot tables:** LiftScore uses this pattern — only latest state matters
- **z-score normalization for composite metrics:** Avoids arbitrary weighting; backtest validates
- **3-tier patcher pattern:** local data → API lookup → category-only fallback for catalog gaps

### Key Lessons
1. **Backtest before building scoring formulas.** The 348-experiment backtest revealed that win_rate (40% of old score) measured price preference, not skill. Would have caught this earlier with data analysis first.
2. **Verify phases formally even when code clearly works.** Missing VERIFICATION.md files made the audit look worse than reality. 5 minutes of verification per phase saves hours of audit cleanup.
3. **Don't implement features you know will be superseded.** Phase 23 entity-alpha was implemented knowing Phase 24-25 would change scoring. Should have skipped or stubbed it.

### Cost Observations
- Model mix: ~40% opus (planning, complex phases), ~55% sonnet (execution), ~5% haiku (entity extraction)
- Notable: Pattern matcher reduced Haiku API calls during discover by catching common team/tournament patterns via regex

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 9 | 29 | Established TDD-first workflow, wave-based parallelization |
| v1.1 | 5 | 12 | Added pipeline decomposition, per-command CLI pattern |
| v1.2 | 11 | 21 | Scope expansion pattern, backtest-driven design, entity intelligence |

### Cumulative Quality

| Milestone | Tests (approx) | LOC | Key Quality Metric |
|-----------|---------------|-----|-------------------|
| v1.0 | ~362 | 26,306 | All 5 phases verified |
| v1.1 | ~450 | 32,065 | Known gaps documented at completion |
| v1.2 | ~500+ | 39,673 | 5/5 E2E flows connected, 8/11 phases unverified |

### Top Lessons (Verified Across Milestones)

1. **Data analysis before algorithm design.** v1.0 and v1.2 both had scoring formulas that needed revision after seeing real data.
2. **Each pipeline command should be standalone and composable.** Established in v1.1, validated in v1.2 — every new capability was added as a CLI command.
3. **Document known gaps at milestone completion.** v1.1's documented gaps (outcome=NULL, node_path=NULL) directly shaped v1.2's roadmap.
