---
phase: 02-classification-discovery
plan: 01
type: tdd
subsystem: taxonomy
tags: [yaml, pydantic, regex, classification, esports]
requires:
  - phase: 01-foundation
    plans: [01-01, 01-02, 01-03, 01-04]
    reason: "Foundation data models and ingestion pipeline required"
provides:
  - YAML-based 4-level eSports taxonomy (Game > Tournament > Team)
  - Pattern-matching classifier with deepest-match-wins strategy
  - Market type detection (match vs prop)
  - Review flagging for unmatched/partial matches
  - Extensible via YAML-only edits (no code changes)
affects:
  - phase: 02-classification-discovery
    plans: [02-02, 02-03]
    reason: "Market classification enables niche detection and trader expertise scoring"
tech-stack:
  added:
    - pyyaml>=6.0: YAML taxonomy file parsing
  patterns:
    - "Precompiled regex patterns for O(patterns) classification"
    - "Pydantic validation for YAML schema enforcement"
    - "Dataclass for classification results"
key-files:
  created:
    - src/taxonomy/__init__.py: Module exports
    - src/taxonomy/models.py: Pydantic hierarchy models (TeamNode, TournamentNode, GameNode, TaxonomyConfig)
    - src/taxonomy/loader.py: YAML loader with safe_load and validation
    - src/taxonomy/classifier.py: PatternMatcher and market type detector
    - data/taxonomy/esports.yaml: Seed taxonomy with 4 games, 40+ team entries
    - tests/test_taxonomy.py: 18 comprehensive tests for all taxonomy components
  modified: []
key-decisions:
  - name: "Cross-game team duplication"
    rationale: "Teams like NaVi and Cloud9 appear under multiple games separately for simpler path queries and self-describing taxonomy paths"
    alternatives: ["Shared team registry with references"]
    impact: "Easier querying, slightly more YAML maintenance"
  - name: "Deepest-match-wins classification"
    rationale: "Title matching both game and team should return team-level (depth 3) for maximum specificity"
    alternatives: ["First match", "Most specific pattern"]
    impact: "Consistent hierarchical classification"
  - name: "Context-aware dash detection"
    rationale: "Pattern \\w+\\s+-\\s+\\w+ matches 'Team A - Team B' but not standalone dashes"
    alternatives: ["Simple \\b-\\b pattern"]
    impact: "Reduces false positives for match type detection"
  - name: "Review flagging strategy"
    rationale: "Flag markets with 'vs' pattern but no team match as partial matches needing review"
    alternatives: ["Only flag complete unknowns"]
    impact: "Catches taxonomy gaps early for manual review"
duration: 4min
completed: 2026-02-06
---

# Phase 2 Plan 01: YAML Taxonomy System Summary

**One-liner:** YAML-driven 4-level eSports taxonomy with regex pattern matching, market type detection, and extensibility without code changes.

## Performance

- **Execution time:** 4 minutes
- **Test coverage:** 18 new tests, all passing
- **Total test suite:** 101 tests (18 taxonomy + 83 foundation)
- **TDD cycle:** RED (failing tests) → GREEN (implementation) → commits
- **Verification:** All 5 success criteria met

## Accomplishments

Built complete YAML-based taxonomy system for eSports market classification:

1. **Pydantic Models** - 4-level hierarchy with validation
   - TeamNode: name, patterns, aliases
   - TournamentNode: name, patterns, tier, teams
   - GameNode: name, patterns, tournaments
   - TaxonomyConfig: name, games

2. **YAML Loader** - Secure loading with validation
   - Uses `yaml.safe_load()` for security (never `yaml.load()`)
   - Validates against Pydantic schema
   - Clear error messages for malformed files

3. **Pattern Matcher Classifier** - Efficient regex-based classification
   - Precompiles all patterns at initialization
   - O(patterns) classification time
   - Deepest-match-wins strategy for hierarchy
   - Returns ClassificationResult with node_path, depth, game/tournament/team

4. **Market Type Detection** - Distinguishes match vs prop markets
   - Match patterns: vs, v, Team-Team, @
   - Prop patterns: winner, top N, over X, champion, MVP
   - Scoring system returns "match", "prop", or None

5. **Review Flagging** - Identifies problematic classifications
   - Completely unmatched titles flagged
   - Partial matches (game found, "vs" present, no team) flagged

6. **Seed Taxonomy** - 4 games with comprehensive coverage
   - CS2: IEM Katowice, BLAST Premier
   - Dota 2: The International, DreamLeague
   - League of Legends: Worlds, LCS, LEC
   - Valorant: VCT Masters, VCT Champions
   - 40+ team entries with patterns and aliases

## Task Commits

| Task | Type | Commit | Description |
|------|------|--------|-------------|
| 1 | chore | 129072a | Add pyyaml>=6.0 dependency and create directories |
| 2 | test | e415c19 | Add failing tests for taxonomy system (RED phase) |
| 3 | feat | ee0169a | Implement taxonomy models, loader, classifier (GREEN phase) |
| 4 | feat | d5895c6 | Add seed eSports taxonomy with 4 games |

## Files Created/Modified

**Created (6 files):**
- `src/taxonomy/__init__.py` - Module exports
- `src/taxonomy/models.py` - Pydantic hierarchy models (114 lines)
- `src/taxonomy/loader.py` - YAML loader with validation (47 lines)
- `src/taxonomy/classifier.py` - PatternMatcher and market type detector (191 lines)
- `data/taxonomy/esports.yaml` - Seed taxonomy (199 lines, 40+ teams)
- `tests/test_taxonomy.py` - Comprehensive test suite (300 lines, 18 tests)

**Modified:**
- `pyproject.toml` - Added pyyaml>=6.0 dependency

## Decisions Made

### 1. Cross-game team duplication
**Decision:** Teams like NaVi, Cloud9, Team Liquid appear under multiple games separately.

**Rationale:** Simpler path queries and self-describing taxonomy paths. Path `eSports.CS2.IEM Katowice.NaVi` is fully self-contained.

**Alternatives considered:** Shared team registry with references from tournaments.

**Trade-off:** Slightly more YAML maintenance for significantly simpler querying.

### 2. Deepest-match-wins classification
**Decision:** When multiple taxonomy levels match a title, return the deepest match.

**Example:** "CS2 NaVi performance" matches both game (CS2) and team (NaVi), returns team-level (depth 3).

**Rationale:** Maximum specificity for classification. Team-level is more valuable than game-level.

### 3. Context-aware dash detection
**Decision:** Use `\w+\s+-\s+\w+` pattern for dash-based match detection instead of simple `\b-\b`.

**Rationale:** Avoids false positives on standalone dashes (dates, ranges, punctuation).

**Example:** "Team Liquid - Cloud9" matches, but "2024-01-15" does not.

### 4. Review flagging for partial matches
**Decision:** Flag markets that match a game but contain "vs" without matching any team.

**Rationale:** Catches taxonomy gaps early. If we see "CS2 TeamA vs TeamB" where TeamA/TeamB aren't in taxonomy, we need to review and potentially add them.

**Impact:** Enables iterative taxonomy improvement based on real market data.

## Deviations from Plan

None - plan executed exactly as written. TDD methodology followed precisely:
1. RED phase: All tests written first and failing
2. GREEN phase: Implementation made tests pass
3. All verification criteria met

## Issues Encountered

### 1. Initial test failures (expected in TDD)
**Issue:** 2 tests failed on first GREEN implementation.

**Root cause:**
- ValidationError re-raise syntax incorrect
- Dash pattern too simple (matched non-match contexts)

**Resolution:**
- Simplified ValidationError handling to re-raise original
- Enhanced dash pattern to require word context: `\w+\s+-\s+\w+`

**Outcome:** All 18 tests pass, no regression in 83 foundation tests.

### 2. data/ directory gitignored
**Issue:** `git add data/taxonomy/esports.yaml` blocked by .gitignore.

**Resolution:** Used `git add -f` to force-add taxonomy file.

**Rationale:** Taxonomy YAML is configuration, not runtime data. Should be version controlled for reproducibility.

## Next Phase Readiness

**Ready for Phase 2 Plan 02:** Market classifier integration.

**Blockers:** None.

**Dependencies satisfied:**
- ✓ Taxonomy models implemented
- ✓ Loader validated with seed YAML
- ✓ Classifier functional with deepest-match-wins
- ✓ Market type detection operational
- ✓ Review flagging working

**Next steps:**
1. Integrate taxonomy classifier into market ingestion pipeline
2. Store classification results (node_path, depth, market_type) in database
3. Build niche detection logic using taxonomy classifications

**Known gaps:**
- Taxonomy covers 4 games initially; will need expansion as more eSports markets appear
- Pattern tuning may be needed based on real Polymarket market titles
- Review flagging will accumulate items for manual taxonomy updates

**Testing readiness:** 101/101 tests passing (18 taxonomy + 83 foundation).
