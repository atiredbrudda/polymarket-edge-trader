# Testing Patterns

**Analysis Date:** 2026-02-12

## Test Framework

**Runner:**
- pytest 8.0+
- Config: No `pytest.ini` or `.pytest.ini` file (uses pyproject.toml defaults)

**Assertion Library:**
- pytest built-in `assert` statements

**Run Commands:**
```bash
pytest tests/                           # Run all tests
pytest tests/ -v                        # Verbose output
pytest tests/test_api_client.py         # Run single test file
pytest tests/test_api_client.py::TestPolymarketClient::test_initialization_with_settings  # Single test
pytest --cov=src tests/                 # Run with coverage
```

**Coverage:**
- pytest-cov integrated (in dev dependencies)
- View coverage: `pytest --cov=src --cov-report=html tests/`
- No enforced coverage threshold

## Test File Organization

**Location:**
- Co-located in `tests/` directory (separate from src)
- Mirrors src structure: `tests/test_api_client.py` → `src/api/client.py`, `tests/blockchain/test_decoder.py` → `src/blockchain/decoder.py`
- Subdirectories: `tests/blockchain/`, `tests/pipeline/` match src organization

**Naming:**
- Test files: `test_*.py` (e.g., `test_api_client.py`, `test_scoring.py`)
- Test classes: `Test<Module>` (e.g., `TestPolymarketClient`, `TestExpertiseScoreResult`)
- Test methods: `test_<what>_<expected_result>` (e.g., `test_initialization_with_settings`, `test_empty_positions`)

**Structure:**
```
tests/
├── test_api_client.py           # 390 lines, ~20 test methods
├── test_api_models.py           # Tests validation models
├── test_ingest.py               # 518 lines, integration tests
├── test_scoring.py              # 672 lines, scoring engine
├── test_discovery.py            # 298 lines, trader discovery
├── blockchain/
│   ├── test_decoder.py
│   └── test_models.py
└── pipeline/
    └── test_ingest_blockchain.py
```

Total test suite: ~11,266 lines across 30+ test files, 362+ test methods

## Test Structure

**Suite Organization:**

All test classes follow this pattern:

```python
class TestPolymarketClient:
    """Test suite for PolymarketClient."""

    @patch("src.api.client.ClobClient")
    def test_initialization_with_settings(self, mock_clob_client):
        """Test that client initializes with settings."""
        # Setup
        settings = Settings()
        client = PolymarketClient(settings=settings)

        # Verify
        mock_clob_client.assert_called_once_with(
            settings.polymarket_api_host,
            key=settings.polymarket_api_key
        )
        assert client.rate_limiter is not None
```

**Patterns:**

1. **Docstrings:** One-liner describing test purpose (not How, just What we're testing)
   ```python
   def test_empty_positions(self):
       """Empty list returns zero."""
   ```

2. **Setup/Assertion separation:** Explicit comment dividers
   ```python
   # Setup: Create data
   trades = [...]

   # Verify: Assert results
   assert len(result) == 2
   ```

3. **Descriptive assertion messages:** pytest defaults (no custom messages needed)
   ```python
   assert markets[0].question == "Will Team Liquid win IEM?"
   ```

## Mocking

**Framework:** unittest.mock (built-in)

**Patterns:**

1. **Patch external dependencies:**
   ```python
   @patch("src.api.client.ClobClient")
   def test_initialization_with_settings(self, mock_clob_client):
       mock_instance = mock_clob_client.return_value
       mock_instance.get_simplified_markets.return_value = [...]
   ```

2. **Mock return values:**
   ```python
   mock_client.get_markets.return_value = [
       MarketResponse(condition_id="0xabc", ...)
   ]
   ```

3. **Side effects for iteration:**
   ```python
   mock_instance.get_simplified_markets.side_effect = [page1, page2]
   ```

4. **MagicMock for spec-based mocks:**
   ```python
   alerter = MagicMock(spec=TelegramAlerter)
   alerter.send = MagicMock()
   ```

5. **What to mock:**
   - External APIs: `PolymarketClient`, `ClobClient`, `TelegramAlerter`
   - Blockchain calls: RPC endpoints
   - Date/time for time-dependent behavior
   - File I/O and network calls

6. **What NOT to mock:**
   - Database ORM: Use in-memory SQLite instead
   - Business logic: Test actual calculation functions
   - Pydantic validation: Let models validate
   - Internal methods: Test through public API

## Fixtures and Factories

**Test Data:**

Database fixtures create in-memory SQLite instances:

```python
@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory
```

**Seeding with test data:**

```python
@pytest.fixture
def seed_esports_data(in_memory_db):
    """Seed database with eSports taxonomy and classified markets."""
    with in_memory_db() as session:
        # Create taxonomy nodes
        root = TaxonomyNode(
            name="eSports",
            slug="esports",
            parent_id=None,
            depth=0,
            node_type="root",
            patterns_json="[]",
        )
        session.add(root)
        session.flush()

        # Create markets
        market1 = Market(
            condition_id="market_cs2_1",
            question="NaVi vs FaZe IEM Katowice",
            category="eSports",
            active=True,
        )
        session.add_all([market1, ...])
        session.commit()

    return in_memory_db
```

**Location:**
- Fixtures defined in individual test files (no conftest.py)
- Reusable fixtures copy-pasted into other test files
- Scope: function-scoped (default), created fresh for each test

## Coverage

**Requirements:** No enforced coverage threshold (optional)

**View Coverage:**
```bash
pytest --cov=src --cov-report=html tests/
# Opens htmlcov/index.html
```

**Coverage patterns observed:**
- High coverage on pipeline modules (~95%+)
- Core business logic fully tested
- Error paths and edge cases included
- Integration tests verify end-to-end flows

## Test Types

**Unit Tests:**
- Scope: Single function or class method
- Examples: `test_market_response_validates_complete_data()`, `test_empty_positions()`
- Mocks external dependencies, tests logic in isolation
- Assertions verify outputs and side effects (db writes, log calls)
- Test count: Majority of suite (~70%)

**Integration Tests:**
- Scope: Multiple components working together
- Examples: `test_ingest_active_markets_persists()` (IngestionPipeline + DB)
- Use in-memory SQLite, mock only external APIs
- Verify end-to-end data flow
- Test count: ~20-25% of suite

**E2E Tests:**
- Not detected in suite
- No integration with live APIs or real databases
- All tests use mocks and in-memory databases

## Common Patterns

**Async Testing:**

Not used. All code is synchronous. No asyncio or async fixtures.

**Error Testing:**

```python
def test_retry_exhaustion_raises_error(self, mock_clob_client):
    """Test that retry exhaustion raises RetryError."""
    mock_instance = mock_clob_client.return_value
    mock_instance.get_simplified_markets.side_effect = ConnectionError("Network down")

    client = PolymarketClient()

    with pytest.raises(RetryError):
        client.get_markets()
```

**Validation Error Testing:**

```python
def test_market_response_requires_mandatory_fields(self):
    """Test that mandatory fields raise ValidationError when missing."""
    data = {"question": "Missing condition_id"}

    with pytest.raises(ValidationError) as exc_info:
        MarketResponse(**data)

    errors = exc_info.value.errors()
    missing_fields = {error["loc"][0] for error in errors}
    assert "condition_id" in missing_fields
```

**Decimal Precision Testing:**

```python
def test_trade_response_decimal_precision(self):
    """Test that Decimal values preserve precision (not float)."""
    data = {
        "id": "trade-123",
        "size": "125.500000",
        "price": "0.650000",
        ...
    }

    trade = TradeResponse(**data)

    assert isinstance(trade.size, Decimal)
    assert isinstance(trade.price, Decimal)
    assert trade.size == Decimal("125.500000")  # Exact match, no float rounding
```

**Pagination Testing:**

```python
def test_get_markets_paginates(self, mock_clob_client):
    """Test that get_markets handles pagination correctly."""
    page1 = {"data": [...], "next_cursor": "cursor_page2"}
    page2 = {"data": [...], "next_cursor": "LTE"}  # Terminator

    mock_instance = mock_clob_client.return_value
    mock_instance.get_simplified_markets.side_effect = [page1, page2]

    client = PolymarketClient()
    markets = client.get_markets()

    assert len(markets) == 2
    mock_instance.get_simplified_markets.assert_called()
```

## Test Fixtures - Repository Patterns

**In-memory DB fixture** (standard across all tests):
```python
@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory
```

**Session fixture with cleanup:**
```python
@pytest.fixture
def session(engine):
    """Create database session for testing."""
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

**Mocked client fixture:**
```python
@pytest.fixture
def mock_client():
    """Create mock PolymarketClient."""
    return Mock()
```

**Category filter fixture:**
```python
@pytest.fixture
def category_filter():
    """Create CategoryFilter configured for eSports."""
    return CategoryFilter(detail_categories=["eSports", "Gaming"])
```

**Market/Trader/Position fixtures:**
```python
@pytest.fixture
def sample_market(session):
    """Create a sample market for testing."""
    market = Market(
        condition_id="0xmarket1",
        question="Will Team A beat Team B?",
        category="eSports",
        active=True,
    )
    session.add(market)
    session.commit()
    return market

@pytest.fixture
def sample_trader(session):
    """Create a sample expert trader."""
    trader = Trader(address="0xexpert1")
    session.add(trader)
    session.commit()
    return trader
```

## Test Execution Summary

**Test statistics:**
- Total test files: 30+
- Total test methods: 362+
- Total LOC in tests: 11,266 lines
- Largest test suites:
  - `test_signal_pipeline.py`: 868 lines
  - `test_scoring.py`: 672 lines
  - `test_evaluation_queries.py`: 575 lines
  - `test_ingest.py`: 518 lines

**Key test coverage areas:**
1. **API validation:** `test_api_models.py`, `test_api_client.py` - Pydantic models, pagination, retry logic
2. **Data ingestion:** `test_ingest.py`, `test_classify_pipeline.py` - Market/trader ingestion, classification
3. **Business logic:** `test_scoring.py`, `test_signal_detector.py` - Expertise scoring, signal detection
4. **Database queries:** `test_queries.py`, `test_evaluation_queries.py` - Query functions with filters
5. **Integration:** `test_alert_delivery.py`, `test_signal_pipeline.py` - End-to-end pipeline flows

---

*Testing analysis: 2026-02-12*
