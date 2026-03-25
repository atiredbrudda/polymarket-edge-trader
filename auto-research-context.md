# Autoresearch + Autocontext Integration Plan

**Project:** Polymarket Smart Money Tracker  
**Version:** 1.2 (Entity-Level Intelligence)  
**Created:** 2026-03-14

---

## Executive Summary

This document details how **Autoresearch** (code mutation + performance optimization) and **Autocontext** (knowledge persistence + learning loops) integrate into a unified system for the Polymarket Smart Money Tracker.

**Core insight:** Data extraction needs *speed* (Autoresearch), while data processing needs *wisdom* (Autocontext). The two systems form a closed loop where performance gains enable more learning iterations, and learning gains focus computation on high-value data.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                     AUTORESEARCH LAYER                            │
│              "Make queries faster, cheaper, bigger"               │
├──────────────────────────────────────────────────────────────────┤
│  Files:                                                          │
│  - src/datasources/jbecker.py       (DuckDB query patterns)      │
│  - src/api/client.py                (API batch strategies)       │
│  - src/graph/client.py              (Subgraph query optimization)│
│  - src/blockchain/client.py         (RPC call batching)          │
│  - src/pipeline/ingest.py           (Ingestion throughput)       │
│  - src/catalog/builder.py           (Token catalog build speed)  │
│                                                                  │
│  Metric: tokens/sec, query latency, cost per trader, rows/sec   │
│  Loop: Mutate code → Run benchmark → Keep if faster             │
└──────────────────────────────────────────────────────────────────┘
                              ↓ feeds data to
┌──────────────────────────────────────────────────────────────────┐
│                     AUTOCONTEXT LAYER                             │
│          "Learn which traders, signals, patterns matter"          │
├──────────────────────────────────────────────────────────────────┤
│  Files:                                                          │
│  - src/evaluation/scoring.py        (Scoring playbooks)          │
│  - src/signals/detection.py         (Detection thresholds)       │
│  - src/taxonomy/classifier.py       (Classification rules)       │
│  - src/taxonomy/esports.yaml        (Keyword evolution)          │
│  - src/alerts/formatter.py          (Alert format testing)       │
│  - knowledge/                       (Persistent learning store)  │
│                                                                  │
│  Metric: signal precision, expert accuracy, alert CTR           │
│  Loop: Run task → Analyze outcome → Update playbook → Persist   │
└──────────────────────────────────────────────────────────────────┘
                              ↓ feeds back to
┌──────────────────────────────────────────────────────────────────┐
│                     FEEDBACK INTEGRATION                          │
│         "Don't waste fast queries on low-value data"              │
├──────────────────────────────────────────────────────────────────┤
│  Autocontext learns: "Traders with <50 trades never produce      │
│                       strong signals"                              │
│         ↓                                                        │
│  Autoresearch implements: Skip low-volume traders in JBecker     │
│                           query → 3x faster ingestion            │
│         ↓                                                        │
│  Autocontext learns: "Tournament specialists have 15% higher     │
│                       signal precision"                            │
│         ↓                                                        │
│  Autoresearch implements: Index tournament_id column → faster    │
│                           tournament queries                      │
└──────────────────────────────────────────────────────────────────┘
```

---

## Detailed Component Map

### Layer 1: Data Extraction (Autoresearch Domain)

| Component | Current State | Autoresearch Experiments | Success Metric |
|-----------|---------------|-------------------------|----------------|
| **JBecker Dataset Queries** | DuckDB with filter pushdown | - Projection pushdown patterns<br>- Batch size optimization (1k, 10k, 100k rows)<br>- Parallel file scans<br>- Index configurations | Query latency (ms), rows/sec |
| **Polymarket API Client** | 50 req/s token bucket | - Request batching (10, 50, 100 per batch)<br>- Connection pooling strategies<br>- Retry backoff patterns<br>- Prefetch hints | Throughput (req/min), 429 rate |
| **The Graph Subgraph** | Single queries per trader | - Query consolidation (multiple traders in one query)<br>- Filter placement optimization<br>- Pagination strategies | Query time (s), API units consumed |
| **Blockchain RPC** | Sequential block scans | - Parallel block ranges<br>- Batch contract calls<br>- State caching strategies | Blocks/sec, RPC cost per trader |
| **Token Catalog Builder** | 25s one-time build | - Parallel file processing<br>- Classification caching<br>- Incremental rebuild | Build time (s), cache hit rate |
| **JBecker Ingestion** | Sequential INSERT with savepoints | - Batch INSERT (100, 1000, 10000)<br>- WAL tuning<br>- Transaction sizing | Rows/sec, DB write latency |

**Autoresearch Protocol:**
1. Agent modifies ONE file (e.g., `src/datasources/jbecker.py`)
2. Runs fixed 5-minute benchmark suite
3. Measures throughput vs baseline
4. Keeps change if ≥10% improvement, else reverts
5. Logs to `autoresearch/logs/experiments.log`

---

### Layer 2: Data Processing (Autocontext Domain)

| Component | Current State | Autocontext Learning Loop | Success Metric |
|-----------|---------------|--------------------------|----------------|
| **Expertise Scoring** | Fixed weights (PnL 40%, WR 30%, Consistency 30%) | - Run: Score with variant weights<br>- Analyze: Which weights predict signal hits?<br>- Update: Playbook with winning formula<br>- Persist: `knowledge/playbooks/scoring.json` | Signal precision (hit rate %) |
| **Consensus Detection** | Fixed thresholds (3+ experts, 75%+ agreement) | - Run: Detect with variant thresholds<br>- Analyze: Precision/recall per threshold<br>- Update: Market-specific thresholds (CS2 vs LoL)<br>- Persist: `knowledge/playbooks/detection.json` | F1 score, false positive rate |
| **Taxonomy Classification** | Static keywords in YAML | - Run: Classify markets<br>- Analyze: Misclassification patterns<br>- Update: Add winning keywords, remove losers<br>- Persist: `knowledge/hints/taxonomy_patterns.json` | Classification coverage %, accuracy |
| **Entity Extraction (LLM)** | Claude Haiku 3.5, fixed prompt | - Run: Extract entities with prompt variants<br>- Analyze: Entity match rate vs manual audit<br>- Update: Prompt templates that work<br>- Persist: `knowledge/hints/entity_prompts.json` | Entity extraction accuracy % |
| **Alert Formatting** | Fixed template | - Run: A/B test alert formats<br>- Analyze: User engagement (if tracked)<br>- Update: Format with highest engagement<br>- Persist: `knowledge/reports/alert_ab_results.json` | Alert engagement rate |
| **Team-Level Win Rates** | Pre-computed TraderTeamStats | - Run: Query-time win rate computation<br>- Analyze: Which teams have predictive traders?<br>- Update: Team-specific signal weights<br>- Persist: `knowledge/playbooks/team_weights.json` | Team signal ROI |

**Autocontext Protocol:**
1. **Competitor** proposes configuration/scoring variant
2. **Analyst** tracks outcomes against historical results
3. **Coach** converts analysis into playbook updates
4. **Curator** gates changes (requires 3 successful validations)
5. Persists to `knowledge/` directory as JSON

---

## Cross-Layer Feedback Loops

### Loop 1: Trader Filtering (Highest Priority)

```
Autocontext learns:
  "Traders with <50 resolved trades produce signals with 12% precision"
  "Traders with ≥50 resolved trades produce signals with 68% precision"
  → Playbook update: MIN_TRADE_THRESHOLD = 50
         ↓
Autoresearch implements:
  JBecker query adds: WHERE trade_count >= 50
  Result: 60% fewer rows scanned, 2.3x faster ingestion
         ↓
Autocontext re-runs:
  Same precision (68%) maintained, but 3x more traders scored per hour
  → Validation passed, playbook confirmed
```

**Files affected:**
- Autocontext: `knowledge/playbooks/trader_filtering.json`
- Autoresearch: `src/datasources/jbecker.py:fetch_trader_history()`
- Autocontext: `knowledge/reports/filter_impact_analysis.json`

---

### Loop 2: Tournament Indexing (High Priority)

```
Autocontext learns:
  "Tournament-level specialists have 73% signal precision vs 58% game-level"
  "Tournament queries are 40% of all scoring queries"
  → Playbook update: Prioritize tournament_id indexing
         ↓
Autoresearch implements:
  CREATE INDEX idx_tournament_id ON trader_team_stats(tournament_id);
  Experiments with: (game_id, tournament_id) composite index
  Result: Tournament queries 5x faster
         ↓
Autocontext re-runs:
  Scoring pipeline completes 18% faster overall
  → Validation passed, index added to schema
```

**Files affected:**
- Autocontext: `knowledge/playbooks/index_strategy.json`
- Autoresearch: `src/db/migrations.py` (new index migration)
- Autocontext: `knowledge/reports/query_benchmark.json`

---

### Loop 3: Entity Coverage Expansion (Medium Priority)

```
Autocontext learns:
  "Markets without entity extraction have 34% lower signal detection rate"
  "LLM entity extraction costs $0.002/market, adds 2s latency"
  → Playbook update: Backfill entities for all historical markets
         ↓
Autoresearch implements:
  Batch entity extraction (100 markets/batch)
  Parallel Haiku API calls (10 concurrent)
  Result: 10,000 markets in 35 min vs 5.5 hours sequential
         ↓
Autocontext re-runs:
  Signal detection increases 22% (more markets classified)
  → Validation passed, backfill scheduled
```

**Files affected:**
- Autocontext: `knowledge/playbooks/entity_backfill.json`
- Autoresearch: `src/gamma/extraction_pipeline.py` (new batch logic)
- Autocontext: `knowledge/reports/entity_coverage_impact.json`

---

### Loop 4: API Rate Adaptation (Medium Priority)

```
Autocontext learns:
  "Rate limit errors spike at 55+ req/s during peak hours (9am-5pm UTC)"
  "Off-peak (1am-7am UTC) sustains 70 req/s without errors"
  → Playbook update: Time-aware rate limiting
         ↓
Autoresearch implements:
  AdaptiveRateLimiter class
  Peak hours: 45 req/s, Off-peak: 65 req/s
  Result: 40% fewer 429 errors, 25% higher throughput
         ↓
Autocontext re-runs:
  Backfill completes 18% faster during off-peak windows
  → Validation passed, adaptive limiting enabled
```

**Files affected:**
- Autocontext: `knowledge/playbooks/rate_limiting.json`
- Autoresearch: `src/api/rate_limiter.py` (new AdaptiveRateLimiter)
- Autocontext: `knowledge/reports/rate_limit_audit.json`

---

### Loop 5: Signal Deduplication (Lower Priority)

```
Autocontext learns:
  "Duplicate alerts (same market, <60min apart) have 89% lower engagement"
  "Users dismiss duplicate alerts within 3 seconds"
  → Playbook update: Extend dedup TTL to 120 minutes
         ↓
Autoresearch implements:
  No code change — configuration only
  ALERT_DEDUP_TTL_MINUTES=120 in settings
  Result: 47% fewer alerts sent, same signal coverage
         ↓
Autocontext re-runs:
  Alert engagement rate increases 34%
  → Validation passed, TTL change persisted
```

**Files affected:**
- Autocontext: `knowledge/playbooks/alert_config.json`
- Autoresearch: N/A (configuration change only)
- Autocontext: `knowledge/reports/alert_dedup_analysis.json`

---

## Implementation Phases

### Phase 1: Foundation (Week 1)

**Goal:** Set up both frameworks with minimal viable loops

| Task | Owner | Files | Acceptance Criteria |
|------|-------|-------|---------------------|
| Create `autoresearch/` directory | Human | `autoresearch/program.md`, `autoresearch/experiment.py` | Can run `uv run autoresearch/experiment.py` |
| Create `knowledge/` directory | Human | `knowledge/playbooks/`, `knowledge/hints/`, `knowledge/reports/` | Directory structure exists |
| Implement Autoresearch benchmark harness | Human + Agent | `autoresearch/benchmark.py` | Measures JBecker query latency, API throughput |
| Implement Autocontext analyst agent | Human + Agent | `autocontext/analyst.py` | Tracks signal outcomes, writes analysis JSON |
| Baseline measurements | Agent | `autoresearch/logs/baseline.log`, `knowledge/reports/baseline.json` | Current performance documented |

**Deliverables:**
- `autoresearch/program.md` — Agent instructions
- `autoresearch/experiment.py` — Single experiment runner (like karpathy's `train.py`)
- `autocontext/analyst.py` — Outcome tracker
- `knowledge/playbooks/.gitkeep` — Initial structure

---

### Phase 2: First Feedback Loop (Week 2)

**Goal:** Complete Loop 1 (Trader Filtering) end-to-end

| Task | Owner | Files | Acceptance Criteria |
|------|-------|-------|---------------------|
| Autocontext: Implement signal outcome tracker | Agent | `autocontext/outcome_tracker.py` | Tracks which signals hit/miss |
| Autocontext: Analyze trader volume vs precision | Agent | `knowledge/reports/trader_volume_analysis.json` | Correlation documented |
| Autocontext: Write trader filtering playbook | Agent | `knowledge/playbooks/trader_filtering.json` | Playbook with MIN_TRADE_THRESHOLD |
| Autoresearch: Implement JBecker filter | Agent | `src/datasources/jbecker.py` | WHERE clause added |
| Autoresearch: Benchmark filter impact | Agent | `autoresearch/logs/filter_benchmark.log` | Performance delta measured |
| Autocontext: Validate signal precision maintained | Agent | `knowledge/reports/filter_validation.json` | Precision within ±2% of baseline |

**Deliverables:**
- Working feedback loop from Autocontext → Autoresearch → Autocontext
- Documented playbook: `knowledge/playbooks/trader_filtering.json`
- Performance improvement: ≥50% faster JBecker ingestion

---

### Phase 3: Expand Learning Loops (Week 3-4)

**Goal:** Implement Loops 2-4 (Tournament Indexing, Entity Coverage, Rate Adaptation)

| Task | Owner | Files | Acceptance Criteria |
|------|-------|-------|---------------------|
| Autocontext: Tournament specialist analysis | Agent | `knowledge/reports/tournament_specialist_audit.json` | Precision by depth documented |
| Autoresearch: Index experimentation | Agent | `src/db/migrations.py`, `autoresearch/logs/index_benchmarks.log` | Index variants tested |
| Autocontext: Entity backfill priority | Agent | `knowledge/playbooks/entity_backfill.json` | Backfill queue generated |
| Autoresearch: Batch entity extraction | Agent | `src/gamma/extraction_pipeline.py` | 100 markets/batch, 10 concurrent |
| Autocontext: Rate limit pattern analysis | Agent | `knowledge/reports/rate_limit_patterns.json` | Peak/off-peak thresholds identified |
| Autoresearch: Adaptive rate limiter | Agent | `src/api/rate_limiter.py` | Time-aware limiting implemented |

**Deliverables:**
- 3 additional working feedback loops
- Tournament query latency reduced ≥40%
- Entity coverage increased ≥50%
- API throughput increased ≥25%

---

### Phase 4: Integration & Automation (Week 5-6)

**Goal:** Connect loops into autonomous overnight operation

| Task | Owner | Files | Acceptance Criteria |
|------|-------|-------|---------------------|
| Implement orchestrator | Agent | `autocontext/orchestrator.py` | Runs both loops in sequence |
| Add guardrails | Agent | `autocontext/guardrails.py` | Prevents destructive changes |
| Implement rollback | Agent | `autocontext/rollback.py` | Reverts bad changes automatically |
| Schedule overnight runs | Human | `cron` job or GitHub Actions | Runs 2am-6am daily |
| Morning digest | Agent | `autocontext/digest.py` | Summarizes overnight experiments |

**Deliverables:**
- `autocontext/orchestrator.py` — Runs full loop autonomously
- Morning email/Slack digest of overnight experiments
- Rollback working for failed experiments

---

### Phase 5: Advanced Optimization (Week 7-8)

**Goal:** Multi-objective optimization and model distillation

| Task | Owner | Files | Acceptance Criteria |
|------|-------|-------|---------------------|
| Implement utility function | Agent | `autocontext/utility.py` | Balances speed vs precision |
| Train small model for signal prediction | Agent | `autocontext/models/signal_predictor.py` | ≥80% accuracy on signal outcomes |
| Implement model inference in scoring | Agent | `src/evaluation/scoring.py` | Model scores used alongside formula |
| A/B test model vs formula | Agent | `knowledge/reports/model_ab_test.json` | Model performance validated |

**Deliverables:**
- Distilled model for signal quality prediction
- Multi-objective optimization (speed + precision + cost)
- Model inference integrated into scoring pipeline

---

## File Dependencies

```
src/datasources/jbecker.py
  └── affected by: knowledge/playbooks/trader_filtering.json
  └── affects: autocontext/outcome_tracker.py (via data quality)

src/api/rate_limiter.py
  └── affected by: knowledge/playbooks/rate_limiting.json
  └── affects: src/pipeline/ingest.py (via throughput)

src/evaluation/scoring.py
  └── affected by: knowledge/playbooks/scoring.json
  └── affects: src/signals/detection.py (via scores)

src/signals/detection.py
  └── affected by: knowledge/playbooks/detection.json
  └── affects: knowledge/reports/signal_audit.json (via outcomes)

src/taxonomy/classifier.py
  └── affected by: knowledge/hints/taxonomy_patterns.json
  └── affects: src/catalog/builder.py (via classification)

knowledge/playbooks/*.json
  └── Read by: All src/ modules that consume playbooks
  └── Written by: autocontext/analyst.py, autocontext/coach.py

autoresearch/logs/*.log
  └── Written by: autoresearch/experiment.py
  └── Read by: autocontext/analyst.py (for performance analysis)
```

---

## Knowledge Store Structure

```
knowledge/
├── playbooks/                    # Validated, production-ready rules
│   ├── trader_filtering.json     # MIN_TRADE_THRESHOLD, filters
│   ├── scoring_weights.json      # PnL/WR/consistency weights
│   ├── detection_thresholds.json # Expert count, agreement %
│   ├── index_strategy.json       # Database index priorities
│   ├── rate_limiting.json        # Time-aware rate limits
│   ├── team_weights.json         # Team-specific signal multipliers
│   └── entity_backfill.json      # Entity extraction priorities
│
├── hints/                        # Experimental, unvalidated patterns
│   ├── taxonomy_patterns.json    # Keyword additions (pending validation)
│   ├── entity_prompts.json       # LLM prompt variants
│   ├── query_hints.json          # Query optimization ideas
│   └── market_patterns.json      # Market-level signal patterns
│
├── reports/                      # Analysis outputs, audit trails
│   ├── baseline.json             # Initial performance measurements
│   ├── trader_volume_analysis.json
│   ├── tournament_specialist_audit.json
│   ├── entity_coverage_impact.json
│   ├── rate_limit_audit.json
│   ├── signal_precision_weekly.json
│   └── filter_validation.json
│
└── models/                       # Distilled models (Phase 5)
    ├── signal_predictor.pkl      # Signal outcome prediction
    ├── trader_quality_model.pkl  # Trader expertise classification
    └── market_volatility_model.pkl
```

---

## Experiment Logging Format

### Autoresearch Logs (`autoresearch/logs/`)

```json
{
  "experiment_id": "ar_20260314_001",
  "timestamp": "2026-03-14T02:15:33Z",
  "target_file": "src/datasources/jbecker.py",
  "change_description": "Added WHERE trade_count >= 50 filter",
  "baseline_metric": {
    "name": "jbecker_query_latency_ms",
    "value": 847
  },
  "experiment_metric": {
    "name": "jbecker_query_latency_ms",
    "value": 312
  },
  "improvement_pct": 63.2,
  "decision": "KEEP",
  "validation_status": "PASSED"
}
```

### Autocontext Logs (`knowledge/reports/`)

```json
{
  "analysis_id": "ac_20260314_001",
  "timestamp": "2026-03-14T02:45:12Z",
  "playbook": "trader_filtering",
  "observation": "Traders with <50 trades have 12% signal precision vs 68% for ≥50",
  "sample_size": 1847,
  "confidence": 0.95,
  "recommendation": "Set MIN_TRADE_THRESHOLD = 50",
  "validation_required_runs": 3,
  "validation_current_runs": 1,
  "status": "PENDING_VALIDATION"
}
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Autoresearch makes destructive DB changes | Guardrails: No DROP TABLE, no DELETE without WHERE |
| Autocontext learns wrong patterns | Curator gates: Requires 3 successful validations |
| Feedback loop amplifies errors | Rollback: Automatic revert if signal precision drops >10% |
| Overnight experiments break CI | Pre-flight: Run pytest before any experiment |
| Knowledge store becomes inconsistent | Schema validation: JSON Schema for all playbooks |
| Model distillation reduces accuracy | A/B testing: Model must match formula within ±5% |

---

## Success Metrics

| Metric | Baseline | Target (8 weeks) | Measurement |
|--------|----------|------------------|-------------|
| JBecker query latency | 847ms | ≤300ms | `autoresearch/benchmark.py` |
| API throughput | 50 req/s | ≥70 req/s | `src/api/rate_limiter.py` logs |
| Signal precision | 68% | ≥80% | `knowledge/reports/signal_precision_weekly.json` |
| Entity coverage | 34% | ≥75% | `knowledge/reports/entity_coverage_impact.json` |
| Scoring pipeline time | 3.2 min | ≤1.5 min | `polymarket score` timing |
| Traders scored per hour | 120 | ≥400 | `knowledge/reports/throughput_audit.json` |

---

## Quick Start Commands

```bash
# Run single Autoresearch experiment (5-min budget)
uv run autoresearch/experiment.py --target jbecker --variant projection_pushdown

# Run Autocontext analysis on latest signals
uv run autocontext/analyst.py --window 7d

# Run full integrated loop (both layers)
uv run autocontext/orchestrator.py --gens 3

# View current playbooks
uv run autocontext list-playbooks

# View experiment history
uv run autoresearch/list --status kept

# Export training data for model distillation (Phase 5)
uv run autocontext export-training-data --all-runs --output training/signal_outcomes.jsonl
```

---

## Next Actions (Immediate)

1. **Create directory structure** (Human, 15 min)
   ```bash
   mkdir -p autoresearch/logs knowledge/{playbooks,hints,reports,models}
   ```

2. **Write `autoresearch/program.md`** (Human + Agent, 1 hour)
   - Agent instructions for data layer experiments
   - Benchmark protocol
   - Success criteria

3. **Write `autocontext/analyst.py`** (Agent, 2 hours)
   - Signal outcome tracker
   - Playbook writer
   - Validation gate

4. **Run baseline measurements** (Agent, 30 min)
   - JBecker latency
   - API throughput
   - Signal precision

5. **Begin Loop 1** (Agent, overnight)
   - Trader filtering analysis
   - JBecker filter implementation
   - Validation

---

## Appendix: Comparison to Reference Projects

| Feature | karpathy/autoresearch | greyhaven/autocontext | This Project |
|---------|----------------------|----------------------|--------------|
| **Target** | LLM training code | Agent behavior | Data pipeline + scoring |
| **Mutation** | Single file (`train.py`) | Playbooks (JSON) | Data layer (Python) + Playbooks (JSON) |
| **Metric** | Validation loss | Task success | Speed + Signal precision |
| **Time budget** | Fixed 5 min | Variable | 5 min (AR) + overnight (AC) |
| **Persistence** | None (discard/keep) | Knowledge store | Knowledge store + code |
| **Feedback loop** | None | Yes (multi-agent) | Yes (cross-layer) |

---

*Last updated: 2026-03-14*
