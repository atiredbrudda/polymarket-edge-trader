#!/usr/bin/env python3
"""Profiling wrapper for backfill process using cProfile.

This script wraps the backfill_trader function with cProfile profiling
to identify performance bottlenecks in the backfill process.

Usage:
    python scripts/profile_backfill.py --niche esports --db-path polymarket.db

Output:
    - backfill.prof: Raw profiling data (can be analyzed with pstats/snakeviz)
    - Console output with component timing breakdown
"""

import argparse
import asyncio
import cProfile
import pstats
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from pstats import SortKey
from typing import Any, Dict, Optional


class BackfillProfiler:
    """Wrapper class for profiling backfill execution with cProfile and component timing."""

    def __init__(self, output_file: str = "backfill.prof"):
        """Initialize profiler.

        Args:
            output_file: Path to save .prof file for later analysis
        """
        self.output_file = output_file
        self.component_times: Dict[str, float] = {}
        self.pr = cProfile.Profile()

    @contextmanager
    def time_component(self, name: str):
        """Time a specific component (API, dedup, processing, DB).

        Args:
            name: Component name for tracking
        """
        start = time.perf_counter()
        yield
        elapsed = time.perf_counter() - start
        self.component_times[name] = self.component_times.get(name, 0) + elapsed
        print(f"  [{name}]: {elapsed:.3f}s")

    def run(self, backfill_func, *args, **kwargs):
        """Run backfill with full profiling.

        Args:
            backfill_func: The backfill function to execute
            *args: Arguments to pass to backfill_func
            **kwargs: Keyword arguments to pass to backfill_func

        Returns:
            Result from backfill_func
        """
        self.pr.enable()
        try:
            result = backfill_func(*args, **kwargs)
        finally:
            self.pr.disable()
            self.pr.dump_stats(self.output_file)

        # Print component breakdown
        print("\n=== COMPONENT TIME BREAKDOWN ===")
        total = sum(self.component_times.values())
        for name, elapsed in sorted(
            self.component_times.items(), key=lambda x: x[1], reverse=True
        ):
            pct = (elapsed / total * 100) if total > 0 else 0
            print(f"{name:20s}: {elapsed:8.2f}s ({pct:5.1f}%)")

        # Print function-level stats
        print("\n=== TOP 20 FUNCTIONS BY CUMULATIVE TIME ===")
        stats = pstats.Stats(self.output_file)
        stats.strip_dirs().sort_stats(SortKey.CUMULATIVE).print_stats(20)

        return result

    def print_component_breakdown(self):
        """Print detailed component timing breakdown."""
        if not self.component_times:
            print("No component timing data collected.")
            return

        print("\n=== DETAILED COMPONENT BREAKDOWN ===")
        total = sum(self.component_times.values())
        print(f"{'Component':<25} {'Time (s)':>12} {'% of Total':>12}")
        print("-" * 49)
        for name, elapsed in sorted(
            self.component_times.items(), key=lambda x: x[1], reverse=True
        ):
            pct = (elapsed / total * 100) if total > 0 else 0
            print(f"{name:<25} {elapsed:>12.3f} {pct:>11.1f}%")
        print("-" * 49)
        print(f"{'TOTAL':<25} {total:>12.3f} {100.0:>11.1f}%")


def run_backfill_with_profiling(
    niche: str, db_path: str, output_file: Optional[str] = None
):
    """Run backfill process with profiling enabled.

    Args:
        niche: Market niche to backfill (e.g., 'esports')
        db_path: Path to SQLite database
        output_file: Path for .prof output file
    """
    # Import here to avoid circular imports and ensure we're profiling the actual execution
    from polymarket_analytics.commands.backfill import backfill_async
    from polymarket_analytics.cli import cli

    if output_file is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_file = f"backfill_{timestamp}.prof"

    profiler = BackfillProfiler(output_file=output_file)

    # Create a mock context object for the backfill
    class MockContext:
        def __init__(self, niche: str):
            self.obj = {
                "niche": niche,
                "config": None,  # Will be loaded by backfill_async
            }

    ctx = MockContext(niche)

    def run_backfill():
        """Wrapper to run async backfill synchronously."""
        return asyncio.run(backfill_async(ctx, db_path))

    print(f"Starting profiled backfill for niche: {niche}")
    print(f"Database: {db_path}")
    print(f"Output file: {output_file}")
    print("-" * 50)

    return profiler.run(run_backfill)


def main():
    """CLI entry point for profiled backfill execution."""
    parser = argparse.ArgumentParser(
        description="Run backfill with cProfile profiling to identify bottlenecks"
    )
    parser.add_argument(
        "--niche",
        type=str,
        default="esports",
        help="Market niche to backfill (default: esports)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="polymarket.db",
        help="Path to SQLite database (default: polymarket.db)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output .prof file path (default: backfill_<timestamp>.prof)",
    )

    args = parser.parse_args()

    try:
        run_backfill_with_profiling(
            niche=args.niche, db_path=args.db_path, output_file=args.output
        )
        print("\n=== PROFILING COMPLETE ===")
        print(f"Profile data saved to: {args.output or 'backfill_<timestamp>.prof'}")
        print("\nTo analyze results:")
        print("  python -m pstats backfill_*.prof")
        print("  snakeviz backfill_*.prof  # Web-based visualization")
    except Exception as e:
        print(f"\nError during profiled backfill: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
