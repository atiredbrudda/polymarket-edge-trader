# Domain Pitfalls: Polymarket eSports Smart Money Tracker

**Domain:** Prediction Market Analytics / Smart Money Tracking
**Focus:** eSports markets on Polymarket
**Researched:** 2026-02-05
**Overall Risk Level:** HIGH - Signal quality is make-or-break

---

## Executive Summary

Building a smart money tracker for Polymarket eSports markets presents unique challenges across data acquisition, trader evaluation, signal quality, and architecture. The core risk is **signal quality**: if expert identification fails or signals are false positives, the tool has zero value.

**Critical insight:** eSports markets are fundamentally different from macro/political markets—they have lower liquidity, specialized knowledge barriers, and game-patch-driven volatility that can invalidate historical trader performance overnight.

---

## Critical Pitfalls

Mistakes that cause rewrites, invalid signals, or project failure.

### 1. Survivorship Bias in Trader Evaluation

**What goes wrong:**
You track only traders who are *currently* profitable, missing that many were lucky on 2-3 bets. You backfill their history and conclude they're "experts" when they're actually coin-flippers who got hot. Conversely, you ignore traders who had bad quarters but possess genuine expertise.

**Why it happens:**
- Starting with "top performers" and working backwards
- Not tracking traders who stopped trading (quit after losses)
- Cherry-picking recent winners without full market context
- Ignoring that 63% of short-term markets have zero volume—winning a $500 market isn't signal

**Consequences:**
- **False expert identification**: Your "smart money" is noise
- **Herding on noise**: You surface consensus among lucky traders, not informed ones
- **Signal degradation over time**: As luck runs out, your alerts lose value
- **Survivorship inflation**: Excluding defunct stocks/traders overstates returns by 1-4% annually in traditional markets—prediction markets likely worse due to higher churn

**Prevention:**
1. **Track all traders in a market**, not just winners—evaluate expertise across full trading history
2. **Require minimum sample size**: Don't score traders with <10 bets in category
3. **Time-window evaluation**: Recalculate expertise quarterly—past performance expires
4. **Account for market liquidity**: Weight bets by market volume (winning a $100k market > winning 10x $1k markets)
5. **Track stopped traders**: Flag when high-volume traders exit a category (signal of changing conditions)

**Detection:**
- Your "experts" have short trading histories (< 6 months)
- Expert list changes drastically quarter-over-quarter
- Consensus signals underperform random baseline
- Experts have high win rates but only 3-5 total bets

**Phase mapping:** Address in **Phase 1: Data Collection** (track all traders) and **Phase 2: Trader Evaluation** (implement anti-survivorship scoring)

---

### 2. Overfitting to Historical Performance

**What goes wrong:**
You build sophisticated trader-scoring models trained on historical outcomes. Model achieves 85% accuracy on backtests. In production, it's 51% (coin-flip). The model memorized past patterns that don't generalize.

**Why it happens:**
- Tuning evaluation parameters to maximize historical accuracy
- Using too many features (trader win rate, average bet size, time-to-bet, position duration, etc.) on small sample
- Not accounting for regime changes (e.g., game patches, meta shifts, tournament format changes)
- Small sample sizes in niche categories make spurious correlations look significant

**Consequences:**
- **Production signals are worthless**: Historical 85% accuracy becomes 51% live
- **Fragile to market changes**: Model breaks when game meta shifts
- **False confidence**: You trust the model because backtests worked
- **Wasted complexity**: Simple heuristics might outperform

**Prevention:**
1. **Out-of-sample testing**: Always test on time periods NOT used for tuning
2. **Cross-validation by tournament/season**: Train on 2024 data, test on 2025 Q1, then retrain
3. **Simple models first**: Start with "win rate + volume + recency" before adding complexity
4. **Regime-aware evaluation**: Score traders separately pre/post major game patches
5. **Penalize complexity**: Use AIC/BIC—model must significantly outperform to justify extra parameters
6. **Walk-forward validation**: Continuously retrain and test on rolling windows

**Detection:**
- Backtest accuracy >> production accuracy (>10% gap is red flag)
- Model uses >5 parameters with <100 trader samples
- Performance collapses after game patches
- Expert scores are unstable week-to-week

**Phase mapping:** Critical for **Phase 2: Trader Evaluation**—build in validation from day one, not after model is built

---

### 3. Thin Market Data Quality Issues

**What goes wrong:**
eSports markets are thin (often <$50k volume per event). You treat a trader's $500 bet the same as their $10k bet. You miss that 63% of short-cycle markets have zero volume within 24 hours. Your "expert" made one $200 bet that moved the entire market—not because they're informed, but because there was no liquidity.

**Why it happens:**
- Polymarket liquidity concentrates on macro/political events (505 contracts with >$10M volume = 47% of all volume)
- eSports events average $1.32M for <1 day cycles, but many individual markets are far smaller
- Single large bet can move illiquid markets 10-20% without information content
- 25% of Polymarket volume may be wash trading (artificial activity)

**Consequences:**
- **Price movements ≠ information**: Trader moved market due to liquidity, not expertise
- **Can't exit positions**: Expert identification fails because you can't verify trader intent—did they want that price or accept it due to thin book?
- **Spurious correlation**: You identify "experts" who are just moving illiquid markets
- **Incomplete data**: Some markets have 12+ hour gaps in price data due to no trading

**Prevention:**
1. **Liquidity filters**: Only evaluate traders on markets with >$10k volume or >100 trades
2. **Market impact adjustment**: Discount trades that moved market >5% as execution noise
3. **Relative sizing**: Weight trader bets by % of market volume they represent—large % = less signal
4. **Time-to-resolution consideration**: Short-cycle markets (<24h) require higher liquidity thresholds
5. **Bid-ask spread analysis**: Wide spreads (>5%) indicate thin market—flag for exclusion
6. **Volume stability**: Require consistent trading activity (not just single spike) before scoring market

**Detection:**
- Experts have large win rates but bets on <$5k volume markets
- Market prices gap frequently (sign of no continuous trading)
- Trader positions are >10% of total market volume
- Can't reconstruct price history at <12h granularity for resolved markets

**Phase mapping:** Address in **Phase 1: Data Collection** (capture liquidity metadata) and **Phase 2: Evaluation** (filter by liquidity thresholds)

---

### 4. Game Patches Invalidating Historical Expertise

**What goes wrong:**
You identify a League of Legends expert with 80% win rate across 20 markets. Riot releases Patch 15.3, buffing mages and nerfing tanks. The meta shifts completely. Your "expert" knows the old meta—their predictions are now worse than random because they're anchored to obsolete patterns. Your tool continues surfacing them as expert.

**Why it happens:**
- Game patches fundamentally alter competitive outcomes (character viability, strategy effectiveness)
- Patches drop every 2-4 weeks for major titles—frequent regime changes
- Historical win rates don't transfer across meta shifts
- Betting operators that don't update models post-patch get "run away with a big portion of their money"—same applies to your tracker

**Consequences:**
- **Expertise expires without detection**: Your top-rated traders become anti-signal
- **Delayed adaptation**: Takes weeks of bad signals before you notice expert degradation
- **User trust loss**: Alerts based on outdated expertise fail repeatedly
- **Missed new experts**: Players who understand new meta aren't identified yet

**Prevention:**
1. **Patch-aware evaluation windows**: When major patch drops, start new evaluation period—don't blend pre/post-patch performance
2. **Recency weighting**: Exponentially decay trader scores—bets from 2+ patches ago get minimal weight
3. **Meta-shift detection**: Monitor for sudden expert win-rate drops across cohort (signals meta change)
4. **Game version metadata**: Tag each market with game version—track expert performance per-patch
5. **Warm-start new patches**: First 1-2 weeks post-patch, reduce confidence scores (everyone is learning)
6. **Cross-meta validation**: Test if expert's edge persists across 2+ major patches before full trust

**Detection:**
- Expert cohort suddenly underperforms (all experts drop >15% win rate simultaneously)
- New dominant strategies emerge in pro play not reflected in expert positions
- Patch notes mention major balance changes but your expert scores unchanged
- Community discussions reference "new meta" but your signals show no adaptation

**Phase mapping:** Critical for **Phase 3: Ongoing Monitoring**—build patch-tracking from start, but automation here prevents signal decay

---

### 5. Herding Mistaken for Consensus

**What goes wrong:**
Five "experts" all bet on Team A to win. Your tool alerts: "Smart money consensus on Team A!" In reality, Expert #1 made a large visible bet, and Experts #2-#5 copied them (herding). No actual information aggregation occurred. Team A loses.

**Why it happens:**
- Information asymmetry leads to cascade effects—informed participant's large bet triggers imitation
- Less-informed traders rationally copy visible large bets, assuming they have information
- Prediction markets show herding behavior—research disagrees whether it's over-reaction or genuine information
- You can't distinguish "five independent experts agree" from "one expert + four copycats"

**Consequences:**
- **False consensus signals**: You amplify herding as if it's information
- **Concentrated risk**: All your "experts" lose together because they weren't independent
- **Cascade amplification**: Your alerts trigger more users to follow, creating larger herding
- **Signal quality illusion**: High agreement looks like confidence but is correlation

**Prevention:**
1. **Time-based clustering analysis**: If multiple experts bet within short window (e.g., 2 hours) after large bet, flag as potential herding
2. **Bet order consideration**: Give higher weight to first expert to take position—discount fast-followers
3. **Independent research signals**: Prefer experts who bet against visible trends (contrarian positions with eventual wins)
4. **Volume-adjusted consensus**: Weight by bet size AND timing—late small bets get minimal weight
5. **Minimum time separation**: Require 6+ hour gaps between "consensus" bets to call it independent
6. **Alternative explanation check**: Before alerting consensus, check if single large bet preceded cluster

**Detection:**
- All expert bets occur within 1-2 hours
- Bets cluster after single large (>$5k) market-moving trade
- Expert bet sizes decrease in time order (first bet largest, followers smaller)
- Consensus signals consistently underperform vs. early-mover-only signals

**Phase mapping:** Address in **Phase 4: Signal Aggregation**—critical to get consensus detection right or alerts are noise

---

### 6. Polymarket API Rate Limits & Data Gaps

**What goes wrong:**
You build aggressive data collection: fetch all active markets every 5 minutes, plus trader history. You hit rate limits (429 errors), requests queue, data arrives delayed or incomplete. You miss trader bets because polling wasn't frequent enough. Historical analysis fails because `/prices-history` returns empty for resolved markets at <12h granularity.

**Why it happens:**
- Polymarket has strict rate limits: `/trades` = 200 req/10s, `/positions` = 150 req/10s
- Historical data endpoint has quirks (requires `startTs/endTs` instead of `interval: "max"` for fine granularity)
- Rate-limited requests queue rather than fail—causes unpredictable delays
- 25 req/min limit on RELAYER endpoint is extremely tight

**Consequences:**
- **Delayed alerts**: By time you detect consensus, odds have moved
- **Incomplete trader histories**: Missing bets = inaccurate expertise scoring
- **Backfill failures**: Can't get granular historical data without workarounds
- **Production instability**: Queuing causes unpredictable latency spikes

**Prevention:**
1. **Respect rate limits in code**: Implement client-side rate limiting (tenacity library with exponential backoff)
2. **Batch requests**: Fetch multiple markets/traders per request where API supports it
3. **Polling optimization**: Use WebSocket for price updates (higher throughput) instead of REST polling
4. **Caching strategy**: Cache market metadata (changes infrequently), fetch positions/trades more often
5. **Historical data workaround**: Always use explicit `startTs/endTs` for price history, never `interval: "max"` for <12h resolution
6. **Prioritize endpoints**: Critical data (trader positions) gets priority over nice-to-have (full order book depth)
7. **Monitor 429s**: Log rate limit hits—if frequent, redesign data collection approach

**Detection:**
- Frequent HTTP 429 errors in logs
- Increasing request queue times (>10s latency)
- Missing trader bets when comparing to Polymarket UI
- Empty results from `/prices-history` for known-active markets

**Phase mapping:** Must address in **Phase 1: Data Collection**—rate limit strategy is architectural, can't bolt on later

---

### 7. Correlation vs. Causation in Expert Signals

**What goes wrong:**
You find that Expert A's bets on Team X correlate with Team X winning 75% of the time. You conclude Expert A has predictive power. Reality: Expert A bets on heavy favorites after odds have moved—they're following the market, not leading it. Or: Expert A bets early and market follows them, but their edge comes from social media audience (they move markets via followers), not analytical skill.

**Why it happens:**
- Conditional markets reveal correlations but can't disentangle correlation from causation
- Trader might be informed, or lucky, or influential (moves market via audience)
- Bet timing isn't always clear—API might not expose when bet was *placed* vs *filled*
- You can't observe trader research process—just results

**Consequences:**
- **Rewarding laggards**: You identify momentum-followers as experts
- **Influencer confusion**: Social media personalities with large audiences move markets but aren't necessarily informed
- **Spurious signals**: Correlation looks like expertise but breaks down in production
- **Gaming vulnerability**: If tracker becomes known, influencers could manipulate by betting early with audience amplification

**Prevention:**
1. **Bet timing analysis**: Prefer traders who bet *before* large market movements, not after
2. **Price impact vs. outcome correlation**: Separate "moved market correctly" from "followed market correctly"
3. **Volume-adjusted timing**: Expert bet early + small volume + price later moved = potential leading indicator
4. **Social media cross-reference**: Flag traders with large followings—their bets might move market mechanically
5. **Contrarian position weighting**: Traders who bet against consensus and win show stronger signal than consensus-followers who win
6. **Randomization test**: Simulate random betting with same timing/sizing—does "expert" outperform?

**Detection:**
- Expert bets consistently after large market movements (follower pattern)
- Expert has large social media following and bets move markets immediately
- Expert performance degrades when you only count pre-movement bets
- Random traders with similar timing have similar "expertise" scores

**Phase mapping:** Address in **Phase 2: Trader Evaluation**—timing analysis must be part of scoring from start

---

## Moderate Pitfalls

Mistakes that cause delays, technical debt, or degraded performance.

### 8. SQLite Schema Design for Time-Series Data

**What goes wrong:**
You design a normalized schema with traders, markets, bets, price_history as separate tables. Joins are slow. You use FLOAT for prices (introduces rounding errors). No indexes on timestamp columns. Queries for "trader performance over last 30 days" take 10+ seconds with 100k bet records.

**Why it happens:**
- Natural tendency to normalize (good for OLTP, bad for analytics)
- Floating-point seems obvious for prices (but prediction markets use 0-1 probabilities → integer cents)
- Indexing as afterthought
- No batch transactions (SQLite is 20x slower without transactions)

**Consequences:**
- **Slow queries**: Can't generate real-time alerts
- **Precision errors**: 0.1 + 0.2 ≠ 0.3 in floating-point → scoring errors compound
- **Write bottlenecks**: Individual inserts are painfully slow
- **Schema refactoring**: Requires migration with production data

**Prevention:**
1. **Denormalize for analytics**: Store flattened records optimized for common queries (trader_performance table with pre-aggregated stats)
2. **Integer storage**: Store probabilities as integers (e.g., 50.5% = 505 basis points)—eliminates rounding
3. **Index critical columns**: Timestamp, trader_id, market_id, category—create indexes during schema creation
4. **Batch transactions**: Wrap bulk inserts in `BEGIN/COMMIT` blocks (20x speedup)
5. **Appropriate data types**: Use INTEGER for IDs/prices, TEXT for hashes, REAL only when necessary
6. **Partitioning strategy**: Consider separate tables by time window (current_bets vs historical_bets) for large datasets

**Detection:**
- Queries take >1s with <100k records
- Floating-point arithmetic errors in profit calculations
- Write throughput <100 records/second
- No `CREATE INDEX` statements in schema

**Phase mapping:** Must get right in **Phase 1: Data Collection**—schema changes are expensive once data accumulates

---

### 9. Premature Optimization: Over-Engineering Pipeline

**What goes wrong:**
You build a sophisticated multi-stage data pipeline with Airflow orchestration, Redis caching, separate write/read DBs, and message queues. It takes 3 weeks to build. You have 50 users. The pipeline's complexity makes debugging impossible. A single-threaded Python script would have worked fine.

**Why it happens:**
- Anticipating scale problems that don't exist yet
- Resume-driven development (want to use new tech)
- Assumption that "proper architecture" requires complexity
- 80% of runtime is I/O/queries, not Python loops—but you optimize Python

**Consequences:**
- **Delayed launch**: 3 weeks on infrastructure, 1 week on actual features
- **Debugging nightmare**: Can't trace bugs across distributed components
- **Maintenance burden**: More components = more failure modes
- **Wrong optimization target**: Spent time optimizing Python when SQL query is the bottleneck

**Prevention:**
1. **Start simple**: Single-process Python script + SQLite can handle 1000s of markets
2. **Optimize bottlenecks**: Profile first—80% of time is likely database queries or API rate limits
3. **Defer complexity**: Don't build caching layer until you measure cache hit rate would help
4. **Boring tech**: Use well-understood tools (Python stdlib, SQLite, cron) until they break
5. **Measure first**: Benchmark actual performance before optimizing—is it actually slow?
6. **Incremental complexity**: Add components only when current system demonstrably fails

**Detection:**
- Project has >3 architectural diagrams before writing feature code
- Infrastructure code > business logic code
- Can't run entire system on single laptop
- Team debates Kafka vs RabbitMQ before handling first API request

**Phase mapping:** Guard against throughout—default to simple in **every phase**

---

### 10. Taxonomy Granularity Mismatch

**What goes wrong:**
You build a 5-level taxonomy: Sport > Game > Tournament > Region > Team. It's thorough! You want to identify "LCS Spring 2026 expert" vs "LEC Winter 2026 expert". Problem: You have 3 traders who've bet on LCS Spring and 1 on LEC Winter—sample size too small. Expertise scores are noise. Meanwhile, you miss that a "League of Legends expert" (aggregated level) exists.

**Why it happens:**
- Desire for precision conflicts with statistical power
- eSports markets are already niche—subdividing makes samples tiny
- Easy to add granularity, hard to aggregate later
- Belief that "more specific = better signal"

**Consequences:**
- **Insufficient sample size**: Can't reliably score experts at granular level
- **Missed broader patterns**: Regional expert exists but hidden by over-subdivision
- **Maintenance nightmare**: Taxonomy requires constant updates (new tournaments, team rebrands)
- **Cold start problem**: New categories have zero traders for months

**Prevention:**
1. **Start broad**: Begin with Sport > Game > Tournament—expand only if sample size supports
2. **Sample size gates**: Require 10+ traders with 5+ bets each before creating subcategory
3. **Hierarchical scoring**: Score at multiple levels (Game expert + Tournament specialist)—use both
4. **Seasonal aggregation**: Group "Spring 2026" and "Summer 2026" into "2026 Season" until sample size grows
5. **Dynamic taxonomy**: Let data dictate structure—if LCS has 50 traders but LEC has 5, different granularity
6. **Rollup strategy**: Always able to aggregate up (Tournament → Game → Sport) when granular level is sparse

**Detection:**
- Categories with <10 total traders
- Expert scores change drastically with single bet addition/removal
- Long tail of empty categories (20+ categories with 0-2 traders each)
- Can't produce signals because no experts meet criteria

**Phase mapping:** Critical decision in **Phase 2: Trader Evaluation**—taxonomy is hard to refactor once scoring logic depends on it

---

### 11. Ignoring Market Resolution Disputes

**What goes wrong:**
You score a trader's expertise based on historical outcomes. Polymarket resolves a market "YES" (Team A won). Your system records it. Later, resolution is disputed and overturned—Team A actually had ineligible player, result invalidated. Your historical scores are now wrong, but you don't detect it because you don't monitor resolution changes.

**Why it happens:**
- Prediction markets have opaque resolution rules
- Disputes happen (especially in edge cases like DQs, forfeitures, technical issues)
- APIs might not expose resolution status changes
- Natural assumption that resolved = final

**Consequences:**
- **Incorrect historical scoring**: Expert was "wrong" per final resolution but you recorded "right"
- **Compounding errors**: Wrong score affects expert ranking, affects future signals
- **Lost trust**: Users notice discrepancy between your scores and actual outcomes
- **Legal ambiguity**: eSports has gray areas (what if tournament pauses mid-match and resumes with different patch?)

**Prevention:**
1. **Resolution status tracking**: Store resolution state (active, resolved, disputed, final)—not just binary
2. **Dispute monitoring**: Check for resolution changes on markets used for scoring
3. **Delayed finalization**: Don't update expertise scores until market has been resolved for X days (cooling-off period)
4. **Edge case taxonomy**: Tag markets with resolution complexity (forfeits, DQs, technical issues)—weight lower in scoring
5. **Manual review flags**: Alert when high-volume market has resolution status change

**Detection:**
- Expert scores don't match user expectations based on Polymarket UI
- Resolution timestamps change (market shows resolution date edited)
- Community discussions about disputed outcomes not reflected in your data
- Your "expert" won a bet everyone knows was overturned

**Phase mapping:** Address in **Phase 1: Data Collection** (track resolution status) and **Phase 5: Validation** (audit historical resolutions)

---

### 12. Seasonal Volatility & Cold Start

**What goes wrong:**
It's eSports off-season. Tournament volume drops 60%. Most of your experts stop trading. New tournament season starts with roster changes—historical expertise may not transfer. Your tool has no signals for 6 weeks, then floods with uncertain signals as new season begins.

**Why it happens:**
- eSports has seasonal tournament calendars (Worlds, Spring/Summer splits, Majors)
- Off-season has roster shuffles, patches, meta changes—historical data less predictive
- Prediction market volumes drop during gaps
- Modern eSports has year-round action but specific games/regions have cycles

**Consequences:**
- **Inconsistent utility**: Tool useful during Worlds, useless during off-season
- **Stale expertise**: Experts identified in Spring split might not be relevant for Summer (roster changes)
- **User churn**: Users forget about tool during dry spells
- **Cold start errors**: First 2 weeks of new season have unreliable signals

**Prevention:**
1. **Cross-game diversification**: Track multiple games to smooth seasonal gaps (League + CS:GO + Dota)
2. **Roster change detection**: Monitor team roster changes—flag experts who specialized in old rosters
3. **Warm-start strategies**: During first 2 weeks of season, increase confidence thresholds for alerts
4. **Off-season modes**: Surface different signals (e.g., "historically strong on new rosters") when main season paused
5. **Tournament calendar integration**: Know when seasons start/end—adjust evaluation windows accordingly
6. **Preseason analysis**: Test if off-season exhibition matches predict regular season (might be noisy)

**Detection:**
- Alert volume drops >50% for multi-week periods
- Expert activity ceases then resumes with seasonal calendar
- New season performance doesn't correlate with previous season for same experts
- User engagement graphs show seasonal saw-tooth pattern

**Phase mapping:** Plan for in **Phase 4: Signal Aggregation**—need strategy for low-volume periods

---

## Minor Pitfalls

Mistakes that cause annoyance but are fixable.

### 13. Webhook Delivery Failures

**What goes wrong:**
You send alerts via webhooks. User's endpoint is down. Webhook fails. You retry immediately, fails again. You give up. User misses consensus signal. They blame your tool.

**Why it happens:**
- Network issues are inevitable
- User endpoints have downtime
- No retry logic or delivery confirmation
- Assumption that HTTP POST success = user received alert

**Prevention:**
1. **Retry with exponential backoff**: 3 retries at 1s, 5s, 25s intervals
2. **Dead letter queue**: Store failed deliveries for manual inspection
3. **Delivery status tracking**: Record success/failure per webhook per alert
4. **Health check endpoint**: Ping user webhook periodically to detect outages proactively
5. **Alternative channels**: Support email/SMS fallback if webhook fails
6. **User visibility**: Dashboard showing recent webhook delivery status

**Detection:**
- Users report missed alerts but logs show send attempts
- High webhook failure rate (>5%)
- No retry attempts in logs
- User endpoints show intermittent downtime but system doesn't compensate

**Phase mapping:** Important for **Phase 6: Webhook Integration**—builds user trust

---

### 14. Ignoring Wash Trading / Sybil Attacks

**What goes wrong:**
You identify an "expert" with 90% win rate. Turns out they're wash trading (betting against themselves with alt accounts) to manipulate scores or farm liquidity rewards. Your tool surfaces them, users follow, the "expert" is fake.

**Why it happens:**
- 25% of Polymarket volume may be artificial activity (wash trading)
- Polymarket offers Maker Rebate Program—incentivizes providing liquidity
- Sybil attacks easy with multiple wallets
- You only observe on-chain actions, not identity

**Consequences:**
- **Fake experts**: Your top-ranked traders are manipulators
- **Gamed signals**: If tool becomes popular, people will game rankings
- **Legal risk**: Potentially amplifying market manipulation
- **Lost credibility**: Users discover fake experts, lose trust

**Prevention:**
1. **Volume pattern analysis**: Flag traders with symmetric bet patterns (bet both sides in close timing)
2. **Address clustering**: Look for traders with correlated wallet patterns (funded from same source, trade in lockstep)
3. **Minimum reputation threshold**: Require traders to have aged accounts (>6 months) and diversified bets
4. **Liquidity provider exclusion**: Filter out addresses that are primarily liquidity providers (bid/ask both sides)
5. **Anomaly detection**: Flag unusual patterns (90% win rate is statistically unlikely unless small sample or manipulation)
6. **Community reporting**: Allow users to report suspected manipulation

**Detection:**
- Expert has suspiciously high win rate with small sample size
- Expert bets both sides of markets with near-identical sizing
- Expert wallet has unusual funding patterns
- Trading behavior correlates with Maker Rebate Program timing

**Phase mapping:** Add detection in **Phase 5: Validation & Testing**—not MVP but important for scale

---

### 15. Category Drift & Mislabeling

**What goes wrong:**
Polymarket labels a market "League of Legends" but it's actually about a tournament that includes multiple games. Or: Market tagged "eSports" but it's really about streamer drama, not competitive outcomes. Your tool includes it, dilutes signal quality.

**Why it happens:**
- Polymarket's category taxonomy might not match yours
- User-generated markets have inconsistent labeling
- "eSports" is broad—competitive gaming vs. gaming culture vs. content creators
- Edge cases (showmatches, charity events, exhibition games)

**Consequences:**
- **Contaminated training data**: Expert evaluation includes irrelevant markets
- **Weak signals**: Averaging across true competitive + non-competitive events dilutes expertise
- **Misclassified experts**: Player thinks they're betting on competitive League but market is about personality drama
- **Category confusion**: Users receive alerts for markets outside their interest

**Prevention:**
1. **Manual category review**: Audit Polymarket's top 100 eSports markets to understand labeling patterns
2. **Market description parsing**: Use LLM or keywords to detect mislabeled markets (look for "tournament," "team," "match" vs. "streamer," "drama")
3. **Subcategory creation**: Separate "Competitive eSports" from "Gaming Culture" markets
4. **Confidence scoring**: Markets with ambiguous labeling get lower weight in expertise calculation
5. **User feedback**: Allow users to report miscategorized markets
6. **Whitelist approach**: Start with known tournaments/leagues, expand carefully

**Detection:**
- Markets labeled "eSports" but comments discuss drama not match outcomes
- Expert identified in "League of Legends" but bets are about player transfers, not games
- Category distribution looks weird (50% of "eSports" markets are about streamers)
- User complaints about irrelevant alerts

**Phase mapping:** Address in **Phase 1: Data Collection**—category filtering is foundational

---

## Phase-Specific Warnings

| Phase Topic | Primary Pitfall Risk | Mitigation Priority |
|-------------|----------------------|---------------------|
| **Data Collection** | API rate limits (#6), thin market data (#3), category mislabeling (#15) | HIGH - Must get right from start |
| **Trader Evaluation** | Survivorship bias (#1), overfitting (#2), correlation vs. causation (#7), taxonomy granularity (#10) | CRITICAL - This is the make-or-break phase |
| **Signal Aggregation** | Herding mistaken for consensus (#5) | HIGH - Bad consensus detection = worthless alerts |
| **Architecture** | SQLite schema design (#8), premature optimization (#9) | MEDIUM - Start simple, refactor when proven necessary |
| **Validation** | Game patches invalidating expertise (#4), resolution disputes (#11), wash trading (#14) | HIGH - Without validation, signals degrade over time |
| **Seasonal Operation** | eSports seasonality (#12) | MEDIUM - Plan for, but not MVP-blocking |
| **Webhook Integration** | Delivery failures (#13) | LOW - Annoying but easy to fix |

---

## Research Confidence

| Area | Confidence | Source Quality |
|------|------------|----------------|
| Polymarket API specifics | **HIGH** | Official docs, verified GitHub issues, developer experiences 2026 |
| Trader evaluation pitfalls | **HIGH** | Academic research on survivorship bias, backtesting, prediction markets |
| Signal quality issues | **MEDIUM-HIGH** | Prediction market research, smart money tracking articles, herding studies |
| eSports-specific challenges | **MEDIUM** | WebSearch aggregation (betting industry articles, tournament impacts) |
| SQLite architecture | **HIGH** | Established best practices for financial time-series data |
| Game patches impact | **MEDIUM** | Betting operator interviews, industry articles—less academic backing |

---

## Key Recommendations for Roadmap

1. **Phase 2 (Trader Evaluation) is highest-risk phase** → Needs deepest research, most validation, longest timeline

2. **Build validation infrastructure early** → Don't wait until Phase 5 to add out-of-sample testing; bake it into Phase 2

3. **Start with liquidity-filtered subset** → Don't try to score all eSports markets; begin with >$10k volume markets only

4. **Plan for meta-shifts** → Game patches will invalidate expertise; need continuous re-evaluation strategy from day one

5. **Simple architecture first** → SQLite + Python script can handle MVP; defer complexity until proven necessary

6. **Taxonomy drives everything** → Get granularity right in Phase 2 or refactor will cascade through entire system

7. **Consensus detection is subtle** → Herding vs. true consensus is hard to distinguish; requires timing analysis, not just position agreement

---

## Sources

### Polymarket API & Data Quality
- [Polymarket API Rate Limits Documentation](https://docs.polymarket.com/quickstart/introduction/rate-limits)
- [Polymarket CLOB API Introduction](https://docs.polymarket.com/developers/CLOB/introduction)
- [GitHub Issue #216: /prices-history endpoint data gaps](https://github.com/Polymarket/py-clob-client/issues/216)
- [The Polymarket API: Architecture, Endpoints, and Use Cases | Medium](https://medium.com/@gwrx2005/the-polymarket-api-architecture-endpoints-and-use-cases-f1d88fa6c1bf)

### Market Liquidity & Volume
- [Polymarket Liquidity Analysis | Phemex News](https://phemex.com/news/article/polymarket-liquidity-analysis-reveals-key-insights-into-prediction-markets-52184)
- [295,000 Data Points Reveal Polymarket Liquidity Truths | KuCoin](https://www.kucoin.com/news/flash/295-000-data-points-reveal-6-counterintuitive-truths-about-polymarket-liquidity)
- [Low-liquidity trading in Polymarket | Atomic Wallet](https://atomicwallet.io/academy/articles/low-liquidity-trading-in-polymarket)
- [Polymarket volume inflated by wash trading | Fortune](https://fortune.com/2025/11/07/polymarket-wash-trading-inflated-prediction-markets-columbia-research/)

### Trader Evaluation & Bias
- [Survivorship Bias in Backtesting Explained | LuxAlgo](https://www.luxalgo.com/blog/survivorship-bias-in-backtesting-explained/)
- [Survivorship Bias in Market Data | Bookmap](https://bookmap.com/blog/survivorship-bias-in-market-data-what-traders-need-to-know)
- [Survivorship Bias in Backtesting | Adventures of Greg](http://adventuresofgreg.com/blog/2026/01/14/survivorship-bias-backtesting-avoiding-traps/)
- [The Seven Sins of Quantitative Investing | Portfolio Optimization Book](https://bookdown.org/palomar/portfoliooptimizationbook/8.2-seven-sins.html)

### Smart Money & Herding
- [Improving prediction market forecasts | ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0377221718305575)
- [The Allure and Pitfalls of Tracking Smart Money | Medium](https://vishalcrypta.medium.com/the-allure-and-pitfalls-of-tracking-smart-money-flows-in-crypto-14965483c7ff)
- [Prediction markets need dumb money and smart money | Statistical Modeling](https://statmodeling.stat.columbia.edu/2024/10/25/prediction-markets-and-the-need-for-dumb-money-as-well-as-smart-money/)

### eSports & Game Patches
- [How patches move Esports odds fast | We Are Brighton](https://www.wearebrighton.com/newsopinion/how-in-game-patches-influence-odds-movement-in-mobile-esports-markets/)
- [Bayes Esports: navigating game patches | SBC News](https://sbcnews.co.uk/features/interviews/2024/04/29/bayes-esports-game-patches/)
- [Esports Betting Deep Dive: Tournament Impact | iGaming Future](https://igamingfuture.com/esports-betting-deep-dive-tournament-impact-and-regional-growth-patterns-in-h1-2025/)
- [The impact of patches on esports betting odds | Egamers World](https://egamersworld.com/blog/the-impact-of-patches-and-updates-on-e-sports-bett-wO-USpjzBL)

### SQLite & Architecture
- [Top 10 Common SQLite Mistakes in Financial Apps | MoldStud](https://moldstud.com/articles/p-top-10-common-sqlite-mistakes-in-financial-app-development-how-to-avoid-them)
- [Common Pitfalls with SQLite Database | MoldStud](https://moldstud.com/articles/p-common-pitfalls-when-working-with-sqlite-database-avoid-these-mistakes-for-better-performance)
- [Storing Financial Time-Series Data Efficiently | Eric Draken](https://ericdraken.com/storing-stock-candle-data-efficiently/)

### Premature Optimization
- [Stop Optimizing the Wrong Things: Data Pipeline Guide | Dagster](https://dagster.io/blog/when-and-when-not-to-optimize-data-pipelines)
- [Premature Optimization: Stop Over-Engineering | Qt](https://www.qt.io/quality-assurance/blog/premature-optimization)
- [Why Premature Optimization is Root of All Evil | GeeksforGeeks](https://www.geeksforgeeks.org/software-engineering/premature-optimization/)

### Prediction Markets Research
- [Using prediction markets to estimate reproducibility | PNAS](https://www.pnas.org/doi/abs/10.1073/pnas.1516179112)
- [Uh oh prediction markets | Statistical Modeling](https://statmodeling.stat.columbia.edu/2026/01/07/uh-oh-prediction-markets/)
- [What Could 2026 Bring For Sports Prediction Markets | Legal Sports Report](https://www.legalsportsreport.com/249858/what-could-2026-bring-for-sports-prediction-markets/)
