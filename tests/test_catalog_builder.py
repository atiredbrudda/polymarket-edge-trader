"""Tests for token catalog builder.

Tests the TokenCatalogBuilder class with mocked Gamma API responses.
Verifies:
- Catalog table is populated from Gamma API events
- All-categories mode fetches events from all categories
- eSports-only mode filters by tag_id=64
- Token extraction from clobTokenIds works correctly
- Build is idempotent (clears and rebuilds)
- Category extraction from events works
"""

import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, TokenCatalog
from src.catalog.builder import TokenCatalogBuilder


# Mock Gamma API events for testing
MOCK_ESPORTS_EVENT = {
    "id": "event_1",
    "title": "CS2 Tournament",
    "category": "eSports",
    "tags": [{"name": "eSports", "slug": "esports"}],
    "markets": [
        {
            "conditionId": "cond_esports_123",
            "question": "Will NaVi win the CS2 tournament?",
            "clobTokenIds": ["111111", "222222"],
        }
    ],
}

MOCK_SPORTS_EVENT = {
    "id": "event_2",
    "title": "NBA Game",
    "category": "Sports",
    "tags": [{"name": "Sports", "slug": "sports"}],
    "markets": [
        {
            "conditionId": "cond_sports_456",
            "question": "Will the Lakers win?",
            "clobTokenIds": ["333333", "444444"],
        }
    ],
}

MOCK_POLITICS_EVENT = {
    "id": "event_3",
    "title": "US Election",
    "category": "Politics",
    "tags": [{"name": "Politics", "slug": "politics"}],
    "markets": [
        {
            "conditionId": "cond_politics_789",
            "question": "Will Trump win 2024?",
            "clobTokenIds": ["555555"],
        }
    ],
}

MOCK_EVENT_WITH_ZERO_TOKEN = {
    "id": "event_4",
    "title": "Test Market",
    "category": "Crypto",
    "markets": [
        {
            "conditionId": "cond_test",
            "question": "Test question",
            "clobTokenIds": ["0", "valid_token_999"],
        }
    ],
}


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


def mock_fetch_events_esports_only(active):
    """Mock fetch that returns only eSports events."""
    if active:
        return [MOCK_ESPORTS_EVENT]
    return []


def mock_fetch_events_all_categories(active):
    """Mock fetch that returns events from all categories."""
    if active:
        return [MOCK_ESPORTS_EVENT, MOCK_SPORTS_EVENT, MOCK_POLITICS_EVENT]
    return [MOCK_EVENT_WITH_ZERO_TOKEN]


def test_builder_init_default():
    """Test builder initializes with all-categories mode by default."""
    builder = TokenCatalogBuilder()
    assert builder.esports_only is False


def test_builder_init_esports_only():
    """Test builder can be initialized in eSports-only mode."""
    builder = TokenCatalogBuilder(esports_only=True)
    assert builder.esports_only is True


def test_is_built_returns_false_when_empty(in_memory_db):
    """Test that is_built() returns False when catalog is empty."""
    builder = TokenCatalogBuilder()
    assert builder.is_built(in_memory_db) is False


def test_is_built_returns_true_after_build(in_memory_db):
    """Test that is_built() returns True after building catalog."""
    builder = TokenCatalogBuilder(esports_only=True)

    with patch.object(
        builder, "_fetch_all_events", side_effect=mock_fetch_events_esports_only
    ):
        builder.build(in_memory_db)

    assert builder.is_built(in_memory_db) is True


def test_build_esports_only_mode(in_memory_db):
    """Test that eSports-only mode only fetches eSports events."""
    builder = TokenCatalogBuilder(esports_only=True)

    with patch.object(
        builder, "_fetch_all_events", side_effect=mock_fetch_events_esports_only
    ):
        count = builder.build(in_memory_db)

    assert count == 2  # Two tokens from MOCK_ESPORTS_EVENT

    tokens = in_memory_db.query(TokenCatalog).all()
    assert len(tokens) == 2

    for token in tokens:
        assert token.niche_slug == "esports"
        assert token.condition_id == "cond_esports_123"


def test_build_all_categories_mode(in_memory_db):
    """Test that all-categories mode fetches events from all categories."""
    builder = TokenCatalogBuilder(esports_only=False)

    with patch.object(
        builder, "_fetch_all_events", side_effect=mock_fetch_events_all_categories
    ):
        count = builder.build(in_memory_db)

    assert (
        count == 6
    )  # 2 (esports) + 2 (sports) + 1 (politics) + 1 (valid_token_999 from closed)

    tokens = in_memory_db.query(TokenCatalog).all()
    assert len(tokens) == 6

    # Check category distribution
    categories = {t.niche_slug for t in tokens}
    assert "esports" in categories
    assert "sports" in categories
    assert "politics" in categories
    assert "crypto" in categories


def test_build_extracts_category_from_tags(in_memory_db):
    """Test that category is extracted from event tags."""
    builder = TokenCatalogBuilder()

    with patch.object(
        builder, "_fetch_all_events", side_effect=mock_fetch_events_all_categories
    ):
        builder.build(in_memory_db)

    tokens = in_memory_db.query(TokenCatalog).all()

    # Find esports token
    esports_token = next(
        (t for t in tokens if t.condition_id == "cond_esports_123"), None
    )
    assert esports_token is not None
    assert esports_token.niche_slug == "esports"


def test_build_extracts_category_from_category_field(in_memory_db):
    """Test that category falls back to category field if tags missing."""
    # Event with no tags but has category field
    event_no_tags = {
        "id": "event_no_tags",
        "category": "Finance",
        "markets": [
            {
                "conditionId": "cond_finance",
                "question": "Will BTC hit 100k?",
                "clobTokenIds": ["token_finance"],
            }
        ],
    }

    def mock_fetch_no_tags(active):
        return [event_no_tags] if active else []

    builder = TokenCatalogBuilder()

    with patch.object(builder, "_fetch_all_events", side_effect=mock_fetch_no_tags):
        builder.build(in_memory_db)

    token = in_memory_db.query(TokenCatalog).first()
    assert token is not None
    assert token.niche_slug == "finance"


def test_build_skips_zero_token_id(in_memory_db):
    """Test that token_id '0' is not inserted."""
    builder = TokenCatalogBuilder()

    def mock_fetch_with_zero(active):
        return [MOCK_EVENT_WITH_ZERO_TOKEN] if active else []

    with patch.object(builder, "_fetch_all_events", side_effect=mock_fetch_with_zero):
        builder.build(in_memory_db)

    tokens = in_memory_db.query(TokenCatalog).all()
    token_ids = {t.token_id for t in tokens}

    assert "0" not in token_ids
    assert "valid_token_999" in token_ids


def test_build_is_idempotent(in_memory_db):
    """Test that calling build() twice clears and rebuilds (not doubled)."""
    builder = TokenCatalogBuilder(esports_only=True)

    with patch.object(
        builder, "_fetch_all_events", side_effect=mock_fetch_events_esports_only
    ):
        count1 = builder.build(in_memory_db)
        count2 = builder.build(in_memory_db)

    assert count1 == 2
    assert count2 == 2

    tokens = in_memory_db.query(TokenCatalog).all()
    assert len(tokens) == 2


def test_build_handles_empty_clob_token_ids(in_memory_db):
    """Test that markets with empty clobTokenIds are skipped."""
    event_empty_tokens = {
        "id": "event_empty",
        "category": "Test",
        "markets": [
            {
                "conditionId": "cond_empty",
                "question": "Test",
                "clobTokenIds": [],
            }
        ],
    }

    def mock_fetch_empty(active):
        return [event_empty_tokens] if active else []

    builder = TokenCatalogBuilder()

    with patch.object(builder, "_fetch_all_events", side_effect=mock_fetch_empty):
        count = builder.build(in_memory_db)

    assert count == 0


def test_build_handles_string_clob_token_ids(in_memory_db):
    """Test that string-formatted clobTokenIds are parsed correctly."""
    event_string_tokens = {
        "id": "event_string",
        "category": "Test",
        "markets": [
            {
                "conditionId": "cond_string",
                "question": "Test",
                "clobTokenIds": '["token_a", "token_b"]',  # JSON string instead of list
            }
        ],
    }

    def mock_fetch_string(active):
        return [event_string_tokens] if active else []

    builder = TokenCatalogBuilder()

    with patch.object(builder, "_fetch_all_events", side_effect=mock_fetch_string):
        count = builder.build(in_memory_db)

    assert count == 2

    tokens = in_memory_db.query(TokenCatalog).all()
    token_ids = {t.token_id for t in tokens}
    assert "token_a" in token_ids
    assert "token_b" in token_ids
