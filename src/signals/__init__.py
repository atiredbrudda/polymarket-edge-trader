"""Signal detection for expert consensus and herding analysis.

This module provides pure functions for detecting when multiple expert traders
converge on a market position (consensus detection) and analyzing their timing
patterns (first-mover identification, follower classification).

Core capabilities:
- Consensus detection: Identify markets where 3+ experts agree on direction
- Confidence scoring: 0-100 score combining agreement %, sample size, uniformity
- First-mover identification: Find earliest expert entry in a direction
- Follower classification: Distinguish first-mover, fast-follower, independent

Design principles:
- Pure functions, no state
- Duck-typed inputs (works with any object having the right attributes)
- All financial math uses Decimal, never float
- No SQLAlchemy imports (keeps module pure and decoupled)
"""

# Conditional imports to support parallel plan execution
# Plan 05-01 creates detection.py and confidence.py
# Plan 05-02 creates queries.py
# Both plans can run independently

__all__ = []

try:
    from src.signals.detection import (
        detect_consensus,
        identify_first_mover,
        classify_followers,
        ConsensusResult,
    )
    __all__.extend([
        "detect_consensus",
        "identify_first_mover",
        "classify_followers",
        "ConsensusResult",
    ])
except ImportError:
    pass

try:
    from src.signals.confidence import calculate_confidence_score
    __all__.append("calculate_confidence_score")
except ImportError:
    pass

try:
    from src.signals.queries import (
        get_latest_signals,
        get_signal_history,
        get_expert_positions_for_market,
        get_markets_by_expert_activity,
    )
    __all__.extend([
        "get_latest_signals",
        "get_signal_history",
        "get_expert_positions_for_market",
        "get_markets_by_expert_activity",
    ])
except ImportError:
    pass
