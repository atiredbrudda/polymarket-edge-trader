"""
Classification pipeline for syncing taxonomy to DB and classifying markets.

Provides ClassificationPipeline class that:
1. Loads taxonomy from YAML
2. Syncs taxonomy hierarchy to TaxonomyNode table
3. Classifies markets using PatternMatcher
4. Persists classifications in MarketClassification table
"""

import json
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import sessionmaker, Session

from src.config.settings import get_settings
from src.db.models import Market, MarketClassification, TaxonomyNode
from src.taxonomy.classifier import PatternMatcher, detect_market_type
from src.taxonomy.loader import load_taxonomy
from src.taxonomy.models import TaxonomyConfig, GameNode, TournamentNode, TeamNode


class ClassificationPipeline:
    """
    Pipeline for taxonomy sync and market classification.

    Loads YAML taxonomy, syncs to database, and classifies markets
    using pattern matching with review flagging.
    """

    def __init__(
        self, session_factory: sessionmaker, taxonomy_path: Optional[Path] = None
    ):
        """
        Initialize pipeline with session factory and taxonomy.

        Args:
            session_factory: SQLAlchemy session factory for DB operations
            taxonomy_path: Path to YAML taxonomy file (uses settings if None)
        """
        self.session_factory = session_factory

        # Load taxonomy from YAML
        if taxonomy_path is None:
            settings = get_settings()
            taxonomy_path = Path(settings.taxonomy_path)

        self.taxonomy = load_taxonomy(taxonomy_path)
        self.matcher = PatternMatcher(self.taxonomy)

    def sync_taxonomy_to_db(self) -> int:
        """
        Sync loaded taxonomy hierarchy to TaxonomyNode table.

        Walks the taxonomy tree and upserts nodes with:
        - Slug for matching (e.g., "esports.cs2.iem-katowice")
        - Depth (0=root, 1=game, 2=tournament, 3=team)
        - Parent relationships
        - Patterns as JSON

        Returns:
            Count of nodes synced

        Uses upsert logic: if slug exists, update; otherwise insert.
        """
        nodes_synced = 0

        with self.session_factory() as session:
            # Root node
            root_slug = self.taxonomy.name.lower()
            root_node = session.query(TaxonomyNode).filter_by(slug=root_slug).first()

            if root_node is None:
                root_node = TaxonomyNode(
                    name=self.taxonomy.name,
                    slug=root_slug,
                    parent_id=None,
                    depth=0,
                    node_type="root",
                    patterns_json="[]",
                )
                session.add(root_node)
                session.flush()  # Get the ID
                nodes_synced += 1
            else:
                # Update existing root
                root_node.name = self.taxonomy.name
                root_node.node_type = "root"
                root_node.patterns_json = "[]"
                nodes_synced += 1

            # Game nodes (depth 1)
            for game in self.taxonomy.games:
                game_slug = f"{root_slug}.{game.name.lower()}"
                game_node = session.query(TaxonomyNode).filter_by(slug=game_slug).first()

                patterns_json = json.dumps(game.patterns)

                if game_node is None:
                    game_node = TaxonomyNode(
                        name=game.name,
                        slug=game_slug,
                        parent_id=root_node.id,
                        depth=1,
                        node_type="game",
                        patterns_json=patterns_json,
                    )
                    session.add(game_node)
                    session.flush()
                    nodes_synced += 1
                else:
                    # Update existing game
                    game_node.name = game.name
                    game_node.parent_id = root_node.id
                    game_node.node_type = "game"
                    game_node.patterns_json = patterns_json
                    nodes_synced += 1

                # Tournament nodes (depth 2)
                for tournament in game.tournaments:
                    tournament_slug = f"{game_slug}.{tournament.name.lower()}"
                    tournament_node = (
                        session.query(TaxonomyNode).filter_by(slug=tournament_slug).first()
                    )

                    patterns_json = json.dumps(tournament.patterns)

                    if tournament_node is None:
                        tournament_node = TaxonomyNode(
                            name=tournament.name,
                            slug=tournament_slug,
                            parent_id=game_node.id,
                            depth=2,
                            node_type="tournament",
                            patterns_json=patterns_json,
                        )
                        session.add(tournament_node)
                        session.flush()
                        nodes_synced += 1
                    else:
                        # Update existing tournament
                        tournament_node.name = tournament.name
                        tournament_node.parent_id = game_node.id
                        tournament_node.node_type = "tournament"
                        tournament_node.patterns_json = patterns_json
                        nodes_synced += 1

                    # Team nodes (depth 3)
                    for team in tournament.teams:
                        team_slug = f"{tournament_slug}.{team.name.lower()}"
                        team_node = (
                            session.query(TaxonomyNode).filter_by(slug=team_slug).first()
                        )

                        patterns_json = json.dumps(team.patterns)

                        if team_node is None:
                            team_node = TaxonomyNode(
                                name=team.name,
                                slug=team_slug,
                                parent_id=tournament_node.id,
                                depth=3,
                                node_type="team",
                                patterns_json=patterns_json,
                            )
                            session.add(team_node)
                            nodes_synced += 1
                        else:
                            # Update existing team
                            team_node.name = team.name
                            team_node.parent_id = tournament_node.id
                            team_node.node_type = "team"
                            team_node.patterns_json = patterns_json
                            nodes_synced += 1

            session.commit()

        return nodes_synced

    def classify_market(self, market: Market) -> MarketClassification:
        """
        Classify a single market using PatternMatcher.

        Args:
            market: Market ORM object with question attribute

        Returns:
            MarketClassification object (not yet persisted)

        Uses classify_with_review() to flag problematic classifications.
        Looks up taxonomy_node_id from TaxonomyNode table by matching node_path.
        """
        # Use PatternMatcher to classify
        result = self.matcher.classify_with_review(market.question)

        # Look up taxonomy node ID from slug
        # Convert node_path to slug format (e.g., "eSports.CS2" -> "esports.cs2")
        node_path_parts = result.node_path.split(".")
        slug = ".".join(part.lower() for part in node_path_parts)

        with self.session_factory() as session:
            taxonomy_node = session.query(TaxonomyNode).filter_by(slug=slug).first()
            taxonomy_node_id = taxonomy_node.id if taxonomy_node else None

        # Detect market type
        market_type = detect_market_type(market.question)

        # Create MarketClassification object
        classification = MarketClassification(
            market_id=market.condition_id,
            taxonomy_node_id=taxonomy_node_id,
            node_path=result.node_path,
            market_type=market_type,
            matched_pattern=result.matched_pattern,
            flagged_for_review=result.flagged_for_review,
        )

        return classification

    def classify_all_markets(self) -> dict:
        """
        Classify all markets without existing classification.

        Queries all markets, classifies each using classify_market,
        and persists classifications in batches.

        Returns:
            Statistics dict with:
                - classified: total markets classified
                - flagged: markets flagged for review
                - match_type: count of match-type markets
                - prop_type: count of prop-type markets
        """
        stats = {
            "classified": 0,
            "flagged": 0,
            "match_type": 0,
            "prop_type": 0,
        }

        with self.session_factory() as session:
            # Get all markets that don't have classification
            unclassified_markets = (
                session.query(Market)
                .outerjoin(
                    MarketClassification,
                    Market.condition_id == MarketClassification.market_id,
                )
                .filter(MarketClassification.id.is_(None))
                .all()
            )

            # Classify each market
            batch = []
            for market in unclassified_markets:
                classification = self.classify_market(market)
                batch.append(classification)

                # Update stats
                stats["classified"] += 1
                if classification.flagged_for_review:
                    stats["flagged"] += 1
                if classification.market_type == "match":
                    stats["match_type"] += 1
                elif classification.market_type == "prop":
                    stats["prop_type"] += 1

                # Commit every 100 records
                if len(batch) >= 100:
                    session.add_all(batch)
                    session.commit()
                    batch = []

            # Commit remaining
            if batch:
                session.add_all(batch)
                session.commit()

        return stats

    def classify_new_markets(self) -> dict:
        """
        Classify only new markets (no existing classification).

        Identical to classify_all_markets (both filter for unclassified).
        Kept as separate method for semantic clarity in incremental runs.

        Returns:
            Statistics dict (same format as classify_all_markets)
        """
        return self.classify_all_markets()
