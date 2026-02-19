"""Tests for token catalog builder.

Tests the TokenCatalogBuilder class with mocked DuckDB scan and in-memory database.
Verifies:
- Catalog table is populated correctly
- Esports markets are classified with niche_slug
- Non-esports markets have niche_slug=NULL
- Build is idempotent (INSERT OR IGNORE)
- Zero token_id is skipped
"""

import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, TokenCatalog
from src.catalog.builder import TokenCatalogBuilder
from src.taxonomy.classifier import ClassificationResult


ESPORTS_ROWS = [
    ("cond_abc", "Will NaVi win IEM Katowice CS:GO 2024?", ["111111", "222222"]),
]

NON_ESPORTS_ROWS = [
    ("cond_xyz", "Will the US election happen in 2024?", ["333333"]),
]

MIXED_ROWS = [
    ("cond_esports", "Will FaZe win the CS2 tournament?", ["token_a", "token_b"]),
    ("cond_politics", "Will Trump win 2024?", ["token_c"]),
    ("cond_zero", "Some market", ["0", "token_valid"]),
]


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def mock_matcher():
    """Create a mock PatternMatcher that classifies CS:GO/CS2 questions as esports."""
    matcher = MagicMock()

    def classify_side_effect(question):
        if (
            "CS:GO" in question
            or "CS2" in question
            or "IEM Katowice" in question
            or "FaZe" in question
        ):
            return ClassificationResult(
                node_path="eSports.CS2.IEM Katowice",
                depth=2,
                game="CS2",
                tournament="IEM Katowice",
                team=None,
                market_type="match",
                matched_pattern="CS:GO|CS2",
                flagged_for_review=False,
            )
        return None

    matcher.classify.side_effect = classify_side_effect
    return matcher


def test_is_built_returns_false_when_empty(in_memory_db):
    """Test that is_built() returns False when catalog is empty."""
    builder = TokenCatalogBuilder("dummy/path", "config/taxonomy.yaml")
    assert builder.is_built(in_memory_db) is False


def test_is_built_returns_true_after_build(in_memory_db, mock_matcher):
    """Test that is_built() returns True after building catalog."""
    builder = TokenCatalogBuilder("dummy/path", "config/taxonomy.yaml")

    with patch.object(builder, "_scan_parquet", return_value=ESPORTS_ROWS):
        with patch("src.catalog.builder.PatternMatcher", return_value=mock_matcher):
            with patch("src.catalog.builder.load_taxonomy"):
                builder.build(in_memory_db)

    assert builder.is_built(in_memory_db) is True


def test_build_classifies_esports_market(in_memory_db, mock_matcher):
    """Test that esports market is classified with niche_slug='esports'."""
    builder = TokenCatalogBuilder("dummy/path", "config/taxonomy.yaml")

    with patch.object(builder, "_scan_parquet", return_value=ESPORTS_ROWS):
        with patch("src.catalog.builder.PatternMatcher", return_value=mock_matcher):
            with patch("src.catalog.builder.load_taxonomy"):
                count = builder.build(in_memory_db)

    assert count == 2

    tokens = in_memory_db.query(TokenCatalog).all()
    assert len(tokens) == 2

    for token in tokens:
        assert token.niche_slug == "esports"
        assert token.node_path is not None
        assert token.depth is not None
        assert token.condition_id == "cond_abc"


def test_build_classifies_non_esports_market(in_memory_db, mock_matcher):
    """Test that non-esports market has niche_slug=None."""
    builder = TokenCatalogBuilder("dummy/path", "config/taxonomy.yaml")

    with patch.object(builder, "_scan_parquet", return_value=NON_ESPORTS_ROWS):
        with patch("src.catalog.builder.PatternMatcher", return_value=mock_matcher):
            with patch("src.catalog.builder.load_taxonomy"):
                count = builder.build(in_memory_db)

    assert count == 1

    token = in_memory_db.query(TokenCatalog).first()
    assert token.niche_slug is None
    assert token.node_path is None
    assert token.depth is None


def test_build_is_idempotent(in_memory_db, mock_matcher):
    """Test that calling build() twice produces same row count (not doubled)."""
    builder = TokenCatalogBuilder("dummy/path", "config/taxonomy.yaml")

    with patch.object(builder, "_scan_parquet", return_value=ESPORTS_ROWS):
        with patch("src.catalog.builder.PatternMatcher", return_value=mock_matcher):
            with patch("src.catalog.builder.load_taxonomy"):
                count1 = builder.build(in_memory_db)
                count2 = builder.build(in_memory_db)

    assert count1 == 2
    assert count2 == 2

    tokens = in_memory_db.query(TokenCatalog).all()
    assert len(tokens) == 2


def test_build_skips_zero_token_id(in_memory_db, mock_matcher):
    """Test that token_id '0' is not inserted."""
    builder = TokenCatalogBuilder("dummy/path", "config/taxonomy.yaml")

    with patch.object(builder, "_scan_parquet", return_value=MIXED_ROWS):
        with patch("src.catalog.builder.PatternMatcher", return_value=mock_matcher):
            with patch("src.catalog.builder.load_taxonomy"):
                builder.build(in_memory_db)

    tokens = in_memory_db.query(TokenCatalog).all()
    token_ids = {t.token_id for t in tokens}

    assert "0" not in token_ids
    assert "token_valid" in token_ids
