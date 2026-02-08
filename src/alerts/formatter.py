"""Telegram HTML alert formatting for signal detection.

Transforms SignalResult data into rich, scannable Telegram push notifications using HTML parse mode.
"""

from html import escape
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.signals.pipeline import SignalResult
from src.db.models import Position


def format_signal_alert(
    event_type: str,
    market_question: str,
    signal: SignalResult,
    expert_positions: list[dict] | None = None,
) -> str:
    """Format signal data into Telegram HTML message.
    
    Args:
        event_type: Event type ("NEW", "STRENGTHENING", "WEAKENING", "LOST")
        market_question: Market question text
        signal: SignalResult dataclass with signal metadata
        expert_positions: Optional list of position dicts with keys:
            address, size, direction, avg_entry_price
    
    Returns:
        Formatted Telegram HTML string
        
    Example:
        >>> positions = [{"address": "0xabc...", "size": Decimal("100"), ...}]
        >>> alert = format_signal_alert("NEW", "Will Team A win?", signal, positions)
    """
    # Event type header mapping
    headers = {
        "NEW": "New Signal",
        "STRENGTHENING": "Signal Strengthened",
        "WEAKENING": "Signal Weakened",
        "LOST": "Signal Lost",
    }
    header = headers.get(event_type, "Signal Update")
    
    # Build message parts
    parts = []
    
    # Header
    parts.append(f"<b>{header}</b>\n")
    
    # Market question (HTML escaped)
    escaped_question = escape(market_question)
    parts.append(f"{escaped_question}\n")
    
    # Signal metrics
    parts.append(f"\n<b>Direction:</b> {signal.direction}")
    parts.append(f"<b>Confidence:</b> <code>{signal.confidence_score}</code>")
    parts.append(f"<b>Experts:</b> {signal.expert_count}/{signal.total_experts_in_market} ({signal.agreement_percentage}% agreement)\n")
    
    # First mover (if available)
    if signal.first_mover_address:
        truncated_first_mover = _truncate_address(signal.first_mover_address)
        parts.append(f"<b>First Mover:</b> <code>{truncated_first_mover}</code>")
        
        # Fast follower count
        fast_follower_count = sum(
            1 for classification in signal.follower_classifications.values()
            if classification == "fast_follower"
        )
        parts.append(f"<b>Fast Followers:</b> {fast_follower_count}\n")
    
    # Expert addresses
    parts.append("<b>Experts:</b>")
    expert_addrs = signal.expert_addresses[:5]  # First 5
    for addr in expert_addrs:
        truncated = _truncate_address(addr)
        parts.append(f"  <code>{truncated}</code>")
    
    # +N more indicator
    if len(signal.expert_addresses) > 5:
        remaining = len(signal.expert_addresses) - 5
        parts.append(f"  +{remaining} more")
    parts.append("")  # Blank line
    
    # Position sizes (if provided)
    if expert_positions:
        parts.append("<b>Positions:</b>")
        for pos in expert_positions:
            truncated = _truncate_address(pos["address"])
            size = pos["size"]
            direction = pos["direction"]
            parts.append(f"  <code>{truncated}</code>: {size} {direction}")
        parts.append("")  # Blank line
    
    # Polymarket link
    polymarket_url = f"https://polymarket.com/market/{signal.market_id}"
    parts.append(f'<a href="{polymarket_url}">View on Polymarket</a>')
    
    return "\n".join(parts)


def _truncate_address(address: str) -> str:
    """Truncate wallet address for readability.
    
    Args:
        address: Full wallet address (42 chars with 0x prefix)
        
    Returns:
        Truncated address: first 10 chars + "..." + last 6 chars
        
    Example:
        >>> _truncate_address("0xabcdef1234567890abcdef1234567890abcdef12")
        '0xabcdef12...cdef12'
    """
    if len(address) <= 18:
        return address
    return f"{address[:10]}...{address[-6:]}"


def get_expert_position_details(
    session: Session,
    market_id: str,
    expert_addresses: list[str],
) -> list[dict]:
    """Query Position table for expert addresses in a given market.
    
    Args:
        session: SQLAlchemy session
        market_id: Market condition_id
        expert_addresses: List of expert wallet addresses
        
    Returns:
        List of dicts with keys: address, size, direction, avg_entry_price
        
    Example:
        >>> positions = get_expert_position_details(session, "0xMarket123", ["0xExpert1"])
        >>> positions[0]["size"]
        Decimal('100.50')
    """
    if not expert_addresses:
        return []
    
    # Query positions for these experts in this market
    query = select(Position).where(
        Position.market_id == market_id,
        Position.trader_address.in_(expert_addresses),
    )
    
    result = session.execute(query)
    positions = result.scalars().all()
    
    # Convert to dict format
    return [
        {
            "address": pos.trader_address,
            "size": pos.size,
            "direction": pos.direction,
            "avg_entry_price": pos.avg_entry_price,
        }
        for pos in positions
    ]
