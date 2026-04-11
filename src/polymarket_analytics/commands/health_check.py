"""health-check command — per-cron pre-flight gate.

Usage in cron script:
    if ! polymarket --niche esports health-check --tier cron; then
        echo "Pre-flight failed. Skipping this run."
        exit 0
    fi

Per D-04: On failure, sends alert via both channels, exits 1 (skip cycle).
Per D-05: Never kills external processes.
Per D-06: Alert only — does not attempt to fix problems.
"""
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from polymarket_analytics.cli import cli
from polymarket_analytics.db.schema import init_database
from polymarket_analytics.health.checks import (
    check_lift_scores_freshness,
    preflight_checks,
)
from polymarket_analytics.health.log import write_health_log
from polymarket_analytics.health.notify import send_alert

console = Console()


@cli.command("health-check")
@click.option(
    "--tier",
    type=click.Choice(["cron", "daily", "weekly"]),
    required=True,
    help="Check tier: cron (pre-flight), daily (summary), weekly (deep report)",
)
@click.option(
    "--stages-failed",
    default="",
    help="Comma-separated list of failed stage names (from cron script)",
)
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database (default: data/analytics.db)",
)
@click.pass_context
def health_check(ctx, tier: str, stages_failed: str, db_path: str):
    """Run pipeline health checks.

    Exit codes:
      0 = all checks pass (proceed with pipeline)
      1 = pre-flight failed (skip this cron cycle)
    """
    niche = ctx.obj["niche"]
    db_path_obj = Path(db_path)
    db = init_database(db_path_obj)

    console.print(f"[bold]Health Check[/bold] tier={tier} niche={niche}")

    if tier == "cron":
        _run_cron_checks(db, db_path_obj, niche, stages_failed)
    elif tier == "daily":
        # Implemented in plan 09-03
        console.print("[yellow]Daily checks not yet implemented[/yellow]")
    elif tier == "weekly":
        # Implemented in plan 09-03
        console.print("[yellow]Weekly checks not yet implemented[/yellow]")


def _run_cron_checks(db, db_path: Path, niche: str, stages_failed: str):
    """Per-cron pre-flight: memory, disk, lift_scores freshness, stage exit codes.

    Per D-08: All stages completed (exit codes), memory/disk pre-flight,
    lift_scores.computed_at freshness (warn if >5h).
    """
    all_checks = {}

    # 1. Memory + disk pre-flight
    pf_results = preflight_checks(str(db_path.parent))
    for check in pf_results:
        all_checks[check["name"]] = check

    # 2. lift_scores freshness
    freshness = check_lift_scores_freshness(db, niche)
    all_checks[freshness["name"]] = freshness

    # 3. Stage exit codes (passed from cron script via --stages-failed)
    if stages_failed:
        failed_list = [s.strip() for s in stages_failed.split(",") if s.strip()]
        all_checks["stage_exit_codes"] = {
            "name": "stage_exit_codes",
            "status": "fail" if failed_list else "pass",
            "value": ", ".join(failed_list) if failed_list else "none",
            "threshold": "0 failures",
            "message": (
                f"Failed stages: {', '.join(failed_list)}"
                if failed_list
                else "All stages passed"
            ),
        }

    # Determine overall status
    has_fail = any(c["status"] == "fail" for c in all_checks.values())
    has_warn = any(c["status"] == "warn" for c in all_checks.values())
    overall = "fail" if has_fail else ("warn" if has_warn else "pass")

    # Display results table
    table = Table(title="Pre-flight Checks")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Value")
    table.add_column("Threshold")
    for check in all_checks.values():
        status_style = {"pass": "green", "warn": "yellow", "fail": "red"}[check["status"]]
        table.add_row(
            check["name"],
            f"[{status_style}]{check['status']}[/]",
            check.get("value", ""),
            check.get("threshold", ""),
        )
    console.print(table)

    # Build summary message
    summary_lines = [check["message"] for check in all_checks.values()]
    summary = "\n".join(summary_lines)

    # Log to health_log (HLTH-06)
    write_health_log(db, tier="cron", status=overall, checks=all_checks, summary=summary, niche=niche)

    # Alert on failure (D-04: alert + skip)
    if has_fail:
        alert_title = f"Pipeline Pre-flight FAILED ({niche})"
        failed_checks = [c["message"] for c in all_checks.values() if c["status"] == "fail"]
        alert_body = "Skipping this cron cycle.\n\n" + "\n".join(failed_checks)
        send_alert(alert_title, alert_body)
        console.print("\n[red bold]PRE-FLIGHT FAILED — skipping cron cycle[/red bold]")
        sys.exit(1)

    # Warn (but don't fail) on warnings
    if has_warn:
        warn_checks = [c["message"] for c in all_checks.values() if c["status"] == "warn"]
        send_alert(f"Pipeline Health Warning ({niche})", "\n".join(warn_checks))

    console.print("\n[green bold]All checks passed[/green bold]")
