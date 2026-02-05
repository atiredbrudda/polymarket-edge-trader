# Project Research Summary

**Project:** Polymarket eSports Smart Money Tracker
**Domain:** Prediction Market Analytics / Smart Money Intelligence Tool
**Researched:** 2026-02-05
**Confidence:** HIGH

## Executive Summary

This project aims to build a specialized smart money tracker for eSports prediction markets on Polymarket. The research reveals a mature prediction market analytics ecosystem (170+ tools) where whale tracking is table stakes, but **specialization depth scoring** represents a key differentiator—identifying traders with proven expertise in eSports, not just general profitability.

**Recommended approach:** Build a 5-layer pipeline architecture using Python 3.10+, Polars for high-performance analytics, SQLite for local-first storage, and py-clob-client for Polymarket integration. Use a taxonomy-driven extensible design where eSports categories are data (YAML configs), not code, enabling future expansion without refactoring. The core value proposition: identify eSports-specialized traders, track their positions, and surface consensus signals when multiple experts converge.

**Key risk:** Signal quality is make-or-break. Survivorship bias, overfitting to historical data, and herding mistaken for consensus can render the tool worthless. Mitigation requires minimum sample sizes (10+ bets per category), out-of-sample validation, and timing-based herding detection from Phase 1. Additionally, eSports markets present unique challenges: thin liquidity (many markets <$10k volume), game patches that invalidate historical expertise every 2-4 weeks, and seasonal volatility. The architecture must account for continuous re-evaluation and meta-shift detection.

## Key Findings

### Recommended Stack

The modern Python stack for prediction market analytics has converged on high-performance, type-safe libraries with excellent developer experience. **Python 3.10+ is required** to ensure compatibility across all dependencies (Polars, pytest, python-telegram-bot all mandate 3.10+).

**Core technologies:**
- **py-clob-client 0.34.5**: Official Polymarket CLOB API client — only supported Python library, maintained by Polymarket Engineering, actively updated (Jan 2026)
- **Polars 1.38.0**: DataFrame operations — 3-10x faster than pandas, critical for analyzing thousands of trader positions with multi-threaded operations
- **SQLAlchemy 2.0.46 + SQLite**: Data persistence — local-first architecture, no server management, sufficient for 1K-5K markets with proper indexing
- **APScheduler 3.11.2**: Background polling — in-process scheduling without external dependencies (Celery requires Redis/RabbitMQ)
- **Typer 0.21.1**: CLI framework — type-hint-driven, automatic help generation, Rich integration for beautiful terminal output
- **Pydantic 2.12.5 + pydantic-settings 2.12.0**: Validation and config — runtime validation of API responses, type-safe configuration management
- **discord-webhook 1.4.1 + python-telegram-bot 22.6**: Alerting — webhook-only for Discord, full async API for Telegram
- **Loguru 0.7.3**: Logging — zero-config structured logging with automatic colorization and exception catching

**Critical decision:** Use Polars instead of pandas. eSports markets involve aggregating positions across hundreds of traders and markets—Polars' Rust-based columnar engine, automatic parallelism, and lazy evaluation make it 3-10x faster than pandas' single-threaded row-based approach.

**Development tooling:** Ruff 0.15.0 (replaces Black+Flake8+isort, 10-100x faster), pytest 9.0.2, and uv for package management (10-100x faster than pip, though Poetry remains a solid fallback).

### Expected Features

Research identified 7 table stakes features, 6 differentiators, and 7 anti-features across the prediction market analytics landscape.

**Must have (table stakes):**
- **Trader identification and discovery** — query by wallet address or username, retrieve historical trades
- **Basic performance metrics** — PnL, win rate, total volume, active positions, current value
- **Position tracking** — current open positions with size, direction (YES/NO), entry vs current price
- **Large position alerting (whale tracking)** — monitor trades ≥$10k threshold, real-time alerts via webhook/Telegram
- **Market filtering by category** — identify eSports markets, tag traders by primary category participation
- **Historical data access** — complete trade history with date ranges and resolved vs active filters
- **Multi-channel alerting** — webhooks (MVP), then Telegram, then email/Discord

**Should have (competitive differentiators):**
- **Specialization depth scoring** (PRIMARY DIFFERENTIATOR) — calculate expertise specifically within eSports, penalize low sample sizes, weight recency, generate composite 0-100 score. A trader with 80% win rate across 50 eSports-only markets is more valuable than 70% across 1000 random markets.
- **Consensus signal detection** — identify when 5+ high-expertise traders independently take same position (75%+ agreement weighted by expertise score)
- **Activity-first event discovery** — proactively surface eSports markets where experts are currently active, ranked by "smart money activity score"
- **Multi-timeframe analysis** — 7d/30d/90d/all-time windows to separate consistent performance from lucky streaks
- **Trader watchlists** — save custom lists, compare side-by-side, alert on watchlist activity
- **Historical performance validation** — backtest consensus signals to demonstrate "if you'd followed our experts last month, you'd have been early to 15/20 profitable markets"

**Defer (v2+):**
- Large position alerting can be deferred to post-MVP (table stakes for whale trackers but not blocking core value)
- Advanced multi-channel alerting (start with webhooks, add others later)
- Historical backtesting (marketing asset, not critical user-facing feature)

**Anti-features (explicitly DO NOT build):**
- **Automated trading execution** — regulatory risk, liability nightmare, out of scope for intelligence tool
- **Market outcome predictions** — we track what experts are doing, not what will happen
- **Broad multi-category coverage** — specialization IS the product; expanding to politics/crypto dilutes value
- **Real-time orderbook depth** — market making domain, not intelligence domain
- **Social/community features** — forum/chat/following saturates quickly, high maintenance burden
- **Portfolio management advice** — position sizing recommendations = financial advice = regulatory minefield
- **Historical replay UI** — high complexity, low retention, users care about "what's happening now"

### Architecture Approach

The system should follow a **layered pipeline architecture** with clear separation between ingestion, storage, analysis, intelligence, and presentation. The key insight is to make categories (eSports > League of Legends > Worlds 2026) data-driven via YAML taxonomy files, not hardcoded, enabling expansion to new domains without refactoring pipeline logic.

**Major components (bottom-up):**

1. **Ingestion Layer** — Polymarket API client wrapper with rate limiter and data normalizer. Respects API limits (200 req/10s for /trades, 150 req/10s for /positions). Uses ETags to avoid reprocessing unchanged data.

2. **Storage Layer** — SQLite database with 4 core tables: Markets (market_id, question, category, end_date), Traders (address, first_seen, last_active, total_volume), Positions (trader, market, side, size, entry_price, outcome), Scores (trader, category, accuracy, roi, confidence, sample_size, last_updated). Denormalized for read performance, indexed on category/trader/market_id.

3. **Analysis Layer** — Trader discovery (extract participants from order books), taxonomy classifier (tag markets via YAML-defined keyword matching), historical backtrack (retrieve trader's past performance in category). Taxonomy-driven extensibility means adding eSports subcategories requires editing YAML, not code.

4. **Intelligence Layer** — Scoring engine (multi-dimensional: accuracy × ROI × sample_size_confidence / time_decay, category-specific), consensus detector (threshold-based with weighted voting, triggers when N experts with score >0.7 agree 75%+ on same position), alerting system (webhook delivery with exponential backoff retries, HMAC signatures for authenticity).

5. **Presentation Layer** — Typer-based CLI with command groups (markets, traders, signals, config) and Rich-formatted output. Webhooks for event-driven alerts (JSON payloads with signal metadata, expert consensus, market context).

**Critical patterns:**
- **Taxonomy as data** — categories defined in config/taxonomies/*.yaml, loaded at runtime, classifier uses them to tag markets. Future-proofs system for expansion.
- **Layered boundaries** — strict separation prevents tight coupling. Presentation layer queries storage, not API. Intelligence layer doesn't call ingestion directly.
- **Event-driven + batch** — supports continuous polling (APScheduler background jobs) and one-time batch analysis (CLI commands).
- **Scoring with confidence** — never report scores without sample_size and confidence intervals. Prevents false signals from traders with 2-3 lucky predictions.

**Data flow (end-to-end):**
Polymarket API → Rate Limiter → Fetch Markets → Normalize → Store → Taxonomy Classifier → Trader Discovery → Historical Backtrack → Scoring Engine → Consensus Detector → Alerting System → CLI/Webhooks

### Critical Pitfalls

Research identified 15 pitfalls across critical/moderate/minor categories. Top 5 with highest impact:

1. **Survivorship bias in trader evaluation (CRITICAL)** — Tracking only current winners misses that many are lucky coin-flippers. You backfill their history and conclude they're "experts" when they got hot on 2-3 bets. **Prevention:** Track all traders in market (not just winners), require minimum sample size (10+ bets in category), recalculate expertise quarterly (performance expires), weight by market liquidity (winning $100k market > 10 × $1k markets), flag when high-volume traders exit category.

2. **Overfitting to historical performance (CRITICAL)** — Sophisticated scoring models achieve 85% accuracy on backtests but 51% in production because they memorized past patterns that don't generalize. Small sample sizes in niche categories make spurious correlations look significant. **Prevention:** Out-of-sample testing always (train on 2024, test on 2025 Q1), cross-validation by tournament/season, start with simple models (win rate + volume + recency) before adding complexity, regime-aware evaluation (score separately pre/post game patches), penalize complexity (AIC/BIC), walk-forward validation on rolling windows.

3. **Thin market data quality issues (CRITICAL)** — eSports markets are thin (often <$50k volume). 63% of short-cycle markets have zero volume within 24 hours. A trader's $500 bet can move entire market without information content. You identify "experts" who are just moving illiquid markets. **Prevention:** Liquidity filters (only evaluate on >$10k volume or >100 trades), market impact adjustment (discount trades that moved market >5%), relative sizing (large % of market = less signal), time-to-resolution thresholds (short-cycle <24h need higher liquidity), bid-ask spread analysis (>5% spread = thin market, exclude).

4. **Game patches invalidating historical expertise (CRITICAL)** — League of Legends Patch 15.3 drops, buffing mages and nerfing tanks. Meta shifts completely. Your "expert" with 80% win rate knows the old meta—their predictions are now worse than random. Patches drop every 2-4 weeks for major titles. **Prevention:** Patch-aware evaluation windows (new period when major patch drops, don't blend pre/post-patch), exponential recency weighting (2+ patches ago gets minimal weight), meta-shift detection (monitor expert cohort win-rate drops), game version metadata (tag each market with patch version), warm-start new patches (first 1-2 weeks reduce confidence), cross-meta validation (expert's edge must persist across 2+ patches).

5. **Herding mistaken for consensus (CRITICAL)** — Five "experts" all bet on Team A. Your tool alerts "consensus!" Reality: Expert #1 made large visible bet, #2-#5 copied (cascade effect). No actual information aggregation. **Prevention:** Time-based clustering (if bets within 2 hours after large bet, flag as herding), bet order consideration (weight first expert higher, discount fast-followers), independent research signals (prefer contrarian positions that eventually win), volume-adjusted consensus (weight by size AND timing), minimum time separation (6+ hour gaps for "independent" consensus), alternative explanation check (did single large bet precede cluster?).

**Phase-critical mapping:**
- Phase 1 (Data Collection): Pitfalls #6 (API rate limits), #3 (thin markets), #15 (category mislabeling)
- Phase 2 (Trader Evaluation): Pitfalls #1 (survivorship bias), #2 (overfitting), #7 (correlation vs causation), #10 (taxonomy granularity) — **highest-risk phase**
- Phase 4 (Signal Aggregation): Pitfall #5 (herding detection) — **critical for alert quality**
- Phase 3 (Ongoing Monitoring): Pitfall #4 (game patches) — **prevents signal decay**

## Implications for Roadmap

Based on combined research, the natural phase structure follows the layered pipeline architecture with careful attention to dependency chains and risk concentration.

### Suggested Phase Structure (7 phases)

#### Phase 1: Foundation (Data Collection & Storage)
**Rationale:** Nothing works without data. Must establish reliable ingestion and persistence before any analysis. This is the architectural foundation—get schema design wrong here and refactoring cascades.

**Delivers:**
- Polymarket API client wrapper around py-clob-client
- Rate limiter middleware (200 req/10s for /trades, 150 req/10s for /positions)
- Data normalizer transforming API responses to internal schema
- SQLite database with 4 core tables (Markets, Traders, Positions, Scores)
- Proper indexing (market_id, category, trader+market composite, last_active)
- Basic CRUD operations

**Addresses features:**
- Market filtering and categorization (partial — stores category field)
- Historical data access (foundation)

**Avoids pitfalls:**
- #6: API rate limits (build rate limiter from start, respect documented limits)
- #8: SQLite schema design (use INTEGER for prices in basis points, not FLOAT; index timestamp columns; denormalize for analytics)
- #15: Category mislabeling (capture raw Polymarket categories, prepare for override)

**Research flag:** LOW — py-clob-client is well-documented, SQLite best practices established

---

#### Phase 2: Classification & Discovery (Analysis Layer — Part 1)
**Rationale:** Before scoring traders, must classify which markets are eSports and identify who's participating. Taxonomy system is architectural—drives all downstream scoring.

**Delivers:**
- Taxonomy system with YAML schema for category definitions (eSports > League of Legends > Worlds 2026)
- Taxonomy loader and versioning
- Market classifier using keyword matching (extensible to ML embeddings later)
- Trader discovery pipeline (extract participants from order books and trade history)
- Position tracking and snapshots

**Addresses features:**
- Market filtering by category (complete)
- Trader identification and discovery (complete)
- Position tracking (complete)

**Avoids pitfalls:**
- #10: Taxonomy granularity mismatch (start broad: Sport > Game > Tournament; require 10+ traders with 5+ bets before subcategory)
- #3: Thin market data (capture liquidity metadata: volume, trade count, bid-ask spread)
- #15: Category drift (manual review of top 100 eSports markets, whitelist known tournaments)

**Research flag:** MEDIUM — taxonomy design requires domain knowledge of eSports tournament structure; may need validation with eSports betting experts

---

#### Phase 3: Historical Evaluation (Analysis Layer — Part 2)
**Rationale:** Expertise scoring requires historical context. This is the highest-risk phase—survivorship bias and overfitting lurk here. Build validation infrastructure from day one.

**Delivers:**
- Historical backtrack system (query trader's past markets in category, fetch resolved outcomes)
- Time-series queries with windowing (7d/30d/90d/all-time)
- Outcome resolution tracking (active/resolved/disputed/final states)
- Out-of-sample validation framework (train/test splits by tournament/season)
- Multi-dimensional scoring preparation (calculate accuracy, ROI, sample size, recency)

**Addresses features:**
- Historical data access (complete)
- Basic performance metrics (foundation for next phase)
- Multi-timeframe analysis (foundation)

**Avoids pitfalls:**
- #1: Survivorship bias (track ALL traders in market, not just current winners; flag stopped traders)
- #3: Thin market filters (exclude markets <$10k volume from expertise calculation)
- #11: Resolution disputes (track resolution state changes, delay finalization 3-7 days)
- #2: Overfitting prevention (build cross-validation from start, not after model built)

**Research flag:** HIGH — scoring algorithm design needs validation; recommend `/gsd:research-phase` on expertise scoring formulas, Bayesian confidence intervals, time-decay functions

---

#### Phase 4: Scoring Engine (Intelligence Layer — Part 1)
**Rationale:** Transforms historical performance into actionable expertise scores. Core differentiator lives here—specialization depth scoring separates this tool from generic whale trackers.

**Delivers:**
- Multi-dimensional scoring engine: `Expertise Score = (Accuracy × ROI × Sample_Size_Confidence) / Time_Decay`
- Category-specific scoring (separate scores per taxonomy category)
- Bayesian confidence intervals (adjust for sample size: 10 predictions vs 100)
- Recency weighting with exponential decay (recent bets weighted more)
- Minimum sample size enforcement (10+ bets in category before scoring)
- Patch-aware evaluation (track game version metadata, start new window on major patches)
- Scores table storage with last_updated timestamps

**Addresses features:**
- Specialization depth scoring (PRIMARY DIFFERENTIATOR — complete)
- Basic performance metrics (complete)
- Multi-timeframe analysis (complete)

**Avoids pitfalls:**
- #2: Overfitting (simple model first: win rate + volume + recency; cross-validate on separate tournaments)
- #4: Game patches invalidating expertise (patch-aware windows, exponential decay after patches)
- #7: Correlation vs causation (bet timing analysis: prefer early movers, not followers)
- #1: Survivorship bias (sample size gates, quarterly re-evaluation)

**Research flag:** HIGH — expertise score weighting requires experimentation; 75%+ consensus threshold is hypothesis needing validation

---

#### Phase 5: Signal Detection (Intelligence Layer — Part 2)
**Rationale:** Identifying when multiple experts converge is the core user value. Herding detection is subtle—must distinguish "five independent experts" from "one expert + four copycats."

**Delivers:**
- Consensus detector with threshold-based logic (N experts with score >0.7 agree 75%+ on position)
- Weighted expert voting (higher scores weighted more in consensus calculation)
- Herding detection via time-based clustering (if bets within 2 hours of large bet, flag potential cascade)
- Bet order analysis (first expert weighted higher, fast-followers discounted)
- Minimum time separation (6+ hour gaps for "independent" signals)
- Signal generation with confidence scores (0-100 based on expert agreement + sample sizes)
- Activity-first event discovery (rank markets by expert attention in past 1/6/24 hours)

**Addresses features:**
- Consensus signal detection (complete)
- Activity-first event discovery (complete)

**Avoids pitfalls:**
- #5: Herding mistaken for consensus (timing analysis, order consideration, volume-adjusted weighting)
- #7: Correlation vs causation (prefer contrarian positions that win vs consensus-followers)

**Research flag:** MEDIUM — consensus threshold calibration (75% is hypothesis) and herding detection heuristics need validation with historical data

---

#### Phase 6: Alerting System (Presentation Layer — Part 1)
**Rationale:** Signals are useless if users don't receive them. Webhook reliability builds trust.

**Delivers:**
- Alerting system with webhook delivery (POST JSON payloads with signal metadata, expert consensus, market context)
- Retry logic with exponential backoff (3 retries at 1s, 5s, 25s intervals)
- HMAC-SHA256 signatures for webhook authenticity
- Dead letter queue for failed deliveries
- Alert history tracking (delivery success/failure rates)
- Telegram bot integration (python-telegram-bot async API)
- Discord webhook integration (discord-webhook library)

**Addresses features:**
- Large position alerting (whale tracking — deferred but straightforward to add)
- Multi-channel alerts (webhooks MVP, Telegram/Discord post-MVP)

**Avoids pitfalls:**
- #13: Webhook delivery failures (retry with backoff, dead letter queue, health checks)

**Research flag:** LOW — webhook patterns well-established in crypto/trading tools

---

#### Phase 7: CLI Interface (Presentation Layer — Part 2)
**Rationale:** CLI is presentation layer, depends on all underlying components. Comes last.

**Delivers:**
- Typer-based command structure with groups (markets, traders, signals, config)
- Commands: `tracker markets list`, `tracker traders discover`, `tracker traders score <addr>`, `tracker signals check`, `tracker signals history`, `tracker config set`
- Rich-formatted output (tables for trader leaderboards, panels for signal alerts, progress bars for long operations)
- Configuration management (pydantic-settings with .env overrides, CLI flag precedence)
- Watchlist functionality (save custom trader lists, alert on watchlist activity)

**Addresses features:**
- Trader comparison and watchlists (complete)
- All CLI interaction patterns

**Avoids pitfalls:**
- #9: Premature optimization (single-process Python script is sufficient; defer Airflow/Redis/message queues until proven necessary)

**Research flag:** LOW — Typer documentation comprehensive, CLI patterns straightforward

---

### Phase Ordering Rationale

**Dependency-driven sequence:**
- Phases 1-2 are **foundation** — data ingestion and classification enable all downstream work
- Phase 3 must precede Phase 4 — can't score expertise without historical performance data
- Phase 4 must precede Phase 5 — consensus detection requires scored experts
- Phases 6-7 are **presentation** — consume intelligence layer outputs

**Risk-informed grouping:**
- Phase 3-4 (Historical Evaluation + Scoring) is **highest-risk duo** — survivorship bias and overfitting concentrate here. Budget extra time for validation, out-of-sample testing, and iterative refinement.
- Phase 5 (Signal Detection) is **critical for value delivery** — herding detection separates signal from noise. Bad consensus = worthless alerts.
- Phases 6-7 are **lower risk** — established patterns, defer until intelligence layer proven.

**Architectural alignment:**
- Phases map cleanly to architecture layers: 1 (Ingestion), 2-3 (Analysis), 4-5 (Intelligence), 6-7 (Presentation)
- Each phase delivers a complete layer before moving up the stack
- No layer skipping (presentation doesn't call ingestion)

**Pitfall mitigation built-in:**
- Phase 1 addresses API rate limits and schema design (can't fix later)
- Phases 2-3 address taxonomy and data quality (architectural decisions)
- Phase 4 addresses scoring methodology (validation from start, not afterthought)
- Phase 5 addresses herding detection (timing analysis baked into consensus logic)

### Research Flags

**Phases needing deeper research during planning:**

- **Phase 2 (Classification & Discovery):** Taxonomy granularity vs sample size trade-offs — recommend `/gsd:research-phase` on eSports market structure (how Polymarket categorizes League vs CS:GO vs Dota, tournament naming conventions, regional splits). Domain expertise needed.

- **Phase 3 (Historical Evaluation):** Out-of-sample validation strategy, time-series cross-validation for prediction markets — recommend `/gsd:research-phase` on validation frameworks that avoid leakage in temporal data.

- **Phase 4 (Scoring Engine):** Expertise score weighting, Bayesian confidence intervals, time-decay functions, patch-aware evaluation — recommend `/gsd:research-phase` on scoring algorithm design. High complexity, requires experimentation and backtest validation.

- **Phase 5 (Signal Detection):** Consensus threshold calibration (75% is hypothesis), herding detection heuristics, timing-based clustering parameters — recommend `/gsd:research-phase` on signal detection thresholds using historical Polymarket data.

**Phases with standard patterns (skip research-phase):**

- **Phase 1 (Foundation):** py-clob-client integration, SQLite schema design, rate limiting — well-documented patterns, proceed to planning directly.

- **Phase 6 (Alerting):** Webhook delivery, retry logic, HMAC signatures — established patterns in crypto/trading tools, proceed to planning directly.

- **Phase 7 (CLI Interface):** Typer command structure, Rich formatting — comprehensive documentation, proceed to planning directly.

**Validation checkpoints:**

- After Phase 4: Run backtests on historical eSports markets (Jan-Dec 2025) to validate expertise scores predict outcomes better than random baseline. Gap >10% between backtest and out-of-sample = red flag for overfitting.

- After Phase 5: Validate consensus signals on 2025 data not used in Phase 4 tuning. Measure: How often did 75%+ expert agreement predict winning outcome? Target: >65% hit rate (vs 50% random baseline).

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| **Stack** | HIGH | All core libraries verified via PyPI, actively maintained with Jan-Feb 2026 releases. py-clob-client is official Polymarket library. Polars performance benchmarks from multiple sources. Python 3.10+ baseline compatible with all dependencies. |
| **Features** | MEDIUM-HIGH | Strong consensus across 10+ prediction market analytics platforms on table stakes (whale tracking, performance metrics). Specialization depth scoring validated by niche analytics trends, but implementation details are custom. Consensus detection validated by sports betting tools, but prediction market application is emerging. |
| **Architecture** | MEDIUM-HIGH | Layered pipeline pattern well-established in data engineering. Taxonomy-driven classification validated by recent AI classification systems. SQLite for local-first analytics is proven approach. Event-driven + batch hybrid is standard. Webhook architecture patterns well-documented. |
| **Pitfalls** | HIGH | Survivorship bias and overfitting extensively documented in trading/finance literature. Polymarket API rate limits verified in official docs and GitHub issues. Thin market liquidity confirmed by Polymarket volume analysis (63% of short-cycle markets have zero volume). Game patches impact validated by eSports betting operator interviews. Herding behavior documented in prediction market research. |

**Overall confidence:** HIGH

The stack, architecture, and pitfalls have strong evidence backing. Features have medium-high confidence because specialization scoring and consensus detection are differentiators without established "correct" implementations—they'll require experimentation and validation.

### Gaps to Address

**During planning/execution:**

1. **Optimal expertise score weighting** — Simple formula proposed (Accuracy × ROI × Sample_Size_Confidence / Time_Decay) but coefficients require tuning. Address in Phase 4 with backtests on 2025 data, iterate based on out-of-sample performance.

2. **Consensus threshold calibration** — 75% expert agreement is hypothesis, not validated. Address in Phase 5 by sweeping thresholds (60%, 70%, 75%, 80%) on historical data, measure hit rates and false positive rates.

3. **Specific eSports market structure on Polymarket** — Research covered general patterns but didn't deep-dive into how Polymarket structures League of Legends vs CS:GO markets, tournament naming conventions, regional splits. Address with `/gsd:research-phase` in Phase 2 focusing specifically on Polymarket eSports taxonomy.

4. **Polymarket API rate limits edge cases** — Official docs specify limits but not behavior when mixing endpoints (e.g., simultaneous /trades + /positions requests). Address in Phase 1 with conservative rate limiting (80% of documented limits) and monitoring of 429 responses.

5. **Herding detection timing thresholds** — Proposed 2-hour window and 6-hour minimum separation are heuristics. Address in Phase 5 by analyzing historical bet clustering patterns in eSports markets (when do cascades occur? what time gaps indicate independence?).

6. **Game patch tracking integration** — Need reliable source for League of Legends, Dota, CS:GO patch releases with version numbers and dates. Address in Phase 4 by identifying community resources (e.g., Liquipedia, official patch notes APIs) to auto-tag markets with game versions.

7. **Thin market volume thresholds** — Proposed $10k minimum is based on general market analysis; eSports markets may need different thresholds by game/tournament tier. Address in Phase 1 by analyzing Polymarket eSports market volume distribution, set thresholds at 75th percentile (exclude bottom 25% illiquid markets).

## Sources

### Primary (HIGH confidence)

**Stack:**
- [py-clob-client PyPI](https://pypi.org/project/py-clob-client/) — official library, version 0.34.5 verified
- [Polars PyPI](https://pypi.org/project/polars/) — version 1.38.0 verified, performance benchmarks
- [SQLAlchemy PyPI](https://pypi.org/project/SQLAlchemy/) — version 2.0.46 verified
- [Typer PyPI](https://pypi.org/project/typer/) — version 0.21.1 verified
- [Pydantic PyPI](https://pypi.org/project/pydantic/) — version 2.12.5 verified
- [Polymarket CLOB API Documentation](https://docs.polymarket.com/developers/CLOB/introduction) — official integration guide

**Features:**
- [Polymarket Analytics Traders Leaderboard](https://polymarketanalytics.com/traders) — industry standard features
- [Top 10 PolyMarket Analytics Tools (2026)](https://signals.coincodecap.com/top-polymarket-analytics-tools) — ecosystem survey
- [Polywhaler Whale Tracker](https://www.polywhaler.com/) — whale tracking patterns
- [Polymarket API Documentation](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets) — data access patterns

**Pitfalls:**
- [Polymarket API Rate Limits](https://docs.polymarket.com/quickstart/introduction/rate-limits) — 200 req/10s trades, 150 req/10s positions verified
- [Survivorship Bias in Backtesting Explained | LuxAlgo](https://www.luxalgo.com/blog/survivorship-bias-in-backtesting-explained/) — 1-4% annual overstatement
- [Polymarket Liquidity Analysis | Phemex](https://phemex.com/news/article/polymarket-liquidity-analysis-reveals-key-insights-into-prediction-markets-52184) — 63% short-cycle zero volume
- [Game Patches Impact on Esports Odds | We Are Brighton](https://www.wearebrighton.com/newsopinion/how-in-game-patches-influence-odds-movement-in-mobile-esports-markets/) — betting operators quote patches
- [Improving Prediction Market Forecasts | ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0377221718305575) — herding behavior research

### Secondary (MEDIUM confidence)

**Architecture:**
- [The Polymarket API Architecture | Medium](https://medium.com/@gwrx2005/the-polymarket-api-architecture-endpoints-and-use-cases-f1d88fa6c1bf) — architectural patterns
- [Data Pipeline Design in Algorithmic Trading | Medium](https://medium.com/@edwinsalguero/data-pipeline-design-in-an-algorithmic-trading-system-ac0d8109c4b9) — layered architecture
- [Layered Architecture for Extensible Apps | Towards Data Science](https://towardsdatascience.com/layered-architecture-for-building-readable-robust-and-extensible-apps/) — component boundaries
- [Webhook System Design Guide | System Design Handbook](https://www.systemdesignhandbook.com/guides/design-a-webhook-system/) — alerting patterns

**Specialization:**
- [Niche Analytics Industry Insights | Data Expertise](https://www.dataexpertise.in/niche-analytics-industry-sector-insights/) — specialization depth value
- [Specialist Market Research Agencies | Insight7](https://insight7.io/specialist-market-research-agencies-for-niche-markets/) — 2026 specialization trends

**eSports specifics:**
- [Bayes Esports Navigating Game Patches | SBC News](https://sbcnews.co.uk/features/interviews/2024/04/29/bayes-esports-game-patches/) — patch adaptation strategies
- [Impact of Patches on Esports Betting Odds | Egamers World](https://egamersworld.com/blog/the-impact-of-patches-and-updates-on-e-sports-bett-wO-USpjzBL) — 2-4 week patch cycles

### Tertiary (LOW confidence — needs validation)

- Consensus threshold of 75% expert agreement — hypothesis based on sports betting consensus tools, not validated in eSports prediction markets specifically
- $10k minimum market volume threshold — based on general Polymarket liquidity analysis, may need adjustment for eSports markets
- 2-hour herding window and 6-hour independence gap — heuristics inferred from cascade behavior literature, not eSports-specific

---

*Research completed: 2026-02-05*
*Ready for roadmap: YES*
