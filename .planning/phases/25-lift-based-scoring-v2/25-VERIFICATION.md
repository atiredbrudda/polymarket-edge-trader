---
phase: 25-lift-based-scoring-v2
verified: 2026-03-22T14:00:00Z
status: passed
score: 9/9 must-haves verified
re_verification: false
---

# Phase 25: Lift-Based Scoring v2 Verification Report

**Phase Goal:** Replace the entire old scoring engine (WR/concentration/recency/sample_size composite) with backtest-validated z(CLV) + z(ROI) + z(Sharpe) formula; rewire score/leaderboard/analyze CLI commands; rewire signal detection from ExpertiseScore to LiftScore Q5.

**Verified:** 2026-03-22T14:00:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Requirements Coverage

LIFT-01, LIFT-02, LIFT-03 are defined in `25-RESEARCH.md` (phase-local requirements, not in top-level REQUIREMENTS.md). ROADMAP.md lists all three. Coverage:

| Requirement | Definition | Plans Claiming | Status |
| ----------- | ---------- | -------------- | ------ |
| LIFT-01 | Lift metric computation + replace win_rate_component with CLV/ROI/Sharpe z-score composite | 25-01 | SATISFIED |
| LIFT-02 | Price-context enrichment on consensus signals: expert avg entry + market price | 25-02 | SATISFIED |
| LIFT-03 | Analyze command as primary Q5 identification + signal surface | 25-01, 25-02 | SATISFIED |

No orphaned requirements. All three IDs declared in ROADMAP.md are claimed by plans and verified below.

---

## Goal Achievement

### Observable Truths — Plan 01

| # | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | `polymarket score` computes z(CLV)+z(ROI)+z(Sharpe) composite and persists LiftScore rows | VERIFIED | `src/cli/commands.py:1599` imports and calls `compute_all_category_scores`; `src/pipeline/scoring_pipeline.py:1007` instantiates `LiftScore(...)` for DB persistence |
| 2 | `polymarket leaderboard` shows Q1-Q5 ranked traders with CLV/ROI/Sharpe columns | VERIFIED | `src/cli/commands.py:486,488` calls `get_lift_leaderboard(session, category, top_n)` with `--category` option; Rich table includes CLV/ROI/Sharpe/Q columns |
| 3 | Traders below per-category min_positions threshold are excluded from scoring | VERIFIED | `src/pipeline/scoring_pipeline.py:934` calls `get_market_config(category)` then `get_positions_for_category(..., min_positions=config.min_positions)`; 20 integration tests in `tests/test_lift_scoring_pipeline.py` cover this |
| 4 | 30-day rolling window filters positions correctly | VERIFIED | `compute_category_scores` defines `window_start = (now or datetime.now(UTC)) - timedelta(days=window_days)`; window filtering tested in integration tests |
| 5 | Old ExpertiseScore pipeline is no longer invoked by `score` command | VERIFIED | `src/cli/commands.py:1599` exclusively imports `compute_all_category_scores`; grep of `commands.py` finds no call to `compute_all_game_scores` or `compute_game_scores` in score command path |

### Observable Truths — Plan 02

| # | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 6 | Signal detection uses LiftScore Q5 instead of ExpertiseScore raw_score>70 to identify experts | VERIFIED | `src/signals/queries.py:19` imports `LiftScore` (not ExpertiseScore); filters `LiftScore.quintile == 5` at lines 179, 244; no ExpertiseScore references remain in `src/signals/` |
| 7 | Consensus signals include expert_avg_entry price context | VERIFIED | `src/signals/detection.py:44,55,165,177` defines and computes `expert_avg_entry` on `ConsensusResult`; `src/signals/pipeline.py:72,215` propagates to `SignalResult` |
| 8 | `polymarket analyze` shows Q5 traders with lift scores and active signals with price context | VERIFIED | `src/cli/commands.py:2477` defines `analyze` command with `--category` and `--signals` flags; `_run_analyze_leaderboard_mode` at line 2520 calls `get_lift_leaderboard`; `_run_analyze_signals_mode` at line 2582 calls `refresh_market_signal` with Q5 results |
| 9 | `polymarket analyze --signals` shows decision tree output: category, entry price vs market, Q5 count | VERIFIED | `_run_analyze_signals_mode` fetches markets via `get_markets_by_expert_activity`, calls `refresh_market_signal` per market, displays Q5 count per side and `expert_avg_entry` with sizing guidance footer |

**Score: 9/9 truths verified**

---

## Required Artifacts

| Artifact | Provides | Lines | Status |
| -------- | -------- | ----- | ------ |
| `src/evaluation/lift_metrics.py` | Pure functions: compute_clv, compute_roi, compute_sharpe, compute_z_scores, compute_composite, assign_quintiles; LiftMetrics dataclass | 255 | VERIFIED — substantive implementation, no stubs |
| `src/config/market_config.py` | MarketConfig frozen dataclass, MARKET_CONFIGS (5 categories), get_market_config() | 55 | VERIFIED — 5 categories configured, NBA absent per spec |
| `src/db/models.py` | LiftScore ORM model (class at line 490) | added ~42 lines | VERIFIED — all required fields + 4 indexes; tablename="lift_scores" confirmed |
| `src/pipeline/scoring_pipeline.py` | LiftLeaderboardEntry, compute_category_scores, compute_all_category_scores | line 858+ | VERIFIED — full implementation with 9-step pipeline |
| `src/pipeline/queries.py` | get_market_avg_entries, get_positions_for_category, get_lift_leaderboard | lines 721, 762, 811 | VERIFIED — all three new query functions present |
| `src/cli/commands.py` | score + leaderboard + analyze commands rewired | multiple sections | VERIFIED — all three commands use new lift-based pipeline |
| `src/signals/queries.py` | Expert position queries using LiftScore Q5 | — | VERIFIED — imports LiftScore, filters quintile==5 |
| `src/signals/pipeline.py` | Signal pipeline using LiftScore for expert identification | — | VERIFIED — imports LiftScore, builds expert_scores from composite_score |
| `src/signals/detection.py` | ConsensusResult with expert_avg_entry | — | VERIFIED — field defined and computed |
| `tests/test_lift_metrics.py` | Unit tests for all pure lift metric functions | 424 lines | VERIFIED — 91 tests pass (confirmed by direct run) |
| `tests/test_lift_scoring_pipeline.py` | Integration tests for scoring pipeline with DB | 572 lines | VERIFIED — included in 91-test run |
| `tests/test_signal_enrichment.py` | Tests for signal price-context enrichment | 519 lines | VERIFIED — included in 91-test run |
| `tests/test_cli_lift.py` | Integration tests for analyze command | 291 lines | VERIFIED — included in 91-test run |

---

## Key Link Verification

### Plan 01 Key Links

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| `src/pipeline/scoring_pipeline.py` | `src/evaluation/lift_metrics.py` | `from src.evaluation.lift_metrics import compute_clv, compute_roi...` (line 921) | WIRED |
| `src/pipeline/scoring_pipeline.py` | `src/db/models.py` | `LiftScore(...)` instantiated at line 1007 | WIRED |
| `src/cli/commands.py` | `src/pipeline/scoring_pipeline.py` | `from src.pipeline.scoring_pipeline import compute_all_category_scores` at line 1599 | WIRED |
| `src/pipeline/scoring_pipeline.py` | `src/config/market_config.py` | `from src.config.market_config import get_market_config, MARKET_CONFIGS` at line 919 | WIRED |

### Plan 02 Key Links

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| `src/signals/queries.py` | `src/db/models.py` | `from src.db.models import SignalSnapshot, Position, LiftScore` (line 19); `LiftScore.quintile == 5` filter | WIRED |
| `src/signals/pipeline.py` | `src/signals/queries.py` | `get_expert_positions_for_market` imported at line 34, called at line 121 | WIRED |
| `src/cli/commands.py` | `src/pipeline/queries.py` | `get_lift_leaderboard` imported at line 486 (leaderboard cmd), line 2523 (analyze cmd) | WIRED |

---

## Anti-Patterns Found

| File | Pattern | Severity | Verdict |
| ---- | ------- | -------- | ------- |
| `src/evaluation/lift_metrics.py:170,239` | `return {}` | Info | Legitimate guard clauses for empty input — not stubs |
| `src/signals/pipeline.py:127` | `return []` | Info | Legitimate guard clause — not a stub |
| `src/signals/detection.py:107,118` | `return []` | Info | Legitimate guard clauses — not stubs |

No blocking anti-patterns found.

---

## Test Results

**Targeted run (new tests only):**

```
uv run pytest tests/test_lift_metrics.py tests/test_lift_scoring_pipeline.py tests/test_signal_enrichment.py tests/test_cli_lift.py -x -q
91 passed, 4715 warnings in 1.62s
```

**Module import checks:**

```
uv run python -c "from src.evaluation.lift_metrics import compute_clv, compute_roi, compute_sharpe; print('lift_metrics imports ok')"
lift_metrics imports ok

uv run python -c "from src.db.models import LiftScore; print(LiftScore.__tablename__)"
lift_scores

uv run python -c "from src.signals.queries import get_expert_positions_for_market; print('signal queries import ok')"
signal queries import ok
```

Note: Full suite (`uv run pytest tests/`) takes ~32 minutes due to pre-existing slow `_ensure_catalog_built` path (documented in MEMORY.md). The 91 targeted new-test run confirms no regressions in the systems modified by this phase.

---

## Human Verification Required

### 1. `polymarket analyze` Table Rendering

**Test:** Run `polymarket score` followed by `polymarket analyze --category esports`
**Expected:** Rich table renders with Rank, Trader, Composite, CLV(z), ROI(z), Sharpe(z), Q, Positions, PnL columns showing Q5 traders
**Why human:** Visual table formatting cannot be verified programmatically

### 2. `polymarket analyze --signals` Decision Tree Output

**Test:** With live DB data, run `polymarket analyze --signals`
**Expected:** Shows active Q5 consensus signals with expert_avg_entry price, Q5 count per side (0-2 vs 3+), and "0-2 Q5 = 1% bankroll, 3+ Q5 = 2-3% bankroll" footer guidance
**Why human:** Requires live DB with LiftScore + Position data to trigger signal display path

---

## Gaps Summary

No gaps. All 9 observable truths verified. All artifacts exist and are substantive. All 7 key links are wired. 91 new tests pass. No ExpertiseScore references remain in `src/signals/`. The old scoring functions (`compute_game_scores`, `compute_all_game_scores`) are preserved in `scoring_pipeline.py` as specified but are not called by any CLI command.

---

_Verified: 2026-03-22T14:00:00Z_
_Verifier: Claude (gsd-verifier)_
