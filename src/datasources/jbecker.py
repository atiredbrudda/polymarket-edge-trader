"""Query layer for Jon Becker's Parquet dataset using DuckDB.

Provides SQL interface to 33.5GB Parquet trade history with:
- Parameterized queries ($1, $2) for security
- Filter pushdown for performance (only matching rows loaded)
- Case-insensitive address matching
"""

import json
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

        from src.datasources.jbecker_index import TraderFileIndex
        self._index = TraderFileIndex(data_path)

    def _scan_target(self, addresses: list[str] | None = None) -> str | list[str]:
        """Return the scan target for a DuckDB query.

        If the index is built and addresses are provided, returns a list of
        specific files to scan. Otherwise returns the full glob pattern.

        Args:
            addresses: Trader addresses to look up. None means full scan.

        Returns:
            Either a JSON-encoded list of specific file paths, or a glob string.
        """
        if addresses and self._index.is_built:
            files = self._index.lookup(addresses)
            if files:
                return json.dumps(files)  # DuckDB accepts JSON array inline
            # No files found for these addresses — no history in dataset
            return None
        return f"'{str(self.trades_path / 'trades_*.parquet')}'"

    def _execute(self, query: str, params: list | None = None):
        """Execute a DuckDB query with memory and thread limits for 8GB machines."""
        conn = duckdb.connect(config={"threads": 2, "memory_limit": "3GB"})
        result = conn.execute(query, params or [])
        return result, conn

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

        scan = self._scan_target([trader_address])
        if scan is None:
            logger.debug(f"No JBecker files for {trader_address[:10]}... (index miss)")
            return []

        query = f"""
            SELECT *
            FROM read_parquet({scan})
            WHERE LOWER(maker) = LOWER($1) OR LOWER(taker) = LOWER($1)
            ORDER BY timestamp DESC
        """

        if limit is not None:
            query += f" LIMIT {int(limit)}"

        logger.debug(f"Querying JBecker dataset for trader {trader_address[:10]}...")
        start = time.time()
        result, conn = self._execute(query, [trader_address])

        # Convert to list of dicts
        trades = result.fetchdf().to_dict("records")
        conn.close()
        elapsed = time.time() - start
        logger.info(
            f"Found {len(trades)} trades for trader {trader_address[:10]}... "
            f"in {elapsed:.2f}s"
        )

        return trades

    def query_trader_history_subbatched(
        self, trader_address: str, max_files_per_batch: int = 1500
    ) -> list[dict]:
        """Query all trades for a whale trader by splitting their files into sub-batches.

        Used when a single trader appears in more files than max_files_per_batch.
        Runs multiple bounded DuckDB queries and combines results.

        Args:
            trader_address: Ethereum address (with or without 0x prefix)
            max_files_per_batch: Max parquet files per DuckDB query.

        Returns:
            Combined list of trade dicts across all sub-batches.
        """
        if not self.is_available():
            raise FileNotFoundError(
                f"JBecker dataset not found. Download from: {self.DOWNLOAD_URL}\n"
                f"Extract to: {self.data_path}"
            )

        if not trader_address.lower().startswith("0x"):
            trader_address = f"0x{trader_address}"

        if not self._index.is_built:
            return self.query_trader_history(trader_address)

        files = self._index.lookup([trader_address])
        if not files:
            return []

        if len(files) <= max_files_per_batch:
            return self.query_trader_history(trader_address)

        num_sub_batches = (len(files) + max_files_per_batch - 1) // max_files_per_batch
        logger.info(
            f"Whale {trader_address[:10]}... has {len(files)} files — "
            f"splitting into {num_sub_batches} sub-batches of {max_files_per_batch}"
        )

        all_trades = []
        start = time.time()

        for i in range(0, len(files), max_files_per_batch):
            sub_files = files[i : i + max_files_per_batch]
            sub_num = i // max_files_per_batch + 1
            file_list = json.dumps(sub_files)

            query = f"""
                SELECT *
                FROM read_parquet({file_list})
                WHERE LOWER(maker) = LOWER($1) OR LOWER(taker) = LOWER($1)
            """

            logger.debug(
                f"  Sub-batch {sub_num}/{num_sub_batches}: {len(sub_files)} files"
            )
            result, conn = self._execute(query, [trader_address])
            trades = result.fetchdf().to_dict("records")
            conn.close()
            all_trades.extend(trades)

        elapsed = time.time() - start
        logger.info(
            f"Whale {trader_address[:10]}...: {len(all_trades)} trades "
            f"across {num_sub_batches} sub-batches in {elapsed:.1f}s"
        )
        return all_trades

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
        result, conn = self._execute(query, [pattern, asset_id])

        trades = result.fetchdf().to_dict("records")
        conn.close()
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
        result, conn = self._execute(query, [pattern, trader_address])
        count = result.fetchone()[0]
        conn.close()
        elapsed = time.time() - start

        logger.info(
            f"Trader {trader_address[:10]}... has {count} trades "
            f"(counted in {elapsed:.2f}s)"
        )
        return count

    def batch_query_traders_history(
        self, trader_addresses: list[str]
    ) -> dict[str, list[dict]]:
        """Query trades for multiple traders in a single query.

        This is significantly faster than querying each trader individually
        because it scans the parquet files once instead of once per trader.

        Args:
            trader_addresses: List of Ethereum addresses

        Returns:
            Dict mapping normalized address (lowercase with 0x) -> list of trades
        """
        if not self.is_available():
            raise FileNotFoundError(
                f"JBecker dataset not found. Download from: {self.DOWNLOAD_URL}\n"
                f"Extract to: {self.data_path}"
            )
        if not trader_addresses:
            return {}

        normalized = []
        for addr in trader_addresses:
            addr_lower = addr.lower()
            if not addr_lower.startswith("0x"):
                addr_lower = f"0x{addr_lower}"
            normalized.append(addr_lower)

        scan = self._scan_target(normalized)
        if scan is None:
            logger.info(f"No JBecker files found for {len(normalized)} traders (index miss)")
            return {addr: [] for addr in normalized}

        placeholders = ", ".join([f"'{addr}'" for addr in normalized])
        query = f"""
            SELECT *
            FROM read_parquet({scan})
            WHERE LOWER(maker) IN ({placeholders}) OR LOWER(taker) IN ({placeholders})
            ORDER BY timestamp DESC
        """

        index_status = "indexed" if self._index.is_built else "full scan"
        logger.info(
            f"Batch querying {len(normalized)} traders from JBecker ({index_status})..."
        )
        start = time.time()
        result, conn = self._execute(query)
        all_trades = result.fetchdf().to_dict("records")
        conn.close()
        elapsed = time.time() - start
        logger.info(
            f"Found {len(all_trades)} total trades for {len(normalized)} traders "
            f"in {elapsed:.2f}s"
        )

        trades_by_address: dict[str, list[dict]] = {addr: [] for addr in normalized}
        for trade in all_trades:
            maker_lower = trade["maker"].lower()
            taker_lower = trade["taker"].lower()
            if maker_lower in trades_by_address:
                trades_by_address[maker_lower].append(trade)
            if taker_lower in trades_by_address and taker_lower != maker_lower:
                trades_by_address[taker_lower].append(trade)

        return trades_by_address

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

        result, conn = self._execute(query, [pattern, trader_address])
        row = result.fetchone()
        conn.close()

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
        result, conn = self._execute(query, [pattern])
        row = result.fetchone()
        conn.close()
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
