"""Backfill command for ingesting historical trades with 2-tier API/Graph orchestration.

This command fetches historical trades for all discovered traders in a niche,
using the Data API first (Tier 1) and falling back to The Graph (Tier 2) when
the API returns 0 trades.

Usage:
    polymarket --niche esports backfill [--db-path PATH]
"""

import asyncio
import hashlib
import json
import os
import re
import signal
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

import click
import httpx
from dotenv import load_dotenv
from rich.console import Console

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
    TextColumn,
)

from polymarket_analytics.cli import cli
from polymarket_analytics.api.data import DataAPIClient
from polymarket_analytics.api.graph import GraphAPIClient, parse_graph_event
from polymarket_analytics.db.schema import init_database
from polymarket_analytics.extraction.patterns import EntityPatternMatcher
from polymarket_analytics.extraction.llm import LLMFallback
from polymarket_analytics.extraction.slug_parser import parse_event_slug as _parse_event_slug
from polymarket_analytics.scoring.thresholds import (
    BOT_TPR_THRESHOLD,
    BOT_TRADE_FLOOR,
    Q5_COMPOSITE_THRESHOLD,
)


console = Console()

# Bot/MM exclusion fragment shared by lean + full backfill trader-selection.
# Same definition as scripts/heal_trapped_batch.py TRAPPED_TRADERS_SQL.
# Q5 whitelist guarantees no scored signal trader is excluded.
BOT_EXCLUSION_SUBQUERY = f"""
    SELECT tt.trader_address
    FROM (SELECT trader_address, COUNT(*) AS n_trades FROM trades GROUP BY trader_address) tt
    JOIN (SELECT trader_address, COUNT(*) AS n_positions FROM positions GROUP BY trader_address) tp
      ON tp.trader_address = tt.trader_address
    LEFT JOIN (
      SELECT trader_address FROM lift_scores
      WHERE composite_score >= {Q5_COMPOSITE_THRESHOLD}
        AND computed_at = (SELECT MAX(computed_at) FROM lift_scores)
    ) q ON q.trader_address = tt.trader_address
    WHERE tt.n_trades > {BOT_TRADE_FLOOR}
      AND tp.n_positions > 0
      AND (1.0 * tt.n_trades / tp.n_positions) > {BOT_TPR_THRESHOLD}
      AND q.trader_address IS NULL
"""

# Max Graph retry attempts before marking a position as permanently data_incomplete
GRAPH_RETRY_LIMIT = 3

# Promote trader to graph_unservable after this many consecutive Graph timeouts
# in full-backfill mode. ~6 whales were observed blocking 8.7h backfills with
# 147 fallback events (project_session12). Skipping them in full backfill cuts
# midnight cron from 8.7h → ~3h. Lean backfill still serves them since
# incremental fetches typically fit a single 40-day window.
GRAPH_UNSERVABLE_THRESHOLD = 2

# Per-trader wall-clock cap on fetch_trader_trades. Without this, one trader
# parked in httpx (e.g. Goldsky drops the TCP connection without RST) can
# block asyncio.gather indefinitely and hang the entire pipeline. The retry
# loop inside fetch_trader_trades bounds individual pages but cannot recover
# from connection-level stalls. 300s is generous: a 2-window 40-day fetch on
# a whale should finish well under this cap.
GRAPH_FETCH_TIMEOUT_S = 300.0

# Component timing tracking
component_timers: Dict[str, float] = {}


class ShutdownManager:
    """Manages graceful shutdown on SIGINT/SIGTERM.

    First signal: sets shutdown_requested, workers finish current item then stop.
    Second signal: forces immediate exit.
    """

    def __init__(self):
        self.shutdown_requested = False
        self._force_count = 0
        self._original_handlers: Dict[int, Any] = {}
        self._traders_completed: List[str] = []
        self._traders_skipped: List[str] = []

    def install(self, loop: asyncio.AbstractEventLoop) -> None:
        """Register signal handlers on the running event loop."""
        for sig in (signal.SIGINT, signal.SIGTERM):
            self._original_handlers[sig] = signal.getsignal(sig)
            loop.add_signal_handler(sig, self._handle_signal, sig)

    def uninstall(self, loop: asyncio.AbstractEventLoop) -> None:
        """Restore original signal handlers."""
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.remove_signal_handler(sig)
            except Exception:
                pass
            original = self._original_handlers.get(sig)
            if original and original not in (signal.SIG_DFL, signal.SIG_IGN):
                signal.signal(sig, original)

    def _handle_signal(self, sig: signal.Signals) -> None:
        if not self.shutdown_requested:
            self.shutdown_requested = True
            console.print(
                "\n[bold yellow]⚠ Graceful shutdown requested — "
                "finishing in-progress traders, skipping remaining...[/bold yellow]"
            )
            console.print(
                "[dim]Press Ctrl+C again to force immediate exit.[/dim]"
            )
        else:
            console.print("\n[bold red]Force shutdown.[/bold red]")
            raise SystemExit(1)

    def record_completed(self, trader_address: str) -> None:
        self._traders_completed.append(trader_address)

    def record_skipped(self, trader_address: str) -> None:
        self._traders_skipped.append(trader_address)

    def print_interrupted_summary(self) -> None:
        if not self.shutdown_requested:
            return
        console.print(
            f"\n[bold yellow]Interrupted — shutdown summary:[/bold yellow]\n"
            f"  Traders completed before shutdown: {len(self._traders_completed):,}\n"
            f"  Traders skipped (not started):     {len(self._traders_skipped):,}"
        )
        console.print(
            "[dim]No partial data was written — skipped traders will resume on next run.[/dim]"
        )


# Module-level instance so backfill_trader can check it (optional future use)
_shutdown = ShutdownManager()


@contextmanager
def _log_drop(
    db,
    reason: str,
    trader: str,
    trade: dict,
    error_msg: Optional[str] = None,
) -> None:
    """Log a dropped or self-healed trade row to backfill_drops (REVIEW.md H-11 #3).

    Reasons:
      - 'no_token_id'           — trade has no asset/asset_id field
      - 'catalog_miss_no_cid'   — token not in catalog AND trade has no conditionId
      - 'catalog_miss_fk'       — self-heal attempted but FK violation (market missing)
      - 'insert_error'          — exception in fallback per-trade insert
      - 'self_healed'           — positive case, catalog row inserted on the spot

    Swallows all exceptions — observability must never break ingest.
    """
    try:
        db["backfill_drops"].insert(
            {
                "trader_address": trader,
                "market_id": trade.get("conditionId") or trade.get("condition_id") or trade.get("market_id"),
                "token_id": str(trade.get("asset") or trade.get("asset_id") or "") or None,
                "reason": reason,
                "trade_payload": json.dumps(trade, default=str)[:2000],
                "error_msg": error_msg,
                "dropped_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception:
        pass


def time_component(name: str):
    """Time a specific component (API, dedup, processing, DB, Graph fallback).

    Args:
        name: Component name for tracking

    Yields:
        None

    Example:
        with time_component("API fetch"):
            trades = await fetch_trades_with_retry(...)
    """
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    component_timers[name] = component_timers.get(name, 0) + elapsed


def print_timing_summary():
    """Print component timing breakdown at end of backfill."""
    if not component_timers:
        return

    print("\n=== COMPONENT TIMING BREAKDOWN ===")
    total = sum(component_timers.values())
    for name, elapsed in sorted(
        component_timers.items(), key=lambda x: x[1], reverse=True
    ):
        pct = (elapsed / total * 100) if total > 0 else 0
        console.print(f"  {name:20s}: {elapsed:8.3f}s ({pct:5.1f}%)")
    console.print(f"  {'TOTAL':20s}: {total:8.3f}s (100.0%)")


async def fetch_trades_with_retry(
    client: DataAPIClient,
    trader_address: str,
    max_retries: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 8.0,
    since_unix_ts: Optional[int] = None,
) -> List[dict]:
    """Fetch trades from Data API with exponential backoff for HTTP 425.

    Args:
        client: DataAPIClient instance
        trader_address: Trader wallet address
        max_retries: Maximum retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        since_unix_ts: Optional unix timestamp — if set, only fetch trades at or after this time

    Returns:
        List of trade dicts from API

    Raises:
        click.ClickException: If max retries exceeded
    """
    delay = base_delay
    last_error: Optional[Exception] = None

    for attempt in range(max_retries):
        try:
            trades = await client.fetch_user_trades(
                trader_address, since_unix_ts=since_unix_ts
            )
            return trades
        except Exception as e:
            error_str = str(e)
            # Retry on rate-limit and transient errors: 408, 425, 429
            if isinstance(e, (httpx.ReadTimeout, httpx.ConnectTimeout)) or any(
                code in error_str
                for code in (
                    "408",
                    "425",
                    "429",
                    "Too Early",
                    "Too Many Requests",
                    "Request Timeout",
                )
            ):
                last_error = e
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)
                continue
            else:
                console.print(
                    f"  [yellow]⚠ Non-retryable error for {trader_address[:10]}...: {e}[/yellow]"
                )
                return []

    # Max retries exceeded
    raise click.ClickException(
        f"Failed to fetch trades for {trader_address[:8]}... after {max_retries} retries: {last_error}"
    )


async def backfill_trader(
    db: Any,
    trader_address: str,
    data_client: DataAPIClient,
    graph_client: GraphAPIClient,
    since_unix_ts: Optional[int] = None,
    prefetched_trades: Optional[list] = None,
    prefetched_graph: Optional[list] = None,
    global_catalog: Optional[Dict[str, str]] = None,
    prefetched_sell_only_markets: Optional[list] = None,
    track_graph_streak: bool = False,
) -> Dict[str, int]:
    """Backfill trades for a single trader with 2-tier logic.

    Args:
        db: sqlite-utils Database instance
        trader_address: Trader wallet address
        data_client: DataAPIClient for Tier 1
        graph_client: GraphAPIClient for Tier 2 fallback
        since_unix_ts: Optional unix timestamp — if set, only fetch trades at or after this time
        prefetched_graph: Optional pre-fetched Graph events (from concurrent Phase A.5)

    Returns:
        Dict with ingested, skipped, fallback counts
    """
    stats = {"ingested": 0, "skipped": 0, "fallback": False}

    # Scoring window: 30 days + 10-day safeguard
    COVERAGE_DAYS = 40
    coverage_cutoff = datetime.now(timezone.utc) - timedelta(days=COVERAGE_DAYS)

    # Tier 1: Try Data API first
    with time_component(f"API fetch ({trader_address[:8]}...)"):
        if prefetched_trades is not None:
            api_trades = prefetched_trades
        else:
            api_trades = await fetch_trades_with_retry(
                data_client, trader_address, since_unix_ts=since_unix_ts
            )

    # Tier 2: Graph fallback if API doesn't cover the full 40-day window.
    # "Covers" means at least one trade predates the cutoff (oldest trade >= 40 days ago).
    # If API returns 0 trades OR all trades are within the last 40 days, use Graph.
    def _api_covers_window(trades: list) -> bool:
        for t in trades:
            ts = t.get("timestamp")
            if ts is None:
                continue
            try:
                if isinstance(ts, int):
                    trade_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                else:
                    trade_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if trade_dt <= coverage_cutoff:
                    return True
            except Exception:
                continue
        return False

    # Graph is needed when:
    # 1. since_unix_ts is None (full backfill, not incremental), AND
    # 2. Data API doesn't cover the 40-day window, AND
    # 3. DB also doesn't have trades older than the window for each market in this batch
    #
    # In incremental mode (since_unix_ts is set), skip Graph fallback entirely —
    # historical coverage is already in the DB from prior full backfills.
    #
    # Per-market check: old trades for Market A must not suppress Graph fallback for
    # Market B. Build a partial catalog cache from API trades to resolve token_ids ->
    # market_ids, then check DB coverage per market.
    def _build_catalog_cache(
        trades: list, existing: dict | None = None
    ) -> dict[str, str]:
        cache = dict(existing) if existing else {}
        new_ids = set()
        for t in trades:
            tid = t.get("token_id") or t.get("asset") or t.get("asset_id")
            if tid and str(tid) not in cache:
                new_ids.add(str(tid))
        if new_ids:
            # SQLite limit: 999 variables per query — chunk large sets
            id_list = list(new_ids)
            for i in range(0, len(id_list), 900):
                chunk = id_list[i : i + 900]
                placeholders = ",".join("?" * len(chunk))
                for row in db.execute(
                    f"SELECT token_id, condition_id FROM token_catalog WHERE token_id IN ({placeholders})",
                    chunk,
                ).fetchall():
                    cache[row[0]] = row[1]
        return cache

    def _db_covers_market(market_id: str) -> bool:
        result = db.execute(
            "SELECT 1 FROM trades WHERE trader_address = :addr AND market_id = :market AND timestamp <= :cutoff LIMIT 1",
            {
                "addr": trader_address,
                "market": market_id,
                "cutoff": coverage_cutoff.isoformat(),
            },
        ).fetchone()
        return result is not None

    # Build early catalog cache from API trades to resolve markets for the coverage check
    # Use pre-built global catalog if available (avoids per-trader DB queries)
    catalog_cache: dict[str, str] = _build_catalog_cache(api_trades, existing=global_catalog)
    api_markets = {cid for cid in catalog_cache.values() if cid}

    needs_graph = (
        since_unix_ts is None
        and (not api_trades or not _api_covers_window(api_trades))
        and not (api_markets and all(_db_covers_market(m) for m in api_markets))
    )

    # SELL-only detection: On Polymarket, you must buy before you can sell/redeem.
    # SELL-only positions = missing historical BUY trades, not legitimate edge cases.
    # Force Graph fallback to fetch full history for affected markets.
    #
    # Scoped to current-batch markets (api_markets) to avoid:
    # 1. Redundant Graph fallbacks for unrelated markets
    # 2. Infinite retry loops for post-resolution redemptions (legitimate sell-only)
    #
    # SELL-only detection: check for markets where this trader has SELLs but no BUYs.
    # In incremental mode (since_unix_ts set), also check: new markets in this batch
    # may have only SELLs because BUYs predate the incremental window.
    if not needs_graph:
        if prefetched_sell_only_markets is not None:
            # Monitor mode: sell-only already computed in bulk before the upsert loop.
            # Skip the per-trader DB queries entirely.
            if prefetched_sell_only_markets:
                needs_graph = True
        elif api_markets:
            # Scope to current-batch markets when we have API trades
            # Skip positions that have exhausted Graph retry attempts
            # SQLite limit: 999 variables per query — chunk large market lists
            market_list = list(api_markets)
            sell_only_markets = []
            for i in range(0, len(market_list), 900):
                chunk = market_list[i : i + 900]
                placeholders = ",".join("?" * len(chunk))
                sell_only_markets.extend(
                    db.execute(
                        f"""
                        SELECT DISTINCT t.market_id FROM trades t
                        LEFT JOIN positions p ON p.trader_address = t.trader_address
                            AND p.market_id = t.market_id
                        WHERE t.trader_address = ? AND t.market_id IN ({placeholders})
                          AND COALESCE(p.graph_retry_count, 0) < ?
                        GROUP BY t.trader_address, t.market_id
                        HAVING SUM(CASE WHEN t.side = 'BUY' THEN 1 ELSE 0 END) = 0
                           AND SUM(CASE WHEN t.side = 'SELL' THEN 1 ELSE 0 END) > 0
                        """,
                        [trader_address] + chunk + [GRAPH_RETRY_LIMIT],
                    ).fetchall()
                )
            if sell_only_markets:
                needs_graph = True
        else:
            # No API trades in this batch — check DB for any sell-only positions
            # on unresolved markets. Runs in both full and incremental mode:
            # incremental batches won't have api_markets for old markets whose
            # BUYs predate the since_unix_ts window.
            # Skip positions that have exhausted Graph retry attempts.
            sell_only_markets = db.execute(
                """
                SELECT DISTINCT t.market_id FROM trades t
                JOIN positions p ON p.trader_address = t.trader_address
                    AND p.market_id = t.market_id
                WHERE t.trader_address = ? AND p.resolved = 0
                  AND COALESCE(p.graph_retry_count, 0) < ?
                GROUP BY t.trader_address, t.market_id
                HAVING SUM(CASE WHEN t.side = 'BUY' THEN 1 ELSE 0 END) = 0
                   AND SUM(CASE WHEN t.side = 'SELL' THEN 1 ELSE 0 END) > 0
                """,
                [trader_address, GRAPH_RETRY_LIMIT],
            ).fetchall()
            if sell_only_markets:
                needs_graph = True

    if needs_graph:
        stats["fallback"] = True
        # Use pre-fetched Graph data if available (from concurrent Phase A.5),
        # otherwise fall back to sequential fetch.
        graph_timed_out = False
        if prefetched_graph is not None:
            graph_events = prefetched_graph
        else:
            with time_component(f"Graph fallback ({trader_address[:8]}...)"):
                try:
                    graph_events = await asyncio.wait_for(
                        graph_client.fetch_trader_trades(
                            trader_address, since_unix_ts=None
                        ),
                        timeout=GRAPH_FETCH_TIMEOUT_S,
                    )
                except (httpx.ReadTimeout, httpx.ConnectTimeout, asyncio.TimeoutError):
                    graph_events = []
                    graph_timed_out = True

        # Promote whales to graph_unservable after consecutive timeouts in
        # full-backfill mode. Only tracked when caller opts in (full mode);
        # lean mode and monitor leave streak alone.
        if track_graph_streak and prefetched_graph is None:
            try:
                if graph_timed_out:
                    db.execute(
                        """
                        UPDATE traders
                        SET graph_timeout_streak = COALESCE(graph_timeout_streak, 0) + 1,
                            graph_unservable = CASE
                                WHEN COALESCE(graph_timeout_streak, 0) + 1 >= ? THEN 1
                                ELSE COALESCE(graph_unservable, 0)
                            END
                        WHERE address = ?
                        """,
                        [GRAPH_UNSERVABLE_THRESHOLD, trader_address],
                    )
                else:
                    # Reset on a successful Graph fetch — even an empty result
                    # set means Goldsky responded in time.
                    db.execute(
                        "UPDATE traders SET graph_timeout_streak = 0 WHERE address = ?",
                        [trader_address],
                    )
            except Exception:
                pass
        # Merge Graph trades with API trades (union — INSERT OR IGNORE deduplicates)
        for event in graph_events:
            api_trades.append(parse_graph_event(event, trader_address))
        # Extend catalog cache with any new token_ids from Graph trades
        catalog_cache = _build_catalog_cache(api_trades, existing=catalog_cache)

    if not api_trades:
        return stats

    # Process trades
    def _normalize_ts(ts) -> str:
        """Return ISO timestamp truncated to seconds. Prevents API/Graph precision mismatch."""
        if isinstance(ts, int):
            return (
                datetime.fromtimestamp(ts, tz=timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            )
        if ts:
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                return dt.replace(microsecond=0).isoformat()
            except Exception:
                pass
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    # catalog_cache is already built above (reused, no duplicate queries)

    trade_batch: list[dict] = []

    for trade in api_trades:
        # Handle both API and Graph trade formats
        if "trade_id" in trade:
            # Already parsed (Graph format)
            trade_id = trade["trade_id"]
            token_id = trade["token_id"]
            side = trade["side"]
            price_str = trade["price"]
            size_str = trade["size"]
            timestamp = trade["timestamp"]
        else:
            # API format
            token_id = trade.get("asset") or trade.get("asset_id")
            side = "BUY" if trade.get("side") == "BUY" else "SELL"
            price_str = str(trade.get("price", "0"))
            size_str = str(trade.get("size", "0"))
            timestamp = trade.get("timestamp")
            trade_id = (
                trade.get("trade_id")
                or trade.get("txHash")
                or hashlib.sha256(
                    f"{trader_address}:{token_id}:{side}:{price_str}:{size_str}:{timestamp}".encode()
                ).hexdigest()[:32]
            )

        if not token_id:
            stats["skipped"] += 1
            _log_drop(db, "no_token_id", trader_address, trade)
            continue

        # Token catalog lookup: resolve token_id -> condition_id (from cache)
        condition_id = catalog_cache.get(str(token_id))
        if not condition_id:
            # H-11 self-heal: Polymarket Data API ships `conditionId` per trade,
            # so when discover.py omits a token_catalog row (Gamma occasionally
            # returns markets with empty clobTokenIds), we can insert the
            # missing catalog entry on the spot rather than silently dropping
            # the trade. Graph trades don't carry conditionId, so this only
            # fixes the API path — which is the H-11 root cause.
            api_condition_id = trade.get("conditionId") or trade.get("condition_id")
            if api_condition_id:
                try:
                    db["token_catalog"].insert(
                        {
                            "token_id": str(token_id),
                            "condition_id": str(api_condition_id),
                        },
                        pk="token_id",
                        ignore=True,  # Race-safe vs concurrent backfill writers
                    )
                    condition_id = str(api_condition_id)
                    catalog_cache[str(token_id)] = condition_id
                    stats["self_healed_catalog"] = stats.get("self_healed_catalog", 0) + 1
                    _log_drop(db, "self_healed", trader_address, trade)
                except Exception as e:
                    # FK violation (market itself missing) or other write
                    # failure — fall through to skip. Rare; a real fix would
                    # also self-heal the market, but that's out of scope.
                    stats["skipped"] += 1
                    _log_drop(db, "catalog_miss_fk", trader_address, trade,
                              error_msg=f"{type(e).__name__}: {e}")
                    continue
            else:
                stats["skipped"] += 1
                _log_drop(db, "catalog_miss_no_cid", trader_address, trade)
                continue

        # Convert price to Decimal
        try:
            price = Decimal(price_str)
            # Convert Graph decimal odds to implied probability if > 1.0
            if price > 1:
                price = Decimal("1") / price
        except Exception:
            price = Decimal("0")

        # Convert size to Decimal
        try:
            size = Decimal(size_str)
        except Exception:
            size = Decimal("0")

        # Convert timestamp to ISO format (second precision)
        timestamp_iso = _normalize_ts(timestamp)

        # Prepare trade record
        trade_data = {
            "trade_id": trade_id,
            "token_id": str(token_id),
            "timestamp": timestamp_iso,
            "side": side,
            "price": price,
            "size": size,
            "market_id": condition_id,  # Real condition_id from catalog lookup
            "trader_address": trader_address,
        }

        # Collect for batch insert
        trade_batch.append(trade_data)

    # Flush trade batch
    if trade_batch:
        try:
            before = db.conn.total_changes
            db["trades"].insert_all(trade_batch, ignore=True)
            inserted = db.conn.total_changes - before
            stats["ingested"] += inserted
            stats["skipped"] += len(trade_batch) - inserted
        except Exception:
            # Batch failed — fall back to individual inserts
            for item in trade_batch:
                try:
                    db["trades"].insert(item, replace=False)
                    stats["ingested"] += 1
                except Exception as e:
                    stats["skipped"] += 1
                    _log_drop(db, "insert_error", trader_address, item,
                              error_msg=f"{type(e).__name__}: {e}")

    # After Graph fallback, check if positions are still sell-only and track retry count
    if stats["fallback"]:
        still_sell_only = db.execute(
            """
            SELECT DISTINCT t.market_id FROM trades t
            JOIN positions p ON p.trader_address = t.trader_address
                AND p.market_id = t.market_id
            WHERE t.trader_address = ?
            GROUP BY t.trader_address, t.market_id
            HAVING SUM(CASE WHEN t.side = 'BUY' THEN 1 ELSE 0 END) = 0
               AND SUM(CASE WHEN t.side = 'SELL' THEN 1 ELSE 0 END) > 0
            """,
            [trader_address],
        ).fetchall()

        for row in still_sell_only:
            market_id = row[0]
            db.execute(
                """
                UPDATE positions
                SET graph_retry_count = COALESCE(graph_retry_count, 0) + 1,
                    data_incomplete = CASE
                        WHEN COALESCE(graph_retry_count, 0) + 1 >= ? THEN 1
                        ELSE data_incomplete
                    END
                WHERE trader_address = ? AND market_id = ?
                """,
                [GRAPH_RETRY_LIMIT, trader_address, market_id],
            )

    # Always stamp last_backfilled_at — zero-trade result is a completed backfill.
    # Without this, traders that return nothing from both API and Graph stay
    # last_backfilled_at IS NULL forever and are re-selected on every lean run.
    update_fields: dict = {"last_backfilled_at": datetime.now(timezone.utc).isoformat()}

    if stats["ingested"] > 0 or stats["skipped"] > 0:
        # Compute max trade timestamp from ingested trades.
        # Normalize all timestamps to ISO strings before comparing to avoid
        # TypeError from mixed int (Graph) vs str (API) types.
        last_trade_iso = None
        for trade in api_trades:
            ts = trade.get("timestamp")
            if ts is None:
                continue
            ts_iso = _normalize_ts(ts)
            if last_trade_iso is None or ts_iso > last_trade_iso:
                last_trade_iso = ts_iso
        update_fields["last_trade_seen_at"] = last_trade_iso
        update_fields["backfill_complete"] = True

    try:
        db["traders"].update(trader_address, update_fields)
    except Exception as _upd_e:
        console.print(
            f"  [yellow]⚠ traders.update {trader_address[:10]}... "
            f"type={type(_upd_e).__name__} args={_upd_e.args!r} "
            f"ingested={stats['ingested']} skipped={stats['skipped']} "
            f"fallback={stats['fallback']}[/yellow]"
        )
        raise

    return stats


async def backfill_async(ctx, db_path: str, new_only: bool = False) -> None:
    """Async backfill implementation."""
    niche = ctx.obj.get("niche", "esports")
    config = ctx.obj.get("config")

    if not config:
        raise click.ClickException(f"No config found for niche: {niche}")

    # Initialize database
    db_path_obj = Path(db_path)
    if not db_path_obj.parent.exists():
        db_path_obj.parent.mkdir(parents=True, exist_ok=True)

    db = init_database(db_path_obj)

    # Install graceful shutdown handlers
    _shutdown.__init__()  # reset state from any prior run
    loop = asyncio.get_running_loop()
    _shutdown.install(loop)

    console.print("[bold]=== Backfilling Trade History ===[/bold]\n")

    # Dependency assertions
    if not db["traders"].exists():
        raise click.ClickException(
            "traders table does not exist. Run discover command first."
        )
    if not db["token_catalog"].exists():
        raise click.ClickException(
            "token_catalog table does not exist. Run classify-tokens command first."
        )

    # One-time dedup: remove duplicate trades caused by unstable fallback IDs or
    # cross-source duplicates (same trade appearing via both API and Graph).
    # Keeps the earliest insert (MIN(rowid)) per logical trade.
    # Edge case: two genuinely identical trades same-second same-price same-size
    # is accepted as an acceptable false-positive loss (extremely rare in practice).
    with console.status("Deduplicating trades table..."):
        with time_component("Deduplication (pre-run)"):
            dedup_result = db.execute(
                """
                DELETE FROM trades
                WHERE rowid NOT IN (
                    SELECT MIN(rowid)
                    FROM trades
                    GROUP BY trader_address, market_id, token_id, side, price, size, timestamp
                )
                """
            )
    dedup_count = dedup_result.rowcount if dedup_result else 0
    if dedup_count:
        console.print(
            f"  [yellow]⚠ Removed {dedup_count:,} duplicate trade(s) from prior runs[/yellow]"
        )

    # Query traders needing backfill using timestamp-based selection
    # --new-only mode: only traders where last_backfilled_at IS NULL (lean cron, ~100-200 traders)
    # Full mode: original selection logic with REFRESH_HOURS threshold (~6,000 traders)
    COVERAGE_DAYS = 40
    REFRESH_HOURS = 6
    cutoff = (datetime.now(timezone.utc) - timedelta(days=COVERAGE_DAYS)).isoformat()
    threshold = (
        datetime.now(timezone.utc) - timedelta(hours=REFRESH_HOURS)
    ).isoformat()

    # Bot/MM exclusion (BOT_EXCLUSION_SUBQUERY) is applied in BOTH branches:
    # we never want to ingest more trades for the ~110 high-velocity bots
    # (~21% of all trade rows) that the behavioral signature catches. Q5
    # whitelist guarantees no scored signal trader is dropped.
    if new_only:
        # Lean mode keeps serving graph_unservable traders — incremental fetches
        # typically fit one 40-day window so they don't trigger fallback.
        traders = list(
            db.execute(
                f"""
            SELECT address, last_trade_seen_at FROM traders
            WHERE last_backfilled_at IS NULL
              AND address NOT IN ({BOT_EXCLUSION_SUBQUERY})
        """
            ).fetchall()
        )
        console.print(f"  [dim]--new-only mode: selecting only never-backfilled traders (bot-filtered)[/dim]")
    else:
        # Full mode skips graph_unservable traders to keep midnight cron under
        # the 4h target — see GRAPH_UNSERVABLE_THRESHOLD.
        traders = list(
            db.execute(
                f"""
            SELECT address, last_trade_seen_at FROM traders
            WHERE
                (last_trade_seen_at IS NULL OR last_trade_seen_at >= :cutoff)
                AND (last_backfilled_at IS NULL OR last_backfilled_at < :threshold)
                AND COALESCE(graph_unservable, 0) = 0
                AND address NOT IN ({BOT_EXCLUSION_SUBQUERY})
        """,
                {"cutoff": cutoff, "threshold": threshold},
            ).fetchall()
        )
        unservable_count = db.execute(
            "SELECT COUNT(*) FROM traders WHERE COALESCE(graph_unservable, 0) = 1"
        ).fetchone()[0]
        if unservable_count:
            console.print(
                f"  [dim]Skipping {unservable_count:,} graph_unservable trader(s) "
                f"(served by lean backfill instead)[/dim]"
            )
        bot_count = db.execute(
            f"SELECT COUNT(*) FROM ({BOT_EXCLUSION_SUBQUERY})"
        ).fetchone()[0]
        if bot_count:
            console.print(
                f"  [dim]Skipping {bot_count:,} bot/MM trader(s) "
                f"(trades>{BOT_TRADE_FLOOR} AND tpr>{BOT_TPR_THRESHOLD} AND not in Q5)[/dim]"
            )

    if not traders:
        console.print(
            "[green]All traders already backfilled. Skipping to entity extraction.[/green]"
        )
    else:
        console.print(
            f"[bold]Step 1/2[/bold] Fetching trades for {len(traders):,} traders..."
        )

    if traders:
        # Initialize API clients
        data_client = DataAPIClient()
        graph_client = GraphAPIClient(api_key=os.getenv("GRAPH_API_KEY"))

        CONCURRENT_LIMIT = 10
        semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)

        start_time = time.time()
        total_stats = {
            "traders_processed": 0,
            "trades_ingested": 0,
            "trades_skipped": 0,
            "graph_fallbacks": 0,
            "errors": 0,
        }

        # Pre-load token catalog to avoid per-trader DB queries
        global_catalog = {
            row[0]: row[1]
            for row in db.execute(
                "SELECT token_id, condition_id FROM token_catalog"
            ).fetchall()
        }
        console.print(
            f"  Loaded {len(global_catalog):,} token catalog entries"
        )

        _fetched = {"n": 0}
        _done = {"n": 0}
        _total = len(traders)

        def _print_progress() -> None:
            print(
                f"\r  [{_done['n']}/{_total}] done  [{_fetched['n']}/{_total}] fetched  "
                f"ingested: {total_stats['trades_ingested']:,} | "
                f"skipped: {total_stats['trades_skipped']:,} | "
                f"graph: {total_stats['graph_fallbacks']:,} | "
                f"errors: {total_stats['errors']:,}    ",
                end="",
                flush=True,
            )

        try:
            # Build per-trader since_unix_ts metadata
            trader_meta: dict[str, dict] = {}
            for trader in traders:
                trader_address = trader[0]
                last_trade_seen_at = trader[1]
                since_unix_ts: Optional[int] = None
                if last_trade_seen_at:
                    try:
                        dt = datetime.fromisoformat(
                            last_trade_seen_at.replace("Z", "+00:00")
                        )
                        since_unix_ts = int(dt.timestamp())
                    except Exception:
                        pass
                trader_meta[trader_address] = {"since_unix_ts": since_unix_ts}

            console.print(
                f"  Processing {len(traders):,} traders concurrently (limit={CONCURRENT_LIMIT})..."
            )

            # Single-phase concurrent fetch + process.
            # Memory is bounded to CONCURRENT_LIMIT × avg_response_size rather than
            # all traders at once. Sell-only Graph fallbacks run inline inside
            # backfill_trader — equivalent throughput to the old pre-fetch approach
            # because Phase B was already concurrent (semaphore=10 either way).
            async def _fetch_and_process(trader_address: str) -> None:
                if _shutdown.shutdown_requested:
                    _shutdown.record_skipped(trader_address)
                else:
                    async with semaphore:
                        if _shutdown.shutdown_requested:
                            _shutdown.record_skipped(trader_address)
                        else:
                            _since = trader_meta[trader_address]["since_unix_ts"]
                            try:
                                api_trades = await fetch_trades_with_retry(
                                    data_client, trader_address, since_unix_ts=_since
                                )
                            except Exception:
                                api_trades = []
                            _fetched["n"] += 1
                            _print_progress()
                            try:
                                stats = await backfill_trader(
                                    db,
                                    trader_address,
                                    data_client,
                                    graph_client,
                                    since_unix_ts=_since,
                                    prefetched_trades=api_trades,
                                    global_catalog=global_catalog,
                                    # Only track the timeout streak in full
                                    # mode; lean (--new-only) traders haven't
                                    # been backfilled before so a single timeout
                                    # shouldn't stick them with the unservable flag.
                                    track_graph_streak=not new_only,
                                )
                                total_stats["traders_processed"] += 1
                                total_stats["trades_ingested"] += stats["ingested"]
                                total_stats["trades_skipped"] += stats["skipped"]
                                if stats["fallback"]:
                                    total_stats["graph_fallbacks"] += 1
                                _shutdown.record_completed(trader_address)
                            except click.ClickException:
                                raise
                            except Exception as e:
                                total_stats["errors"] += 1
                                total_stats["traders_processed"] += 1
                                _shutdown.record_completed(trader_address)
                                console.print(
                                    f"\n  [red]✗ {trader_address[:10]}... "
                                    f"{type(e).__name__}({e.args!r}): {e}[/red]"
                                )
                _done["n"] += 1
                _print_progress()

            await asyncio.gather(
                *[_fetch_and_process(t[0]) for t in traders]
            )
            print()  # end the \r progress line

            elapsed = time.time() - start_time
            status_label = (
                "[bold yellow]Backfill interrupted[/bold yellow]"
                if _shutdown.shutdown_requested
                else "[bold green]Backfill complete[/bold green]"
            )
            console.print(
                f"\n{status_label} ({elapsed:.1f}s)\n"
                f"  Traders processed:    {total_stats['traders_processed']:,}\n"
                f"  Trades ingested:      {total_stats['trades_ingested']:,}\n"
                f"  Trades skipped:       {total_stats['trades_skipped']:,}\n"
                f"  Graph fallbacks used: {total_stats['graph_fallbacks']:,}\n"
                f"  Errors:               {total_stats['errors']:,}"
            )
            _shutdown.print_interrupted_summary()

            # Report incomplete positions that can still be retried
            try:
                retryable = db.execute(
                    """
                    SELECT COUNT(*) FROM positions
                    WHERE data_incomplete = 1
                      AND COALESCE(graph_retry_count, 0) < ?
                      AND resolved = 0
                    """,
                    [GRAPH_RETRY_LIMIT],
                ).fetchone()[0]
                exhausted = db.execute(
                    "SELECT COUNT(*) FROM positions WHERE data_incomplete = 1 AND graph_retry_count >= ?",
                    [GRAPH_RETRY_LIMIT],
                ).fetchone()[0]
                if retryable > 0:
                    console.print(
                        f"\n  [yellow]ℹ {retryable:,} incomplete position(s) with retries remaining.[/yellow]\n"
                        f"  Run [bold]polymarket --niche {niche} retry-incomplete[/bold] to retry."
                    )
                if exhausted > 0:
                    console.print(
                        f"  [dim]{exhausted:,} position(s) confirmed irreducible ({GRAPH_RETRY_LIMIT}/{GRAPH_RETRY_LIMIT} attempts).[/dim]"
                    )
            except Exception:
                pass

        finally:
            await data_client.close()
            await graph_client.close()
            _shutdown.uninstall(loop)

        # Post-run dedup: catch cross-source duplicates inserted during this run.
        with console.status("Deduplicating trades table (post-run)..."):
            with time_component("Deduplication (post-run)"):
                dedup_result = db.execute(
                    """
                    DELETE FROM trades
                    WHERE rowid NOT IN (
                        SELECT MIN(rowid)
                        FROM trades
                        GROUP BY trader_address, market_id, token_id, side, price, size, timestamp
                    )
                    """
                )
        dedup_count = dedup_result.rowcount if dedup_result else 0
        if dedup_count:
            console.print(
                f"  [yellow]⚠ Removed {dedup_count:,} duplicate trade(s) from this run[/yellow]"
            )

    # Skip entity extraction on interrupted shutdown — trades are consistent
    # but we don't want to start a long LLM extraction pass.
    if _shutdown.shutdown_requested:
        print_timing_summary()
        return

    # -------------------------------------------------------------------------
    # Step 2: Post-backfill entity extraction
    # Markets touched by backfill may never have been seen by discover,
    # so they have no market_entities row → invisible to build-positions.
    # -------------------------------------------------------------------------
    console.print("\n[bold]Step 2/2[/bold] Post-backfill entity extraction...")

    markets_needing_entities = list(
        db.query(
            """
        SELECT DISTINCT t.market_id AS condition_id, m.question, m.event_slug
        FROM trades t
        JOIN markets m ON m.condition_id = t.market_id
        LEFT JOIN market_entities me ON me.condition_id = t.market_id
        WHERE me.condition_id IS NULL
          AND m.niche_slug = :niche
          AND m.question IS NOT NULL
        """,
            {"niche": niche},
        )
    )

    if not markets_needing_entities:
        console.print("  [green]✓[/green] All markets already have entities extracted.")
        return

    console.print(
        f"  Found {len(markets_needing_entities):,} markets without entity rows"
    )

    # Setup extractors
    pattern_matcher = EntityPatternMatcher()
    llm_fallback: Optional[LLMFallback] = None
    try:
        llm_fallback = LLMFallback()
        console.print("  [green]✓[/green] LLM fallback ready")
    except ValueError as e:
        console.print(f"  [yellow]⚠ LLM unavailable: {e}[/yellow]")

    # Pre-seed event_slug → entities from DB (siblings extracted in prior runs)
    event_slug_entities: Dict[str, Dict[str, Any]] = {}
    rows = db.execute("""
        SELECT m.event_slug, me.game, me.team_a, me.team_b, me.tournament, me.market_type
        FROM market_entities me
        JOIN markets m ON me.condition_id = m.condition_id
        WHERE m.event_slug IS NOT NULL AND me.game IS NOT NULL
    """).fetchall()
    for row in rows:
        slug = row[0]
        if slug and slug not in event_slug_entities:
            event_slug_entities[slug] = {
                "game": row[1],
                "team_a": row[2],
                "team_b": row[3],
                "tournament": row[4],
                "market_type": row[5],
            }

    entity_records: List[Dict[str, Any]] = []
    pattern_count = 0
    llm_count = 0
    event_slug_count = 0
    slug_parse_count = 0
    llm_disabled = False  # becomes True on first API error

    def _entity_id(condition_id: str, entities: Dict[str, Any]) -> str:
        entity_str = json.dumps(entities, sort_keys=True)
        return hashlib.sha256(f"{condition_id}:{entity_str}".encode()).hexdigest()[:16]

    def _desc() -> str:
        return (
            f"[cyan]Entities[/cyan]  "
            f"[dim]pattern: {pattern_count - event_slug_count - slug_parse_count:,} | "
            f"event_slug: {event_slug_count:,} | slug_parse: {slug_parse_count:,} | "
            f"llm: {llm_count:,} | total: {len(entity_records):,}[/dim]"
        )

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(_desc(), total=len(markets_needing_entities))

        for row in markets_needing_entities:
            cid = row["condition_id"]
            question = row["question"]
            event_slug = row["event_slug"]

            entities = pattern_matcher.extract(question)
            pattern_incomplete = (
                entities.get("game") is None or entities.get("team_a") is None
            )

            # event_slug fallback: inherit entities from a sibling market
            if pattern_incomplete and event_slug and event_slug in event_slug_entities:
                entities = event_slug_entities[event_slug]
                event_slug_count += 1
                pattern_incomplete = False

            # slug parse fallback: extract game+teams directly from slug structure
            if pattern_incomplete and event_slug:
                parsed = _parse_event_slug(event_slug)
                if parsed.get("game"):
                    entities = parsed
                    slug_parse_count += 1
                    pattern_incomplete = False
                    # seed cache so siblings use this result, not slug parse again
                    event_slug_entities[event_slug] = entities

            # LLM fallback: only if pattern, event_slug, and slug parse all failed
            if pattern_incomplete and not llm_disabled and llm_fallback is not None:
                progress.update(
                    task,
                    description=f"[cyan]⚙ LLM[/cyan]  [dim]{question[:58]}[/dim]",
                )
                try:
                    entities = llm_fallback.extract(question, event_slug=event_slug)
                    llm_count += 1
                except Exception as e:
                    llm_disabled = True
                    llm_fallback = None
                    console.print(
                        f"  [yellow]⚠ LLM disabled after error: {e}[/yellow]\n"
                        f"  [dim]Remaining markets will use pattern-only extraction.[/dim]"
                    )

            if entities.get("game") is not None or entities.get("team_a") is not None:
                pattern_count += 1
                # Cache for siblings processed later in this run
                if event_slug and event_slug not in event_slug_entities:
                    event_slug_entities[event_slug] = entities

            entity_records.append(
                {
                    "id": _entity_id(cid, entities),
                    "condition_id": cid,
                    "game": entities.get("game"),
                    "team_a": entities.get("team_a"),
                    "team_b": entities.get("team_b"),
                    "tournament": entities.get("tournament"),
                    "market_type": entities.get("market_type"),
                }
            )

            progress.update(task, description=_desc())
            progress.advance(task)

    if entity_records:
        with console.status(
            f"[bold green]Writing {len(entity_records):,} entities to DB...",
            spinner="dots",
        ):
            with db.conn:
                db.conn.executemany(
                    """
                    INSERT INTO market_entities (id, condition_id, game, team_a, team_b, tournament, market_type)
                    VALUES (:id, :condition_id, :game, :team_a, :team_b, :tournament, :market_type)
                    ON CONFLICT(condition_id) DO UPDATE SET
                        id          = excluded.id,
                        game        = excluded.game,
                        team_a      = excluded.team_a,
                        team_b      = excluded.team_b,
                        tournament  = excluded.tournament,
                        market_type = excluded.market_type
                    """,
                    entity_records,
                )
        console.print(
            f"  [green]✓[/green] {len(entity_records):,} entities written "
            f"(pattern: {pattern_count - event_slug_count - slug_parse_count:,}, "
            f"event_slug: {event_slug_count:,}, slug_parse: {slug_parse_count:,}, LLM: {llm_count:,})"
        )

    # Print component timing breakdown
    print_timing_summary()

    return


@cli.command()
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database (default: data/analytics.db)",
)
@click.option(
    "--new-only",
    is_flag=True,
    default=False,
    help="Only backfill traders never backfilled before (last_backfilled_at IS NULL).",
)
@click.pass_context
def backfill(ctx, db_path: str, new_only: bool) -> None:
    """Backfill historical trades for niche traders.

    This command:
    1. Asserts dependencies exist (traders, token_catalog tables)
    2. Queries traders with backfill_complete=False
    3. For each trader:
       - Tier 1: Fetch trades from Data API
       - Tier 2: Graph fallback if API returns 0 trades
    4. Resolves token_id -> condition_id via token_catalog lookup
    5. Inserts trades with INSERT OR IGNORE (idempotent)
    6. Sets backfill_complete=True after successful backfill

    Use --new-only for lean cron runs (Mon-Sat): only backfills traders
    that discover just added. Full backfill (no flag) on Sundays.

    Args:
        ctx: Click context with niche and config
        db_path: Path to SQLite database
        new_only: If True, only backfill traders where last_backfilled_at IS NULL
    """
    asyncio.run(backfill_async(ctx, db_path, new_only=new_only))


async def retry_incomplete_async(ctx, db_path: str) -> None:
    """Retry Graph fallback for incomplete positions that haven't exhausted attempts."""
    niche = ctx.obj.get("niche", "esports")

    db_path_obj = Path(db_path)
    db = init_database(db_path_obj)

    # Install graceful shutdown handlers
    _shutdown.__init__()  # reset state from any prior run
    loop = asyncio.get_running_loop()
    _shutdown.install(loop)

    console.print("[bold]=== Retrying Incomplete Positions ===[/bold]\n")

    # Purge exhausted positions older than 40 days.
    # After 40 days the Graph has rotated past those trades entirely — no
    # chance of recovering the missing BUYs.  Deleting frees them from the
    # data_incomplete list; if the trader trades on that market again,
    # discover will recreate the position with fresh data.
    cutoff_40d = (
        datetime.now(timezone.utc) - timedelta(days=40)
    ).replace(microsecond=0).isoformat()
    purge_count = db.execute(
        """
        DELETE FROM positions
        WHERE data_incomplete = 1
          AND graph_retry_count >= ?
          AND resolved = 0
          AND trader_address IN (
              SELECT address FROM traders
              WHERE last_backfilled_at IS NOT NULL
                AND last_backfilled_at < ?
          )
        """,
        [GRAPH_RETRY_LIMIT, cutoff_40d],
    ).rowcount
    if purge_count:
        console.print(
            f"  [yellow]✂ Purged {purge_count:,} exhausted position(s) "
            f"(last backfilled >40 days ago)[/yellow]"
        )

    # Find positions with retries remaining
    retryable = db.execute(
        """
        SELECT p.trader_address, p.market_id, p.graph_retry_count
        FROM positions p
        WHERE p.data_incomplete = 1
          AND COALESCE(p.graph_retry_count, 0) < ?
          AND p.resolved = 0
        """,
        [GRAPH_RETRY_LIMIT],
    ).fetchall()

    if not retryable:
        console.print("[green]No incomplete positions with retries remaining.[/green]")
        return

    # Group by trader for efficient Graph fetching
    trader_markets: Dict[str, list] = {}
    for row in retryable:
        trader_markets.setdefault(row[0], []).append(
            {"market_id": row[1], "retry_count": row[2]}
        )

    console.print(
        f"  Found {len(retryable):,} position(s) across {len(trader_markets):,} trader(s)"
    )

    graph_client = GraphAPIClient(api_key=os.getenv("GRAPH_API_KEY"))

    total_fixed = 0
    total_still_incomplete = 0
    total_exhausted = 0

    try:
        CONCURRENT_LIMIT = 10
        semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
        completed = 0
        total = len(trader_markets)

        async def _retry_one(trader_address: str, markets: list) -> None:
            nonlocal completed, total_fixed, total_still_incomplete, total_exhausted
            if _shutdown.shutdown_requested:
                return
            async with semaphore:
                if _shutdown.shutdown_requested:
                    return
                try:
                    graph_events = await asyncio.wait_for(
                        graph_client.fetch_trader_trades(
                            trader_address, since_unix_ts=None
                        ),
                        timeout=GRAPH_FETCH_TIMEOUT_S,
                    )
                except Exception as e:
                    console.print(
                        f"  [red]✗ {trader_address[:10]}...: {e}[/red]"
                    )
                    completed += 1
                    return

                # Parse and insert any new trades
                if graph_events:
                    trade_batch = []
                    for event in graph_events:
                        parsed = parse_graph_event(event, trader_address)
                        token_id = parsed.get("token_id")
                        if not token_id:
                            continue
                        # Resolve token_id -> condition_id
                        cid_row = db.execute(
                            "SELECT condition_id FROM token_catalog WHERE token_id = ?",
                            [str(token_id)],
                        ).fetchone()
                        if not cid_row:
                            continue
                        condition_id = cid_row[0]

                        price = Decimal(str(parsed.get("price", "0")))
                        if price > 1:
                            price = Decimal("1") / price
                        size = Decimal(str(parsed.get("size", "0")))
                        ts = parsed.get("timestamp")
                        if isinstance(ts, int):
                            ts_iso = datetime.fromtimestamp(
                                ts, tz=timezone.utc
                            ).replace(microsecond=0).isoformat()
                        else:
                            ts_iso = str(ts) if ts else datetime.now(
                                timezone.utc
                            ).replace(microsecond=0).isoformat()

                        trade_batch.append({
                            "trade_id": parsed.get("trade_id", ""),
                            "token_id": str(token_id),
                            "timestamp": ts_iso,
                            "side": parsed.get("side", ""),
                            "price": price,
                            "size": size,
                            "market_id": condition_id,
                            "trader_address": trader_address,
                        })

                    if trade_batch:
                        try:
                            db["trades"].insert_all(trade_batch, ignore=True)
                        except Exception:
                            pass

                # Check each market: still sell-only?
                for market_info in markets:
                    market_id = market_info["market_id"]
                    still_sell_only_row = db.execute(
                        """
                        SELECT 1 FROM trades
                        WHERE trader_address = ? AND market_id = ?
                        GROUP BY trader_address, market_id
                        HAVING SUM(CASE WHEN side = 'BUY' THEN 1 ELSE 0 END) = 0
                           AND SUM(CASE WHEN side = 'SELL' THEN 1 ELSE 0 END) > 0
                        """,
                        [trader_address, market_id],
                    ).fetchone()

                    new_count = (market_info["retry_count"] or 0) + 1

                    if still_sell_only_row:
                        if new_count >= GRAPH_RETRY_LIMIT:
                            total_exhausted += 1
                        else:
                            total_still_incomplete += 1
                        db.execute(
                            """
                            UPDATE positions
                            SET graph_retry_count = ?,
                                data_incomplete = CASE WHEN ? >= ? THEN 1 ELSE 1 END
                            WHERE trader_address = ? AND market_id = ?
                            """,
                            [new_count, new_count, GRAPH_RETRY_LIMIT,
                             trader_address, market_id],
                        )
                    else:
                        # BUYs found — fixed!
                        total_fixed += 1
                        db.execute(
                            """
                            UPDATE positions
                            SET data_incomplete = 0, graph_retry_count = ?
                            WHERE trader_address = ? AND market_id = ?
                            """,
                            [new_count, trader_address, market_id],
                        )

                completed += 1
                if completed % 10 == 0 or completed == total:
                    print(
                        f"\r  [{completed}/{total}] retrying traders...    ",
                        end="",
                        flush=True,
                    )

        console.print(
            f"  Retrying {total:,} traders concurrently (limit={CONCURRENT_LIMIT})..."
        )
        await asyncio.gather(
            *[_retry_one(addr, mkts) for addr, mkts in trader_markets.items()]
        )
        print()

    finally:
        await graph_client.close()
        _shutdown.uninstall(loop)

    status_label = (
        "[bold yellow]Retry interrupted[/bold yellow]"
        if _shutdown.shutdown_requested
        else "[bold green]Retry complete[/bold green]"
    )
    console.print(
        f"\n{status_label}\n"
        f"  Fixed (BUYs found):       {total_fixed:,}\n"
        f"  Still incomplete:         {total_still_incomplete:,}\n"
        f"  Exhausted ({GRAPH_RETRY_LIMIT}/{GRAPH_RETRY_LIMIT} attempts): {total_exhausted:,}"
    )
    if _shutdown.shutdown_requested:
        console.print(
            "[dim]Interrupted traders were not modified — they will resume on next run.[/dim]"
        )


@cli.command("retry-incomplete")
@click.option(
    "--db-path",
    default="data/analytics.db",
    help="Path to SQLite database (default: data/analytics.db)",
)
@click.pass_context
def retry_incomplete(ctx, db_path: str) -> None:
    """Retry Graph fallback for incomplete sell-only positions.

    Targets positions flagged data_incomplete=1 that haven't exhausted
    their Graph retry attempts (< 3). Run this at your convenience to
    give sell-only positions additional chances before they're confirmed
    as irreducible.
    """
    asyncio.run(retry_incomplete_async(ctx, db_path))
