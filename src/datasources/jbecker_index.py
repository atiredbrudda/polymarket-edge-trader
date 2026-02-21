"""Trader-to-file index for fast JBecker dataset queries.

Eliminates full 45GB scan by pre-indexing which parquet files contain each trader.

Without index: DuckDB opens all 40,000 files to find one trader → OOM on 8GB.
With index:    DuckDB opens only the 5-50 files that trader actually traded in → fast.

Build once (~20 min), use forever.
"""

import json
import sqlite3
import time
from pathlib import Path

import duckdb
from loguru import logger


class TraderFileIndex:
    """Maps trader addresses to the parquet files they appear in.

    Built once via build(), stored in trader_index.db alongside the dataset.
    After building, lookup() returns only the relevant files for a trader set,
    reducing DuckDB scans from 40,000 files to typically 5-50.
    """

    INDEX_DB_NAME = "trader_index.db"
    BUILD_BATCH_SIZE = 100  # files per DuckDB query — 100 × 1.2MB = ~120MB, safe on 8GB

    def __init__(self, data_path: str):
        self.data_path = Path(data_path)
        self.trades_path = self.data_path / "polymarket" / "trades"
        self.index_path = self.data_path / "polymarket" / self.INDEX_DB_NAME

    @property
    def is_built(self) -> bool:
        if not self.index_path.exists():
            return False
        try:
            conn = sqlite3.connect(self.index_path)
            count = conn.execute("SELECT COUNT(*) FROM trader_files").fetchone()[0]
            conn.close()
            return count > 0
        except Exception:
            return False

    def build(self, batch_size: int = BUILD_BATCH_SIZE) -> int:
        """Scan all parquet files and build the trader → files index.

        Two-phase build to avoid SQLite index maintenance overhead:
          Phase 1 — Bulk insert all (trader, filename) pairs into a staging table
                    with NO constraints and NO indexes. SQLite appends at disk speed.
          Phase 2 — Deduplicate into the final table and create the index once.

        This is ~10-20x faster than inserting with a live unique constraint.

        Args:
            batch_size: Parquet files per DuckDB query. Default 100 (~120MB/batch).

        Returns:
            Total number of unique (trader, file) pairs indexed.
        """
        files = sorted(self.trades_path.glob("trades_*.parquet"))
        if not files:
            raise FileNotFoundError(f"No parquet files found at {self.trades_path}")

        logger.info(f"Building trader index from {len(files):,} parquet files...")

        db = sqlite3.connect(self.index_path)

        # Speed pragmas — safe to use since we rebuild from scratch
        db.execute("PRAGMA journal_mode=OFF")
        db.execute("PRAGMA synchronous=OFF")
        db.execute("PRAGMA cache_size=100000")
        # Note: do NOT set temp_store=MEMORY — Phase 2 copy needs disk temp for large tables

        # Phase 1: staging table — no constraints, no indexes, just fast appends
        db.execute("DROP TABLE IF EXISTS _staging")
        db.execute("""
            CREATE TABLE _staging (
                trader_address TEXT,
                filename       TEXT
            )
        """)
        db.commit()

        num_batches = (len(files) + batch_size - 1) // batch_size
        total_inserted = 0
        overall_start = time.time()

        for batch_idx in range(0, len(files), batch_size):
            batch = files[batch_idx : batch_idx + batch_size]
            batch_num = batch_idx // batch_size + 1
            file_list = json.dumps([str(f) for f in batch])

            conn = duckdb.connect(config={"threads": 2, "memory_limit": "2GB"})
            try:
                result = conn.execute(f"""
                    SELECT DISTINCT LOWER(maker) AS addr, filename
                    FROM read_parquet({file_list}, filename=true)
                    UNION
                    SELECT DISTINCT LOWER(taker), filename
                    FROM read_parquet({file_list}, filename=true)
                """)
                rows = result.fetchall()
            finally:
                conn.close()

            normalized = [
                (addr, Path(filename).name)
                for addr, filename in rows
                if addr and addr != "0" and addr != "0x0"
            ]

            db.executemany("INSERT INTO _staging VALUES (?, ?)", normalized)
            # Commit every 10 batches to avoid huge transactions
            if batch_num % 10 == 0:
                db.commit()

            total_inserted += len(normalized)
            elapsed = time.time() - overall_start
            rate = (batch_idx + len(batch)) / max(elapsed, 0.1)
            remaining = (len(files) - batch_idx - len(batch)) / rate
            logger.info(
                f"Phase 1 — {batch_num}/{num_batches} | "
                f"{total_inserted:,} rows | ~{remaining / 60:.0f}m left"
            )

        db.commit()

        # Phase 2: copy staging into final table and build index once
        # No DISTINCT needed — staging rows are already unique:
        #   each DuckDB batch uses UNION (not UNION ALL), and each file is only in one batch.
        logger.info("Phase 2 — copying to final table and building index...")
        db.execute("DROP TABLE IF EXISTS trader_files")
        db.execute("""
            CREATE TABLE trader_files AS
            SELECT trader_address, filename
            FROM _staging
            WHERE trader_address IS NOT NULL
        """)
        db.execute("CREATE INDEX idx_addr ON trader_files(trader_address)")
        db.execute("DROP TABLE _staging")
        db.execute("PRAGMA journal_mode=WAL")
        db.commit()
        db.close()

        elapsed = time.time() - overall_start
        logger.info(
            f"Index build complete in {elapsed / 60:.1f}m"
        )
        return self.stats().get("total_pairs", 0)

    def lookup(self, trader_addresses: list[str]) -> list[str]:
        """Return absolute parquet file paths that contain any of the given traders.

        Args:
            trader_addresses: Wallet addresses (any case, with or without 0x).

        Returns:
            List of absolute parquet file paths to scan. Empty if none found.
        """
        if not self.is_built:
            return []

        normalized = []
        for addr in trader_addresses:
            addr = addr.lower()
            if not addr.startswith("0x"):
                addr = f"0x{addr}"
            normalized.append(addr)

        placeholders = ",".join("?" * len(normalized))
        db = sqlite3.connect(self.index_path)
        try:
            rows = db.execute(
                f"SELECT DISTINCT filename FROM trader_files "
                f"WHERE trader_address IN ({placeholders})",
                normalized,
            ).fetchall()
        finally:
            db.close()

        return [str(self.trades_path / row[0]) for row in rows]

    def lookup_per_trader(self, trader_addresses: list[str]) -> dict[str, list[str]]:
        """Return {normalized_address: [file_paths]} for all traders in one SQLite query.

        More efficient than calling lookup() per trader when building dynamic batches.

        Args:
            trader_addresses: Wallet addresses (any case, with or without 0x).

        Returns:
            Dict mapping normalized address -> list of absolute parquet file paths.
            Traders with no JBecker history map to empty lists.
        """
        if not self.is_built or not trader_addresses:
            return {}

        normalized = []
        for addr in trader_addresses:
            addr = addr.lower()
            if not addr.startswith("0x"):
                addr = f"0x{addr}"
            normalized.append(addr)

        result: dict[str, list[str]] = {addr: [] for addr in normalized}

        # SQLite default variable limit is 999 — chunk to stay safe
        chunk_size = 900
        db = sqlite3.connect(self.index_path)
        try:
            for i in range(0, len(normalized), chunk_size):
                chunk = normalized[i : i + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                rows = db.execute(
                    f"SELECT trader_address, filename FROM trader_files "
                    f"WHERE trader_address IN ({placeholders})",
                    chunk,
                ).fetchall()
                for trader_addr, filename in rows:
                    if trader_addr in result:
                        result[trader_addr].append(str(self.trades_path / filename))
        finally:
            db.close()

        return result

    def stats(self) -> dict:
        """Return index statistics."""
        if not self.is_built:
            return {"built": False}

        db = sqlite3.connect(self.index_path)
        try:
            total_pairs = db.execute(
                "SELECT COUNT(*) FROM trader_files"
            ).fetchone()[0]
            unique_traders = db.execute(
                "SELECT COUNT(DISTINCT trader_address) FROM trader_files"
            ).fetchone()[0]
            unique_files = db.execute(
                "SELECT COUNT(DISTINCT filename) FROM trader_files"
            ).fetchone()[0]
        finally:
            db.close()

        import os
        size_mb = os.path.getsize(self.index_path) / 1024 / 1024

        return {
            "built": True,
            "total_pairs": total_pairs,
            "unique_traders": unique_traders,
            "unique_files": unique_files,
            "size_mb": round(size_mb, 1),
        }
