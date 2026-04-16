"""Tests for ingest-events incremental mode.

Tests:
- INCR-01: First run fetches all markets (closed=None)
- INCR-02: Re-run fetches only active markets (closed=False)
- INCR-03: --full flag forces full fetch regardless of existing data
- INCR-04: Incremental mode upserts harmlessly
"""

from unittest.mock import AsyncMock, patch


def test_first_run_fetches_all_markets(tmp_path):
    """INCR-01: First run with no existing markets fetches everything."""
    from polymarket_analytics.db.schema import init_database
    from polymarket_analytics.commands.ingest_events import _ingest_events_async

    db_path = tmp_path / "test.db"
    db = init_database(db_path)

    # Mock config
    class MockConfig:
        slug = "esports"
        tag_id = 64

    class MockContext:
        obj = {"config": MockConfig()}

    # Mock market data
    mock_markets = [
        {
            "conditionId": "0xmarket1",
            "question": "Test market 1",
            "outcomes": "YES,NO",
            "endDate": "2025-12-31T23:59:59Z",
            "tags": [],
            "active": True,
            "closed": False,
            "category": "esports",
            "events": [],
        },
        {
            "conditionId": "0xmarket2",
            "question": "Test market 2",
            "outcomes": "YES,NO",
            "endDate": "2025-12-31T23:59:59Z",
            "tags": [],
            "active": False,
            "closed": True,
            "category": "esports",
            "events": [],
        },
    ]

    async def run_test():
        with patch(
            "polymarket_analytics.commands.ingest_events.GammaAPIClient.fetch_markets",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = mock_markets
            await _ingest_events_async(MockContext(), str(db_path), full=False)

            # First run fetches active + closed separately (two calls)
            assert mock_fetch.call_count == 2, (
                f"First run should make 2 fetch calls (active + closed), got {mock_fetch.call_count}"
            )
            first_kwargs = mock_fetch.call_args_list[0].kwargs
            second_kwargs = mock_fetch.call_args_list[1].kwargs
            assert first_kwargs.get("closed") is False, (
                f"First call should fetch active (closed=False), got {first_kwargs.get('closed')}"
            )
            assert second_kwargs.get("closed") is True, (
                f"Second call should fetch closed (closed=True), got {second_kwargs.get('closed')}"
            )

    import asyncio

    asyncio.run(run_test())

    # Verify markets were inserted
    market_count = db.execute(
        "SELECT COUNT(*) FROM markets WHERE niche_slug = ?", ["esports"]
    ).fetchone()[0]
    assert market_count == 2


def test_rerun_fetches_active_only(tmp_path):
    """INCR-02: Re-run with existing markets fetches only active."""
    from polymarket_analytics.db.schema import init_database
    from polymarket_analytics.commands.ingest_events import _ingest_events_async

    db_path = tmp_path / "test.db"
    db = init_database(db_path)

    # Pre-populate with existing markets
    db["markets"].insert_all(
        [
            {
                "condition_id": "0xexisting",
                "question": "Existing market",
                "outcome": None,
                "resolved": False,
                "niche_slug": "esports",
                "created_at": "2025-01-01T00:00:00Z",
                "end_date": "2025-12-31T23:59:59Z",
                "category": "esports",
                "active": True,
                "tokens": "[]",
                "event_slug": None,
            },
        ]
    )

    # Mock config
    class MockConfig:
        slug = "esports"
        tag_id = 64

    class MockContext:
        obj = {"config": MockConfig()}

    # Mock new active market data
    mock_active_markets = [
        {
            "conditionId": "0xnewmarket",
            "question": "New active market",
            "outcomes": "YES,NO",
            "endDate": "2025-12-31T23:59:59Z",
            "tags": [],
            "active": True,
            "closed": False,
            "category": "esports",
            "events": [],
        },
    ]

    async def run_test():
        with patch(
            "polymarket_analytics.commands.ingest_events.GammaAPIClient.fetch_markets",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = mock_active_markets
            await _ingest_events_async(MockContext(), str(db_path), full=False)

            # Assert fetch_markets was called with closed=False (active only)
            mock_fetch.assert_called_once()
            call_kwargs = mock_fetch.call_args.kwargs
            assert call_kwargs.get("closed") is False, (
                f"Re-run should fetch active only (closed=False), got closed={call_kwargs.get('closed')}"
            )

    import asyncio

    asyncio.run(run_test())

    # Verify new market was upserted
    market_count = db.execute(
        "SELECT COUNT(*) FROM markets WHERE niche_slug = ?", ["esports"]
    ).fetchone()[0]
    assert market_count == 2  # existing + new


def test_full_flag_forces_full_fetch(tmp_path):
    """INCR-03: --full flag forces full fetch regardless of existing data."""
    from polymarket_analytics.db.schema import init_database
    from polymarket_analytics.commands.ingest_events import _ingest_events_async

    db_path = tmp_path / "test.db"
    db = init_database(db_path)

    # Pre-populate with existing markets
    db["markets"].insert_all(
        [
            {
                "condition_id": "0xexisting",
                "question": "Existing market",
                "outcome": None,
                "resolved": False,
                "niche_slug": "esports",
                "created_at": "2025-01-01T00:00:00Z",
                "end_date": "2025-12-31T23:59:59Z",
                "category": "esports",
                "active": True,
                "tokens": "[]",
                "event_slug": None,
            },
        ]
    )

    # Mock config
    class MockConfig:
        slug = "esports"
        tag_id = 64

    class MockContext:
        obj = {"config": MockConfig()}

    # Mock full market data (active + closed)
    mock_full_markets = [
        {
            "conditionId": "0xactive",
            "question": "Active market",
            "outcomes": "YES,NO",
            "endDate": "2025-12-31T23:59:59Z",
            "tags": [],
            "active": True,
            "closed": False,
            "category": "esports",
            "events": [],
        },
        {
            "conditionId": "0xclosed",
            "question": "Closed market",
            "outcomes": "YES,NO",
            "endDate": "2025-01-01T23:59:59Z",
            "tags": [],
            "active": False,
            "closed": True,
            "result": "YES",
            "category": "esports",
            "events": [],
        },
    ]

    async def run_test():
        with patch(
            "polymarket_analytics.commands.ingest_events.GammaAPIClient.fetch_markets",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = mock_full_markets
            # Pass full=True to force full fetch
            await _ingest_events_async(MockContext(), str(db_path), full=True)

            # --full fetches active + closed separately (two calls)
            assert mock_fetch.call_count == 2, (
                f"--full should make 2 fetch calls (active + closed), got {mock_fetch.call_count}"
            )
            first_kwargs = mock_fetch.call_args_list[0].kwargs
            second_kwargs = mock_fetch.call_args_list[1].kwargs
            assert first_kwargs.get("closed") is False, (
                f"First call should fetch active (closed=False), got {first_kwargs.get('closed')}"
            )
            assert second_kwargs.get("closed") is True, (
                f"Second call should fetch closed (closed=True), got {second_kwargs.get('closed')}"
            )

    import asyncio

    asyncio.run(run_test())


def test_incremental_upsert_harmlessly(tmp_path):
    """INCR-04: Incremental mode upserts existing markets without duplicates."""
    from polymarket_analytics.db.schema import init_database
    from polymarket_analytics.commands.ingest_events import _ingest_events_async

    db_path = tmp_path / "test.db"
    db = init_database(db_path)

    # Pre-populate with existing market
    db["markets"].insert_all(
        [
            {
                "condition_id": "0xsame",
                "question": "Original question",
                "outcome": None,
                "resolved": False,
                "niche_slug": "esports",
                "created_at": "2025-01-01T00:00:00Z",
                "end_date": "2025-12-31T23:59:59Z",
                "category": "esports",
                "active": True,
                "tokens": "[]",
                "event_slug": None,
            },
        ]
    )

    # Mock config
    class MockConfig:
        slug = "esports"
        tag_id = 64

    class MockContext:
        obj = {"config": MockConfig()}

    # Mock market with updated data
    mock_updated_markets = [
        {
            "conditionId": "0xsame",
            "question": "Updated question text",
            "outcomes": "YES,NO",
            "endDate": "2025-12-31T23:59:59Z",
            "tags": ["updated-tag"],
            "active": True,
            "closed": False,
            "category": "esports",
            "events": [{"slug": "updated-slug", "title": "Updated Title"}],
        },
    ]

    async def run_test():
        with patch(
            "polymarket_analytics.commands.ingest_events.GammaAPIClient.fetch_markets",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = mock_updated_markets
            await _ingest_events_async(MockContext(), str(db_path), full=False)

    import asyncio

    asyncio.run(run_test())

    # Verify upsert updated the row, not created duplicate
    market_count = db.execute(
        "SELECT COUNT(*) FROM markets WHERE niche_slug = ?", ["esports"]
    ).fetchone()[0]
    assert market_count == 1, "Should be 1 market (upsert), not duplicate"

    # Verify data was updated
    row = db["markets"].get("0xsame")
    assert row["question"] == "Updated question text"
    assert row["event_slug"] == "updated-slug"
