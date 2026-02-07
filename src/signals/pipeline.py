"""Orchestration layer for signal detection pipeline.

This module connects the pure detection functions (src.signals.detection) to the database layer.
It detects expert consensus, calculates confidence scores, persists signal snapshots, and provides
ranked signal output for Phase 6 alerting.

Pipeline flow:
1. Query expert positions for market
2. Query latest expertise scores for those traders
3. Call detect_consensus() to find expert agreement
4. Calculate confidence scores for each consensus
5. Classify first-movers and followers
6. Persist SignalSnapshot (append-only INSERT)
7. Handle "signal lost" detection (inactive snapshots)
8. Return SignalResult dataclass

Design principles:
- Append-only signal history (INSERT new rows on each run)
- Batch processing for efficiency (refresh_all_signals)
- Time-window filtering for 1h/6h/24h views
- Herding stub deferred per user decision
"""

from dataclasses import dataclass
from datetime import datetime, UTC
from decimal import Decimal

from sqlalchemy.orm import Session

from src.db.models import SignalSnapshot, ExpertiseScore
from src.signals.detection import detect_consensus, identify_first_mover, classify_followers
from src.signals.confidence import calculate_confidence_score
from src.signals.queries import (
    get_expert_positions_for_market,
    get_markets_by_expert_activity,
    get_latest_signals,
    get_signal_history,
)


@dataclass(frozen=True)
class SignalResult:
    """Immutable signal detection result.

    Attributes:
        market_id: Market identifier
        direction: Consensus direction ("LONG" or "SHORT")
        confidence_score: Confidence score (0-100)
        expert_count: Number of experts agreeing on this direction
        total_experts_in_market: Total unique experts in market (across all directions)
        agreement_percentage: Percentage of experts agreeing
        expert_addresses: List of expert wallet addresses in this direction
        first_mover_address: Earliest entrant address, or None if no timestamps
        follower_classifications: Dict mapping address -> classification label
        herding_status: Always "not_analyzed" in Phase 5 (stub)
        status: "active" or "inactive"
        computed_at: Timestamp of signal detection
    """

    market_id: str
    direction: str
    confidence_score: Decimal
    expert_count: int
    total_experts_in_market: int
    agreement_percentage: Decimal
    expert_addresses: list[str]
    first_mover_address: str | None
    follower_classifications: dict[str, str]
    herding_status: str
    status: str
    computed_at: datetime


def refresh_market_signal(
    session: Session,
    market_id: str,
    min_experts: int = 3,
    min_agreement_pct: Decimal = Decimal("75"),
    now: datetime | None = None,
) -> list[SignalResult]:
    """Refresh signal detection for a single market.

    Pipeline flow:
    1. Query expert positions for the market
    2. Query latest expertise scores for traders in those positions
    3. Call detect_consensus() from detection.py
    4. For each ConsensusResult:
       a. Calculate confidence score
       b. Classify followers
       c. Determine status (active if confidence > 0)
       d. Persist SignalSnapshot (append-only INSERT)
       e. Build SignalResult dataclass
    5. Handle "signal lost" case: Create inactive snapshot if previously active
    6. Commit and return results

    Args:
        session: SQLAlchemy session
        market_id: Market condition_id
        min_experts: Minimum number of experts required for consensus (default: 3)
        min_agreement_pct: Minimum agreement percentage (default: 75)
        now: Optional current timestamp (default: datetime.now(UTC))

    Returns:
        List of SignalResult objects (one per detected consensus direction)
        Empty list if no consensus detected

    Example:
        # Refresh signal for a market
        results = refresh_market_signal(session, "0xMarket123")

        # Check for LONG consensus with custom thresholds
        results = refresh_market_signal(
            session, "0xMarket123", min_experts=5, min_agreement_pct=Decimal("80")
        )
    """
    if now is None:
        now = datetime.now(UTC)

    # 1. Query expert positions for the market
    positions = get_expert_positions_for_market(session, market_id)

    if not positions:
        # No expert positions, check for signal lost
        _handle_signal_lost_all_directions(session, market_id, now)
        session.commit()
        return []

    # 2. Query latest expertise scores for traders in those positions
    # Use max(computed_at) subquery to get latest score per trader
    from sqlalchemy import select, func

    trader_addresses = {p.trader_address for p in positions}

    subquery = (
        select(
            ExpertiseScore.trader_address,
            func.max(ExpertiseScore.computed_at).label("max_computed_at"),
        )
        .where(ExpertiseScore.trader_address.in_(trader_addresses))
        .group_by(ExpertiseScore.trader_address)
        .subquery()
    )

    query = (
        select(ExpertiseScore)
        .join(
            subquery,
            (ExpertiseScore.trader_address == subquery.c.trader_address)
            & (ExpertiseScore.computed_at == subquery.c.max_computed_at),
        )
    )

    result = session.execute(query)
    expert_scores_list = result.scalars().all()

    # Build dict {trader_address: raw_score}
    expert_scores = {score.trader_address: score.raw_score for score in expert_scores_list}

    # 3. Call detect_consensus
    consensus_results = detect_consensus(positions, expert_scores, min_experts, min_agreement_pct)

    # Track which directions have active consensus
    active_directions = {result.direction for result in consensus_results}

    # 4. Process each ConsensusResult
    signal_results = []
    for consensus in consensus_results:
        # a. Calculate confidence score
        confidence = calculate_confidence_score(
            consensus.expert_positions, consensus.total_experts_in_market, min_experts
        )

        # b. Classify followers
        follower_classifications = classify_followers(
            consensus.expert_positions, consensus.first_mover_address
        )

        # c. Determine status
        status = "active" if confidence > 0 else "inactive"

        # d. Create SignalSnapshot ORM object and session.add()
        expert_addresses = [p.trader_address for p in consensus.expert_positions]
        expert_addresses_str = ",".join(sorted(set(expert_addresses)))

        snapshot = SignalSnapshot(
            market_id=market_id,
            direction=consensus.direction,
            confidence_score=confidence,
            expert_count=consensus.expert_count,
            total_experts_in_market=consensus.total_experts_in_market,
            agreement_percentage=consensus.agreement_percentage,
            expert_addresses_json=expert_addresses_str,
            first_mover_address=consensus.first_mover_address,
            status=status,
            computed_at=now,
        )
        session.add(snapshot)

        # e. Build SignalResult dataclass
        signal_result = SignalResult(
            market_id=market_id,
            direction=consensus.direction,
            confidence_score=confidence,
            expert_count=consensus.expert_count,
            total_experts_in_market=consensus.total_experts_in_market,
            agreement_percentage=consensus.agreement_percentage,
            expert_addresses=sorted(set(expert_addresses)),
            first_mover_address=consensus.first_mover_address,
            follower_classifications=follower_classifications,
            herding_status="not_analyzed",  # Stub per user decision
            status=status,
            computed_at=now,
        )
        signal_results.append(signal_result)

    # 5. Handle "signal lost" case
    _handle_signal_lost(session, market_id, active_directions, now)

    # 6. Commit
    session.commit()

    # 7. Return results
    return signal_results


def _handle_signal_lost(
    session: Session, market_id: str, active_directions: set[str], now: datetime
) -> None:
    """Create inactive snapshots for previously active directions that lost consensus.

    Args:
        session: SQLAlchemy session
        market_id: Market condition_id
        active_directions: Set of directions currently active ("LONG", "SHORT")
        now: Current timestamp
    """
    # Query signal history to find previously active directions
    history = get_signal_history(session, market_id, limit=2)

    if not history:
        return

    # Get most recent snapshot per direction
    latest_by_direction = {}
    for snapshot in history:
        if snapshot.direction not in latest_by_direction:
            latest_by_direction[snapshot.direction] = snapshot

    # Check for lost signals
    for direction, snapshot in latest_by_direction.items():
        # If previously active but no longer in active_directions, mark as lost
        if snapshot.status == "active" and direction not in active_directions:
            inactive_snapshot = SignalSnapshot(
                market_id=market_id,
                direction=direction,
                confidence_score=Decimal("0"),
                expert_count=0,
                total_experts_in_market=0,
                agreement_percentage=Decimal("0"),
                expert_addresses_json="",
                first_mover_address=None,
                status="inactive",
                computed_at=now,
            )
            session.add(inactive_snapshot)


def _handle_signal_lost_all_directions(
    session: Session, market_id: str, now: datetime
) -> None:
    """Create inactive snapshots for all previously active directions when no expert positions exist.

    Args:
        session: SQLAlchemy session
        market_id: Market condition_id
        now: Current timestamp
    """
    # Query signal history to find previously active directions
    history = get_signal_history(session, market_id, limit=2)

    if not history:
        return

    # Get most recent snapshot per direction
    latest_by_direction = {}
    for snapshot in history:
        if snapshot.direction not in latest_by_direction:
            latest_by_direction[snapshot.direction] = snapshot

    # Create inactive snapshots for all previously active directions
    for direction, snapshot in latest_by_direction.items():
        if snapshot.status == "active":
            inactive_snapshot = SignalSnapshot(
                market_id=market_id,
                direction=direction,
                confidence_score=Decimal("0"),
                expert_count=0,
                total_experts_in_market=0,
                agreement_percentage=Decimal("0"),
                expert_addresses_json="",
                first_mover_address=None,
                status="inactive",
                computed_at=now,
            )
            session.add(inactive_snapshot)


def refresh_all_signals(
    session: Session,
    window_hours: int = 24,
    min_experts: int = 3,
    min_agreement_pct: Decimal = Decimal("75"),
    now: datetime | None = None,
) -> list[SignalResult]:
    """Refresh signal detection for all markets with expert activity.

    Pipeline flow:
    1. Query markets with expert activity in time window
    2. For each market, call refresh_market_signal()
    3. Collect all SignalResults
    4. Sort by confidence_score DESC

    Args:
        session: SQLAlchemy session
        window_hours: Time window in hours for expert activity (default: 24)
        min_experts: Minimum number of experts required for consensus (default: 3)
        min_agreement_pct: Minimum agreement percentage (default: 75)
        now: Optional current timestamp (default: datetime.now(UTC))

    Returns:
        List of SignalResult objects sorted by confidence_score DESC

    Example:
        # Refresh all markets with activity in last 24 hours
        results = refresh_all_signals(session)

        # Refresh with custom thresholds and 6-hour window
        results = refresh_all_signals(
            session, window_hours=6, min_experts=5, min_agreement_pct=Decimal("80")
        )
    """
    if now is None:
        now = datetime.now(UTC)

    # 1. Get markets with expert activity
    markets = get_markets_by_expert_activity(session, window_hours, min_experts=1)

    # 2. Refresh signal for each market
    all_results = []
    for market_id, expert_count, latest_activity in markets:
        results = refresh_market_signal(session, market_id, min_experts, min_agreement_pct, now)
        all_results.extend(results)

    # 3. Sort by confidence_score DESC
    all_results.sort(key=lambda x: x.confidence_score, reverse=True)

    return all_results


def get_ranked_signals(
    session: Session,
    window_hours: int | None = None,
    min_confidence: Decimal | None = None,
    limit: int = 50,
) -> list[SignalResult]:
    """Query ranked signals with optional time-window and confidence filters.

    Provides time-window filtered views (1h/6h/24h) for SGNL-04.

    Pipeline flow:
    1. Call get_latest_signals() to get active signals
    2. If window_hours provided, filter to markets with expert activity in that window
    3. Build SignalResult objects from SignalSnapshot ORM objects
    4. Return sorted by confidence_score DESC

    Args:
        session: SQLAlchemy session
        window_hours: Optional time window in hours for expert activity filter
        min_confidence: Optional minimum confidence_score filter (0-100)
        limit: Maximum number of entries to return (default: 50)

    Returns:
        List of SignalResult objects sorted by confidence_score DESC

    Example:
        # Get top 20 active signals
        signals = get_ranked_signals(session, limit=20)

        # Get signals from markets with activity in last 1 hour
        hot_signals = get_ranked_signals(session, window_hours=1)

        # Get high confidence signals (>80)
        strong_signals = get_ranked_signals(session, min_confidence=Decimal("80"))
    """
    # 1. Get latest active signals
    snapshots = get_latest_signals(session, status="active", min_confidence=min_confidence, limit=limit)

    # 2. If window_hours provided, filter to markets with recent expert activity
    if window_hours is not None:
        active_market_ids = {
            market_id
            for market_id, expert_count, latest_activity in get_markets_by_expert_activity(
                session, window_hours, min_experts=1
            )
        }
        snapshots = [s for s in snapshots if s.market_id in active_market_ids]

    # 3. Build SignalResult objects
    results = []
    for snapshot in snapshots:
        # Parse expert_addresses from comma-separated string
        expert_addresses = (
            sorted(snapshot.expert_addresses_json.split(",")) if snapshot.expert_addresses_json else []
        )

        # Build follower_classifications from snapshot metadata
        # Note: Full classification requires re-querying positions, simplified here
        follower_classifications = {}
        if snapshot.first_mover_address:
            follower_classifications[snapshot.first_mover_address] = "first_mover"

        result = SignalResult(
            market_id=snapshot.market_id,
            direction=snapshot.direction,
            confidence_score=snapshot.confidence_score,
            expert_count=snapshot.expert_count,
            total_experts_in_market=snapshot.total_experts_in_market,
            agreement_percentage=snapshot.agreement_percentage,
            expert_addresses=expert_addresses,
            first_mover_address=snapshot.first_mover_address,
            follower_classifications=follower_classifications,
            herding_status="not_analyzed",  # Stub per user decision
            status=snapshot.status,
            computed_at=snapshot.computed_at,
        )
        results.append(result)

    # Already sorted by confidence in get_latest_signals, but ensure DESC order
    results.sort(key=lambda x: x.confidence_score, reverse=True)

    return results


def assess_herding(signal_result: SignalResult) -> str:
    """Assess herding behavior for a signal (STUB).

    Herding detection deferred per user decision. All expert positions count equally
    regardless of timing proximity. See Phase 5 CONTEXT.md for details.

    This function exists to formally satisfy SGNL-03 with a minimal stub. Full
    implementation would require temporal clustering analysis of position entry times.

    Args:
        signal_result: SignalResult object to assess

    Returns:
        Always returns "not_analyzed" in Phase 5

    Example:
        >>> signal = refresh_market_signal(session, "0xMarket123")[0]
        >>> assess_herding(signal)
        'not_analyzed'
    """
    return "not_analyzed"
