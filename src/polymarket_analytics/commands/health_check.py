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
    check_data_completeness,
    check_lift_scores_freshness,
    check_quiet_canary,
    check_scoring_drift,
    compute_q5_diff,
    daily_summary,
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
        _run_daily_checks(db, niche, stages_failed)
    elif tier == "weekly":
        _run_weekly_checks(db, niche)


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


def _run_daily_checks(db, niche: str, stages_failed: str):
    """Daily summary (D-09): signals, traders, errors in last 24h."""
    failed_list = [s.strip() for s in stages_failed.split(",") if s.strip()] if stages_failed else []
    summary_data = daily_summary(db, niche, stages_failed=failed_list)

    # Format message
    lines = [
        f"New signals: {summary_data['new_signals']}",
        f"Updated signals: {summary_data['updated_signals']}",
        f"Traders discovered: {summary_data['traders_discovered']}",
        f"Traders backfilled: {summary_data['traders_backfilled']}",
    ]
    if summary_data["errored_stages"]:
        lines.append(f"Errored stages: {', '.join(summary_data['errored_stages'])}")

    summary_text = "\n".join(lines)

    # Display
    console.print(f"\n[bold]Daily Summary ({niche})[/bold]")
    for line in lines:
        console.print(f"  {line}")

    # Determine status
    status = "warn" if summary_data["errored_stages"] else "pass"

    # Log
    write_health_log(db, tier="daily", status=status, checks=summary_data, summary=summary_text, niche=niche)

    # Alert via both channels
    send_alert(f"Daily Summary ({niche})", summary_text)


def _run_weekly_checks(db, niche: str):
    """Weekly deep health report (D-10): Q5 diff, scoring drift, completeness, canary."""
    all_checks = {}

    # Q5 diff
    q5_diff = compute_q5_diff(db, niche)
    all_checks["q5_diff"] = {
        "name": "q5_diff",
        "status": "pass",
        "value": q5_diff["message"],
        "entered": q5_diff["entered"],
        "exited": q5_diff["exited"],
    }

    # Scoring drift
    drift = check_scoring_drift(db, niche)
    all_checks["scoring_drift"] = drift

    # Data completeness
    completeness = check_data_completeness(db)
    all_checks["data_completeness"] = completeness

    # Quiet canary
    canary = check_quiet_canary(db, niche)
    all_checks["quiet_canary"] = canary

    # Store Q5 snapshot and median for next week's diff
    all_checks["q5_snapshot"] = q5_diff["current_snapshot"]
    if drift.get("value", "").startswith("median="):
        try:
            median_str = drift["value"].split("median=")[1].split(" ")[0]
            all_checks["median_composite"] = float(median_str)
        except (IndexError, ValueError):
            pass

    # Determine overall
    has_warn = any(
        c.get("status") == "warn"
        for c in all_checks.values()
        if isinstance(c, dict) and "status" in c
    )
    overall = "warn" if has_warn else "pass"

    # Display
    console.print(f"\n[bold]Weekly Health Report ({niche})[/bold]")
    console.print(f"  Q5 changes: +{len(q5_diff['entered'])} entered, -{len(q5_diff['exited'])} exited")
    if q5_diff["entered"]:
        entered_preview = q5_diff["entered"][:5]
        suffix = "..." if len(q5_diff["entered"]) > 5 else ""
        console.print(f"    Entered: {', '.join(entered_preview)}{suffix}")
    if q5_diff["exited"]:
        exited_preview = q5_diff["exited"][:5]
        suffix = "..." if len(q5_diff["exited"]) > 5 else ""
        console.print(f"    Exited: {', '.join(exited_preview)}{suffix}")
    console.print(f"  Scoring drift: {drift['value']}")
    console.print(f"  Data completeness: {completeness['value']}")
    console.print(f"  Quiet canary: {canary['value']}")

    # Build summary
    summary_lines = [
        f"Q5: {q5_diff['message']}",
        f"Drift: {drift['message']}",
        f"Completeness: {completeness['message']}",
        f"Canary: {canary['message']}",
    ]
    summary = "\n".join(summary_lines)

    # Log (includes q5_snapshot and median_composite for next week's diff)
    write_health_log(db, tier="weekly", status=overall, checks=all_checks, summary=summary, niche=niche)

    # Alert
    title = f"Weekly Health Report ({niche})"
    if has_warn:
        title = f"Weekly Health WARNING ({niche})"
    send_alert(title, summary)
