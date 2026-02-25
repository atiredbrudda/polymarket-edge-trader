"""Tests for Gamma token classification from event tags."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.gamma.classification import (
    _extract_classification,
    classify_tokens_from_gamma_events,
)


class TestExtractClassification:
    """Unit tests for _extract_classification function."""

    def test_empty_tags_returns_none(self):
        """Empty tags list returns (None, None)."""
        result = _extract_classification([])
        assert result == (None, None)

    def test_esports_only_returns_none(self):
        """Tags with only 'esports' root returns (None, None)."""
        tags = [{"id": 64, "slug": "esports"}]
        result = _extract_classification(tags)
        assert result == (None, None)

    def test_game_only(self):
        """Tags with esports and game returns (node_path, depth=1)."""
        tags = [{"slug": "esports"}, {"slug": "cs2"}]
        result = _extract_classification(tags)
        assert result == ("esports/cs2", 1)

    def test_game_and_tournament(self):
        """Tags with game and tournament returns depth=2."""
        tags = [{"slug": "esports"}, {"slug": "cs2"}, {"slug": "iem-katowice-2024"}]
        result = _extract_classification(tags)
        assert result == ("esports/cs2/iem-katowice-2024", 2)

    def test_game_tournament_team(self):
        """Tags with game, tournament, team returns depth=3."""
        tags = [
            {"slug": "esports"},
            {"slug": "cs2"},
            {"slug": "iem-katowice-2024"},
            {"slug": "navi"},
        ]
        result = _extract_classification(tags)
        assert result == ("esports/cs2/iem-katowice-2024/navi", 3)

    def test_depth_capped_at_3(self):
        """Depth is capped at 3 even with more tags."""
        tags = [
            {"slug": "esports"},
            {"slug": "cs2"},
            {"slug": "iem-katowice-2024"},
            {"slug": "navi"},
            {"slug": "extra_tag"},
        ]
        result = _extract_classification(tags)
        assert result == ("esports/cs2/iem-katowice-2024/navi", 3)

    def test_missing_slug_field_skipped(self):
        """Tags without 'slug' key are skipped."""
        tags = [{"slug": "esports"}, {"id": 123}, {"slug": "cs2"}]
        result = _extract_classification(tags)
        assert result == ("esports/cs2", 1)

    def test_empty_slug_skipped(self):
        """Tags with empty slug string are filtered out."""
        tags = [{"slug": "esports"}, {"slug": ""}, {"slug": "cs2"}]
        result = _extract_classification(tags)
        assert result == ("esports/cs2", 1)


class TestClassifyTokensFromGammaEvents:
    """Mock-based tests for classify_tokens_from_gamma_events."""

    def test_classifies_single_event_two_tokens(self):
        """Event with cs2 tag and 2 tokens results in 2 classified."""
        mock_session = MagicMock()

        mock_event = MagicMock()
        mock_event.event_id = "evt_1"
        mock_event.tags = json.dumps([{"slug": "esports"}, {"slug": "cs2"}])
        mock_event.clob_token_ids = json.dumps(["tok_a", "tok_b"])

        mock_session.query.return_value.all.return_value = [mock_event]

        result = classify_tokens_from_gamma_events(mock_session)

        assert result["classified"] == 2
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_skips_event_with_no_tags(self):
        """Event with tags=None is counted as skipped_no_tags."""
        mock_session = MagicMock()

        mock_event = MagicMock()
        mock_event.event_id = "evt_1"
        mock_event.tags = None
        mock_event.clob_token_ids = json.dumps(["tok_a"])

        mock_session.query.return_value.all.return_value = [mock_event]

        result = classify_tokens_from_gamma_events(mock_session)

        assert result["skipped_no_tags"] == 1
        assert result["classified"] == 0

    def test_skips_event_with_esports_only_tags(self):
        """Root-only tags (no sub-classification) counted as skipped_shallow."""
        mock_session = MagicMock()

        mock_event = MagicMock()
        mock_event.event_id = "evt_1"
        mock_event.tags = json.dumps([{"slug": "esports"}])
        mock_event.clob_token_ids = json.dumps(["tok_a"])

        mock_session.query.return_value.all.return_value = [mock_event]

        result = classify_tokens_from_gamma_events(mock_session)

        assert result["skipped_shallow"] == 1
        assert result["classified"] == 0

    def test_skips_event_with_no_token_ids(self):
        """Valid tags but clob_token_ids=None counts as skipped_no_tokens."""
        mock_session = MagicMock()

        mock_event = MagicMock()
        mock_event.event_id = "evt_1"
        mock_event.tags = json.dumps([{"slug": "esports"}, {"slug": "cs2"}])
        mock_event.clob_token_ids = None

        mock_session.query.return_value.all.return_value = [mock_event]

        result = classify_tokens_from_gamma_events(mock_session)

        assert result["skipped_no_tokens"] == 1
        assert result["classified"] == 0

    def test_skips_event_with_invalid_tags_json(self):
        """Invalid tags JSON string counts as skipped_no_tags."""
        mock_session = MagicMock()

        mock_event = MagicMock()
        mock_event.event_id = "evt_1"
        mock_event.tags = "not json"
        mock_event.clob_token_ids = json.dumps(["tok_a"])

        mock_session.query.return_value.all.return_value = [mock_event]

        result = classify_tokens_from_gamma_events(mock_session)

        assert result["skipped_no_tags"] == 1

    def test_commits_session(self):
        """Session is committed after updates."""
        mock_session = MagicMock()

        mock_event = MagicMock()
        mock_event.event_id = "evt_1"
        mock_event.tags = json.dumps([{"slug": "esports"}, {"slug": "cs2"}])
        mock_event.clob_token_ids = json.dumps(["tok_a"])

        mock_session.query.return_value.all.return_value = [mock_event]

        classify_tokens_from_gamma_events(mock_session)

        mock_session.commit.assert_called_once()

    def test_executes_bulk_update(self):
        """Bulk UPDATE is executed via session.execute with list of dicts."""
        mock_session = MagicMock()

        mock_event = MagicMock()
        mock_event.event_id = "evt_1"
        mock_event.tags = json.dumps([{"slug": "esports"}, {"slug": "cs2"}])
        mock_event.clob_token_ids = json.dumps(["tok_a", "tok_b"])

        mock_session.query.return_value.all.return_value = [mock_event]

        classify_tokens_from_gamma_events(mock_session)

        mock_session.execute.assert_called_once()
        call_args = mock_session.execute.call_args
        assert "UPDATE token_catalog" in call_args[0][0].text


class TestClassifyTokensIdempotency:
    """In-memory SQLite tests for idempotency."""

    def test_idempotent_re_run(self):
        """Running classification twice produces same result."""
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        from src.db.models import Base, GammaEvent, TokenCatalog

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            event = GammaEvent(
                event_id="evt_1",
                tags=json.dumps([{"slug": "esports"}, {"slug": "cs2"}]),
                clob_token_ids=json.dumps(["tok_a"]),
            )
            session.add(event)

            catalog_entry = TokenCatalog(
                token_id="tok_a",
                condition_id="cond_1",
                question="Test?",
                niche_slug="esports",
            )
            session.add(catalog_entry)
            session.commit()

            result1 = classify_tokens_from_gamma_events(session)

            session.expire_all()

            refreshed = session.query(TokenCatalog).filter_by(token_id="tok_a").first()
            assert refreshed.node_path == "esports/cs2"
            assert refreshed.depth == 1

            result2 = classify_tokens_from_gamma_events(session)

            assert result1["classified"] == result2["classified"]
        finally:
            session.close()
