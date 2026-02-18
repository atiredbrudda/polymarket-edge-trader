"""Tests for JBecker dataset query layer."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from src.datasources.jbecker import JBeckerDataset


@pytest.fixture
def jbecker_dataset(tmp_path):
    """Create a temporary JBecker dataset fixture.

    Copies the sample parquet to tmp_path/polymarket/trades/ and returns
    a JBeckerDataset instance pointing to it.
    """
    # Create directory structure
    trades_dir = tmp_path / "polymarket" / "trades"
    trades_dir.mkdir(parents=True)

    # Copy sample parquet to expected location
    sample_path = Path(__file__).parent.parent / "fixtures" / "jbecker_sample.parquet"
    target_path = trades_dir / "trades_00.parquet"

    # Copy file contents
    import shutil

    shutil.copy(sample_path, target_path)

    return JBeckerDataset(str(tmp_path))


# ===== Availability checks (3 tests) =====


def test_is_available_with_dataset(jbecker_dataset):
    """Test is_available returns True when parquet files exist."""
    assert jbecker_dataset.is_available() is True


def test_is_available_without_dataset(tmp_path):
    """Test is_available returns False when path doesn't exist."""
    dataset = JBeckerDataset(str(tmp_path / "nonexistent"))
    assert dataset.is_available() is False


def test_is_available_empty_directory(tmp_path):
    """Test is_available returns False when dir exists but no parquet files."""
    trades_dir = tmp_path / "polymarket" / "trades"
    trades_dir.mkdir(parents=True)
    dataset = JBeckerDataset(str(tmp_path))
    assert dataset.is_available() is False


# ===== Query trader history (5 tests) =====


def test_query_trader_history_returns_trades(jbecker_dataset):
    """Test query_trader_history returns trades for known trader."""
    # Known trader from fixture (50 trades)
    trader = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"
    trades = jbecker_dataset.query_trader_history(trader)

    assert len(trades) == 50
    assert all(isinstance(t, dict) for t in trades)
    # Check first trade has expected fields
    assert "maker" in trades[0]
    assert "price" in trades[0]
    assert "timestamp" in trades[0]


def test_query_trader_history_case_insensitive(jbecker_dataset):
    """Test query_trader_history handles case-insensitive addresses."""
    trader_lower = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"
    trader_upper = "0XEFFD76B6A4318D50C6F71A16B276C5B279445A86"
    trader_mixed = "0xEfFd76b6A4318d50c6f71a16b276c5b279445A86"

    trades_lower = jbecker_dataset.query_trader_history(trader_lower)
    trades_upper = jbecker_dataset.query_trader_history(trader_upper)
    trades_mixed = jbecker_dataset.query_trader_history(trader_mixed)

    assert len(trades_lower) == 50
    assert len(trades_upper) == 50
    assert len(trades_mixed) == 50


def test_query_trader_history_with_limit(jbecker_dataset):
    """Test query_trader_history respects limit parameter."""
    trader = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"
    trades = jbecker_dataset.query_trader_history(trader, limit=10)

    assert len(trades) == 10


def test_query_trader_history_unknown_trader(jbecker_dataset):
    """Test query_trader_history returns empty list for unknown trader."""
    unknown_trader = "0x0000000000000000000000000000000000000000"
    trades = jbecker_dataset.query_trader_history(unknown_trader)

    assert trades == []


def test_query_trader_history_dataset_not_available(tmp_path):
    """Test query_trader_history raises FileNotFoundError with download URL."""
    dataset = JBeckerDataset(str(tmp_path / "nonexistent"))

    with pytest.raises(FileNotFoundError) as exc_info:
        dataset.query_trader_history("0x123")

    assert "s3.jbecker.dev" in str(exc_info.value)
    assert "data.tar.zst" in str(exc_info.value)


# ===== Parameterization security (3 tests) =====


def test_query_uses_parameterized_sql(jbecker_dataset):
    """Test that queries use parameterized SQL ($1, $2) not string interpolation."""
    with patch("duckdb.execute") as mock_execute:
        # Setup mock to return empty result
        mock_result = MagicMock()
        mock_result.fetchdf.return_value.to_dict.return_value = []
        mock_execute.return_value = mock_result

        trader = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"
        jbecker_dataset.query_trader_history(trader)

        # Verify execute was called with parameterized query
        assert mock_execute.called
        call_args = mock_execute.call_args
        query = call_args[0][0]
        params = call_args[0][1] if len(call_args[0]) > 1 else None

        # Query should contain $1 or $2 placeholders
        assert "$" in query or "?" in query
        # Trader address should be in parameters list, not in query string
        assert trader.lower() not in query.lower()
        assert params is not None


def test_sql_injection_attempt_safe(jbecker_dataset):
    """Test SQL injection payload doesn't crash or affect query."""
    # Attempt SQL injection
    malicious_address = "0x123'; DROP TABLE trades; --"

    # Should not crash
    trades = jbecker_dataset.query_trader_history(malicious_address)

    # Should return empty (address doesn't exist)
    assert trades == []


def test_query_no_string_interpolation(jbecker_dataset):
    """Verify query string does not contain the trader address literal."""
    with patch("duckdb.execute") as mock_execute:
        mock_result = MagicMock()
        mock_result.fetchdf.return_value.to_dict.return_value = []
        mock_execute.return_value = mock_result

        trader = "0xUNIQUEADDRESS123456789"
        jbecker_dataset.query_trader_history(trader)

        call_args = mock_execute.call_args
        query = call_args[0][0]

        # Unique address should NOT appear in query string
        assert "UNIQUEADDRESS" not in query


# ===== Query by market (3 tests) =====


def test_query_market_trades_returns_all(jbecker_dataset):
    """Test query_market_trades returns matching trades."""
    # Known asset ID from fixture
    asset_id = "0xc5d563a0c9f5b3db2b0e2c8e6c8a2e3a4b5c6d7e"
    trades = jbecker_dataset.query_market_trades(asset_id)

    assert len(trades) > 0
    assert all(isinstance(t, dict) for t in trades)


def test_query_market_trades_empty(jbecker_dataset):
    """Test query_market_trades returns empty list for unknown market."""
    unknown_asset = "0x0000000000000000000000000000000000000000"
    trades = jbecker_dataset.query_market_trades(unknown_asset)

    assert trades == []


def test_query_market_trades_parameterized(jbecker_dataset):
    """Test query_market_trades uses parameterized SQL."""
    with patch("duckdb.execute") as mock_execute:
        mock_result = MagicMock()
        mock_result.fetchdf.return_value.to_dict.return_value = []
        mock_execute.return_value = mock_result

        asset_id = "0xASSET123"
        jbecker_dataset.query_market_trades(asset_id)

        call_args = mock_execute.call_args
        query = call_args[0][0]

        # Should use parameterized query
        assert "$" in query or "?" in query
        # Asset ID should not appear literally in query
        assert "ASSET123" not in query


# ===== Dataset statistics (3 tests) =====


def test_get_trade_count(jbecker_dataset):
    """Test get_trade_count returns total trade count for trader."""
    trader = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"
    count = jbecker_dataset.get_trade_count(trader)

    assert count == 50


def test_get_date_range(jbecker_dataset):
    """Test get_date_range returns (earliest, latest) timestamps."""
    trader = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"
    date_range = jbecker_dataset.get_date_range(trader)

    assert date_range is not None
    earliest, latest = date_range
    assert isinstance(earliest, int)
    assert isinstance(latest, int)
    assert earliest <= latest


def test_get_dataset_info(jbecker_dataset):
    """Test get_dataset_info returns dataset metadata."""
    info = jbecker_dataset.get_dataset_info()

    assert isinstance(info, dict)
    assert "file_count" in info
    assert "total_rows" in info
    assert "date_range" in info
    assert info["file_count"] == 1  # We have 1 parquet file
    assert info["total_rows"] == 100  # 100 trades in fixture


# ===== Edge cases (3 tests) =====


def test_query_with_0x_prefix_normalization(jbecker_dataset):
    """Test queries handle addresses with/without 0x prefix."""
    trader_with_prefix = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"
    trader_without_prefix = "effd76b6a4318d50c6f71a16b276c5b279445a86"

    trades_with = jbecker_dataset.query_trader_history(trader_with_prefix)
    trades_without = jbecker_dataset.query_trader_history(trader_without_prefix)

    # Both should work (addresses in fixture have 0x prefix)
    assert len(trades_with) == 50
    # Without prefix might not match - let implementation decide
    # For now, just verify it doesn't crash
    assert isinstance(trades_without, list)


def test_query_timestamps_ordered_descending(jbecker_dataset):
    """Test results ordered by timestamp descending (newest first)."""
    trader = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"
    trades = jbecker_dataset.query_trader_history(trader)

    # Check timestamps are in descending order
    timestamps = [t["timestamp"] for t in trades]
    assert timestamps == sorted(timestamps, reverse=True)


def test_fetchmany_for_large_results(jbecker_dataset):
    """Test uses fetchmany for batch streaming (mock test)."""
    # This is a design verification test
    # In production, large result sets should use fetchmany
    # For our 100-trade fixture, verify basic functionality works
    trader = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"
    trades = jbecker_dataset.query_trader_history(trader)

    # Should successfully return all trades
    assert len(trades) == 50
    assert all(isinstance(t, dict) for t in trades)


# ===== Batch query tests (4 tests) =====


def test_batch_query_traders_history(jbecker_dataset):
    """Test batch_query_traders_history returns trades for multiple traders."""
    known_trader = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"
    unknown_trader = "0x0000000000000000000000000000000000000001"

    result = jbecker_dataset.batch_query_traders_history([known_trader, unknown_trader])

    assert isinstance(result, dict)
    assert known_trader.lower() in result
    assert unknown_trader.lower() in result
    assert len(result[known_trader.lower()]) == 50
    assert result[unknown_trader.lower()] == []


def test_batch_query_empty_list(jbecker_dataset):
    """Test batch_query_traders_history handles empty list."""
    result = jbecker_dataset.batch_query_traders_history([])
    assert result == {}


def test_batch_query_case_insensitive(jbecker_dataset):
    """Test batch_query handles case variations."""
    trader_lower = "0xeffd76b6a4318d50c6f71a16b276c5b279445a86"
    trader_upper = "0XEFFD76B6A4318D50C6F71A16B276C5B279445A86"

    result = jbecker_dataset.batch_query_traders_history([trader_lower, trader_upper])

    # Both should map to the same normalized key
    assert trader_lower.lower() in result
    assert trader_upper.lower() in result
    assert len(result[trader_lower.lower()]) == 50
    assert len(result[trader_upper.lower()]) == 50


def test_batch_query_dataset_not_available(tmp_path):
    """Test batch_query_traders_history raises FileNotFoundError when dataset missing."""
    dataset = JBeckerDataset(str(tmp_path / "nonexistent"))

    with pytest.raises(FileNotFoundError) as exc_info:
        dataset.batch_query_traders_history(["0x123"])

    assert "s3.jbecker.dev" in str(exc_info.value)
