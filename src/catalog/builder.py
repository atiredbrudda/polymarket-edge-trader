"""Token catalog builder for JBecker markets parquet classification.

Scans all 41 JBecker markets parquet files via DuckDB, classifies each market
question with PatternMatcher, and writes results to the token_catalog SQLite table.
"""

import duckdb
from pathlib import Path
from loguru import logger
from sqlalchemy.orm import Session

from src.taxonomy.loader import load_taxonomy
from src.taxonomy.classifier import PatternMatcher


class TokenCatalogBuilder:
    """Builds token_catalog table from JBecker markets parquet files.

    Uses DuckDB to scan the markets parquet glob in one SQL query, then
    classifies each market question with PatternMatcher (existing classifier),
    and writes all rows to SQLite via a single-transaction executemany.

    Args:
        markets_path: Path to directory containing markets_*.parquet files
                      (e.g., data/polymarket/markets/)
        taxonomy_path: Path to taxonomy YAML file (e.g., config/taxonomy.yaml)
    """

    def __init__(self, markets_path: str | Path, taxonomy_path: str | Path):
        self.markets_path = Path(markets_path)
        self.taxonomy_path = Path(taxonomy_path)

    def is_built(self, session: Session) -> bool:
        """Check if catalog has been built (table is non-empty).

        Args:
            session: Active SQLAlchemy session

        Returns:
            True if token_catalog table has at least one row
        """
        from src.db.models import TokenCatalog

        count = session.query(TokenCatalog).limit(1).count()
        return count > 0

    def _scan_parquet(self, glob_pattern: str) -> list[tuple]:
        """Scan parquet files via DuckDB and return raw rows.

        Args:
            glob_pattern: Glob pattern for parquet files

        Returns:
            List of (condition_id, question, clob_token_ids) tuples
        """
        con = duckdb.connect()
        rows = con.execute(
            f"""
            SELECT condition_id, question, clob_token_ids
            FROM read_parquet('{glob_pattern}')
            WHERE condition_id IS NOT NULL
              AND question IS NOT NULL
              AND clob_token_ids IS NOT NULL
              AND len(clob_token_ids) > 0
            """
        ).fetchall()
        con.close()
        return rows

    def build(self, session: Session) -> int:
        """Scan markets parquet, classify, and write to token_catalog.

        Uses DuckDB to read all markets_*.parquet in one pass (0.5s), then
        classifies each row with PatternMatcher (~15s for 408k markets), and
        writes all token rows to SQLite in a single INSERT OR IGNORE transaction.

        Args:
            session: Active SQLAlchemy session (caller manages commit)

        Returns:
            Number of token rows inserted
        """
        glob_pattern = str(self.markets_path / "markets_*.parquet")
        logger.info(f"Building token catalog from: {glob_pattern}")

        taxonomy = load_taxonomy(self.taxonomy_path)
        matcher = PatternMatcher(taxonomy)

        rows = self._scan_parquet(glob_pattern)
        logger.info(f"DuckDB scanned {len(rows)} markets from parquet")

        from src.db.models import TokenCatalog
        from sqlalchemy import text

        token_rows = []
        for condition_id, question, clob_token_ids in rows:
            if not clob_token_ids:
                continue

            result = matcher.classify(question)
            if result is not None:
                niche_slug = "esports" if result.depth >= 1 else None
                node_path = result.node_path if result.depth >= 1 else None
                depth = result.depth if result.depth >= 1 else None
                market_type = result.market_type
            else:
                niche_slug = None
                node_path = None
                depth = None
                market_type = None

            for token_id in clob_token_ids:
                token_str = str(token_id).strip()
                if not token_str or token_str == "0":
                    continue
                token_rows.append(
                    {
                        "token_id": token_str,
                        "condition_id": str(condition_id),
                        "question": str(question)[:500],
                        "niche_slug": niche_slug,
                        "node_path": node_path,
                        "depth": depth,
                        "market_type": market_type,
                    }
                )

        logger.info(f"Classified {len(token_rows)} token rows, writing to SQLite")

        if not token_rows:
            logger.warning("No token rows to insert — markets parquet may be empty")
            return 0

        session.execute(
            text(
                """
                INSERT OR IGNORE INTO token_catalog
                  (token_id, condition_id, question, niche_slug, node_path, depth, market_type)
                VALUES
                  (:token_id, :condition_id, :question, :niche_slug, :node_path, :depth, :market_type)
                """
            ),
            token_rows,
        )
        session.commit()
        logger.info(f"Token catalog built: {len(token_rows)} rows written")
        return len(token_rows)
