"""Pure formatter functions for CLI output.

All formatters are pure functions that take data objects and return Rich renderables
(Tables, Panels, Groups). No database access or side effects.

Formatters:
- truncate_address: Shorten wallet addresses for display
- format_markets_table: Display markets in a table
- format_trader_profile: Display trader summary with sections
- format_signals_table: Display expert consensus signals
- format_leaderboard_table: Display game leaderboard rankings
- format_sweep_summary: Display sweep operation results
- format_research_table: Display JBecker trade history
- format_batch_summary: Display batch-analyze results
"""

from datetime import datetime
from decimal import Decimal

from rich.table import Table
from rich.panel import Panel
from rich.console import Group
from rich.text import Text


def truncate_address(address: str) -> str:
    """Truncate wallet address for display.

    Args:
        address: Wallet address string

    Returns:
        Truncated address (first 6 + last 4 chars) if > 10 chars,
        otherwise returns full address

    Example:
        >>> truncate_address("0xAbCdEf1234567890AbCdEf1234567890AbCdEf12")
        '0xAbCd...Ef12'
        >>> truncate_address("0x123456")
        '0x123456'
    """
    if len(address) <= 10:
        return address
    return f"{address[:6]}...{address[-4:]}"


def format_markets_table(markets: list) -> Table:
    """Format markets list as a Rich Table.

    Args:
        markets: List of dicts/objects with question, slug, active fields

    Returns:
        Rich Table with columns: Market, Game, Status

    Example:
        >>> markets = [{"question": "Will Team A win?", "slug": "esports.cs2", "active": True}]
        >>> table = format_markets_table(markets)
    """
    table = Table(title="Active Markets", show_header=True, header_style="bold cyan")
    table.add_column("Market", style="white", no_wrap=False)
    table.add_column("Game", style="yellow")
    table.add_column("Status", style="green")

    # Filter only markets with classification (slug is not None)
    classified_markets = [m for m in markets if m.get("slug")]

    for market in classified_markets:
        question = market.get("question", "")
        slug = market.get("slug", "")
        active = market.get("active", False)
        status = "active" if active else "resolved"

        table.add_row(question, slug, status)

    return table


def format_trader_profile(
    trader_address: str, summaries: list, positions: list, scores: list
) -> Group:
    """Format trader profile as Rich Group with multiple sections.

    Args:
        trader_address: Trader wallet address
        summaries: List of category summaries (category, volume, trade_count)
        positions: List of current positions (market_question, direction, size, avg_entry_price)
        scores: List of expertise scores (game, score, percentile, specialization)

    Returns:
        Rich Group containing header panel and section tables

    Example:
        >>> profile = format_trader_profile("0xTrader123", summaries, positions, scores)
    """
    sections = []

    # Section 1: Header panel
    header = Panel(
        f"[bold cyan]Trader Profile[/bold cyan]\n{truncate_address(trader_address)}",
        border_style="cyan",
    )
    sections.append(header)

    # Section 2: Category summary table
    if summaries:
        summary_table = Table(
            title="Category Summary", show_header=True, header_style="bold"
        )
        summary_table.add_column("Category", style="cyan")
        summary_table.add_column("Volume", justify="right", style="green")
        summary_table.add_column("Trades", justify="right", style="yellow")

        for summary in summaries:
            category = summary.get("category", "")
            volume = summary.get("volume", Decimal("0"))
            trade_count = summary.get("trade_count", 0)
            summary_table.add_row(category, f"${volume:,.2f}", str(trade_count))

        sections.append(summary_table)

    # Section 3: Current positions table
    if positions:
        positions_table = Table(
            title="Current Positions", show_header=True, header_style="bold"
        )
        positions_table.add_column("Market", style="white", no_wrap=False)
        positions_table.add_column("Direction", style="cyan")
        positions_table.add_column("Size", justify="right", style="green")
        positions_table.add_column("Entry Price", justify="right", style="yellow")

        for position in positions:
            market_question = position.get("market_question", "")
            direction = position.get("direction", "")
            size = position.get("size", Decimal("0"))
            entry_price = position.get("avg_entry_price")
            entry_str = f"{entry_price:.4f}" if entry_price else "N/A"
            positions_table.add_row(
                market_question, direction, f"{size:,.2f}", entry_str
            )

        sections.append(positions_table)

    # Section 4: Expertise scores table
    if scores:
        scores_table = Table(
            title="Expertise Scores", show_header=True, header_style="bold"
        )
        scores_table.add_column("Game", style="cyan")
        scores_table.add_column("Score", justify="right", style="green")
        scores_table.add_column("Percentile", justify="right", style="yellow")
        scores_table.add_column("Specialization", style="magenta")

        for score in scores:
            game = score.get("game", "")
            raw_score = score.get("score", Decimal("0"))
            percentile = score.get("percentile", Decimal("0"))
            specialization = score.get("specialization", "")
            scores_table.add_row(
                game, f"{raw_score:.1f}", f"{percentile:.0f}", specialization
            )

        sections.append(scores_table)

    return Group(*sections)


def format_signals_table(signals: list) -> Table:
    """Format signals list as a Rich Table.

    Args:
        signals: List of dicts with market_question, direction, confidence,
                 expert_count, first_mover_address fields

    Returns:
        Rich Table with columns: Market, Direction, Confidence, Experts, First Mover

    Example:
        >>> signals = [{"market_question": "Will Team A win?", "direction": "LONG", ...}]
        >>> table = format_signals_table(signals)
    """
    table = Table(title="Expert Signals", show_header=True, header_style="bold cyan")
    table.add_column("Market", style="white", no_wrap=False)
    table.add_column("Direction", style="cyan")
    table.add_column("Confidence", justify="right", style="green")
    table.add_column("Experts", justify="right", style="yellow")
    table.add_column("First Mover", style="magenta")

    for signal in signals:
        market_question = signal.get("market_question", "")
        direction = signal.get("direction", "")
        confidence = signal.get("confidence", Decimal("0"))
        expert_count = signal.get("expert_count", 0)
        first_mover = signal.get("first_mover_address")

        # Format confidence as percentage with color hint
        confidence_pct = f"{confidence:.1f}%"
        if confidence >= 80:
            confidence_display = f"[bold green]{confidence_pct}[/bold green]"
        elif confidence >= 60:
            confidence_display = f"[green]{confidence_pct}[/green]"
        else:
            confidence_display = f"[yellow]{confidence_pct}[/yellow]"

        # Truncate first mover address
        first_mover_display = truncate_address(first_mover) if first_mover else "N/A"

        table.add_row(
            market_question,
            direction,
            Text.from_markup(confidence_display),
            str(expert_count),
            first_mover_display,
        )

    return table


def format_leaderboard_table(
    entries: list, slug: str, depth_label: str = "Game"
) -> Table:
    """Format leaderboard entries as a Rich Table.

    Args:
        entries: List of dicts with rank, trader_address, score, win_rate fields
        slug: Taxonomy identifier for table title
        depth_label: Label for depth (default "Game", or "Tournament", "Team")

    Returns:
        Rich Table with columns: Rank, Trader, Score, Win Rate

    Example:
        >>> entries = [{"rank": 1, "trader_address": "0xTrader123", "score": 95.5, ...}]
        >>> table = format_leaderboard_table(entries, "esports.cs2", depth_label="Game")
    """
    table = Table(
        title=f"{depth_label} Leaderboard: {slug}",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Rank", justify="right", style="cyan")
    table.add_column("Trader", style="white")
    table.add_column("Score", justify="right", style="green")
    table.add_column("Win Rate", justify="right", style="yellow")

    for entry in entries:
        rank = entry.get("rank", 0)
        trader_address = entry.get("trader_address", "")
        score = entry.get("score", Decimal("0"))
        win_rate = entry.get("win_rate", Decimal("0"))

        # Format win rate as percentage
        win_rate_pct = float(win_rate) * 100

        table.add_row(
            str(rank),
            truncate_address(trader_address),
            f"{score:.1f}",
            f"{win_rate_pct:.1f}%",
        )

    return table


def format_sweep_summary(results: dict) -> Panel:
    """Format sweep operation results as a Rich Panel.

    Args:
        results: Dict with processing_time, markets_count, signals_count, alerts_sent

    Returns:
        Rich Panel with summary stats

    Example:
        >>> results = {"processing_time": 12.5, "markets_count": 42, ...}
        >>> panel = format_sweep_summary(results)
    """
    processing_time = results.get("processing_time", 0.0)
    markets_count = results.get("markets_count", 0)
    signals_count = results.get("signals_count", 0)
    alerts_sent = results.get("alerts_sent", 0)

    content = f"""[bold green]Sweep Complete[/bold green]

Processing Time: {processing_time:.1f}s
Markets Scanned: {markets_count}
Signals Detected: {signals_count}
Alerts Sent: {alerts_sent}"""

    return Panel(content, border_style="green", title="Sweep Summary")


def format_research_table(
    trades_data: list[dict], trader_address: str, total_count: int
) -> Table:
    """Format JBecker trade history as Rich table.

    Args:
        trades_data: List of trade dicts from JBeckerDataset (raw DuckDB output)
        trader_address: Trader address being queried
        total_count: Total trades found (may differ from len(trades_data) if truncated)

    Returns:
        Rich Table renderable

    Example:
        >>> trades = [{"maker": "0xAbc...", "timestamp": 1234567890, ...}]
        >>> table = format_research_table(trades, "0xAbc...", 100)
    """
    table = Table(
        title=f"Trade History: {truncate_address(trader_address)} ({total_count} trades)",
        show_header=True,
        header_style="bold cyan",
    )

    table.add_column("#", justify="right", style="dim")
    table.add_column("Timestamp", style="white")
    table.add_column("Role", style="cyan")
    table.add_column("Side", style="white")
    table.add_column("Size (USDC)", justify="right", style="green")
    table.add_column("Price", justify="right", style="yellow")
    table.add_column("Block", justify="right", style="dim")

    for idx, trade in enumerate(trades_data, start=1):
        # Determine role (MAKER or TAKER)
        maker = trade.get("maker", "")
        taker = trade.get("taker", "")
        is_maker = maker.lower() == trader_address.lower()
        role = "MAKER" if is_maker else "TAKER"

        # Determine size based on role
        maker_amount = trade.get("makerAmountFilled", 0)
        taker_amount = trade.get("takerAmountFilled", 0)
        size_raw = maker_amount if is_maker else taker_amount
        size = float(size_raw) / 1e6  # Convert from 6 decimals to USDC

        # Format timestamp
        timestamp = trade.get("timestamp", 0)
        dt = datetime.fromtimestamp(timestamp)
        timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S")

        # Get side (BUY/SELL) and apply color
        side = trade.get("side", "UNKNOWN")
        if side == "BUY":
            side_display = "[green]BUY[/green]"
        elif side == "SELL":
            side_display = "[red]SELL[/red]"
        else:
            side_display = side

        # Get price
        price = trade.get("price", 0)
        price_str = f"{float(price):.4f}"

        # Get block number
        block = trade.get("blockNumber", 0)

        table.add_row(
            str(idx),
            timestamp_str,
            role,
            Text.from_markup(side_display),
            f"{size:,.2f}",
            price_str,
            str(block),
        )

    # Add footer if truncated
    if len(trades_data) < total_count:
        table.caption = f"Showing {len(trades_data)} of {total_count} trades"

    return table


def format_batch_summary(results: list[dict]) -> Table:
    """Format batch-analyze results summary.

    Args:
        results: List of per-trader stats dicts from pipeline ingestion

    Returns:
        Rich Table with trader address, trades found, inserted, skipped, status

    Example:
        >>> results = [{"address": "0xAbc...", "found": 100, "inserted": 95, ...}]
        >>> table = format_batch_summary(results)
    """
    table = Table(
        title="Batch Analysis Summary", show_header=True, header_style="bold cyan"
    )

    table.add_column("Trader", style="white")
    table.add_column("Found", justify="right", style="cyan")
    table.add_column("Inserted", justify="right", style="green")
    table.add_column("Skipped", justify="right", style="yellow")
    table.add_column("Status", style="white")

    for result in results:
        address = result.get("address", "")
        found = result.get("found", 0)
        inserted = result.get("inserted", 0)
        skipped = result.get("skipped", 0)
        error = result.get("error")

        # Determine status and color
        if error:
            status_display = "[red]Error[/red]"
        elif inserted == 0 and found == 0:
            status_display = "[yellow]No trades[/yellow]"
        else:
            status_display = "[green]OK[/green]"

        table.add_row(
            truncate_address(address),
            str(found),
            str(inserted),
            str(skipped),
            Text.from_markup(status_display),
        )

    return table


def format_pipeline_status(counts: dict, pending_traders: list) -> Group:
    """Format pipeline discovery/backfill status as Rich panels.

    Args:
        counts: Dict with keys 'discovered', 'backfilled', 'total' (from get_trader_counts_by_status)
        pending_traders: List of dicts with keys 'address', 'first_seen' (traders needing backfill)

    Returns:
        Rich Group with summary panel and pending traders table

    Example:
        status = format_pipeline_status(
            {"discovered": 5, "backfilled": 10, "total": 15},
            [{"address": "0xAbc...", "first_seen": "2025-01-01 12:00"}]
        )
        console.print(status)
    """
    summary_table = Table(show_header=False, box=None, padding=(0, 2))
    summary_table.add_column("Label", style="bold")
    summary_table.add_column("Value", justify="right")

    summary_table.add_row("Total traders", str(counts.get("total", 0)))
    summary_table.add_row(
        "Backfilled",
        f"[green]{counts.get('backfilled', 0)}[/green]",
    )
    summary_table.add_row(
        "Pending backfill",
        f"[yellow]{counts.get('discovered', 0)}[/yellow]",
    )

    summary_panel = Panel(summary_table, title="Pipeline Status", border_style="blue")

    if pending_traders:
        traders_table = Table(
            title=f"Traders Pending Backfill ({len(pending_traders)})"
        )
        traders_table.add_column("#", style="dim", width=4)
        traders_table.add_column("Address", style="cyan")
        traders_table.add_column("Discovered", style="dim")

        for idx, trader in enumerate(pending_traders, 1):
            traders_table.add_row(
                str(idx),
                truncate_address(trader["address"]),
                trader.get("first_seen", ""),
            )

        return Group(summary_panel, Text(""), traders_table)

    return Group(summary_panel, Text("\n[green]All traders backfilled![/green]"))


def format_expertise_breakdown(address: str, scores_by_depth: dict[int, list]) -> Group:
    """Format trader expertise breakdown across taxonomy depths.

    Args:
        address: Trader wallet address
        scores_by_depth: Dict mapping depth (1,2,3) to list of score dicts
            Each dict: {"slug": str, "score": Decimal, "percentile": Decimal, "specialization": str}

    Returns:
        Rich Group with Panel for each depth level
    """
    from rich.panel import Panel
    from rich.table import Table

    depth_names = {1: "Game Scores", 2: "Tournament Scores", 3: "Team Scores"}

    panels = []

    for depth in [1, 2, 3]:
        scores = scores_by_depth.get(depth, [])

        if scores:
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Slug", style="white")
            table.add_column("Score", justify="right", style="green")
            table.add_column("Percentile", justify="right", style="yellow")
            table.add_column("Specialization", style="magenta")

            for score in scores:
                table.add_row(
                    score["slug"],
                    f"{score['score']:.1f}",
                    f"{score['percentile']:.1f}",
                    score["specialization"],
                )

            panels.append(
                Panel(
                    table,
                    title=f"[bold]{depth_names[depth]}[/bold]",
                    border_style="cyan",
                )
            )
        else:
            panels.append(
                Panel(
                    "[dim]No scores at this depth[/dim]",
                    title=f"[bold]{depth_names[depth]}[/bold]",
                    border_style="cyan",
                )
            )

    header = Panel(
        f"[bold cyan]Expertise Breakdown[/bold cyan]\n[dim]Trader: {address}[/dim]",
        border_style="cyan",
    )

    return Group(header, Text(""), *panels)


def format_specialists_table(specialists: list[dict], game_slug: str) -> Table:
    """Format hidden specialists as a Rich Table.

    Args:
        specialists: List of specialist dicts with trader_address, game_score, deep_slug, deep_score, score_delta
        game_slug: Game identifier for table title

    Returns:
        Rich Table with columns: Trader, Game Score, Niche, Niche Score, Delta
    """
    table = Table(
        title=f"Hidden Specialists: {game_slug}",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Trader", style="white")
    table.add_column("Game Score", justify="right", style="yellow")
    table.add_column("Niche", style="cyan")
    table.add_column("Niche Score", justify="right", style="green")
    table.add_column("Delta", justify="right", style="magenta")

    for spec in specialists:
        table.add_row(
            truncate_address(spec["trader_address"]),
            f"{spec['game_score']:.1f}",
            spec["deep_slug"],
            f"{spec['deep_score']:.1f}",
            f"+{spec['score_delta']:.1f}",
        )

    return table
