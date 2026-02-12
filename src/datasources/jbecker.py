"""Query layer for Jon Becker's Parquet dataset using DuckDB.

Provides SQL interface to 33.5GB Parquet trade history with:
- Parameterized queries ($1, $2) for security
- Filter pushdown for performance (only matching rows loaded)
- Case-insensitive address matching
"""

from pathlib import Path
from typing import Optional
import time
import duckdb
from loguru import logger


class JBeckerDataset:
    """Query Jon Becker's Parquet dataset using DuckDB.

    Provides SQL interface to 33.5GB Parquet trade history.
    Uses parameterized queries ($1, $2) for security.
    Uses filter pushdown for performance (only matching rows loaded).

    Attributes:
        data_path: Path to extracted dataset root
        trades_path: Path to trades parquet files directory

    Args:
        data_path: Path to extracted dataset root (contains polymarket/trades/)

    Example:
        >>> dataset = JBeckerDataset("./data")
        >>> if dataset.is_available():
        ...     trades = dataset.query_trader_history("0xeffd76...")
    """

    DOWNLOAD_URL = "https://s3.jbecker.dev/data.tar.zst"

    def __init__(self, data_path: str):
        """Initialize dataset with path to extracted data.

        Args:
            data_path: Path to extracted dataset root
        """
        self.data_path = Path(data_path)
        self.trades_path = self.data_path / "polymarket" / "trades"

    def is_available(self) -> bool:
        """Check if dataset is available.

        Returns:
            True if trades directory exists and contains parquet files
        """
        if not self.trades_path.exists():
            return False

        # Check for any trades_*.parquet files
        parquet_files = list(self.trades_path.glob("trades_*.parquet"))
        return len(parquet_files) > 0

    def query_trader_history(
        self, trader_address: str, limit: Optional[int] = None
    ) -> list[dict]:
        """Query all trades for a trader address.

        Args:
            trader_address: Ethereum address (with or without 0x prefix)
            limit: Optional limit on number of results

        Returns:
            List of trade dictionaries ordered by timestamp DESC

        Raises:
            FileNotFoundError: If dataset is not available
        """
        if not self.is_available():
            raise FileNotFoundError(
                f"JBecker dataset not found. Download from: {self.DOWNLOAD_URL}\n"
                f"Extract to: {self.data_path}"
            )

        # Normalize address (add 0x if missing, handle uppercase 0X)
        if not trader_address.lower().startswith("0x"):
            trader_address = f"0x{trader_address}"

        # Build parameterized query
        pattern = str(self.trades_path / "trades_*.parquet")
        query = """
            SELECT *
            FROM read_parquet($1)
            WHERE LOWER(maker) = LOWER($2) OR LOWER(taker) = LOWER($2)
            ORDER BY timestamp DESC
        """

        if limit is not None:
            query += f" LIMIT {int(limit)}"

        logger.debug(f"Querying JBecker dataset for trader {trader_address[:10]}...")
        start = time.time()
        result = duckdb.execute(query, [pattern, trader_address])

        # Convert to list of dicts
        trades = result.fetchdf().to_dict("records")
        elapsed = time.time() - start
        logger.info(
            f"Found {len(trades)} trades for trader {trader_address[:10]}... "
            f"in {elapsed:.2f}s"
        )

        return trades

    def query_market_trades(
        self, asset_id: str, limit: Optional[int] = None
    ) -> list[dict]:
        """Query all trades for a market (asset ID).

        Args:
            asset_id: Polymarket asset ID (condition ID)
            limit: Optional limit on number of results

        Returns:
            List of trade dictionaries ordered by timestamp DESC

        Raises:
            FileNotFoundError: If dataset is not available
        """
        if not self.is_available():
            raise FileNotFoundError(
                f"JBecker dataset not found. Download from: {self.DOWNLOAD_URL}\n"
                f"Extract to: {self.data_path}"
            )

        # Build parameterized query
        pattern = str(self.trades_path / "trades_*.parquet")
        query = """
            SELECT *
            FROM read_parquet($1)
            WHERE makerAssetId = $2 OR takerAssetId = $2
            ORDER BY timestamp DESC
        """

        if limit is not None:
            query += f" LIMIT {int(limit)}"

        logger.debug(f"Querying JBecker dataset for market {asset_id[:10]}...")
        start = time.time()
        result = duckdb.execute(query, [pattern, asset_id])

        trades = result.fetchdf().to_dict("records")
        elapsed = time.time() - start
        logger.info(
            f"Found {len(trades)} trades for market {asset_id[:10]}... "
            f"in {elapsed:.2f}s"
        )

        return trades

    def get_trade_count(self, trader_address: str) -> int:
        """Get total trade count for a trader.

        Args:
            trader_address: Ethereum address

        Returns:
            Total number of trades

        Raises:
            FileNotFoundError: If dataset is not available
        """
        if not self.is_available():
            raise FileNotFoundError(
                f"JBecker dataset not found. Download from: {self.DOWNLOAD_URL}\n"
                f"Extract to: {self.data_path}"
            )

        # Normalize address (add 0x if missing, handle uppercase 0X)
        if not trader_address.lower().startswith("0x"):
            trader_address = f"0x{trader_address}"

        pattern = str(self.trades_path / "trades_*.parquet")
        query = """
            SELECT COUNT(*) as count
            FROM read_parquet($1)
            WHERE LOWER(maker) = LOWER($2) OR LOWER(taker) = LOWER($2)
        """

        start = time.time()
        result = duckdb.execute(query, [pattern, trader_address])
        count = result.fetchone()[0]
        elapsed = time.time() - start

        logger.info(
            f"Trader {trader_address[:10]}... has {count} trades "
            f"(counted in {elapsed:.2f}s)"
        )
        return count

    def get_date_range(self, trader_address: str) -> tuple[int, int] | None:
        """Get earliest and latest timestamp for a trader.

        Args:
            trader_address: Ethereum address

        Returns:
            (earliest_timestamp, latest_timestamp) or None if no trades

        Raises:
            FileNotFoundError: If dataset is not available
        """
        if not self.is_available():
            raise FileNotFoundError(
                f"JBecker dataset not found. Download from: {self.DOWNLOAD_URL}\n"
                f"Extract to: {self.data_path}"
            )

        # Normalize address (add 0x if missing, handle uppercase 0X)
        if not trader_address.lower().startswith("0x"):
            trader_address = f"0x{trader_address}"

        pattern = str(self.trades_path / "trades_*.parquet")
        query = """
            SELECT MIN(timestamp) as earliest, MAX(timestamp) as latest
            FROM read_parquet($1)
            WHERE LOWER(maker) = LOWER($2) OR LOWER(taker) = LOWER($2)
        """

        result = duckdb.execute(query, [pattern, trader_address])
        row = result.fetchone()

        if row[0] is None or row[1] is None:
            return None

        return (row[0], row[1])

    def get_dataset_info(self) -> dict:
        """Get dataset metadata.

        Returns:
            Dictionary with:
                - file_count: Number of parquet files
                - total_rows: Approximate total row count
                - date_range: (min_timestamp, max_timestamp) across all files

        Raises:
            FileNotFoundError: If dataset is not available
        """
        if not self.is_available():
            raise FileNotFoundError(
                f"JBecker dataset not found. Download from: {self.DOWNLOAD_URL}\n"
                f"Extract to: {self.data_path}"
            )

        # Count parquet files
        parquet_files = list(self.trades_path.glob("trades_*.parquet"))
        file_count = len(parquet_files)

        # Get total row count and date range
        pattern = str(self.trades_path / "trades_*.parquet")
        query = """
            SELECT
                COUNT(*) as total_rows,
                MIN(timestamp) as earliest,
                MAX(timestamp) as latest
            FROM read_parquet($1)
        """

        start = time.time()
        result = duckdb.execute(query, [pattern])
        row = result.fetchone()
        elapsed = time.time() - start

        logger.info(
            f"Dataset info: {file_count} files, {row[0]:,} rows "
            f"(scanned in {elapsed:.2f}s)"
        )

        return {
            "file_count": file_count,
            "total_rows": row[0],
            "date_range": (row[1], row[2]) if row[1] and row[2] else None,
        }
