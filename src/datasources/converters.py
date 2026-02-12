"""Converters for transforming JBecker dataset data to internal formats."""

from datetime import datetime
from decimal import Decimal

from src.api.models import TradeResponse


def jbecker_trade_to_api_response(jbecker_trade: dict, trader_address: str) -> TradeResponse:
    """Convert JBecker Parquet trade to API TradeResponse format.

    This allows JBecker trades to be processed by existing pipeline logic
    without code changes, maintaining compatibility with Graph and API sources.

    Args:
        jbecker_trade: Trade dict from JBecker dataset (DuckDB query result)
        trader_address: The trader address we're querying for

    Returns:
        TradeResponse compatible with existing pipeline

    JBecker trade format:
        {
          "id": "0x..._0x...",
          "maker": "0x...",
          "taker": "0x...",
          "makerAmountFilled": "1500000",  # 6 decimals (USDC)
          "takerAmountFilled": "3000000",
          "makerAssetId": "123457",  # Token ID
          "takerAssetId": "789012",
          "fee": "1000",
          "timestamp": 1704067200,  # Unix timestamp
          "blockNumber": 50000000,
          "transactionHash": "0xabcdef...",
          "orderHash": "0xfedcba...",
          "side": "BUY",
          "price": "0.65",
          "_fetched_at": "2024-01-01T00:00:00",
          "_contract": "ctf_exchange"
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

    Raises:
        ValidationError: If price is outside (0,1) exclusive range (from TradeResponse validator)

    Examples:
        >>> trade = {
        ...     "id": "0x123_0x456",
        ...     "maker": "0xabc...",
        ...     "taker": "0xdef...",
        ...     "makerAmountFilled": "1500000",
        ...     "takerAmountFilled": "3000000",
        ...     "makerAssetId": "123",
        ...     "takerAssetId": "456",
        ...     "timestamp": 1704067200,
        ...     "transactionHash": "0xabc...",
        ...     "side": "BUY",
        ...     "price": "0.65"
        ... }
        >>> result = jbecker_trade_to_api_response(trade, "0xabc...")
        >>> result.size
        Decimal('1.5')
        >>> result.side
        'BUY'
    """
    # Normalize addresses for case-insensitive matching (EIP-55 compliance)
    trader_address = trader_address.lower()
    maker = jbecker_trade["maker"].lower()
    taker = jbecker_trade["taker"].lower()

    # Determine trader's role (maker or taker)
    is_maker = (trader_address == maker)

    # Convert amounts from 6-decimal integers to Decimal
    # IMPORTANT: Wrap in str() first to handle both string and numeric types from DuckDB
    maker_amount = Decimal(str(jbecker_trade["makerAmountFilled"])) / Decimal("1000000")
    taker_amount = Decimal(str(jbecker_trade["takerAmountFilled"])) / Decimal("1000000")

    # Determine trade details based on role
    if is_maker:
        # Trader is maker - they provided makerAmount
        size = maker_amount
        asset_id = jbecker_trade["makerAssetId"]
        # Side from JBecker already indicates maker's direction
        side = jbecker_trade["side"]  # BUY or SELL
    else:
        # Trader is taker - they provided takerAmount
        size = taker_amount
        asset_id = jbecker_trade["takerAssetId"]
        # Taker takes opposite side of maker
        side = "SELL" if jbecker_trade["side"] == "BUY" else "BUY"

    # Parse price (do NOT catch ValueError - let TradeResponse validator handle invalid prices)
    price = Decimal(str(jbecker_trade["price"]))

    # Convert timestamp from Unix timestamp to datetime
    timestamp = datetime.fromtimestamp(int(jbecker_trade["timestamp"]))

    # Market ID: Use transaction hash + asset_id as unique identifier
    # This matches the pattern from graph_trade_to_api_response
    market_id = f"jbecker_{jbecker_trade['transactionHash']}_{asset_id}"

    # Asset ticker: Determine YES/NO from asset_id parity
    # In Polymarket CTF: even assetId = NO, odd assetId = YES
    try:
        asset_id_int = int(asset_id)
        asset_ticker = "YES" if asset_id_int % 2 == 1 else "NO"
    except (ValueError, TypeError):
        asset_ticker = "UNKNOWN"

    # Create TradeResponse (Pydantic validation happens here)
    return TradeResponse(
        id=jbecker_trade["id"],
        market=market_id,
        asset_id=str(asset_id),
        trader=trader_address,
        side=side,
        size=size,
        price=price,
        timestamp=timestamp,
        asset_ticker=asset_ticker,
    )
