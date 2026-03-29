"""Token catalog builder for ingesting fixture data.

Phase 1: Uses fixture data for development.
Future: Will integrate with Gamma API client.
"""

import json
from pathlib import Path

import sqlite_utils


class TokenCatalogBuilder:
    """Build token catalog from fixture data or Gamma API.

    Attributes:
        db: sqlite_utils Database instance
    """

    def __init__(self, db: sqlite_utils.Database):
        """Initialize builder with database connection.

        Args:
            db: sqlite_utils Database instance with schema initialized
        """
        self.db = db

    def build_from_fixture(self, fixture_path: str) -> int:
        """Load and ingest token catalog from JSON fixture.

        Args:
            fixture_path: Path to JSON fixture file

        Returns:
            Count of entries inserted into token_catalog table

        Validates each entry has required fields before insertion.
        Also inserts corresponding market records to satisfy FK constraints.
        Uses upsert_all for deduplication and batching.
        """
        with open(fixture_path, "r") as f:
            data = json.load(f)

        # Validate required fields
        required_fields = [
            "token_id",
            "condition_id",
            "question",
            "niche_slug",
            "node_path",
        ]
        for entry in data:
            for field in required_fields:
                if field not in entry:
                    raise ValueError(
                        f"Missing required field '{field}' in token entry: {entry}"
                    )

        # Insert corresponding market records first (FK dependency)
        markets = []
        for entry in data:
            markets.append(
                {
                    "condition_id": entry["condition_id"],
                    "question": entry["question"],
                    "outcome": None,  # Not yet resolved
                    "resolved": False,
                    "niche_slug": entry["niche_slug"],
                    "created_at": "2025-01-01T00:00:00Z",  # Placeholder timestamp
                }
            )

        self.db["markets"].upsert_all(markets, pk="condition_id")

        # Insert token catalog entries
        self.db["token_catalog"].upsert_all(data, pk="token_id")

        return len(data)

    def build(self, niche: str) -> int:
        """Build token catalog for a niche.

        Args:
            niche: Niche slug (e.g., "esports")

        Returns:
            Count of entries inserted

        Phase 1: Uses fixture data hardcoded path.
        Future: Will switch to Gamma API client.
        """
        # Phase 1: Use fixture data
        fixture_path = (
            Path(__file__).parent.parent.parent.parent
            / "tests"
            / "fixtures"
            / "gamma_responses"
            / "token_catalog_fixture.json"
        )

        if fixture_path.exists():
            print("Using fixture data for Phase 1 development")
            return self.build_from_fixture(str(fixture_path))
        else:
            raise FileNotFoundError(f"Fixture file not found: {fixture_path}")
