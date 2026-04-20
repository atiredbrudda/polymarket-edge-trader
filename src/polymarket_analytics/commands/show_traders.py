"""Show-traders command: display Q5 traders and their signal contributions.

Sections:
  1. Q5 Traders — all top-quintile addresses with composite/CLV/ROI/Sharpe/PnL
  2. Active Signals — each signal with the contributing Q5 addresses

Usage:
    polymarket --niche esports show-traders [--db-path PATH]
"""

from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table
from rich import box

from polymarket_analytics.cli import cli
from polymarket_analytics.db.schema import init_database
from polymarket_analytics.scoring.thresholds import Q5_COMPOSITE_THRESHOLD

console = Console()


def _q5_traders_table(db, niche_slug: str) -> Table:
    rows = list(db.execute(
        """
        SELECT
            trader_address,
            composite_score,
            clv_raw,
            roi_raw,
            sharpe_raw,
            position_count,
            total_pnl
        FROM q5_traders
        WHERE category = :niche_slug
        ORDER BY composite_score DESC
        """,
        {"niche_slug": niche_slug},
    ))

    table = Table(
        title=f"Q5 Traders — {niche_slug}  ({len(rows)} total)",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        highlight=True,
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Address", style="cyan", no_wrap=True)
    table.add_column("Score", justify="right")
    table.add_column("CLV", justify="right")
    table.add_column("ROI", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("Positions", justify="right")
    table.add_column("PnL", justify="right")

    for i, row in enumerate(rows, 1):
        addr, score, clv, roi, sharpe, pos_count, pnl = row
        pnl_style = "green" if (pnl or 0) >= 0 else "red"
        table.add_row(
            str(i),
            addr,
            f"{score:.4f}" if score is not None else "—",
            f"{clv:.4f}" if clv is not None else "—",
            f"{roi:.4f}" if roi is not None else "—",
            f"{sharpe:.4f}" if sharpe is not None else "—",
            str(pos_count) if pos_count is not None else "—",
            f"[{pnl_style}]{pnl:.4f}[/{pnl_style}]" if pnl is not None else "—",
        )

    return table


def _signals_table(db, niche_slug: str) -> None:
    signals = list(db.execute(
        """
        SELECT
            s.id,
            s.market_id,
            s.direction,
            s.q5_count,
            s.avg_score,
            COALESCE(m.question, s.market_id) AS question,
            m.event_title,
            CASE WHEN datetime(m.end_date) > datetime('now', '+5 hours') THEN 'upcoming' ELSE 'live' END AS status
        FROM signals s
        LEFT JOIN markets m ON m.condition_id = s.market_id
        WHERE (m.end_date IS NULL OR datetime(m.end_date) > datetime('now'))
        ORDER BY status ASC, s.avg_score DESC
        """
    ))

    if not signals:
        console.print("[yellow]No signals in database.[/yellow]")
        return

    # Latest scoring run cutoff for Q5 filter
    cutoff_row = list(db.execute(
        "SELECT MAX(computed_at) FROM lift_scores WHERE category = :niche_slug",
        {"niche_slug": niche_slug},
    ))
    cutoff = cutoff_row[0][0] if cutoff_row else None

    upcoming = [s for s in signals if s[7] == "upcoming"]
    live     = [s for s in signals if s[7] == "live"]

    def _print_group(group, label, label_style):
        if not group:
            return
        console.print(f"\n[{label_style}][bold]{label} ({len(group)})[/bold][/{label_style}]\n")
        for sig in group:
            sig_id, market_id, direction, q5_count, avg_score, question, event_title, status = sig
            if event_title and event_title != question:
                console.print(f"  [bold #875fff]{event_title}[/bold #875fff]")
            _print_signal(market_id, direction, q5_count, avg_score, question, niche_slug, cutoff, db)

    def _print_signal(market_id, direction, q5_count, avg_score, question, niche_slug, cutoff, db):
        dir_color = "green" if direction == "LONG" else "red"
        console.print(
            f"  [bold]{question}[/bold]\n"
            f"  Direction: [{dir_color}]{direction}[/{dir_color}]  "
            f"Q5 traders: [bold]{q5_count}[/bold]  "
            f"Avg score: [bold]{avg_score:.4f}[/bold]\n"
            f"  market_id: [dim]{market_id}[/dim]"
        )
        contributors = list(db.execute(
            """
            SELECT p.trader_address, ls.composite_score, p.size, p.avg_entry_price
            FROM positions p
            JOIN lift_scores ls ON ls.trader_address = p.trader_address
            WHERE p.market_id = :market_id
              AND p.direction = :direction
              AND p.resolved = 0
              AND p.size > 0
              AND ls.quintile = 5
              AND ls.composite_score >= :q5_threshold
              AND ls.category = :niche_slug
              AND ls.computed_at = :cutoff
            ORDER BY ls.composite_score DESC
            """,
            {"market_id": market_id, "direction": direction,
             "niche_slug": niche_slug, "cutoff": cutoff, "q5_threshold": Q5_COMPOSITE_THRESHOLD},
        ))
        if contributors:
            ctab = Table(box=box.MINIMAL, show_header=True, padding=(0, 1))
            ctab.add_column("Address", style="cyan", no_wrap=True)
            ctab.add_column("Score", justify="right")
            ctab.add_column("Size", justify="right")
            ctab.add_column("Avg Entry", justify="right")
            for addr, cscore, size, entry in contributors:
                ctab.add_row(
                    addr,
                    f"{cscore:.4f}" if cscore is not None else "—",
                    f"{size:.4f}" if size is not None else "—",
                    f"{entry:.4f}" if entry is not None else "—",
                )
            console.print(ctab)
        else:
            console.print("  [dim]  (no contributor detail available)[/dim]")
        console.rule(style="dim")

    _print_group(upcoming, "Upcoming", "bold")
    _print_group(live, "Live / Settling", "yellow")


@cli.command("show-traders")
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database (default: data/analytics.db)",
)
@click.pass_context
def show_traders(ctx: Any, db_path: str) -> None:
    """Display Q5 traders and their active signal contributions."""
    niche = ctx.obj.get("niche", "esports")
    config = ctx.obj.get("config")

    if not config:
        raise click.ClickException(f"No config found for niche: {niche}")

    db_path_obj = Path(db_path)
    db = init_database(db_path_obj)

    if not db["lift_scores"].exists():
        raise click.ClickException("lift_scores table missing. Run score first.")

    console.print("[bold]=== Smart Money Tracker: Detected Addresses ===[/bold]\n")

    # Section 1: Q5 traders
    console.print(_q5_traders_table(db, niche))

    # Section 2: signals + contributors
    _signals_table(db, niche)
