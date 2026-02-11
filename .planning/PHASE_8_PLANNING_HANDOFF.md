# Phase 8 Planning Handoff Document
**For:** Kimi k2.5 (Planning Agent)
**Target:** Claude Sonnet 4.5 (Execution Agent)
**Date:** 2026-02-11
**Phase:** 8 - Complete Trader History via Blockchain

---

## 🎯 Your Mission

Plan Phase 8 implementation that eliminates the 100-trade API limitation by adding blockchain-based trader history indexing.

**Your deliverable:** A complete Phase 8 plan following the GSD PLAN.md format (see template below) that Claude can execute with minimal clarification.

---

## 📋 Project Context

### Project Overview
**Name:** Polymarket Smart Money Tracker
**Goal:** Surface where informed eSports traders are moving on Polymarket
**Stack:** Python 3.11, SQLite, py-clob-client, pytest
**Status:** Phases 1-7 complete (438 tests passing), Phase 8 planning needed

### Current Architecture
```
src/
├── api/
│   └── client.py              # PolymarketClient (Data API + CLOB)
├── pipeline/
│   └── ingest.py              # TraderIngestionPipeline
├── models/
│   └── db.py                  # SQLAlchemy models
├── scoring/
│   └── expertise.py           # Expertise scoring engine
├── signals/
│   └── consensus.py           # Consensus detection
└── cli/
    └── commands.py            # Click CLI commands
```

### Phase Completion Summary
- **Phase 1:** Foundation - API client, database, ingestion (62 tests)
- **Phase 2:** Classification & Discovery - Taxonomy, trader discovery (51 tests)
- **Phase 3:** Historical Evaluation - Performance metrics, validation (121 tests)
- **Phase 4:** Scoring Engine - Expertise scores, leaderboards (73 tests)
- **Phase 5:** Signal Detection - Consensus detection (55 tests)
- **Phase 6:** Alerting System - Telegram delivery (39 tests)
- **Phase 7:** CLI Interface - User commands (37 tests)

---

## ❌ The Critical Problem (Why Phase 8 Exists)

### Current Data Collection Flow
1. **Discovery:** Fetch trades from active eSports markets → extract trader addresses
2. **Backfill:** For each trader, call `https://data-api.polymarket.com/trades?proxyWallet={address}`
3. **❌ THE PROBLEM:** API returns only ~100 most recent trades per trader (hard limit, no pagination)

### Impact of 100-Trade Limit
**Example scenario:**
```
Trader 0x113dae:
- Made 3 LoL trades 2 months ago (why we discovered them from LoL market)
- Made 150 Crypto trades in last month
- API returns: 100 most recent = all Crypto trades (0 LoL trades!)
- Database ends up with: 0 LoL trades despite discovering from LoL market
```

**Current workaround:**
- Store trades immediately during discovery (before they age out)
- ✅ Prevents data loss for discovery markets
- ❌ Still can't get full trader history (only recent 100)
- ❌ Concentration metrics incomplete (recent trades over-represented)
- ❌ Expertise scores biased toward recent activity

### What We Need
- **Complete trader histories** (all trades since Polymarket launch, not just 100)
- **Accurate concentration metrics** (true % of volume in eSports)
- **Historical market discovery** (find resolved eSports markets)
- **Unbiased expertise scoring** (full performance record)

---

## ✅ The Solution: Blockchain Indexing

### Technical Approach
**Instead of Polymarket Data API, query Polygon blockchain directly:**

```python
# Current (limited):
trades = api.get_trader_trades(address)  # Returns 100 max

# New (complete):
trades = blockchain.get_all_trader_trades(address)  # Returns ALL trades
```

### How Blockchain Indexing Works
1. **Source:** Polygon blockchain (Polymarket trades are on-chain)
2. **Contract:** CTF Exchange contract (`0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`)
3. **Events:** `OrderFilled` events contain trade data
4. **Method:** Query event logs using Web3.py + Polygon RPC endpoint
5. **Range:** Query block ranges from contract deployment to current

### Reference Implementation
**Repo:** https://github.com/Jon-Becker/prediction-market-analysis
**Key files:**
- `indexers/polymarket/trades.py` - Blockchain trade indexing
- Shows how to decode `OrderFilled` events
- Demonstrates block range queries and pagination

### Technology Requirements
- **web3.py** (≥6.0.0) - Ethereum/Polygon interaction
- **Polygon RPC endpoint** - Free tier from Alchemy/Infura/QuickNode
- **CTF Exchange ABI** - For event decoding

---

## 🏗️ Architecture Design Guidelines

### Recommended Hybrid Approach
```
┌─────────────────────────────────────────┐
│ Discovery (Real-time)                   │
│ - Keep current API approach             │
│ - Fast, works for active markets        │
│ - Immediate trade storage (prevents loss)│
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│ Backfill (Comprehensive)                │
│ - NEW: Blockchain queries               │
│ - Complete trader history               │
│ - Process overnight/batches             │
│ - Cache results                         │
└─────────────────────────────────────────┘
```

### Module Structure
Create new `src/blockchain/` module:
```
src/blockchain/
├── __init__.py
├── client.py          # PolygonBlockchainClient
├── models.py          # BlockchainTrade response model
├── decoder.py         # OrderFilled event decoding
└── cache.py           # Optional: Block range caching
```

### Integration Points
1. **TraderIngestionPipeline.ingest_trader_history()** - Switch to blockchain client
2. **Keep API client** for market metadata (still needed)
3. **Deduplication** - Trades checked by trade_id before insertion
4. **Configuration** - Add RPC URL, batch size to settings.py

### Performance Considerations
- Blockchain queries slower than API (block range iteration)
- **Solution:** Batch processing, background jobs
- **RPC limits:** Free tier ~300k req/month (sufficient for 100s of traders)
- **Caching:** Store last queried block per trader to avoid re-scanning

---

## 📊 Requirements (From ROADMAP.md Context)

Phase 8 should fulfill these requirements:

### Data Completeness Requirements
- **HIST-01:** System retrieves complete trading history for discovered traders
- **HIST-02:** System queries blockchain event logs for OrderFilled events
- **HIST-03:** System handles block range pagination for large histories
- **HIST-04:** System caches blockchain query results to avoid redundant scanning

### Integration Requirements
- **INTG-01:** Blockchain client integrates with existing TraderIngestionPipeline
- **INTG-02:** System maintains API client for market metadata (hybrid approach)
- **INTG-03:** Trade deduplication works across API and blockchain sources
- **INTG-04:** Configuration supports RPC URL and batch size settings

### Performance Requirements
- **PERF-01:** Batch processing handles multiple traders efficiently
- **PERF-02:** System tracks last queried block to enable incremental updates
- **PERF-03:** RPC rate limiting prevents hitting provider limits

---

## 🔍 Key Technical Decisions to Make

### 1. RPC Provider Strategy
**Options:**
- Free public RPC (polygon-rpc.com) - Rate limited, less reliable
- Alchemy/Infura free tier - 300k req/month, better reliability
- QuickNode free tier - Similar limits

**Recommendation needed:** Which to use? (Default to Alchemy with public fallback?)

### 2. Block Range Strategy
**Options:**
- Query all blocks from contract deployment (slow first run, complete)
- Query recent 6 months (faster, may miss old trades)

**Recommendation needed:** How far back to query initially?

### 3. Caching Strategy
**Options:**
- In-memory dict (simple, lost on restart)
- SQLite table (persistent, queryable)
- File-based (simple persistence)

**Recommendation needed:** Where to store last_queried_block per trader?

### 4. Processing Mode
**Options:**
- Synchronous (blocking, simple)
- Async with asyncio (faster, more complex)
- Background job queue (decoupled, robust)

**Recommendation needed:** How to orchestrate blockchain backfill?

### 5. Event Decoding
**Options:**
- Manual decoding (no ABI needed, brittle)
- web3.py contract interface (requires ABI, robust)
- Pre-built decoder from Jon's repo (copy approach)

**Recommendation needed:** How to decode OrderFilled events?

---

## 📝 GSD PLAN.md Template

Your output should follow this exact structure:

```markdown
---
phase: 8
plan: 1  # Or 2, 3 if breaking into multiple plans
wave: 1  # Parallelization: plans with same wave run in parallel
status: planned
---

# Plan 08-01: [Short Title]

## Goal
[1-2 sentences: What this plan achieves]

## Context
[Why this is needed, what problem it solves. Reference journey doc if relevant]

## Approach

### Changes Required

**New Files:**
- `src/blockchain/client.py` - [Description]
- `src/blockchain/models.py` - [Description]
- `tests/blockchain/test_client.py` - [Description]

**Modified Files:**
- `src/pipeline/ingest.py` - [What changes and why]
- `src/config/settings.py` - [What changes and why]

### Implementation Steps

1. **Setup blockchain client foundation**
   - Install web3.py dependency
   - Create PolygonBlockchainClient class
   - Add RPC URL configuration

2. **Implement event querying**
   - Add get_order_filled_events() method
   - Implement block range pagination
   - Add event decoding logic

3. **Integration with ingestion pipeline**
   - Modify ingest_trader_history() to use blockchain client
   - Add blockchain/API source deduplication
   - Preserve existing API metadata fetching

4. **Testing**
   - Unit tests for blockchain client
   - Integration tests for pipeline
   - Test with known trader address

[Continue with detailed steps...]

## Testing Strategy

### Unit Tests
- `test_blockchain_client_initialization` - [What to test]
- `test_get_order_filled_events` - [What to test]
- `test_event_decoding` - [What to test]

### Integration Tests
- `test_trader_backfill_blockchain_source` - [What to test]
- `test_hybrid_api_blockchain_deduplication` - [What to test]

### Manual Verification
- Query blockchain for known trader (0x113dae...)
- Compare trade count: blockchain vs API
- Verify all LoL trades captured

## Risks & Mitigations

**Risk:** RPC rate limits exceeded during batch processing
**Mitigation:** Implement exponential backoff, batch size tuning

**Risk:** Event decoding fails for unexpected event formats
**Mitigation:** Extensive error handling, skip malformed events with logging

[Continue with other risks...]

## Dependencies
- Requires web3.py>=6.0.0
- Requires Polygon RPC endpoint (free tier sufficient)
- Depends on Phase 2 trader discovery (already complete)

## Success Criteria
- [ ] PolygonBlockchainClient can query OrderFilled events
- [ ] TraderIngestionPipeline successfully uses blockchain client
- [ ] Complete trader histories retrieved (>100 trades)
- [ ] All tests passing
- [ ] Documentation updated

## Estimated Scope
[Small/Medium/Large] - [Brief justification]
```

---

## 🎓 Example Plan Reference

See existing Phase 1-7 plans in `.planning/phases/` for examples:
- **Good TDD example:** `.planning/phases/01-foundation/01-02-PLAN.md`
- **Good integration example:** `.planning/phases/02-classification-discovery/02-03-PLAN.md`
- **Good testing strategy:** `.planning/phases/04-scoring-engine/04-02-PLAN.md`

---

## 🔬 Research Tasks

Before writing the plan, research:

1. **Web3.py documentation** - How to query event logs on Polygon
2. **Jon Becker's repo** - How he decodes OrderFilled events
3. **CTF Exchange contract** - Event signature and structure
4. **Polygon RPC providers** - Free tier limits and reliability

**Sources:**
- https://web3py.readthedocs.io/en/stable/
- https://github.com/Jon-Becker/prediction-market-analysis
- https://docs.alchemy.com/docs/polygon-api
- https://polygonscan.com/address/0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E

---

## ✅ Checklist for Your Plan

Before submitting to Claude, verify:

- [ ] Follows GSD PLAN.md frontmatter format (phase/plan/wave/status)
- [ ] Addresses the 100-trade limitation problem explicitly
- [ ] Includes blockchain client implementation details
- [ ] Maintains hybrid approach (API for metadata, blockchain for trades)
- [ ] Has comprehensive testing strategy (unit + integration + manual)
- [ ] Considers RPC rate limits and error handling
- [ ] Provides clear success criteria
- [ ] Breaks work into logical, testable steps
- [ ] Estimates scope realistically
- [ ] References technical decisions made

---

## 📤 Deliverable Format

**Output as:** Single markdown file OR multiple PLAN.md files if breaking into multiple plans

**Naming:**
- If 1 plan: `08-01-PLAN.md`
- If 2 plans: `08-01-PLAN.md`, `08-02-PLAN.md`
- If 3 plans: `08-01-PLAN.md`, `08-02-PLAN.md`, `08-03-PLAN.md`

**Parallelization guidance:**
- Independent work (e.g., client implementation vs. config updates) → Same wave
- Dependent work (e.g., client must exist before integration) → Sequential waves

---

## 🤝 Handoff Back to Claude

After you complete planning, the user will:

1. Save your plan(s) to `.planning/phases/08-complete-trader-history-via-blockchain/`
2. Tell Claude: `/gsd:execute-phase 8`
3. Claude reads the plan(s) and executes with atomic commits + state tracking

**Your plan quality directly impacts execution speed!** Clear, detailed plans = fast execution.

---

## 💡 Tips for Success

1. **Be specific:** "Add RPC URL to settings.py" not "Update config"
2. **Think TDD:** Tests should drive implementation structure
3. **Consider edge cases:** Empty blockchain response, malformed events, RPC timeout
4. **Reference existing patterns:** Similar to how API client handles rate limiting
5. **Plan for failure:** What if RPC is down? What if event format changes?
6. **Keep it focused:** If plan feels too large (>8 major steps), split into 2 plans

---

## 📚 Additional Context Files

**Read these for full context:**
- `.planning/TRADER_DISCOVERY_JOURNEY.md` - Problem deep-dive and solution research
- `.planning/PROJECT.md` - Project overview and requirements
- `src/api/client.py` - Current API client pattern to follow
- `src/pipeline/ingest.py` - Integration point (ingest_trader_history method)
- `src/config/settings.py` - Configuration pattern

**Key code patterns to follow:**
- Rate limiting: See `src/api/client.py:RateLimiter` (adapt for RPC)
- Pydantic models: See `src/api/models.py:TradeResponse` (create BlockchainTrade)
- Error handling: Try/except with logging, graceful degradation
- Deduplication: Check by trade_id before insert (see `ingest.py`)

---

## 🎯 Success = Claude Can Execute Without Questions

Your plan should be so clear that Claude:
- Knows exactly what files to create/modify
- Understands the testing approach
- Can write code without clarifying requirements
- Knows when the plan is complete

**Good luck! You're saving the project from the 100-trade limitation. 🚀**
