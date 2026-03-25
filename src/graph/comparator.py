"""Comparison tool for validating Graph vs API/JBecker trade data.

This module provides tools to:
1. Pull trades for the same traders from both Graph and API/JBecker sources
2. Compare outputs to identify divergence points
3. Generate ground truth test sets for validation
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from src.api.client import PolymarketClient
from src.datasources.jbecker import JBeckerDataset
from src.graph.client import GraphClient


@dataclass
class ComparisonResult:
    """Result of comparing trades between two sources."""

    trader_address: str
    source_a_count: int
    source_b_count: int
    source_a_name: str = "Graph"
    source_b_name: str = "API/JBecker"

    # Match statistics
    matched_by_market_side_timestamp: int = 0
    matched_by_market_side_size: int = 0
    unmatched_source_a: int = 0
    unmatched_source_b: int = 0

    # Divergence analysis
    market_id_divergences: list[dict] = field(default_factory=list)
    size_divergences: list[dict] = field(default_factory=list)
    side_divergences: list[dict] = field(default_factory=list)

    # Sample trades for inspection
    sample_matches: list[tuple[dict, dict]] = field(default_factory=list)
    sample_unmatched_a: list[dict] = field(default_factory=list)
    sample_unmatched_b: list[dict] = field(default_factory=list)


class TradeComparator:
    """Compare trades between Graph and API/JBecker sources."""

    def __init__(
        self,
        graph_client: Optional[GraphClient] = None,
        api_client: Optional[PolymarketClient] = None,
        jbecker_dataset: Optional[JBeckerDataset] = None,
    ):
        """Initialize comparator with data source clients.

        Args:
            graph_client: The Graph client instance
            api_client: Polymarket API client instance
            jbecker_dataset: JBecker dataset instance
        """
        self.graph_client = graph_client
        self.api_client = api_client
        self.jbecker_dataset = jbecker_dataset

        logger.info("Initialized TradeComparator")

    def _normalize_trade_for_comparison(self, trade: dict, source: str) -> dict:
        """Normalize a trade dict for comparison.

        Args:
            trade: Trade dict or Pydantic model from either source
            source: 'graph' or 'api' or 'jbecker'

        Returns:
            Normalized dict with standard fields
        """

        # Helper to get attribute from dict or Pydantic model
        def get_val(key: str, default=None):
            if isinstance(trade, dict):
                return trade.get(key, default)
            else:
                # Pydantic model
                return getattr(trade, key, default)

        if source == "graph":
            # Graph trade format from orderFilledEvents
            maker_asset = get_val("makerAssetId", "")
            taker_asset = get_val("takerAssetId", "")
            is_maker_token = maker_asset and maker_asset != "0"
            is_taker_token = taker_asset and taker_asset != "0"

            # Pick the conditional token (non-USDC asset)
            if is_maker_token and not is_taker_token:
                asset_id = maker_asset
                size = float(get_val("makerAmountFilled", 0)) / 1e6
            elif is_taker_token and not is_maker_token:
                asset_id = taker_asset
                size = float(get_val("takerAmountFilled", 0)) / 1e6
            elif is_maker_token and is_taker_token:
                # Both non-zero: use maker's asset
                asset_id = maker_asset
                size = float(get_val("makerAmountFilled", 0)) / 1e6
            else:
                # Both zero — shouldn't happen
                asset_id = "0"
                size = float(get_val("makerAmountFilled", 0)) / 1e6

            return {
                "market": str(asset_id),
                "side": str(get_val("side", "")).upper(),
                "timestamp": int(get_val("timestamp", 0)),
                "size": size,
                "price": float(get_val("price", 0)),
                "raw": trade,
            }
        elif source == "jbecker":
            # JBecker parquet format (snake_case)
            maker_asset = str(get_val("maker_asset_id", ""))
            taker_asset = str(get_val("taker_asset_id", ""))
            is_maker_token = maker_asset and maker_asset != "0"
            is_taker_token = taker_asset and taker_asset != "0"

            # Pick the conditional token (non-USDC asset)
            if is_maker_token and not is_taker_token:
                asset_id = maker_asset
                size = float(get_val("maker_amount", 0)) / 1e6
                is_maker = True
            elif is_taker_token and not is_maker_token:
                asset_id = taker_asset
                size = float(get_val("taker_amount", 0)) / 1e6
                is_maker = False
            elif is_maker_token and is_taker_token:
                # Both non-zero: use maker's asset
                asset_id = maker_asset
                size = float(get_val("maker_amount", 0)) / 1e6
                is_maker = True
            else:
                asset_id = "0"
                size = float(get_val("maker_amount", 0)) / 1e6
                is_maker = True

            # Derive side from trader role
            maker = str(get_val("maker", "")).lower()
            taker = str(get_val("taker", "")).lower()

            # For comparison purposes, just flag as BUY/SELL based on role
            side = "BUY" if is_maker else "SELL"

            # Timestamp handling
            ts = get_val("timestamp")
            if ts is None:
                fetched = get_val("_fetched_at")
                if hasattr(fetched, "timestamp"):
                    timestamp = int(fetched.timestamp())
                else:
                    timestamp = 0
            else:
                timestamp = int(ts) if ts else 0

            # Calculate price (maker_amount / taker_amount)
            maker_amt = float(get_val("maker_amount", 0)) / 1e6
            taker_amt = float(get_val("taker_amount", 0)) / 1e6
            price = maker_amt / taker_amt if taker_amt > 0 else 0.5

            return {
                "market": str(asset_id),
                "side": side,
                "timestamp": timestamp,
                "size": size,
                "price": price,
                "raw": trade,
            }
        elif source in ("api", "polymarket"):
            # API TradeResponse format (Pydantic model)
            ts_val = get_val("timestamp")
            if isinstance(ts_val, (int, float)):
                timestamp = int(ts_val)
            elif hasattr(ts_val, "timestamp"):
                timestamp = int(ts_val.timestamp())
            else:
                timestamp = 0

            return {
                "market": str(get_val("market", get_val("asset_id", ""))),
                "side": str(get_val("side", "")).upper(),
                "timestamp": timestamp,
                "size": float(get_val("size", 0)),
                "price": float(get_val("price", 0)),
                "raw": trade,
            }
        else:
            raise ValueError(f"Unknown source: {source}")

    def _trades_match(
        self,
        trade_a: dict,
        trade_b: dict,
        tolerance: dict | None = None,
    ) -> bool:
        """Check if two trades match within tolerance.

        Args:
            trade_a: Normalized trade from source A
            trade_b: Normalized trade from source B
            tolerance: Dict with tolerance thresholds

        Returns:
            True if trades match within tolerance
        """
        if tolerance is None:
            tolerance = {
                "timestamp_tolerance": 60,  # 1 minute
                "size_tolerance": 0.01,  # 1%
                "price_tolerance": 0.01,  # 1%
            }

        # Market must match (or be resolvable)
        if trade_a["market"] != trade_b["market"]:
            return False

        # Side must match
        if trade_a["side"] != trade_b["side"]:
            return False

        # Timestamp within tolerance
        if (
            abs(trade_a["timestamp"] - trade_b["timestamp"])
            > tolerance["timestamp_tolerance"]
        ):
            return False

        # Size within tolerance
        if abs(trade_a["size"] - trade_b["size"]) > tolerance["size_tolerance"] * max(
            trade_a["size"], trade_b["size"], 1
        ):
            return False

        return True

    def compare_trader(
        self,
        trader_address: str,
        max_trades: int = 1000,
    ) -> ComparisonResult:
        """Compare trades for a single trader between Graph and API/JBecker.

        Args:
            trader_address: Trader wallet address to compare
            max_trades: Maximum trades to fetch per source

        Returns:
            ComparisonResult with match statistics and samples
        """
        result = ComparisonResult(
            trader_address=trader_address,
            source_a_count=0,
            source_b_count=0,
        )

        # Fetch from Graph
        if self.graph_client:
            try:
                graph_trades = self.graph_client.get_trader_trades(
                    trader_address, max_total=max_trades
                )
                result.source_a_count = len(graph_trades)
                logger.info(
                    f"Fetched {len(graph_trades)} trades from Graph for {trader_address[:8]}..."
                )
            except Exception as e:
                logger.error(f"Failed to fetch Graph trades: {e}")
                graph_trades = []
        else:
            logger.warning("No Graph client configured")
            graph_trades = []

        # Fetch from API/JBecker
        if self.api_client:
            try:
                api_trades = self.api_client.get_trader_trades(
                    trader_address, limit=max_trades
                )
                result.source_b_count = len(api_trades)
                logger.info(
                    f"Fetched {len(api_trades)} trades from API for {trader_address[:8]}..."
                )
            except Exception as e:
                logger.error(f"Failed to fetch API trades: {e}")
                api_trades = []
        elif self.jbecker_dataset and self.jbecker_dataset.is_available():
            try:
                jbecker_trades = self.jbecker_dataset.query_trader_history(
                    trader_address, limit=max_trades
                )
                result.source_b_count = len(jbecker_trades)
                logger.info(
                    f"Fetched {len(jbecker_trades)} trades from JBecker for {trader_address[:8]}..."
                )
                api_trades = jbecker_trades
            except Exception as e:
                logger.error(f"Failed to fetch JBecker trades: {e}")
                api_trades = []
        else:
            logger.warning("No API or JBecker client configured")
            api_trades = []

        # Normalize trades
        graph_normalized = [
            self._normalize_trade_for_comparison(t, "graph") for t in graph_trades
        ]
        api_normalized = [
            self._normalize_trade_for_comparison(t, "api") for t in api_trades
        ]

        # Match trades
        matched_a = set()
        matched_b = set()

        for i, trade_a in enumerate(graph_normalized):
            for j, trade_b in enumerate(api_normalized):
                if j in matched_b:
                    continue

                if self._trades_match(trade_a, trade_b):
                    matched_a.add(i)
                    matched_b.add(j)
                    result.matched_by_market_side_timestamp += 1

                    # Save sample matches (up to 5)
                    if len(result.sample_matches) < 5:
                        result.sample_matches.append((trade_a["raw"], trade_b["raw"]))
                    break

        # Count unmatched
        result.unmatched_source_a = len(graph_normalized) - len(matched_a)
        result.unmatched_source_b = len(api_normalized) - len(matched_b)

        # Save sample unmatched trades (up to 10 each)
        for i, trade in enumerate(graph_normalized):
            if i not in matched_a and len(result.sample_unmatched_a) < 10:
                result.sample_unmatched_a.append(trade["raw"])

        for j, trade in enumerate(api_normalized):
            if j not in matched_b and len(result.sample_unmatched_b) < 10:
                result.sample_unmatched_b.append(trade["raw"])

        # Analyze divergences for unmatched trades
        self._analyze_divergences(
            graph_normalized, api_normalized, matched_a, matched_b, result
        )

        return result

    def _analyze_divergences(
        self,
        graph_trades: list[dict],
        api_trades: list[dict],
        matched_a: set,
        matched_b: set,
        result: ComparisonResult,
    ):
        """Analyze why trades don't match.

        Args:
            graph_trades: Normalized Graph trades
            api_trades: Normalized API trades
            matched_a: Indices of matched Graph trades
            matched_b: Indices of matched API trades
            result: ComparisonResult to populate
        """
        # Check unmatched Graph trades for market_id issues
        for i, trade_a in enumerate(graph_trades):
            if i in matched_a:
                continue

            # Check if there's a near-match with different market_id
            for j, trade_b in enumerate(api_trades):
                if j in matched_b:
                    continue

                # Same timestamp and size, different market?
                if (
                    abs(trade_a["timestamp"] - trade_b["timestamp"]) < 120
                    and abs(trade_a["size"] - trade_b["size"]) < 0.1
                    and trade_a["market"] != trade_b["market"]
                ):
                    if len(result.market_id_divergences) < 20:
                        result.market_id_divergences.append(
                            {
                                "graph_market": trade_a["market"],
                                "api_market": trade_b["market"],
                                "timestamp_diff": abs(
                                    trade_a["timestamp"] - trade_b["timestamp"]
                                ),
                                "size_diff": abs(trade_a["size"] - trade_b["size"]),
                                "graph_trade": trade_a["raw"],
                                "api_trade": trade_b["raw"],
                            }
                        )
                    break

    def compare_multiple_traders(
        self,
        trader_addresses: list[str],
        output_path: Optional[Path] = None,
    ) -> list[ComparisonResult]:
        """Compare trades for multiple traders.

        Args:
            trader_addresses: List of trader addresses to compare
            output_path: Optional path to save comparison results

        Returns:
            List of ComparisonResult objects
        """
        results = []

        for address in trader_addresses:
            logger.info(f"Comparing trades for {address[:8]}...")
            result = self.compare_trader(address)
            results.append(result)

            # Log summary
            total_a = result.source_a_count
            total_b = result.source_b_count
            matched = result.matched_by_market_side_timestamp
            match_rate = (
                (matched / max(total_a, total_b) * 100) if total_a or total_b else 0
            )

            logger.info(
                f"  Graph: {total_a}, API/JBecker: {total_b}, "
                f"Matched: {matched} ({match_rate:.1f}%)"
            )

        # Save results if output path provided
        if output_path:
            self._save_results(results, output_path)

        return results

    def _save_results(self, results: list[ComparisonResult], output_path: Path):
        """Save comparison results to JSON.

        Args:
            results: List of ComparisonResult objects
            output_path: Path to save results
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        serializable = []
        for result in results:
            serializable.append(
                {
                    "trader_address": result.trader_address,
                    "source_a_name": result.source_a_name,
                    "source_b_name": result.source_b_name,
                    "source_a_count": result.source_a_count,
                    "source_b_count": result.source_b_count,
                    "matched_by_market_side_timestamp": result.matched_by_market_side_timestamp,
                    "unmatched_source_a": result.unmatched_source_a,
                    "unmatched_source_b": result.unmatched_source_b,
                    "market_id_divergences_count": len(result.market_id_divergences),
                    "sample_matches_count": len(result.sample_matches),
                    "sample_unmatched_a": result.sample_unmatched_a[:5],
                    "sample_unmatched_b": result.sample_unmatched_b[:5],
                    "market_id_divergences_sample": result.market_id_divergences[:5],
                }
            )

        with open(output_path, "w") as f:
            json.dump(serializable, f, indent=2, default=str)

        logger.info(f"Saved comparison results to {output_path}")


def build_ground_truth_test_set(
    trader_addresses: list[str],
    output_dir: Path,
    graph_client: Optional[GraphClient] = None,
    api_client: Optional[PolymarketClient] = None,
    jbecker_dataset: Optional[JBeckerDataset] = None,
):
    """Build ground truth test set for Graph vs API comparison.

    This is the main entry point for building the test set described in:
    .planning/todos/pending/2026-03-25-token-catalog-market-resolution-gap.md

    Args:
        trader_addresses: List of 10 trader addresses
        output_dir: Directory to save test set
        graph_client: The Graph client
        api_client: Polymarket API client
        jbecker_dataset: JBecker dataset
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    comparator = TradeComparator(
        graph_client=graph_client,
        api_client=api_client,
        jbecker_dataset=jbecker_dataset,
    )

    # Split: first 5 for test, last 5 for validation
    test_traders = trader_addresses[:5]
    validation_traders = trader_addresses[5:10]

    logger.info(f"Building ground truth test set with {len(trader_addresses)} traders")
    logger.info(f"  Test set: {len(test_traders)} traders")
    logger.info(f"  Validation set: {len(validation_traders)} traders")

    # Generate test set
    test_results = comparator.compare_multiple_traders(
        test_traders,
        output_dir / "test_set_comparison.json",
    )

    # Generate validation set
    validation_results = comparator.compare_multiple_traders(
        validation_traders,
        output_dir / "validation_set_comparison.json",
    )

    # Generate summary report
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_traders": len(trader_addresses),
        "test_traders": len(test_traders),
        "validation_traders": len(validation_traders),
        "test_results": [
            {
                "trader": r.trader_address[:10],
                "graph_trades": r.source_a_count,
                "api_trades": r.source_b_count,
                "matched": r.matched_by_market_side_timestamp,
                "unmatched_graph": r.unmatched_source_a,
                "unmatched_api": r.unmatched_source_b,
                "market_divergences": len(r.market_id_divergences),
            }
            for r in test_results
        ],
        "validation_results": [
            {
                "trader": r.trader_address[:10],
                "graph_trades": r.source_a_count,
                "api_trades": r.source_b_count,
                "matched": r.matched_by_market_side_timestamp,
                "unmatched_graph": r.unmatched_source_a,
                "unmatched_api": r.unmatched_source_b,
                "market_divergences": len(r.market_id_divergences),
            }
            for r in validation_results
        ],
    }

    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    logger.info(f"Ground truth test set saved to {output_dir}")
    return summary
