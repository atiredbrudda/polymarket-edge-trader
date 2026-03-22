# Phase 21 Plan 02 Summary

## Objective
Wire LLM extraction into the discover command and add taxonomy normalization so LLM team/tournament names are canonicalized against esports.yaml aliases.

## Changes Made

### src/extraction/normalizer.py (NEW)
- `_load_alias_maps()`: Loads data/taxonomy/esports.yaml at import time, builds alias -> canonical maps
  - team_aliases: "NaVi".lower() -> "Natus Vincere", "FaZe".lower() -> "FaZe Clan"
  - tournament_map: "iem katowice".lower() -> "IEM Katowice"
  - game_map: "cs2".lower() -> "CS2"
- `normalize_entities(result: EntityResult) -> EntityResult`: Returns new EntityResult with normalized fields
  - team_a, team_b: Look up against team_aliases (case-insensitive)
  - tournament: Look up against tournament_map (case-insensitive)
  - game: Look up against game_map (case-insensitive)
  - market_type: Pass through unchanged
  - None values: Pass through as None
  - Unknown names: Keep as-is from LLM

### src/cli/commands.py (MODIFIED)
- Added imports: `extract_entities`, `EntityResult`, `normalize_entities`, `MarketEntity`, `datetime`
- Added `entities_extracted = 0` counter before market loop
- Added entity extraction inside discover try block (after trader discovery):
  1. Call `extract_entities(market.question)` to get raw LLM result
  2. Call `normalize_entities(raw_result)` to canonicalize names
  3. Upsert to market_entities table (update existing or insert new)
  4. Commit and increment `entities_extracted` counter
- Added output line: `Entities stored: {entities_extracted}`

### tests/extraction/test_normalizer.py (NEW)
5 unit tests:
1. `test_known_alias_normalized`: "NaVi" -> "Natus Vincere", "FaZe" -> "FaZe Clan"
2. `test_unknown_team_kept`: Unknown names pass through unchanged
3. `test_none_fields_pass_through`: EntityResult() with all None returns all None
4. `test_game_normalized`: "cs2" -> "CS2"
5. `test_tournament_normalized`: "iem katowice" -> "IEM Katowice"

## Verification
- All 9 extraction tests pass (4 from 21-01 + 5 from 21-02)
- 26 catalog tests pass (no regressions)
- discover command imports without error
- Upsert logic verified: existing rows updated, new rows inserted

## Test Results
- 9/9 extraction tests pass
- 26/26 catalog tests pass
- Pre-existing failure in test_jbecker.py (unrelated to this change)

## Notes
- Alias lookup is case-insensitive on both sides
- Path resolution uses `Path(__file__).parent.parent.parent` to find esports.yaml — works from any directory
- Extraction happens inside try block but has its own exception handling — failures log warning but don't abort discover
- market_entities table has unique constraint on condition_id — prevents duplicate extractions
- Plan 23 will use these entities for contextual win rate scoring
