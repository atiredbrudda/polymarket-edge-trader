"""Tests for classify-tokens DB-first token catalog build.

Tests:
- CTDB-01: classify_tokens reads from DB instead of API
- CTDB-02: classify_tokens fails gracefully if markets table is empty
- CTDB-03: classify_tokens handles NULL clob_token_ids with synthetic fallback
"""

import json
import pytest


def test_classify_tokens_reads_from_db_not_api(tmp_path):
    """CTDB-01: classify_tokens builds catalog from DB without Gamma API calls."""
    from polymarket_analytics.db.schema import init_database
    from polymarket_analytics.commands.classify_tokens import _classify_tokens_from_db
    import polymarket_analytics.commands.classify_tokens as ct_module

    db_path = tmp_path / "test.db"
    db = init_database(db_path)

    # Insert test markets with clob_token_ids
    db["markets"].insert(
        {
            "condition_id": "0xmarket1",
            "question": "Test market 1",
            "outcome": None,
            "resolved": False,
            "niche_slug": "esports",
            "end_date": "2025-12-31T23:59:59Z",
            "category": "esports",
            "active": True,
            "tokens": json.dumps([]),
            "event_slug": "test-event-1",
            "event_title": "Test Event",
            "clob_token_ids": json.dumps(["token_yes_1", "token_no_1"]),
        }
    )

    # Mock config
    class MockConfig:
        slug = "esports"
        tag_id = 64

    class MockContext:
        obj = {"config": MockConfig()}

    # Verify GammaAPIClient is NOT imported (no API calls possible)
    assert not hasattr(ct_module, "GammaAPIClient"), (
        "GammaAPIClient should not be imported"
    )

    # Run classify_tokens
    _classify_tokens_from_db(MockContext(), str(db_path))

    # Verify token_catalog was populated
    catalog_count = db.execute("SELECT COUNT(*) FROM token_catalog").fetchone()[0]
    assert catalog_count == 2  # Two tokens (YES and NO) for one market

    # Verify token IDs match clob_token_ids from DB
    tokens = [
        row[0] for row in db.execute("SELECT token_id FROM token_catalog").fetchall()
    ]
    assert "token_yes_1" in tokens
    assert "token_no_1" in tokens


def test_classify_tokens_fails_without_markets(tmp_path):
    """CTDB-02: classify_tokens fails with helpful error if markets table is empty."""
    from polymarket_analytics.commands.classify_tokens import _classify_tokens_from_db
    import click

    db_path = tmp_path / "test.db"

    # Mock config
    class MockConfig:
        slug = "esports"
        tag_id = 64

    class MockContext:
        obj = {"config": MockConfig()}

    # Run classify_tokens on empty markets table
    with pytest.raises(click.ClickException) as exc_info:
        _classify_tokens_from_db(MockContext(), str(db_path))

    # Verify error message tells user to run ingest-events first
    assert "Run 'ingest-events' command first" in str(exc_info.value)


def test_classify_tokens_handles_null_clob_token_ids(tmp_path, capsys):
    """CTDB-03: classify_tokens uses synthetic IDs when clob_token_ids is NULL."""
    from polymarket_analytics.db.schema import init_database
    from polymarket_analytics.commands.classify_tokens import _classify_tokens_from_db

    db_path = tmp_path / "test.db"
    db = init_database(db_path)

    # Insert test market with NULL clob_token_ids
    db["markets"].insert(
        {
            "condition_id": "0xmarket_null",
            "question": "Test market with NULL tokens",
            "outcome": None,
            "resolved": False,
            "niche_slug": "esports",
            "end_date": "2025-12-31T23:59:59Z",
            "category": "esports",
            "active": True,
            "tokens": json.dumps([]),
            "event_slug": "test-event-null",
            "event_title": "Test Event NULL",
            "clob_token_ids": None,  # NULL clob_token_ids
        }
    )

    # Mock config
    class MockConfig:
        slug = "esports"
        tag_id = 64

    class MockContext:
        obj = {"config": MockConfig()}

    # Run classify_tokens - should use synthetic fallback
    _classify_tokens_from_db(MockContext(), str(db_path))

    # Capture output to verify warning was printed
    captured = capsys.readouterr()

    # Verify synthetic token IDs were created
    tokens = [
        row[0]
        for row in db.execute(
            "SELECT token_id FROM token_catalog WHERE condition_id = '0xmarket_null'"
        ).fetchall()
    ]
    assert len(tokens) == 2
    assert "0xmarket_null:0" in tokens
    assert "0xmarket_null:1" in tokens

    # Verify warning was printed (to stderr)
    assert "Warning: No clobTokenIds" in captured.err
