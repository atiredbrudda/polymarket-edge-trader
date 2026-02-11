"""CLI module for Polymarket Smart Money Tracker.

Provides command-line interface for market exploration, trader analysis,
signal monitoring, leaderboard queries, and automated polling.
"""

from src.cli.scheduler import run_sweep, run_polling_loop

__all__ = ["run_sweep", "run_polling_loop"]
