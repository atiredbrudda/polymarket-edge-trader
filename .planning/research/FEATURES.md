# Feature Landscape: Prediction Market Smart Money Tracking

**Domain:** Prediction market analytics and smart money tracking tools
**Focus:** eSports markets on Polymarket
**Researched:** 2026-02-05
**Overall Confidence:** MEDIUM-HIGH

## Executive Summary

The prediction market analytics space has matured significantly by 2026, with platforms like Polymarket spawning an entire ecosystem of 170+ tracking tools, bots, and analytics products. The core value proposition across all tools: **identify informed traders and surface their positioning before the crowd moves**.

Key ecosystem insights:
- **Whale tracking is table stakes** - Every competitive tool tracks large positions ($10k+)
- **Real-time alerting separates winners** - Sub-50ms latency for competitive tools
- **Specialization detection is emerging** - Niche expertise tagging is a differentiator
- **API access is fundamental** - Polymarket's REST + WebSocket APIs enable all tooling
- **Multi-channel alerts are expected** - Telegram/Discord/Email/Webhook are standard

For an **eSports-focused smart money tracker**, the key differentiator is **specialization depth scoring** - most tools track general PnL and volume, but few evaluate domain expertise or convergence within niche markets.

---

## Table Stakes Features

Features users expect from any smart money tracking tool. Missing any = product feels incomplete or broken.

### 1. Trader Identification and Discovery
**Why Expected:** Core use case - "who are the smart traders?"
**Complexity:** Medium
**Sources:** [Polymarket Analytics Traders](https://polymarketanalytics.com/traders), [HashDive Smart Scoring](https://signals.coincodecap.com/top-polymarket-analytics-tools)

**Requirements:**
- Query traders by wallet address (0x format)
- Query traders by username (@handle format)
- Access to Polymarket API for trader history
- Historical trade data retrieval (all-time or filtered)

**Implementation notes:**
- Polymarket REST API provides `/trades` endpoint filtered by user
- WebSocket for real-time trade monitoring
- Gamma API provides indexed on-chain data

**Dependencies:** None (foundational feature)

---

### 2. Basic Performance Metrics
**Why Expected:** Users need proof traders are actually skilled
**Complexity:** Low-Medium
**Sources:** [Polymarket Leaderboard](https://polymarketanalytics.com/traders), [PolymarketDash Analytics](https://polymark.et/product/polymarketdash)

**Requirements:**
- **Profit/Loss (PnL):** Total wins - total losses
- **Win Rate:** Percentage of resolved markets where trader profited
- **Total Volume:** Aggregate USDC traded across all positions
- **Active Positions:** Count of unresolved markets with open positions
- **Current Value:** Market value of all open positions

**Implementation notes:**
- PnL and win rate calculated from historical trades
- Real-time position values require orderbook pricing
- Update frequency: 5-minute intervals is industry standard

**Dependencies:** Trader identification (Feature 1)

---

### 3. Position Tracking
**Why Expected:** Core intelligence - "what are they betting on?"
**Complexity:** Medium
**Sources:** [Polymarket API Docs](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets), [Whale Tracker Features](https://www.polywhaler.com/)

**Requirements:**
- Current open positions for tracked traders
- Position size (shares/USDC value)
- Position direction (YES/NO on binary markets)
- Entry price vs current price
- Unrealized PnL on open positions

**Implementation notes:**
- Positions endpoint: `/positions?user={address}`
- Requires orderbook data for current pricing
- Handle multi-outcome markets (not just binary YES/NO)

**Dependencies:** Trader identification, basic metrics

---

### 4. Large Position Alerting (Whale Tracking)
**Why Expected:** Industry standard - every tool has this
**Complexity:** Medium
**Sources:** [Polywhaler](https://www.polywhaler.com/), [PolyWatch](https://www.polywatch.tech/), [Unusual Whales](https://unusualwhales.com/predictions)

**Requirements:**
- Monitor trades ≥ configurable threshold ($1k, $5k, $10k+)
- Real-time alerts when threshold exceeded
- Notification channels: Email, Telegram, webhook minimum
- Trade details: trader, market, size, direction, price

**Implementation notes:**
- WebSocket subscription to trades feed
- Filter by `amount_usd >= threshold`
- Unusual Whales released whale tracker module in 2026
- $10k+ is industry standard "whale" threshold

**Dependencies:** Position tracking, alert infrastructure

---

### 5. Market Filtering and Categorization
**Why Expected:** Users want domain-specific insights
**Complexity:** Low
**Sources:** [Polymarket Categories](https://docs.polymarket.com/developers/gamma-markets-api/overview), [Wallet Categorization](https://polymark.et/product/polywallet)

**Requirements:**
- Filter markets by category (Sports, eSports, Politics, Crypto, etc.)
- Identify trader activity within specific categories
- Tag traders by primary category participation

**Implementation notes:**
- Polymarket Gamma API provides market metadata with categories
- Category tags: "Politics", "Crypto", "Sports" are built-in
- eSports may be under "Sports" or separate category

**Dependencies:** Market data access

---

### 6. Historical Data Access
**Why Expected:** Can't evaluate expertise without history
**Complexity:** Medium
**Sources:** [Polymarket Historical API](https://docs.polymarket.com/developers/CLOB/timeseries), [Backtesting Context](https://www.buildalpha.com/backtesting-trading-strategies/)

**Requirements:**
- Access to trader's complete trade history
- Date range filtering
- Market-specific filtering
- Resolved vs active market filtering

**Implementation notes:**
- CLOB REST API provides all historical trades
- GraphQL subgraphs for on-chain verification
- Timeseries endpoint: `/timeseries?market={id}&interval={duration}`

**Dependencies:** Trader identification

---

## Differentiator Features

Features that set the product apart from generic whale trackers. Not expected, but highly valued.

### 7. Specialization Depth Scoring (PRIMARY DIFFERENTIATOR)
**Why Valuable:** Most tools show "who's profitable" - this shows "who's an expert in eSports"
**Complexity:** High
**Sources:** [Niche Analytics](https://www.dataexpertise.in/niche-analytics-industry-sector-insights/), [Specialization Trends 2026](https://insight7.io/specialist-market-research-agencies-for-niche-markets/)

**Value Proposition:**
A trader with 70% win rate across 1000 random markets is less valuable for eSports intel than a trader with 80% win rate across 50 eSports-only markets. Specialization depth separates signal from noise.

**Requirements:**
- Calculate % of trader's volume in target category (eSports)
- Calculate win rate specifically within eSports markets
- Penalize low sample sizes (require minimum N markets)
- Score recency (recent activity weighted higher)
- Generate composite "expertise score" (0-100)

**Algorithm components:**
```
Expertise Score = f(
  category_concentration,  // % of volume in eSports
  category_win_rate,       // win rate within eSports only
  sample_size,             // number of eSports markets traded
  recency,                 // time-weighted recent activity
  consistency              // variance of performance over time
)
```

**Example implementation:**
- HashDive uses "Smart Score" -100 to +100 based on performance, open interest, stability
- Our version: 0-100 scale focused on eSports specialization depth

**Dependencies:** Historical data, market categorization, win rate calculation

---

### 8. Consensus Signal Detection
**Why Valuable:** "Smart money convergence" = strongest signal
**Complexity:** High
**Sources:** [Consensus Betting](https://www.sportsbettingdime.com/nfl/public-betting-trends/), [Smart Money Concepts](https://cointelegraph.com/news/smart-money-concepts-smc-in-crypto-trading-how-to-track-profit)

**Value Proposition:**
When 5+ high-expertise eSports traders independently take the same position on a market, that's a consensus signal worth amplifying.

**Requirements:**
- Track position direction for all expert traders on each market
- Calculate % taking YES vs NO position
- Identify markets with high expert concentration (≥3 experts active)
- Calculate consensus strength (weighted by expertise score)
- Alert when consensus threshold reached (e.g., 75%+ agree)

**Detection logic:**
```
For each eSports market:
  - Identify all traders with expertise_score ≥ 70
  - Check their positions (YES/NO)
  - If 75%+ positioned same direction → CONSENSUS SIGNAL
  - Weight by expertise score for confidence level
```

**Output:**
- Market ID + description
- Consensus direction (YES/NO)
- Expert count + % agreement
- Total expert capital deployed
- Confidence score (0-100)

**Dependencies:** Specialization scoring, position tracking, multiple trader monitoring

---

### 9. Activity-First Event Discovery
**Why Valuable:** Surface emerging opportunities before they're obvious
**Complexity:** Medium
**Sources:** [PrediEdge Smart Money Flow](https://signals.coincodecap.com/top-polymarket-analytics-tools), [Event-First Architecture](https://polymarketanalytics.com)

**Value Proposition:**
Don't wait for users to search markets - proactively surface where experts are currently active.

**Requirements:**
- Monitor all active eSports markets continuously
- Detect when expert traders enter new markets
- Score markets by expert attention (count + volume)
- Rank markets by "smart money activity score"

**Implementation:**
- WebSocket feed of all trades
- Filter: trader in expert_list AND market in eSports category
- Aggregate: markets with most expert entry in past 1/6/24 hours
- Output: "Trending with experts" feed

**Dependencies:** Specialization scoring, real-time trade monitoring, market categorization

---

### 10. Multi-Timeframe Analysis
**Why Valuable:** Separate short-term traders from long-term experts
**Complexity:** Medium
**Sources:** [Trading Analytics](https://www.pragmaticcoders.com/blog/top-ai-tools-for-traders), [Performance Tracking](https://polymarketanalytics.com/traders)

**Requirements:**
- Calculate metrics across multiple windows: 7d, 30d, 90d, all-time
- Identify traders with consistent performance vs lucky streaks
- Detect recency of activity (last trade timestamp)

**Implementation:**
- Store time-bucketed metrics
- Compare variance across timeframes
- Flag traders with recent activity spike

**Dependencies:** Historical data, basic metrics

---

### 11. Trader Comparison and Watchlists
**Why Valuable:** Users need to organize their intel stream
**Complexity:** Low-Medium
**Sources:** [PolyWatch](https://www.polywatch.tech/), [PolyTrack Watchlists](https://www.polytrackhq.app/blog/how-to-track-polymarket-whales)

**Requirements:**
- Save custom lists of tracked traders
- Compare multiple traders side-by-side
- Alert when watchlist trader makes a move
- Export watchlist data

**Implementation:**
- Local SQLite storage for watchlists
- Monitor watchlist wallets via WebSocket
- Generate alerts for watchlist activity only

**Dependencies:** Trader identification, alert infrastructure

---

### 12. Historical Performance Validation (Backtesting)
**Why Valuable:** Prove the system works - show past expert calls
**Complexity:** High
**Sources:** [Backtesting Trading Strategies](https://www.buildalpha.com/backtesting-trading-strategies/), [PredictionMarketBench Framework](https://arxiv.org/html/2602.00133)

**Value Proposition:**
"If you'd followed our top 10 eSports experts last month, you'd have been early to 15/20 profitable markets."

**Requirements:**
- Replay historical trades with expertise scores
- Show what consensus signals occurred historically
- Calculate ROI if user had followed signals
- Avoid overfitting pitfall (don't optimize on same data)

**Implementation:**
- Run expertise algorithm on historical window
- Identify consensus signals that occurred
- Measure market outcomes for those signals
- Report hit rate + theoretical ROI

**Warning:**
High risk of overfitting. Per [backtesting limitations](https://www.forex.com/en-us/trading-guides/how-to-backtest-your-trading-strategy/), past performance doesn't guarantee future results. Use for validation only, not optimization.

**Dependencies:** Complete historical data, specialization scoring, consensus detection

---

## Anti-Features

Features to explicitly NOT build. Common mistakes or scope creep traps.

### AF1: Automated Trading Execution
**Why Avoid:** Regulatory risk, out of scope, liability nightmare
**What Users Might Ask For:** "Can this place bets automatically?"
**What to Do Instead:**
- Provide intelligence and alerts only
- Offer webhook outputs for users to integrate with their own systems
- Clear messaging: "Intelligence tool, not trading bot"

**Sources:** [Prediction Market Regulatory Risks 2026](https://www.ainvest.com/news/rise-prediction-markets-regulatory-risks-2026-2601/), [Risk Management](https://medium.com/@hhethereumm/how-to-avoid-pitfalls-in-prediction-markets-risk-management-and-ethics-16f4da57ec29)

**Rationale:**
- 2026 regulatory environment increasingly complex
- IRS reporting requirements for crypto transactions
- Liability for losses if automation fails
- Out of scope for intelligence/awareness tool

---

### AF2: Market Outcome Predictions
**Why Avoid:** We're tracking traders, not predicting outcomes
**What Users Might Ask For:** "What does the tool think will happen?"
**What to Do Instead:**
- Show what expert traders are betting on
- Show consensus positions
- Let user interpret signal, don't prescribe action

**Sources:** [Market Predictions Miss the Mark](https://www.edelmanfinancialengines.com/education/investment-management/market-predictions/), [Prediction Market Pitfalls](https://medium.com/@hhethereumm/how-to-avoid-pitfalls-in-prediction-markets-risk-management-and-ethics-16f4da57ec29)

**Rationale:**
- Markets are notoriously efficient at extracting edge
- Overconfidence drains bankroll faster than anything
- Our value: surface where experts are, not predict outcomes
- Avoid false confidence - show data, not predictions

---

### AF3: Broad Multi-Category Coverage
**Why Avoid:** Specialization is the product - breadth dilutes it
**What Users Might Ask For:** "Can it track politics and crypto too?"
**What to Do Instead:**
- Double down on eSports depth
- Build category-agnostic infrastructure but curate for eSports
- If expanding, create separate specialized tools per category

**Sources:** [Niche Analytics Value](https://www.dataexpertise.in/niche-analytics-industry-sector-insights/), [Specialization Trends 2026](https://insight7.io/specialist-market-research-agencies-for-niche-markets/)

**Rationale:**
- Research shows specialization outperforms generalization in 2026
- eSports traders ≠ politics traders - different expertise patterns
- Trying to be everything = diluted value proposition
- Market positioning: "eSports smart money tracker", not "generic tracker"

---

### AF4: Real-Time Price Feeds / Market Making Data
**Why Avoid:** Out of scope, high complexity, low ROI for intel tool
**What Users Might Ask For:** "Show me live orderbook depth"
**What to Do Instead:**
- Show position entry price vs current price (high-level)
- Link to Polymarket for deep market data
- Focus on trader behavior, not market microstructure

**Sources:** [Market Making Guide](https://newyorkcityservers.com/blog/prediction-market-making-guide), [CLOB Infrastructure](https://docs.polymarket.com/developers/CLOB/trades/trades-overview)

**Rationale:**
- Market making requires <50ms latency infrastructure
- Orderbook depth is market maker domain, not intel tool domain
- Users who need this are building trading bots (different product)
- Our users: awareness seekers, not high-frequency traders

---

### AF5: Social/Community Features (Forums, Chat, Following)
**Why Avoid:** Social platforms are saturated, maintenance burden high
**What Users Might Ask For:** "Can I chat with other users?"
**What to Do Instead:**
- Export data for users to share elsewhere
- Focus on data quality over social features
- Integrate with existing platforms (Discord/Telegram alerts)

**Sources:** [Platform Features 2026](https://www.legalsportsreport.com/prediction-markets/), [Social Trading Features](https://www.vegasinsider.com/prediction-markets/best-prediction-market-apps/)

**Rationale:**
- Kalshi's "Follow" feature exists - we're not competing there
- Social features require moderation, spam handling, engagement loops
- Python CLI + webhooks architecture doesn't fit social model
- Value is intelligence delivery, not community building

---

### AF6: Portfolio Management / Position Sizing Advice
**Why Avoid:** Financial advice = regulatory minefield
**What Users Might Ask For:** "How much should I bet?"
**What to Do Instead:**
- Show what experts are doing (position sizes as data)
- No recommendations on user position sizing
- Disclaimer: "For informational purposes only"

**Sources:** [Risk Management Mistakes](https://medium.com/@hhethereumm/how-to-avoid-pitfalls-in-prediction-markets-risk-management-and-ethics-16f4da57ec29), [Regulatory Compliance 2026](https://www.ainvest.com/news/rise-prediction-markets-regulatory-risks-2026-2601/)

**Rationale:**
- Bet sizing advice = financial advice in many jurisdictions
- Don't allocate more capital than you can afford to lose (user responsibility)
- We show data, user makes decisions
- Avoid "we recommend X" language

---

### AF7: Historical Replay / Time Machine UI
**Why Avoid:** High complexity, low user retention, niche use case
**What Users Might Ask For:** "Let me replay what happened last week"
**What to Do Instead:**
- Backtesting validation (one-time analysis)
- Historical performance summaries (aggregated)
- Focus on forward-looking signals, not past replay

**Rationale:**
- Time-series replay UI is engineering-heavy
- Users care about "what's happening now" and "what's next"
- Historical context = yes, full replay = no
- CLI tool not suited for interactive time navigation

---

## Feature Dependencies

```
Foundation Layer:
├─ Market Categorization (TS5)
├─ Trader Identification (TS1)
└─ Historical Data Access (TS6)

Analytics Layer:
├─ Basic Performance Metrics (TS2)
│  └─ depends on: TS1, TS6
├─ Position Tracking (TS3)
│  └─ depends on: TS1
└─ Multi-Timeframe Analysis (D10)
   └─ depends on: TS2, TS6

Intelligence Layer:
├─ Specialization Depth Scoring (D7) **[PRIMARY DIFFERENTIATOR]**
│  └─ depends on: TS2, TS5, TS6
├─ Consensus Signal Detection (D8)
│  └─ depends on: D7, TS3
└─ Activity-First Event Discovery (D9)
   └─ depends on: D7, TS5

Alerting Layer:
├─ Large Position Alerting (TS4)
│  └─ depends on: TS3
└─ Trader Comparison and Watchlists (D11)
   └─ depends on: TS1, TS3

Validation Layer:
└─ Historical Performance Validation (D12)
   └─ depends on: D7, D8, TS6
```

**Critical Path for MVP:**
1. TS1: Trader Identification
2. TS6: Historical Data Access
3. TS5: Market Categorization
4. TS2: Basic Performance Metrics
5. D7: Specialization Depth Scoring
6. TS3: Position Tracking
7. D8: Consensus Signal Detection

---

## MVP Recommendation

**For MVP (Minimum Viable Product), prioritize:**

### Must-Have (MVP Blockers):
1. **Trader Identification** (TS1) - Can't do anything without this
2. **Historical Data Access** (TS6) - Required for expertise evaluation
3. **Market Categorization** (TS5) - Required for eSports filtering
4. **Basic Performance Metrics** (TS2) - Required for scoring
5. **Specialization Depth Scoring** (D7) - **THE core differentiator**
6. **Position Tracking** (TS3) - Required for consensus detection
7. **Consensus Signal Detection** (D8) - Core value: "where's smart money?"

### Nice-to-Have (Post-MVP):
- Large Position Alerting (TS4) - Table stakes for whale trackers, but can defer
- Activity-First Event Discovery (D9) - Differentiator but not blocking
- Multi-Timeframe Analysis (D10) - Adds depth, not core value
- Trader Watchlists (D11) - UX improvement, not core intelligence

### Defer to Post-Launch:
- Historical Performance Validation (D12) - Marketing asset, not user-facing
- Advanced alerting channels - Start with webhooks, add others later

**MVP Value Proposition:**
"Identify eSports experts on Polymarket, track their positions, surface where they're converging."

**MVP Workflow:**
1. User runs tool against eSports markets
2. Tool scores all active traders by eSports expertise
3. Tool identifies traders with expertise_score ≥ 70
4. Tool shows current positions for top experts
5. Tool flags markets with expert consensus (75%+ agree)
6. Output: List of markets with strong smart money signals

---

## Complexity Assessment

| Feature | Complexity | Data Requirements | API Dependencies |
|---------|------------|-------------------|------------------|
| TS1: Trader Identification | Medium | Wallet addresses, usernames | Polymarket REST API |
| TS2: Basic Metrics | Low-Medium | Trade history, resolutions | Polymarket REST API |
| TS3: Position Tracking | Medium | Current positions, pricing | REST + orderbook |
| TS4: Whale Alerting | Medium | Real-time trades | WebSocket |
| TS5: Market Categorization | Low | Market metadata | Gamma API |
| TS6: Historical Data | Medium | Full trade history | REST + GraphQL |
| D7: Specialization Scoring | **High** | Category-filtered history | Multiple endpoints |
| D8: Consensus Detection | **High** | Multi-trader positions | REST + aggregation |
| D9: Activity-First Discovery | Medium | Real-time trades filtered | WebSocket + filtering |
| D10: Multi-Timeframe | Medium | Time-bucketed data | REST with date ranges |
| D11: Watchlists | Low-Medium | Local storage | None (local) |
| D12: Backtesting | **High** | Complete historical set | REST + local compute |

**High-complexity features require:**
- Sophisticated algorithms (scoring, detection)
- Cross-trader aggregation
- Time-series analysis
- Overfitting prevention (backtesting)

---

## Implementation Notes

### Data Refresh Rates
**Industry Standard:** 5-minute intervals for batch updates ([Polymarket Analytics](https://polymarketanalytics.com))
**Real-time needs:** WebSocket for trade alerts, whale detection

**Recommendation:**
- **Core metrics:** 5-minute batch refresh (adequate for intelligence tool)
- **Whale alerts:** Real-time WebSocket (competitive necessity)
- **Consensus signals:** 15-minute refresh (balance freshness vs compute)

### Storage Requirements
**Local-first SQLite approach:**
- Trader profiles: ~1KB per trader
- Trade history: ~500 bytes per trade
- Position snapshots: ~200 bytes per position
- 10,000 trades per expert × 100 experts = ~50MB
- Manageable for SQLite, no need for external DB

### API Rate Limits
**Polymarket API considerations:**
- REST endpoints: Rate limits not publicly documented
- WebSocket: Single connection for real-time feeds
- GraphQL subgraphs: Decentralized, no single rate limit

**Risk mitigation:**
- Batch requests where possible
- Cache aggressively (5-min refresh)
- Use WebSocket for real-time, not polling

### Alert Channels Priority
**MVP:** Webhooks (universal integration)
**Post-MVP:** Telegram (community standard), Email
**Defer:** Discord, Slack, SMS, Push notifications

---

## Sources

**Prediction Market Analytics Platforms:**
- [Polymarket Analytics – Traders Leaderboard](https://polymarketanalytics.com/traders)
- [Top 10 PolyMarket Analytics Tools (2026)](https://signals.coincodecap.com/top-polymarket-analytics-tools)
- [10 Powerful Polymarket Analytics Tools (January 2026)](https://coincodecap.com/polymarket-analytics-tools)
- [Best Prediction Market Apps in February 2026](https://www.legalsportsreport.com/prediction-markets/)

**Smart Money Tracking:**
- [Polywhaler - Whale Tracker](https://www.polywhaler.com/)
- [PolyWatch - Free Whale Tracker](https://www.polywatch.tech/)
- [Unusual Whales Prediction Markets](https://unusualwhales.com/predictions)
- [How to Track Smart Money in Crypto](https://coinmarketcap.com/academy/article/how-to-track-smart-money-in-the-crypto-space)
- [Smart Money Concepts in Crypto Trading](https://cointelegraph.com/news/smart-money-concepts-smc-in-crypto-trading-how-to-track-profit)

**Trader Scoring and Leaderboards:**
- [Polymarket Traders Leaderboard](https://polymarketanalytics.com/traders)
- [PredictingTop - Real-time Leaderboard Tracking](https://polymark.et/product/predicting-top)

**API and Data Access:**
- [Polymarket API Documentation - Get Trades](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets)
- [Polymarket Historical Timeseries Data](https://docs.polymarket.com/developers/CLOB/timeseries)
- [Polymarket API Architecture (Medium, Jan 2026)](https://medium.com/@gwrx2005/the-polymarket-api-architecture-endpoints-and-use-cases-f1d88fa6c1bf)

**Specialization and Niche Analytics:**
- [Niche Analytics: Industry-Specific Insights](https://www.dataexpertise.in/niche-analytics-industry-sector-insights/)
- [Specialist Market Research Agencies](https://insight7.io/specialist-market-research-agencies-for-niche-markets/)

**Backtesting and Validation:**
- [Backtesting Trading Strategies – Build Alpha](https://www.buildalpha.com/backtesting-trading-strategies/)
- [PredictionMarketBench Framework (arxiv, Feb 2026)](https://arxiv.org/html/2602.00133)

**Risk Management and Anti-Patterns:**
- [How to Avoid Pitfalls in Prediction Markets (Medium, Jan 2026)](https://medium.com/@hhethereumm/how-to-avoid-pitfalls-in-prediction-markets-risk-management-and-ethics-16f4da57ec29)
- [Rise of Prediction Markets and Regulatory Risks 2026](https://www.ainvest.com/news/rise-prediction-markets-regulatory-risks-2026-2601/)

**eSports and Sports Betting Analytics:**
- [Best Apps for Bettors 2026](https://rotogrinders.com/sports-betting/guides/best-apps-for-bettors)
- [Esports Industry Data and Analytics](https://oddsmatrix.com/esports-data/)
- [NFL Public Betting Trends](https://www.sportsbettingdime.com/nfl/public-betting-trends/)

**Consensus and Smart Money Signals:**
- [Smart Betting Tools & Data-Driven Guide 2026](https://www.oddsshark.com/data-driven-sports-betting)

---

## Confidence Assessment

| Area | Level | Reasoning |
|------|-------|-----------|
| **Table Stakes Features** | HIGH | Strong consensus across multiple platforms, well-documented APIs |
| **Specialization Scoring** | MEDIUM | Concept validated by niche analytics trends, but implementation details are custom |
| **Consensus Detection** | MEDIUM | Validated by sports betting consensus tools, but prediction market application is emerging |
| **API Access Patterns** | HIGH | Polymarket documentation comprehensive, multiple working tools reference it |
| **Alert Infrastructure** | MEDIUM-HIGH | Webhook/Telegram patterns well-established in crypto/trading tools |
| **Backtesting Complexity** | HIGH | Well-understood in trading, clear pitfalls documented, but overfitting risk is real |
| **Anti-Features** | MEDIUM | Based on regulatory research and risk management literature, some inference |

**Overall Feature Landscape Confidence:** MEDIUM-HIGH

**Gaps:**
- Specific eSports market structure on Polymarket (may differ from general sports)
- Optimal expertise score weighting (requires experimentation)
- Consensus threshold calibration (75% is hypothesis, needs validation)
- Polymarket API rate limits (not publicly documented)

**Next Steps:**
These feature requirements inform the roadmap. During implementation phases, specific features may need deeper technical research (e.g., scoring algorithm tuning, consensus detection thresholds).
