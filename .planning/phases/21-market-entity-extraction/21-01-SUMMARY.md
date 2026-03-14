# Phase 21 Plan 01 Summary

## Objective
Define the MarketEntity DB model and the LLM extraction function that turns a market question string into structured entity data.

## Changes Made

### src/db/models.py (MODIFIED)
Appended MarketEntity ORM model:
- `__tablename__ = "market_entities"`
- `condition_id`: String(100), unique, non-nullable (one extraction per market)
- `team_a`, `team_b`, `tournament`, `game`: String(200), nullable
- `market_type`: String(10), nullable ("match"/"prop"/None)
- `extracted_at`: datetime, default=datetime.utcnow
- Unique index on condition_id
- No foreign keys — plain string key to avoid migration complexity

### src/extraction/ (NEW package)
- `__init__.py`: Package marker
- `llm_extractor.py`: LLM extraction module
  - `EntityResult` dataclass with 5 fields (team_a, team_b, tournament, game, market_type)
  - `extract_entities(question, client)` function using Anthropic Claude Haiku 3.5
  - Prompt instructs JSON-only response
  - Graceful failure: returns EntityResult() with all None on API errors or JSON parse failures

### pyproject.toml (MODIFIED)
Added `anthropic>=0.84.0` to dependencies

### tests/extraction/test_llm_extractor.py (NEW)
4 unit tests using unittest.mock.MagicMock:
1. `test_extract_match_market`: Mock returns valid JSON with both teams
2. `test_extract_prop_market`: Mock returns tournament+game only, teams=null
3. `test_extract_api_failure`: Mock raises anthropic.APIError → returns all-None EntityResult
4. `test_extract_malformed_json`: Mock returns non-JSON text → returns all-None EntityResult

## Verification
- Imports verified: `from src.db.models import MarketEntity; from src.extraction.llm_extractor import extract_entities, EntityResult`
- No foreign keys: `[c.foreign_keys for c in MarketEntity.__table__.columns]` returns all empty sets
- All 4 tests pass (0 real API calls)

## Test Results
- 4/4 new tests pass
- Tests use mocked anthropic client — no real API calls

## Notes
- Model uses SQLAlchemy 2.0 declarative style with Mapped[] type hints
- Extraction failures never propagate exceptions — always return EntityResult() with all None
- Tournament-only markets supported (team_a=None, team_b=None, tournament populated)
- Plan 02 will wire this into discover command with taxonomy normalization
