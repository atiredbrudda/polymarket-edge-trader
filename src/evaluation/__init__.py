"""
Performance metrics evaluation for trader analysis.

This module provides pure functions for calculating trader performance metrics
including realized/unrealized PnL, win rates, and volume aggregation.
"""

from src.evaluation.metrics import (
    calculate_realized_pnl,
    calculate_win_rate,
    calculate_total_volume,
    calculate_unrealized_pnl,
    aggregate_trader_metrics,
)

__all__ = [
    "calculate_realized_pnl",
    "calculate_win_rate",
    "calculate_total_volume",
    "calculate_unrealized_pnl",
    "aggregate_trader_metrics",
]
