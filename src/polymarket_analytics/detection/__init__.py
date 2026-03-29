"""Detection module for consensus signal detection.

This module provides functions for detecting when multiple Q5 (top quintile) traders
are positioned in the same market with the same direction.

Core functionality:
- detect_convergence: Find markets where ≥2 Q5 traders converge on same direction
- upsert_signal: Insert or update individual signal with timestamp tracking
- upsert_signals_batch: Batch process convergence results with progress bar
"""

from .convergence import detect_convergence
from .writer import upsert_signal, upsert_signals_batch

__all__ = ["detect_convergence", "upsert_signal", "upsert_signals_batch"]
