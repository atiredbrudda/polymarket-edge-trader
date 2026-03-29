"""Sanity check command to verify data quality before Phase 4 (Position Engine) runs.

This command runs 5 SQL validation queries to catch data quality issues early:
1. No synthetic market_ids in trades
2. All trades have market_entities with game set
3. Resolved positions exist in scoring window
4. Markets have outcomes set
5. Markets with outcomes have end_date set

Usage:
    polymarket --niche esports sanity-check [--db-path PATH] [--min-positions N]
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import click
from rich.console import Console

from src.polymarket_analytics.cli import cli
from src.polymarket_analytics.config.loader import load_niche_config
from src.polymarket_analytics.db.schema import init_database


console = Console()


class SanityCheckResult:
    """Result of a single sanity check."""

    def __init__(
        self, name: str, expected: str, actual: Any, passed: bool, details: str = ""
    ):
        self.name = name
        self.expected = expected
        self.actual = actual
        self.passed = passed
        self.details = details


def run_sanity_checks(
    db: Any,
    niche: str,
    min_positions: Optional[int] = None,
) -> Tuple[List[SanityCheckResult], int]:
    """Run all 5 sanity checks and return results.

    Args:
        db: sqlite-utils Database instance
        niche: Niche slug for config lookup
        min_positions: Minimum resolved positions required (from config if not provided)

    Returns:
        Tuple of (list of results, count of failed checks)
    """
    results: List[SanityCheckResult] = []
    failed_count = 0

    # Load niche config for min_positions if not provided
    if min_positions is None:
        config_path = (
            Path(__file__).parent.parent.parent.parent / "niches" / f"{niche}.yaml"
        )
        try:
            config = load_niche_config(config_path)
            min_positions = config.min_positions
        except Exception:
            min_positions = 30  # Default fallback

    console.print("[bold]=== Running Sanity Checks ===[/bold]")
    console.print("These checks must pass before running build-positions and score")
    console.print()

    # Check 1: No synthetic market_ids
    # Expected: 0 (all market_ids should start with '0x')
    try:
        query = "SELECT COUNT(*) as count FROM trades WHERE market_id NOT LIKE '0x%'"
        result = list(db.query(query))
        count = result[0]["count"] if result else 0
        passed = count == 0
        if passed:
            console.print(
                f"Check 1: No synthetic market_ids ............ [green]PASS[/green] ({count} synthetic IDs)"
            )
        else:
            console.print(
                f"Check 1: No synthetic market_ids ............ [red]FAIL[/red] ({count} synthetic IDs found)"
            )
            failed_count += 1
        results.append(
            SanityCheckResult(
                name="No synthetic market_ids",
                expected="0",
                actual=str(count),
                passed=passed,
                details="Run classify-tokens then re-run backfill if this fails",
            )
        )
    except Exception as e:
        console.print(
            f"Check 1: No synthetic market_ids ............ [red]ERROR[/red] ({e})"
        )
        failed_count += 1
        results.append(
            SanityCheckResult(
                name="No synthetic market_ids",
                expected="0",
                actual=f"ERROR: {e}",
                passed=False,
                details="Database error - check trades table exists",
            )
        )

    # Check 2: All trades have market_entities with game set
    # Expected: 0 (no NULL games)
    try:
        query = """
            SELECT COUNT(*) as count FROM trades t
            LEFT JOIN market_entities me ON me.condition_id = t.market_id
            WHERE me.game IS NULL
        """
        result = list(db.query(query))
        count = result[0]["count"] if result else 0
        passed = count == 0
        if passed:
            console.print(
                f"Check 2: All trades have game entity ........ [green]PASS[/green] ({count} NULL games)"
            )
        else:
            console.print(
                f"Check 2: All trades have game entity ........ [red]FAIL[/red] ({count} NULL games)"
            )
            failed_count += 1
        results.append(
            SanityCheckResult(
                name="All trades have game entity",
                expected="0",
                actual=str(count),
                passed=passed,
                details="Run entity extraction (pattern matcher + LLM fallback) for the niche if this fails",
            )
        )
    except Exception as e:
        console.print(
            f"Check 2: All trades have game entity ........ [red]ERROR[/red] ({e})"
        )
        failed_count += 1
        results.append(
            SanityCheckResult(
                name="All trades have game entity",
                expected="0",
                actual=f"ERROR: {e}",
                passed=False,
                details="Database error - check market_entities table exists",
            )
        )

    # Check 3: Resolved positions exist in scoring window
    # Expected: >= min_positions (default 30 for esports)
    try:
        query = """
            SELECT COUNT(*) as count FROM positions
            WHERE resolved = 1
              AND last_trade_timestamp >= datetime('now', '-30 days')
        """
        result = list(db.query(query))
        count = result[0]["count"] if result else 0
        passed = count >= min_positions
        if passed:
            console.print(
                f"Check 3: Resolved positions in window ....... [green]PASS[/green] ({count} positions, need {min_positions})"
            )
        else:
            console.print(
                f"Check 3: Resolved positions in window ....... [red]FAIL[/red] ({count} positions, need {min_positions})"
            )
            failed_count += 1
        results.append(
            SanityCheckResult(
                name="Resolved positions in window",
                expected=f">= {min_positions}",
                actual=str(count),
                passed=passed,
                details="Need more time for markets to resolve, or extend backfill window with Graph if this fails",
            )
        )
    except Exception as e:
        console.print(
            f"Check 3: Resolved positions in window ....... [red]ERROR[/red] ({e})"
        )
        failed_count += 1
        results.append(
            SanityCheckResult(
                name="Resolved positions in window",
                expected=f">= {min_positions}",
                actual=f"ERROR: {e}",
                passed=False,
                details="Database error - check positions table exists",
            )
        )

    # Check 4: Markets have outcomes set
    # Expected: > 0 (some markets resolved)
    try:
        query = "SELECT COUNT(*) as count FROM markets WHERE outcome IS NOT NULL"
        result = list(db.query(query))
        count = result[0]["count"] if result else 0
        passed = count > 0
        if passed:
            console.print(
                f"Check 4: Markets have outcomes set .......... [green]PASS[/green] ({count} markets)"
            )
        else:
            console.print(
                f"Check 4: Markets have outcomes set .......... [red]FAIL[/red] ({count} markets with outcome)"
            )
            failed_count += 1
        results.append(
            SanityCheckResult(
                name="Markets have outcomes set",
                expected="> 0",
                actual=str(count),
                passed=passed,
                details="Run resolve-outcomes command if this fails",
            )
        )
    except Exception as e:
        console.print(
            f"Check 4: Markets have outcomes set .......... [red]ERROR[/red] ({e})"
        )
        failed_count += 1
        results.append(
            SanityCheckResult(
                name="Markets have outcomes set",
                expected="> 0",
                actual=f"ERROR: {e}",
                passed=False,
                details="Database error - check markets table exists",
            )
        )

    # Check 5: Markets with outcomes have end_date set
    # Expected: 0 (no missing end_dates for resolved markets)
    try:
        query = """
            SELECT COUNT(*) as count FROM markets
            WHERE end_date IS NULL AND outcome IS NOT NULL
        """
        result = list(db.query(query))
        count = result[0]["count"] if result else 0
        passed = count == 0
        if passed:
            console.print(
                f"Check 5: Markets have end_date set .......... [green]PASS[/green] ({count} missing)"
            )
        else:
            console.print(
                f"Check 5: Markets have end_date set .......... [red]FAIL[/red] ({count} missing end_dates)"
            )
            failed_count += 1
        results.append(
            SanityCheckResult(
                name="Markets have end_date set",
                expected="0",
                actual=str(count),
                passed=passed,
                details="Run ingest-events to backfill end_dates from Gamma API if this fails",
            )
        )
    except Exception as e:
        console.print(
            f"Check 5: Markets have end_date set .......... [red]ERROR[/red] ({e})"
        )
        failed_count += 1
        results.append(
            SanityCheckResult(
                name="Markets have end_date set",
                expected="0",
                actual=f"ERROR: {e}",
                passed=False,
                details="Database error - check markets table exists",
            )
        )

    return results, failed_count


def print_summary(results: List[SanityCheckResult], failed_count: int) -> None:
    """Print summary of all checks and recommendations.

    Args:
        results: List of check results
        failed_count: Number of failed checks
    """
    console.print()
    console.print("[bold]=== Sanity Check Results ===[/bold]")

    for result in results:
        status = "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]"
        console.print(
            f"  {result.name} ............ {status} (expected: {result.expected}, actual: {result.actual})"
        )

    console.print()

    if failed_count == 0:
        console.print(
            f"  [green]All checks passed: {len(results)}/{len(results)}[/green]"
        )
        console.print()
        console.print("[bold green]SAFE TO PROCEED TO SCORING[/bold green]")
    else:
        console.print(
            f"  [red]Checks passed: {len(results) - failed_count}/{len(results)}[/red]"
        )
        console.print()
        console.print("[bold red]DO NOT PROCEED TO SCORING[/bold red]")
        console.print("Fix the following issues first:")
        for result in results:
            if not result.passed:
                console.print(f"  - {result.name}: {result.details}")
        console.print()
        console.print(
            "[yellow]Address the issues above before running build-positions or score.[/yellow]"
        )


@cli.command()
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database (default: data/analytics.db)",
)
@click.option(
    "--min-positions",
    type=int,
    default=None,
    help="Minimum resolved positions required (default: from niche config)",
)
@click.pass_context
def sanity_check(ctx, db_path: str, min_positions: Optional[int]) -> None:
    """Run sanity checks to verify data quality before scoring.

    This command runs 5 SQL validation queries to ensure:
    1. No synthetic market_ids in trades (token catalog was complete)
    2. All trades have market_entities with game set (entity extraction ran)
    3. Resolved positions exist in scoring window (enough data for scoring)
    4. Markets have outcomes set (some markets resolved)
    5. Markets with outcomes have end_date set (needed for CLV calculation)

    Args:
        ctx: Click context with niche and config
        db_path: Path to SQLite database
        min_positions: Minimum resolved positions required
    """
    niche = ctx.obj.get("niche", "esports")
    config = ctx.obj.get("config")

    if not config:
        raise click.ClickException(f"No config found for niche: {niche}")

    # Initialize database
    db_path_obj = Path(db_path)
    if not db_path_obj.parent.exists():
        db_path_obj.parent.mkdir(parents=True, exist_ok=True)

    # Check if database exists
    if not db_path_obj.exists():
        raise click.ClickException(
            f"Database not found at {db_path}. Run backfill command first."
        )

    db = init_database(db_path_obj)

    # Assert required tables exist
    required_tables = ["trades", "market_entities", "positions", "markets"]
    missing_tables = [t for t in required_tables if not db[t].exists()]
    if missing_tables:
        raise click.ClickException(
            f"Missing required tables: {', '.join(missing_tables)}. "
            f"Run backfill and related commands first."
        )

    # Run sanity checks
    results, failed_count = run_sanity_checks(db, niche, min_positions)

    # Print summary
    print_summary(results, failed_count)

    # Exit with code 1 if any check failed
    if failed_count > 0:
        sys.exit(1)
