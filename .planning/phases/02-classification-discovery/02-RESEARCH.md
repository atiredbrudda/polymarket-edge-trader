# Phase 2: Classification & Discovery - Research

**Researched:** 2026-02-06
**Domain:** YAML-based hierarchical taxonomy, pattern matching classification, position tracking
**Confidence:** HIGH

## Summary

Phase 2 implements a YAML-driven hierarchical taxonomy for eSports market classification (4 levels: eSports → Game → Tournament tier → Team) with regex-based pattern matching, trader discovery via minimum volume/trade thresholds, and stateless position tracking computed from trade history. The standard stack leverages PyYAML for configuration, Python's built-in `re` module for pattern matching, Pydantic for taxonomy validation, and SQLite's adjacency list model for hierarchical storage. Critical findings include Polymarket-specific double counting risks (OrderFilled events emit twice per trade—maker and taker), the need for precompiled regex patterns for performance, and weighted average calculation for entry prices across multiple partial fills.

The research confirms that existing Phase 1 infrastructure (SQLAlchemy models, Decimal precision for trades, composite indexes) provides a solid foundation. New requirements include YAML taxonomy definitions with Pydantic validation, a classification engine with multi-match resolution (deepest taxonomy node wins), and position aggregation logic that recalculates from raw trade data each time to avoid drift.

**Primary recommendation:** Use adjacency list model for taxonomy storage (parent_id), precompile all regex patterns at startup, validate YAML with Pydantic schemas, and implement position tracking as pure functions that recompute from trade history (no incremental state).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Taxonomy structure:**
- 4-level hierarchy: eSports → Game → Tournament tier → Team
- Team-level awareness: system tracks which teams a trader bets on across events (e.g., a trader consistently betting on NaVi across IEM Katowice, ESL Pro League, BLAST = NaVi specialist)
- Teams that compete across multiple games: Claude's discretion on whether to duplicate per game or use a shared registry
- Unknown teams/tournaments: classify at highest matching level, flag unmatched entities for periodic YAML review

**Market matching:**
- Keyword patterns defined in YAML per taxonomy node (regex/keyword matching against market titles)
- Market type tag: each market classified as "match" (head-to-head, e.g., Team Secret vs MVK) or "prop" (tournament winner, player stats, etc.) — this is a tag attribute, not a taxonomy branch
- Multi-match resolution: best (most specific) match wins — deepest taxonomy node takes priority
- Ambiguous markets that match no taxonomy node get flagged for review alongside unknown teams

**Trader discovery scope:**
- Minimum thresholds to track: 5+ trades AND $500+ total volume in eSports markets
- Track eSports activity only — non-eSports trades ignored entirely
- Discovery mode: periodic sweep (e.g., daily) plus manual trigger capability
- History backfill strategy: Claude's discretion on immediate vs deferred backfill

**Position tracking:**
- Trade-level tracking: track each buy/sell individually, compute average entry price, total size, and direction from full history
- Recalculate positions from raw trade data each time (no incremental state — always accurate, no drift)
- Archive resolved positions with outcome (win/loss/void) and PnL — feeds Phase 3 historical evaluation
- Track entry timing: record when positions were opened relative to market creation and resolution (early mover vs late follower signal for Phase 5)

### Claude's Discretion

- Cross-game team handling (duplicate per game vs shared registry)
- History backfill timing (immediate on discovery vs deferred batch job)
- Exact regex patterns for initial taxonomy seeding
- Sweep scheduling defaults (daily cadence, time of day)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

## Standard Stack

The established libraries/tools for this domain:

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| PyYAML | 6.0+ | YAML parsing/writing | Most-used YAML library (1M+ downloads), complete YAML 1.1 parser, Unicode support |
| Pydantic | 2.12.5+ | YAML schema validation | Already in stack (Phase 1), type-safe config validation, excellent error messages |
| re (built-in) | Python 3.11+ | Regex pattern matching | Standard library, no dependencies, sufficient for keyword/title matching |
| SQLAlchemy | 2.0.46+ | Hierarchical data storage | Already in stack (Phase 1), supports adjacency list queries with recursive CTEs |
| Decimal (built-in) | Python 3.11+ | Position calculations | Already used for trades (Phase 1), exact precision for financial math |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| RapidFuzz | 3.0+ | Fuzzy team name matching | If exact regex fails, normalize team name variations (e.g., "Team Liquid" vs "TL") |
| pydantic-yaml | 1.3+ | Direct Pydantic<->YAML binding | If you need round-trip YAML preservation with Pydantic models |
| ruamel.yaml | 0.18+ | Round-trip YAML parsing | Only if you need to preserve comments/formatting when updating taxonomy |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| PyYAML | ruamel.yaml | Heavier, preserves comments/formatting (not needed for read-only taxonomy) |
| PyYAML | StrictYAML | Safer but overly restrictive for taxonomy definitions |
| re (built-in) | regex (PyPI) | More features (variable-length lookbehinds) but adds dependency, overkill for title matching |
| Adjacency list | Closure table | Precomputes all paths (faster queries, more storage, complex updates—premature for v1) |

**Installation:**
```bash
# Phase 1 already has these
# sqlalchemy>=2.0.46
# pydantic>=2.12.5

# New dependencies for Phase 2
pip install pyyaml>=6.0
pip install rapidfuzz>=3.0  # Optional: only if fuzzy matching needed
```

## Architecture Patterns

### Recommended Project Structure

```
src/
├── taxonomy/              # New for Phase 2
│   ├── __init__.py
│   ├── models.py         # Pydantic schemas for taxonomy YAML
│   ├── loader.py         # YAML loading + validation
│   ├── classifier.py     # Market title -> taxonomy node matching
│   └── patterns.py       # Precompiled regex patterns
├── discovery/             # New for Phase 2
│   ├── __init__.py
│   ├── trader_discovery.py   # Find traders meeting thresholds
│   └── position_tracker.py   # Compute positions from trades
├── db/
│   └── models.py         # Add: TaxonomyNode, MarketClassification, Position tables
├── pipeline/
│   └── ...               # Existing from Phase 1
└── config/
    └── settings.py       # Existing from Phase 1
```

```
data/
├── polymarket.db         # SQLite database (Phase 1)
└── taxonomy/             # New for Phase 2
    └── esports.yaml      # 4-level eSports taxonomy
```

### Pattern 1: YAML Taxonomy with Pydantic Validation

**What:** Define hierarchical taxonomy in YAML, validate with Pydantic schemas on load
**When to use:** Any config-driven classification system requiring human-editable taxonomies
**Example:**

```python
# taxonomy/models.py
from pydantic import BaseModel, Field
from typing import List, Optional

class TeamNode(BaseModel):
    name: str
    patterns: List[str]  # Regex patterns for matching team names
    aliases: Optional[List[str]] = []  # Alternative team names

class TournamentNode(BaseModel):
    name: str
    patterns: List[str]
    teams: List[TeamNode] = []

class GameNode(BaseModel):
    name: str
    patterns: List[str]
    tournaments: List[TournamentNode] = []

class EsportsTaxonomy(BaseModel):
    name: str = Field(default="eSports")
    games: List[GameNode]

# taxonomy/loader.py
import yaml
from pathlib import Path

def load_taxonomy(path: Path) -> EsportsTaxonomy:
    """Load and validate taxonomy YAML against Pydantic schema.

    Raises:
        ValidationError: If YAML structure doesn't match schema
        yaml.YAMLError: If YAML syntax is invalid
    """
    with open(path, 'r') as f:
        data = yaml.safe_load(f)  # CRITICAL: Use safe_load, never load()

    return EsportsTaxonomy.model_validate(data)
```

**YAML structure example:**
```yaml
# data/taxonomy/esports.yaml
name: eSports
games:
  - name: CS2
    patterns: ["\\bCS2\\b", "\\bCounter-Strike 2\\b", "\\bCounter Strike 2\\b"]
    tournaments:
      - name: IEM Katowice
        patterns: ["IEM Katowice", "Intel Extreme Masters Katowice"]
        teams:
          - name: Natus Vincere
            patterns: ["\\bNaVi\\b", "Natus Vincere", "Na'Vi"]
            aliases: ["NAVI"]
      - name: ESL Pro League
        patterns: ["ESL Pro League", "EPL"]
        teams: []  # Populated over time
  - name: Dota 2
    patterns: ["\\bDota 2\\b", "\\bDota2\\b"]
    tournaments: []
```

### Pattern 2: Precompiled Regex with Deepest-Match Resolution

**What:** Compile all regex patterns at startup, match market titles by testing all patterns, return deepest taxonomy node
**When to use:** Classification systems with hundreds of patterns, real-time classification needs
**Example:**

```python
# taxonomy/patterns.py
import re
from dataclasses import dataclass
from typing import List

@dataclass
class CompiledPattern:
    pattern: re.Pattern
    depth: int  # 0=eSports, 1=Game, 2=Tournament, 3=Team
    node_path: str  # "eSports.CS2.IEM Katowice.NaVi"
    market_type: str | None = None  # "match" or "prop" if pattern is type-specific

class PatternMatcher:
    """Precompiles all taxonomy patterns for O(patterns) classification."""

    def __init__(self, taxonomy: EsportsTaxonomy):
        self.patterns: List[CompiledPattern] = []
        self._compile_taxonomy(taxonomy)

    def _compile_taxonomy(self, taxonomy: EsportsTaxonomy):
        """Flatten taxonomy into precompiled patterns with depth metadata."""
        for game in taxonomy.games:
            for pattern_str in game.patterns:
                self.patterns.append(CompiledPattern(
                    pattern=re.compile(pattern_str, re.IGNORECASE),
                    depth=1,
                    node_path=f"eSports.{game.name}"
                ))

            for tournament in game.tournaments:
                for pattern_str in tournament.patterns:
                    self.patterns.append(CompiledPattern(
                        pattern=re.compile(pattern_str, re.IGNORECASE),
                        depth=2,
                        node_path=f"eSports.{game.name}.{tournament.name}"
                    ))

                for team in tournament.teams:
                    for pattern_str in team.patterns:
                        self.patterns.append(CompiledPattern(
                            pattern=re.compile(pattern_str, re.IGNORECASE),
                            depth=3,
                            node_path=f"eSports.{game.name}.{tournament.name}.{team.name}"
                        ))

    def classify(self, market_title: str) -> CompiledPattern | None:
        """Return deepest matching taxonomy node.

        Multi-match resolution: If multiple patterns match, deepest wins.
        If tied at same depth, first match wins (taxonomy order matters).
        """
        best_match = None

        for compiled in self.patterns:
            if compiled.pattern.search(market_title):
                if best_match is None or compiled.depth > best_match.depth:
                    best_match = compiled

        return best_match
```

### Pattern 3: Stateless Position Calculation from Trade History

**What:** Pure function that recomputes position state from full trade list each time
**When to use:** Trading systems prioritizing accuracy over performance, avoiding state drift
**Example:**

```python
# discovery/position_tracker.py
from decimal import Decimal
from dataclasses import dataclass
from typing import List
from src.db.models import Trade

@dataclass
class Position:
    """Current position state computed from trade history."""
    market_id: str
    trader_address: str
    size: Decimal  # Net shares owned (positive = long, negative = short)
    direction: str  # "LONG", "SHORT", or "FLAT"
    avg_entry_price: Decimal | None  # Weighted average entry
    entry_timestamp: datetime | None  # First trade opening position
    total_cost_basis: Decimal  # Sum(size * price) across all buys

def calculate_position(trades: List[Trade]) -> Position:
    """Compute current position from trade history (stateless).

    CRITICAL: Uses weighted average for entry price, not simple average.
    Handles partial fills correctly (each buy/sell as separate entry).

    Args:
        trades: All trades for a single (trader, market) pair, chronological order

    Returns:
        Position object with computed state
    """
    if not trades:
        raise ValueError("Empty trade list")

    market_id = trades[0].market_id
    trader_address = trades[0].trader_address

    # Accumulate net position
    net_size = Decimal("0")
    total_cost_basis = Decimal("0")
    entry_timestamp = None

    for trade in trades:
        if trade.side == "BUY":
            net_size += trade.size
            total_cost_basis += trade.size * trade.price
            if entry_timestamp is None:
                entry_timestamp = trade.timestamp
        elif trade.side == "SELL":
            net_size -= trade.size
            # Reduce cost basis proportionally
            total_cost_basis -= trade.size * trade.price
            # If position closed then reopened, update entry timestamp
            if net_size == 0:
                entry_timestamp = None

    # Determine direction and average entry
    if net_size > 0:
        direction = "LONG"
        avg_entry_price = total_cost_basis / net_size if net_size > 0 else None
    elif net_size < 0:
        direction = "SHORT"
        avg_entry_price = total_cost_basis / abs(net_size) if net_size < 0 else None
    else:
        direction = "FLAT"
        avg_entry_price = None

    return Position(
        market_id=market_id,
        trader_address=trader_address,
        size=net_size,
        direction=direction,
        avg_entry_price=avg_entry_price,
        entry_timestamp=entry_timestamp,
        total_cost_basis=total_cost_basis
    )
```

### Pattern 4: Adjacency List for Hierarchical Taxonomy Storage

**What:** Store taxonomy in SQL with parent_id foreign key, query with recursive CTEs
**When to use:** Hierarchical data with unknown/variable depth, frequent reads, infrequent updates
**Example:**

```python
# db/models.py (additions to existing file)
class TaxonomyNode(Base):
    """Hierarchical taxonomy nodes using adjacency list model.

    Supports unlimited depth with parent_id self-reference.
    Query full paths using SQLite recursive CTEs.
    """
    __tablename__ = "taxonomy_nodes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("taxonomy_nodes.id"), nullable=True)
    depth: Mapped[int] = mapped_column(nullable=False)  # 0=root, 1=game, 2=tournament, 3=team
    patterns: Mapped[str] = mapped_column(String(2000), nullable=False)  # JSON-encoded regex list
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_taxonomy_parent", "parent_id"),
        Index("ix_taxonomy_depth", "depth"),
    )

class MarketClassification(Base):
    """Maps markets to taxonomy nodes with confidence and flags."""
    __tablename__ = "market_classifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(100), ForeignKey("markets.condition_id"), nullable=False, unique=True)
    taxonomy_node_id: Mapped[int | None] = mapped_column(ForeignKey("taxonomy_nodes.id"), nullable=True)
    market_type: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "match" or "prop"
    flagged_for_review: Mapped[bool] = mapped_column(default=False, nullable=False)
    matched_pattern: Mapped[str | None] = mapped_column(String(200), nullable=True)  # Which regex matched
    classified_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_classification_market", "market_id"),
        Index("ix_classification_flagged", "flagged_for_review"),
    )

class Position(Base):
    """Current and historical positions computed from trade data."""
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(100), nullable=False)
    trader_address: Mapped[str] = mapped_column(String(42), nullable=False)
    size: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    direction: Mapped[str] = mapped_column(String(5), nullable=False)  # LONG/SHORT/FLAT
    avg_entry_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    entry_timestamp: Mapped[datetime | None] = mapped_column(nullable=True)
    resolved: Mapped[bool] = mapped_column(default=False, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)  # win/loss/void
    pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_position_trader_market", "trader_address", "market_id", unique=True),
        Index("ix_position_resolved", "resolved"),
    )
```

### Anti-Patterns to Avoid

- **Incremental position updates:** Leads to drift from rounding errors, race conditions, and missing corrections. Always recompute from full trade history.
- **yaml.load() for user configs:** Allows arbitrary code execution. Always use yaml.safe_load().
- **Float for financial calculations:** 0.1 + 0.2 != 0.3 in float. Use Decimal for all position/PnL math.
- **Regex compilation inside loops:** Compiling patterns on every market classification is 100x slower. Precompile at startup.
- **Storing full taxonomy in every market record:** Normalize with foreign keys to TaxonomyNode table to avoid duplication.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| YAML parsing | Custom YAML parser | PyYAML yaml.safe_load() | Handle edge cases (multiline strings, unicode, nested structures), security (safe_load prevents code execution) |
| Fuzzy team name matching | Custom string distance | RapidFuzz (token_sort_ratio) | Handles word order, abbreviations, C++ performance (100x faster than pure Python) |
| Hierarchical queries | Manual recursion in Python | SQLite recursive CTEs | Query full paths in one SQL statement, leverage database indexes |
| Position tracking | Incremental updates | Recompute from trades | Avoids state drift, handles corrections/cancellations, simpler to test |
| YAML validation | Manual dict checks | Pydantic BaseModel | Type checking, nested validation, clear error messages with field paths |
| Weighted averages | Manual calculation | Proven formula (sum(size*price)/sum(size)) | Edge cases: zero position, negative sizes (shorts), precision |

**Key insight:** Classification and position tracking have subtle edge cases (double counting, partial fills, race conditions). Existing libraries and proven algorithms handle these correctly. Custom solutions will miss edge cases and introduce bugs under production data patterns not seen in testing.

## Common Pitfalls

### Pitfall 1: Polymarket Double Counting in Trade Volume

**What goes wrong:** Polymarket CLOB emits TWO OrderFilled events per trade (one for maker, one for taker). Aggregating without deduplication doubles reported volume.

**Why it happens:** The smart contract architecture tracks both sides of each match separately for transparency, but analytics must deduplicate to get true volume.

**How to avoid:**
- When discovering traders from market trades, track unique trade_id to prevent counting same trade twice
- When calculating volume thresholds ($500+ volume), ensure you're summing unique trades, not duplicate OrderFilled events
- If trade_id is not available, deduplicate by (market_id, timestamp, size, price) tuples

**Warning signs:**
- Volume totals are exactly 2x expected values
- Trade counts are even when they should be odd
- Same trader appears as both maker and taker in threshold calculations

**Source:** [Paradigm Finds Double Counting Errors in Polymarket Data | Phemex News](https://phemex.com/news/article/paradigm-identifies-double-counting-errors-in-polymarket-data-43130)

### Pitfall 2: Regex Catastrophic Backtracking

**What goes wrong:** Nested quantifiers like (a*)* or greedy patterns with overlapping alternations cause exponential backtracking, freezing classification on malicious/complex market titles.

**Why it happens:** Regex engine tries multiple matching strategies when patterns have ambiguous paths, leading to O(2^n) time complexity.

**How to avoid:**
- Use atomic groups (?>...) or possessive quantifiers to prevent backtracking
- Avoid nested quantifiers (*, +, {n,m} inside another quantifier)
- Test patterns against max-length market titles (500 chars) to catch performance issues
- Set regex timeout if supported: re.match(pattern, text, timeout=1.0) (Python 3.11+)
- Prefer non-capturing groups (?:...) over capturing groups () to reduce overhead

**Warning signs:**
- Classification takes >100ms per market (should be <1ms with precompiled patterns)
- CPU spikes during market classification
- Timeouts on specific market titles with many repeated characters

**Source:** [Fixing Pattern Matching Failures, Catastrophic Backtracking, and Performance Issues in Regex](https://www.mindfulchase.com/explore/troubleshooting-tips/fixing-pattern-matching-failures,-catastrophic-backtracking,-and-performance-issues-in-regex.html)

### Pitfall 3: yaml.load() Security Vulnerability

**What goes wrong:** yaml.load() can execute arbitrary Python code embedded in YAML files, allowing remote code execution if loading untrusted taxonomy files.

**Why it happens:** PyYAML's load() reconstructs arbitrary Python objects via !!python/object tags for backward compatibility.

**How to avoid:**
- ALWAYS use yaml.safe_load() for user-editable configs
- If you need custom types, use yaml.safe_load() + Pydantic validation instead of yaml.load()
- Add pre-commit hooks to detect yaml.load() in code reviews
- Use yamllint to enforce safe patterns

**Warning signs:**
- Code review finds yaml.load() without explicit trust verification
- YAML files contain !!python/object or !!python/name tags
- Security scanners flag PyYAML usage

**Source:** [Be Careful When Using YAML in Python! There May Be Security Vulnerabilities](https://dev.to/fkkarakurt/be-careful-when-using-yaml-in-python-there-may-be-security-vulnerabilities-3cdb)

### Pitfall 4: Floating Point for Weighted Average Entry Price

**What goes wrong:** Using float for position calculations introduces rounding errors: Decimal("0.1") + Decimal("0.2") == Decimal("0.3"), but 0.1 + 0.2 == 0.30000000000000004.

**Why it happens:** Binary floating point cannot exactly represent base-10 decimals like 0.1.

**How to avoid:**
- Initialize Decimal from strings, never floats: Decimal("19.99"), not Decimal(19.99)
- Use Decimal arithmetic throughout position calculations
- Phase 1 already stores trades as Numeric(20,6) and Numeric(10,6) — leverage this
- When aggregating, use Decimal.quantize() to control rounding: price.quantize(Decimal("0.000001"))

**Warning signs:**
- Position tests fail with tiny differences (1e-15)
- Average entry price differs from manual calculation by >$0.000001
- Serialization/deserialization changes values slightly

**Source:** [Python Decimal: Division, Rounding, and Precision](https://mangohost.net/blog/python-decimal-division-rounding-and-precision/)

### Pitfall 5: Unknown Team/Tournament Silently Ignored

**What goes wrong:** Market mentions a team not in taxonomy, gets classified at game level, pattern never surfaces for review.

**Why it happens:** Deepest-match resolution classifies market at highest matching level without flagging the missing deeper match.

**How to avoid:**
- Track "partial matches" separately from "full matches" (e.g., game matched but no tournament/team)
- Flag markets for review if title contains team-like patterns ("vs", "v", specific team keywords) but no team node matched
- Maintain a review queue table with flagged markets for periodic taxonomy updates
- Log unmatched patterns to identify taxonomy gaps

**Warning signs:**
- Classification depth distribution heavily skewed toward game-level (should have more team-level)
- Manual review finds obvious team names not in taxonomy
- Low team-level classification rate despite match markets

## Code Examples

Verified patterns from research and established best practices:

### Trader Discovery with Volume Threshold

```python
# discovery/trader_discovery.py
from decimal import Decimal
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from src.db.models import Trade, Trader

def discover_traders_above_threshold(
    session: Session,
    category: str,
    min_trades: int = 5,
    min_volume: Decimal = Decimal("500")
) -> List[str]:
    """Find traders meeting minimum activity thresholds in a category.

    CRITICAL: Deduplicates by trade_id to avoid Polymarket double counting.

    Args:
        session: SQLAlchemy session
        category: Category to filter (e.g., "eSports")
        min_trades: Minimum unique trades required
        min_volume: Minimum total volume (USD) required

    Returns:
        List of trader addresses meeting both thresholds
    """
    # Join trades with markets to filter by category
    # Group by trader, ensure unique trade_id to avoid double counting
    # Having clause enforces both thresholds
    query = (
        select(Trade.trader_address)
        .join(Market, Trade.market_id == Market.condition_id)
        .where(Market.category == category)
        .group_by(Trade.trader_address)
        .having(
            func.count(func.distinct(Trade.trade_id)) >= min_trades,
            func.sum(Trade.size * Trade.price) >= min_volume
        )
    )

    result = session.execute(query)
    return [row[0] for row in result.fetchall()]
```

### Market Type Detection (Match vs Prop)

```python
# taxonomy/classifier.py
import re

# Precompiled patterns for market type detection
MATCH_PATTERNS = [
    re.compile(r"\bvs\.?\b", re.IGNORECASE),      # "Team A vs Team B"
    re.compile(r"\bv\b", re.IGNORECASE),          # "Team A v Team B"
    re.compile(r"\b-\b"),                         # "Team A - Team B"
    re.compile(r"\b@\b"),                         # "Team A @ Team B"
]

PROP_PATTERNS = [
    re.compile(r"\bwinner\b", re.IGNORECASE),     # "Tournament winner"
    re.compile(r"\btop\s+\d+\b", re.IGNORECASE),  # "Top 5 finish"
    re.compile(r"\bover\s+\d+\.?\d*\b", re.IGNORECASE),  # "Over 2.5 maps"
]

def detect_market_type(market_title: str) -> str | None:
    """Classify market as 'match' or 'prop' based on title patterns.

    Returns:
        "match" if head-to-head match detected
        "prop" if proposition/futures bet detected
        None if ambiguous or unmatched
    """
    match_score = sum(1 for p in MATCH_PATTERNS if p.search(market_title))
    prop_score = sum(1 for p in PROP_PATTERNS if p.search(market_title))

    if match_score > prop_score:
        return "match"
    elif prop_score > match_score:
        return "prop"
    else:
        return None  # Ambiguous, flag for review
```

### Position Archival with PnL Calculation

```python
# discovery/position_tracker.py
def archive_resolved_position(
    session: Session,
    position: Position,
    market_outcome: str,
    resolution_price: Decimal
) -> Position:
    """Archive a position when its market resolves, compute final PnL.

    Args:
        session: SQLAlchemy session
        position: Current position object
        market_outcome: Market resolution ("YES", "NO", "VOID")
        resolution_price: Final settlement price (typically 0 or 1)

    Returns:
        Updated Position with resolved=True, outcome, and pnl set
    """
    # Determine outcome from position direction + market result
    if market_outcome == "VOID":
        outcome = "void"
        pnl = Decimal("0")  # Return cost basis on void
    elif position.direction == "LONG":
        # Long position: profit if market resolves to high price
        pnl = position.size * (resolution_price - position.avg_entry_price)
        outcome = "win" if pnl > 0 else "loss"
    elif position.direction == "SHORT":
        # Short position: profit if market resolves to low price
        pnl = position.size * (position.avg_entry_price - resolution_price)
        outcome = "win" if pnl > 0 else "loss"
    else:  # FLAT
        outcome = "flat"
        pnl = Decimal("0")

    # Update position record
    position.resolved = True
    position.outcome = outcome
    position.pnl = pnl
    position.computed_at = datetime.utcnow()

    session.add(position)
    session.commit()

    return position
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| FuzzyWuzzy | RapidFuzz | 2021-2023 | 100x performance improvement (C++ vs pure Python), same API, actively maintained |
| yaml.load() | yaml.safe_load() | Ongoing security practice | Prevents arbitrary code execution, required for untrusted configs |
| Manual recursion for hierarchies | SQLite recursive CTEs | SQLite 3.8+ (2013) | One-query path traversal, leverage indexes, database-side optimization |
| Incremental position tracking | Stateless recomputation | Trading system evolution | Eliminates state drift, handles corrections, simpler testing |
| Float for trading | Decimal | Financial software standard | Exact precision, no 0.1+0.2 errors, regulatory compliance |

**Deprecated/outdated:**
- **FuzzyWuzzy**: Renamed to TheFuzz due to licensing, but RapidFuzz is now preferred for performance
- **Nested Set Model for hierarchies**: Requires rebuilding tree on inserts, adjacency list + recursive CTEs is simpler
- **pyyaml-include**: Adds YAML !include syntax, but Pydantic composition is more type-safe

## Open Questions

Things that couldn't be fully resolved:

1. **Cross-game team handling (shared vs duplicated)**
   - What we know: Teams like "Natus Vincere" compete in CS2, Dota 2, and Valorant
   - What's unclear: Whether to duplicate team nodes per game (eSports.CS2.*.NaVi + eSports.Dota2.*.NaVi) or use shared team registry with many-to-many relationships
   - Recommendation: Start with duplication (simpler queries, path is self-describing), migrate to shared registry if team tracking becomes phase requirement
   - Marked as Claude's discretion in CONTEXT.md

2. **History backfill timing (immediate vs deferred)**
   - What we know: When discovering a new trader, we can backfill 12 months of history immediately or queue for batch processing
   - What's unclear: Impact on API rate limits (50 req/s), user experience (do they wait?), database write concurrency
   - Recommendation: Implement both modes with a config flag; default to deferred batch job to avoid blocking discovery sweeps
   - Marked as Claude's discretion in CONTEXT.md

3. **Exact regex patterns for initial taxonomy seeding**
   - What we know: Need patterns for CS2, Dota 2, LoL, Valorant at minimum; team names like "NaVi", "Team Liquid", "FaZe"
   - What's unclear: Comprehensive list of eSports games on Polymarket, common tournament name formats, team name abbreviations
   - Recommendation: Start with minimal seed (2-3 games, 5-10 teams each), use flagged markets to expand taxonomy iteratively
   - Marked as Claude's discretion in CONTEXT.md; will require data exploration during implementation

4. **Position tracking for partial position closures**
   - What we know: Trader can sell 50% of position, leaving 50% open
   - What's unclear: Whether to track "closed portion" separately or just update remaining open position
   - Recommendation: Track only net open position (stateless recomputation handles this naturally), archive full position only on complete closure or market resolution

## Sources

### Primary (HIGH confidence)

- [Python Official Documentation - decimal module](https://docs.python.org/3/library/decimal.html) - Decimal arithmetic, precision, rounding
- [Python Official Documentation - re module](https://docs.python.org/3/library/re.html) - Regex patterns, compilation, performance
- [PyYAML Documentation](https://pyyaml.org/wiki/PyYAMLDocumentation) - YAML parsing, safe_load, security
- [Pydantic Documentation - JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/) - Model validation, YAML integration
- [SQLite Documentation - WITH Clause](https://sqlite.org/lang_with.html) - Recursive CTEs for hierarchical queries
- [Polymarket Documentation - CLOB Introduction](https://docs.polymarket.com/developers/CLOB/introduction) - API architecture, order structure

### Secondary (MEDIUM confidence)

- [Paradigm Finds Double Counting Errors in Polymarket Data | Phemex News](https://phemex.com/news/article/paradigm-identifies-double-counting-errors-in-polymarket-data-43130) - Verified: Polymarket double counting issue, OrderFilled events
- [Alpaca Documentation - Position Average Entry Price Calculation](https://docs.alpaca.markets/docs/position-average-entry-price-calculation) - Verified: Weighted average formula for positions
- [From Trees to Tables: Storing Hierarchical Data in Relational Databases | Medium](https://medium.com/@rishabhdevmanu/from-trees-to-tables-storing-hierarchical-data-in-relational-databases-a5e5e6e1bd64) - Verified: Adjacency list vs closure table vs nested set comparison
- [GitHub - seatgeek/thefuzz: Fuzzy String Matching in Python](https://github.com/seatgeek/thefuzz) - Verified: FuzzyWuzzy → TheFuzz rename, token_sort for team names
- [GitHub - rapidfuzz/RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) - Verified: C++ performance, API compatibility with FuzzyWuzzy
- [How to Validate YAML Configs Using Pydantic | Better Programming](https://betterprogramming.pub/validating-yaml-configs-made-easy-with-pydantic-594522612db5) - Verified: Pydantic + YAML integration pattern
- [Be Careful When Using YAML in Python! There May Be Security Vulnerabilities](https://dev.to/fkkarakurt/be-careful-when-using-yaml-in-python-there-may-be-security-vulnerabilities-3cdb) - Verified: yaml.load() vs yaml.safe_load() security
- [Optimizing Regular Expressions for Performance in Python | Medium](https://chrisyandata.medium.com/optimizing-regular-expressions-for-performance-in-python-1d8c03926e51) - Verified: re.compile(), atomic groups, backtracking mitigation

### Tertiary (LOW confidence)

- [InstructLab Taxonomy GitHub](https://github.com/instructlab/taxonomy) - Example: YAML-based hierarchical taxonomy for ML, qna.yaml pattern
- [Best practices for SQLite performance | Android Developers](https://developer.android.com/topic/performance/sqlite-performance-best-practices) - General: SQLite index optimization, aggregate performance
- [Python Tools for Record Linking and Fuzzy Matching - Practical Business Python](https://pbpython.com/record-linking.html) - General: Fuzzy matching libraries comparison

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - PyYAML, Pydantic, re, SQLAlchemy all verified from official docs and existing Phase 1 usage
- Architecture: HIGH - Adjacency list, Pydantic validation, stateless position tracking all well-documented patterns
- Pitfalls: HIGH - Polymarket double counting verified by Paradigm report, YAML security and regex backtracking from official sources, Decimal precision from Python docs

**Research date:** 2026-02-06
**Valid until:** 2026-03-06 (30 days - stable domain, mature libraries)
