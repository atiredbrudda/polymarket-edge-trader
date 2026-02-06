"""
Tests for classification pipeline.

Tests classification pipeline with in-memory SQLite database.
Verifies taxonomy sync, market classification, and incremental processing.
"""

import pytest
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Market, TaxonomyNode, MarketClassification
from src.pipeline.classify import ClassificationPipeline


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory


@pytest.fixture
def sample_markets(in_memory_db):
    """Create sample markets for testing."""
    with in_memory_db() as session:
        markets = [
            Market(
                condition_id="market1",
                question="NaVi vs FaZe IEM Katowice 2024",
                category="eSports",
                active=True,
            ),
            Market(
                condition_id="market2",
                question="Who will win Dota 2 TI 2024?",
                category="eSports",
                active=True,
            ),
            Market(
                condition_id="market3",
                question="US Presidential Election 2024",
                category="Politics",
                active=True,
            ),
            Market(
                condition_id="market4",
                question="G2 vs T1 League of Legends Worlds 2024",
                category="eSports",
                active=True,
            ),
        ]
        session.add_all(markets)
        session.commit()
    return markets


def test_sync_taxonomy_to_db(in_memory_db):
    """Sync taxonomy from YAML to database."""
    taxonomy_path = Path("data/taxonomy/esports.yaml")
    pipeline = ClassificationPipeline(in_memory_db, taxonomy_path=taxonomy_path)

    # Sync taxonomy
    count = pipeline.sync_taxonomy_to_db()

    # Verify nodes were created
    assert count > 0

    with in_memory_db() as session:
        # Check root node exists
        root = session.query(TaxonomyNode).filter_by(depth=0).first()
        assert root is not None
        assert root.name == "eSports"
        assert root.slug == "esports"
        assert root.parent_id is None

        # Check game nodes exist (depth 1)
        games = session.query(TaxonomyNode).filter_by(depth=1).all()
        assert len(games) > 0

        # Check at least one game has correct parent
        for game in games:
            assert game.parent_id == root.id

        # Check tournament nodes exist (depth 2)
        tournaments = session.query(TaxonomyNode).filter_by(depth=2).all()
        assert len(tournaments) > 0

        # Check team nodes exist (depth 3)
        teams = session.query(TaxonomyNode).filter_by(depth=3).all()
        assert len(teams) > 0


def test_classify_market_esports(in_memory_db, sample_markets):
    """Classify eSports market with team match."""
    taxonomy_path = Path("data/taxonomy/esports.yaml")
    pipeline = ClassificationPipeline(in_memory_db, taxonomy_path=taxonomy_path)

    # Sync taxonomy first
    pipeline.sync_taxonomy_to_db()

    # Get a market
    with in_memory_db() as session:
        market = session.query(Market).filter_by(condition_id="market1").first()

        # Classify it
        classification = pipeline.classify_market(market)

        # Should be classified under CS2
        assert classification.market_id == "market1"
        assert "CS2" in classification.node_path or "cs2" in classification.node_path.lower()
        assert classification.flagged_for_review is False


def test_classify_market_non_esports(in_memory_db, sample_markets):
    """Non-eSports market gets flagged or root classification."""
    taxonomy_path = Path("data/taxonomy/esports.yaml")
    pipeline = ClassificationPipeline(in_memory_db, taxonomy_path=taxonomy_path)

    # Sync taxonomy first
    pipeline.sync_taxonomy_to_db()

    # Get non-eSports market
    with in_memory_db() as session:
        market = session.query(Market).filter_by(condition_id="market3").first()

        # Classify it
        classification = pipeline.classify_market(market)

        # Should be flagged for review or at root level
        assert classification.market_id == "market3"
        # Either flagged or at root depth
        if classification.flagged_for_review:
            assert classification.flagged_for_review is True
        else:
            # Should be at root level if not flagged
            assert classification.node_path == "eSports" or classification.depth == 0


def test_classify_all_markets(in_memory_db, sample_markets):
    """Classify all markets and verify stats."""
    taxonomy_path = Path("data/taxonomy/esports.yaml")
    pipeline = ClassificationPipeline(in_memory_db, taxonomy_path=taxonomy_path)

    # Sync taxonomy first
    pipeline.sync_taxonomy_to_db()

    # Classify all markets
    stats = pipeline.classify_all_markets()

    # Should have classified all 4 markets
    assert stats["classified"] == 4

    # Verify classifications were persisted
    with in_memory_db() as session:
        classifications = session.query(MarketClassification).all()
        assert len(classifications) == 4

        # Each market should have exactly one classification
        market_ids = ["market1", "market2", "market3", "market4"]
        for market_id in market_ids:
            classification = (
                session.query(MarketClassification)
                .filter_by(market_id=market_id)
                .first()
            )
            assert classification is not None


def test_classify_new_markets_incremental(in_memory_db, sample_markets):
    """Only unclassified markets get processed on second run."""
    taxonomy_path = Path("data/taxonomy/esports.yaml")
    pipeline = ClassificationPipeline(in_memory_db, taxonomy_path=taxonomy_path)

    # Sync taxonomy
    pipeline.sync_taxonomy_to_db()

    # First run: classify all markets
    stats1 = pipeline.classify_all_markets()
    assert stats1["classified"] == 4

    # Second run: should classify 0 new markets (all already classified)
    stats2 = pipeline.classify_new_markets()
    assert stats2["classified"] == 0

    # Add a new market
    with in_memory_db() as session:
        new_market = Market(
            condition_id="market5",
            question="Valorant Masters Tokyo - Fnatic vs LOUD",
            category="eSports",
            active=True,
        )
        session.add(new_market)
        session.commit()

    # Third run: should classify only the new market
    stats3 = pipeline.classify_new_markets()
    assert stats3["classified"] == 1

    # Verify total classifications
    with in_memory_db() as session:
        total = session.query(MarketClassification).count()
        assert total == 5
