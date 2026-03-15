# Plan 24-01 Summary: Scoring Rewire to MarketEntity

## What Was Built

Rewired 13 functions across 4 source files from `MarketClassification`/`TaxonomyNode` joins to `MarketEntity` joins for eSports market detection and scoring.

### Files Modified

1. **src/discovery/trader_discovery.py**
   - `discover_esports_traders()` - now joins Trade -> MarketEntity where game IS NOT NULL
   - `compute_and_store_positions()` - now queries MarketEntity for market filtering

2. **src/pipeline/queries.py**
   - `get_all_game_slugs_with_positions()` - returns distinct game names (e.g., "CS2")
   - `get_positions_for_game()` - joins Position -> MarketEntity on game name
   - `get_positions_for_slug()` - detects entity level (game/tournament/team) from MarketEntity columns
   - `get_all_slugs_with_positions_at_depth()` - queries MarketEntity.game/tournament/team columns by depth

3. **src/pipeline/scoring_pipeline.py**
   - `_get_esports_positions()` - joins Position -> MarketEntity where game IS NOT NULL
   - `_get_positions_for_depth()` - looks up parent entity via MarketEntity columns
   - `compute_taxonomy_scores()` - trader discovery via MarketEntity joins based on depth

4. **src/pipeline/ingest.py**
   - `_get_esports_market_ids()` - queries MarketEntity.condition_id where game IS NOT NULL

### Test Files Updated

- tests/test_discovery.py - fixture uses MarketEntity instead of TaxonomyNode/MarketClassification
- tests/test_scoring_pipeline.py - fixture and assertions updated for game names ("CS2" not "esports.cs2")
- tests/test_scoring_pipeline_deep.py - fixture and assertions updated for entity names

## Key Decisions

1. **Game slug format change**: `ExpertiseScore.game_slug` now stores actual game names ("CS2", "Dota 2") instead of taxonomy slugs ("esports.cs2")

2. **Entity detection in `get_positions_for_slug()`**: Function now detects which entity level (game/tournament/team) the slug matches by querying MarketEntity columns directly

3. **`identify_hidden_specialists()` rewrite**: Changed from LIKE pattern matching on dot-separated slugs to MarketEntity-based lookup of tournaments/teams belonging to a game

## Test Results

All 26 modified tests pass:
- tests/test_discovery.py: 7 passed
- tests/test_scoring_pipeline.py: 13 passed  
- tests/test_scoring_pipeline_deep.py: 6 passed

## Verification

```bash
# No taxonomy references in rewired source files
grep -c "MarketClassification\|TaxonomyNode" src/discovery/trader_discovery.py src/pipeline/queries.py src/pipeline/scoring_pipeline.py
# Output: all 0

# Note: ingest.py has 9 remaining references in functions outside this task's scope
# (discover_traders_from_market and taxonomy classification creation logic)
```

## Known Issues

None. All rewired functions work correctly with MarketEntity joins.

## Follow-up Items

None. The rewire is complete for all 13 functions specified in the plan.
