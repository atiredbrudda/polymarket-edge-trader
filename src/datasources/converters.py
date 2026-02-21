"""Converters for transforming JBecker dataset data to internal formats."""

from datetime import datetime, timezone
from decimal import Decimal

from src.api.models import TradeResponse


_POLYGON_BLOCK_ANCHORS: list[tuple[int, int]] = [
    (40_000_000, 1678035645),
    (50_000_000, 1700108689),
    (60_000_000, 1722368382),
    (70_000_000, 1744013119),
    (80_000_000, 1765105043),
]


def block_number_to_timestamp(block_number: int) -> datetime:
    anchors = _POLYGON_BLOCK_ANCHORS

    for i in range(len(anchors) - 1):
        b0, t0 = anchors[i]
        b1, t1 = anchors[i + 1]
        if b0 <= block_number <= b1:
            frac = (block_number - b0) / (b1 - b0)
            unix_ts = t0 + frac * (t1 - t0)
            return datetime.fromtimestamp(unix_ts, tz=timezone.utc).replace(tzinfo=None)

    if block_number < anchors[0][0]:
        b0, t0 = anchors[0]
        b1, t1 = anchors[1]
    else:
        b0, t0 = anchors[-2]
        b1, t1 = anchors[-1]

    frac = (block_number - b0) / (b1 - b0)
    unix_ts = t0 + frac * (t1 - t0)
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).replace(tzinfo=None)


def jbecker_trade_to_api_response(
    jbecker_trade: dict, trader_address: str
) -> TradeResponse:
    """Convert JBecker Parquet trade to API TradeResponse format.

    Handles the actual JBecker parquet schema (snake_case columns):
        block_number, transaction_hash, log_index, order_hash,
        maker, taker, maker_asset_id, taker_asset_id,
        maker_amount, taker_amount, fee, timestamp,
        _fetched_at, _contract

    Note: The parquet data does NOT contain side, price, or a unique id field.
    These are derived: price = maker_amount / taker_amount (USDC per token),
    side is inferred from maker/taker role, id from transaction_hash + log_index.
    Timestamp may be None — falls back to _fetched_at.
    """
    trader_address = trader_address.lower()
    maker = jbecker_trade["maker"].lower()
    taker = jbecker_trade["taker"].lower()

    is_maker = trader_address == maker

    maker_amount = Decimal(str(jbecker_trade["maker_amount"])) / Decimal("1000000")
    taker_amount = Decimal(str(jbecker_trade["taker_amount"])) / Decimal("1000000")

    if is_maker:
        size = maker_amount
        asset_id = str(jbecker_trade["maker_asset_id"])
        side = "SELL"
    else:
        size = taker_amount
        asset_id = str(jbecker_trade["taker_asset_id"])
        side = "BUY"

    if taker_amount > 0 and maker_amount > 0:
        price = maker_amount / taker_amount
    else:
        price = Decimal("0.5")

    if price <= 0 or price >= 1:
        price = Decimal("1") - price if price >= 1 else Decimal("0.5")
    if price <= 0 or price >= 1:
        price = Decimal("0.5")

    timestamp: datetime | None = None
    block_number = jbecker_trade.get("block_number")
    if block_number is not None:
        try:
            timestamp = block_number_to_timestamp(int(block_number))
        except (ValueError, TypeError):
            pass

    if timestamp is None:
        fetched = jbecker_trade.get("_fetched_at")
        if fetched is not None:
            try:
                if hasattr(fetched, "to_pydatetime"):
                    timestamp = fetched.to_pydatetime().replace(tzinfo=None)
                else:
                    timestamp = datetime.fromisoformat(str(fetched)).replace(tzinfo=None)
            except Exception:
                timestamp = datetime(2024, 1, 1)
        else:
            timestamp = datetime(2024, 1, 1)

    if timestamp is None:
        timestamp = datetime(2024, 1, 1)

    tx_hash = str(jbecker_trade.get("transaction_hash", "unknown"))
    log_index = str(jbecker_trade.get("log_index", "0"))
    trade_id = f"jbecker_{tx_hash}_{log_index}"

    market_id = asset_id

    try:
        asset_id_int = int(asset_id)
        asset_ticker = "YES" if asset_id_int % 2 == 1 else "NO"
    except (ValueError, TypeError):
        asset_ticker = "UNKNOWN"

    return TradeResponse(
        id=trade_id,
        market=market_id,
        trader=trader_address,
        side=side,
        size=size,
        price=price,
        timestamp=timestamp,
        asset_ticker=asset_ticker,
    )
