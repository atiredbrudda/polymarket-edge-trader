"""Converters for transforming Graph data to internal formats."""

import logging
from datetime import datetime
from decimal import Decimal

from src.api.models import TradeResponse

logger = logging.getLogger(__name__)


def graph_trade_to_api_response(
    graph_trade: dict,
    trader_address: str,
    token_to_condition: dict[str, str] | None = None,
) -> TradeResponse:
    """Convert Graph OrderFilledEvent to API TradeResponse format.

    This allows Graph trades to be processed by existing pipeline logic
    without code changes.

    Args:
        graph_trade: OrderFilledEvent dict from The Graph
        trader_address: The trader address we're querying for
        token_to_condition: Optional dict mapping token_id -> condition_id.
            If provided, asset_id is looked up to get real condition_id.
            If not provided or asset_id not found, uses synthetic market_id.

    Returns:
        TradeResponse compatible with existing pipeline

    Graph trade format:
        {
          "id": "0x..._0x...",
          "maker": "0x...",
          "taker": "0x...",
          "makerAmountFilled": "1000000",  # 6 decimals (USDC)
          "takerAmountFilled": "2000000",
          "makerAssetId": "123",  # Token ID
          "takerAssetId": "456",
          "fee": "1000",
          "timestamp": "1234567890",
          "blockNumber": "82466624",
          "transactionHash": "0x...",
          "orderHash": "0x...",
          "side": "BUY",
          "price": "0.5"
        }

    API TradeResponse format:
        {
          "id": "unique_trade_id",
          "market": "condition_id",
          "asset_id": "token_id",
          "trader": "0x...",
          "side": "BUY",
          "size": Decimal("1.5"),  # Number of tokens
          "price": Decimal("0.65"),  # Price per token
          "timestamp": datetime(...),
          "asset_ticker": "YES/NO"
        }
    """
    trader_address = trader_address.lower()
    maker = graph_trade["maker"].lower()
    taker = graph_trade["taker"].lower()

    # Determine trader's role (maker or taker)
    is_maker = trader_address == maker

    # Extract amounts (convert from 6 decimals to Decimal)
    maker_amount = Decimal(graph_trade["makerAmountFilled"]) / Decimal("1000000")
    taker_amount = Decimal(graph_trade["takerAmountFilled"]) / Decimal("1000000")

    # Determine side based on role
    if is_maker:
        side = graph_trade["side"]  # BUY or SELL
    else:
        # Taker takes opposite side of maker
        side = "SELL" if graph_trade["side"] == "BUY" else "BUY"

    # Pick the conditional token (non-USDC asset).
    # In Polymarket's CTF Exchange, one side is USDC (asset_id="0")
    # and the other is the conditional token we need for market matching.
    # The old logic picked asset_id by trader role, which grabbed "0"
    # whenever the trader was on the USDC side — orphaning 48% of trades.
    maker_asset = graph_trade["makerAssetId"]
    taker_asset = graph_trade["takerAssetId"]
    maker_is_token = maker_asset and maker_asset != "0"
    taker_is_token = taker_asset and taker_asset != "0"

    if maker_is_token and not taker_is_token:
        asset_id = maker_asset
        size = maker_amount
    elif taker_is_token and not maker_is_token:
        asset_id = taker_asset
        size = taker_amount
    elif maker_is_token and taker_is_token:
        # Both non-zero (token-for-token swap): use trader's role
        asset_id = maker_asset if is_maker else taker_asset
        size = maker_amount if is_maker else taker_amount
    else:
        # Both zero — shouldn't happen, but don't crash
        asset_id = "0"
        size = maker_amount if is_maker else taker_amount

    # Price from Graph is in decimal odds format (can be > 1 for underdogs)
    # Convert to probability format (0-1 range) expected by TradeResponse
    price = Decimal(graph_trade["price"])
    if price > 1:
        # Convert decimal odds to implied probability
        price = Decimal("1") / price

    # Timestamp (Unix timestamp to datetime)
    timestamp = datetime.fromtimestamp(int(graph_trade["timestamp"]))

    # Market ID: Resolve condition_id from token_catalog if available
    if token_to_condition and asset_id in token_to_condition:
        market_id = token_to_condition[asset_id]
    else:
        market_id = f"graph_{graph_trade['transactionHash']}_{asset_id}"
        if token_to_condition is not None:
            logger.debug(f"Token {asset_id} not in catalog, using synthetic market_id")

    # Asset ticker: Determine YES/NO from asset_id parity
    # In Polymarket CTF: even assetId = NO, odd assetId = YES
    try:
        asset_id_int = int(asset_id)
        asset_ticker = "YES" if asset_id_int % 2 == 1 else "NO"
    except (ValueError, TypeError):
        asset_ticker = "UNKNOWN"

    # Create TradeResponse
    return TradeResponse(
        id=graph_trade["id"],
        market=market_id,
        asset_id=asset_id,
        trader=trader_address,
        side=side,
        size=size,
        price=price,
        timestamp=timestamp,
        asset_ticker=asset_ticker,
    )


def extract_condition_id_from_asset_id(asset_id: str) -> str:
    """Extract condition_id from Polymarket asset_id.

    Polymarket uses CTF (Conditional Token Framework) where:
    - assetId = hash(conditionId, outcomeIndex)
    - We need to reverse this to get conditionId

    Note: This may require additional data or heuristics.
    For now, returns a placeholder.

    Args:
        asset_id: Token asset ID from Graph

    Returns:
        Condition ID (market identifier)
    """
    # TODO: Implement proper extraction if needed
    # May need to maintain a mapping or query additional data
    return f"condition_from_{asset_id}"
