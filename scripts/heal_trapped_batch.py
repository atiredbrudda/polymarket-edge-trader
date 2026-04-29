"""Batch-heal trapped sell-only pairs using the fixed Graph pagination.

A "trapped" pair is (trader_address, market_id) where we have SELL trades but
no BUY trades — impossible by construction, explained by pagination truncation
in fetch_trader_trades (see project_graph_pagination_truncation memory).

This script iterates trapped traders in small batches, re-fetches their full
Graph history using the fixed pagination, and inserts the missing trades via
INSERT OR IGNORE. It runs safely alongside an active monitor:

- Does not modify the traders table (no last_trade_seen_at reset) — zero
  contention with backfill state management.
- Uses INSERT OR IGNORE on trades — idempotent, never clobbers existing rows.
- Concurrency capped at 4 Graph requests in flight to avoid crowding the
  monitor's own API budget.
- Sleeps between batches so the monitor's SELECTs don't get starved.
- Resumable: completed trader addresses are written to a progress file.

Usage:
  scripts/heal_trapped_batch.py --dry-run              # list + stats only
  scripts/heal_trapped_batch.py --batch-size 50        # default batch
  scripts/heal_trapped_batch.py --limit 200            # cap total traders
  scripts/heal_trapped_batch.py --resume               # skip already-done

Auto-retry mode:
  When --resume sees an empty new-queue but a non-empty failed set, the run
  automatically switches to retrying the failed traders with progressively
  longer per-trader timeouts (RETRY_SCHEDULE) and a tighter Graph concurrency
  cap. After GRADUATION_THRESHOLD timeouts, a trader is promoted to
  traders.graph_unservable=1 (matches the backfill side's verdict) and drops
  out of TRAPPED_TRADERS_SQL on subsequent passes.

Ctrl+C saves progress and exits cleanly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlite_utils import Database

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from polymarket_analytics.api.graph import GraphAPIClient, parse_graph_event
from polymarket_analytics.db.connection import get_db

DB_PATH = REPO / "data" / "analytics.db"
PROGRESS_PATH = REPO / "data" / "audit" / "heal_trapped_batch_progress.json"
CONCURRENCY = 4
CONCURRENCY_RETRY = 2  # auto-retry mode halves Graph load on long-tail attempts
DEFAULT_BATCH_SIZE = 50
DEFAULT_BATCH_SLEEP_S = 5.0
# Per-trader wall-clock cap. With 40-day windowing in fetch_trader_trades,
# even whales need at most 2 windows (<2 min). Cap at 300s = safety margin
# for Goldsky slowness without letting anything genuinely stuck grind forever.
PER_TRADER_TIMEOUT_S = 300.0
# Progressive timeout schedule for auto-retry mode, indexed by attempt count.
# attempt 0 = first try (300s, full concurrency).
# attempt 1 = first retry (600s, halved concurrency).
# attempt 2 = second retry (900s, halved concurrency).
# attempt 3+ = graduate to traders.graph_unservable=1, never tried again.
RETRY_TIMEOUTS_S = [300.0, 600.0, 900.0]
GRADUATION_THRESHOLD = len(RETRY_TIMEOUTS_S)

# Trapped definition matches scripts/recover_trapped_traders.sh and
# dryrun_trapped_recovery.py: (trader, market) pairs with >=1 SELL and 0 BUY.
# We pull the full set of such traders (both no-position-row and exhausted
# position-row cases) so a single Graph fetch per trader heals every trapped
# market they own.
TRAPPED_TRADERS_SQL = """
WITH pairs AS (
  SELECT trader_address, market_id,
         SUM(CASE WHEN side='BUY'  THEN 1 ELSE 0 END) AS buys,
         SUM(CASE WHEN side='SELL' THEN 1 ELSE 0 END) AS sells
  FROM trades
  GROUP BY trader_address, market_id
)
SELECT DISTINCT p.trader_address
FROM pairs p
LEFT JOIN traders t ON t.address = p.trader_address
WHERE p.buys = 0
  AND p.sells > 0
  AND COALESCE(t.graph_unservable, 0) = 0
ORDER BY p.trader_address
"""


_stop_requested = False


def _install_signal_handlers() -> None:
    def _handler(signum, frame):
        global _stop_requested
        _stop_requested = True
        print("\n[heal] SIGINT received — finishing current batch, then stopping.")

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def load_progress() -> tuple[set[str], set[str], dict[str, int]]:
    """Return (completed, failed, attempts). All default to empty if missing/malformed.

    `attempts` is a per-trader timeout-failure counter used by auto-retry mode
    to escalate the per-trader timeout and eventually graduate the trader to
    traders.graph_unservable=1.
    """
    if not PROGRESS_PATH.exists():
        return set(), set(), {}
    try:
        data = json.loads(PROGRESS_PATH.read_text())
        return (
            set(data.get("completed", [])),
            set(data.get("failed", [])),
            dict(data.get("attempts", {})),
        )
    except Exception:
        return set(), set(), {}


def save_progress(
    completed: set[str],
    failed: set[str],
    attempts: dict[str, int],
    stats: dict,
) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(
        json.dumps(
            {
                "completed": sorted(completed),
                "failed": sorted(failed),
                "attempts": dict(sorted(attempts.items())),
                "stats": stats,
                "updated_at": datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat(),
            },
            indent=2,
        )
    )


def build_token_catalog(db: Database) -> dict[str, str]:
    return {
        row[0]: row[1]
        for row in db.execute(
            "SELECT token_id, condition_id FROM token_catalog"
        ).fetchall()
    }


def trader_trapped_markets(db: Database, trader: str) -> set[str]:
    """Which markets is this trader currently trapped (SELL-only) on?"""
    rows = db.execute(
        """
        SELECT market_id
        FROM trades
        WHERE trader_address = ?
        GROUP BY market_id
        HAVING SUM(CASE WHEN side='BUY'  THEN 1 ELSE 0 END) = 0
           AND SUM(CASE WHEN side='SELL' THEN 1 ELSE 0 END) > 0
        """,
        [trader],
    ).fetchall()
    return {r[0] for r in rows}


async def heal_one_trader(
    graph: GraphAPIClient,
    db: Database,
    catalog: dict[str, str],
    trader: str,
    sem: asyncio.Semaphore,
    timeout: float = PER_TRADER_TIMEOUT_S,
) -> dict:
    """Fetch full Graph history for a trader and insert any missing trades."""
    trapped_before = trader_trapped_markets(db, trader)

    async with sem:
        t0 = time.time()
        try:
            events = await asyncio.wait_for(
                graph.fetch_trader_trades(trader, since_unix_ts=None),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return {
                "trader": trader,
                "error": f"timeout (>{timeout:.0f}s)",
                "events": 0,
                "inserted": 0,
                "healed_markets": 0,
                "trapped_before": len(trapped_before),
            }
        except Exception as e:
            return {
                "trader": trader,
                "error": f"{type(e).__name__}: {e}",
                "events": 0,
                "inserted": 0,
                "healed_markets": 0,
                "trapped_before": len(trapped_before),
            }
        elapsed = time.time() - t0

    # Parse + build trade rows
    batch: list[dict] = []
    for ev in events:
        parsed = parse_graph_event(ev, trader)
        token_id = parsed.get("token_id")
        if not token_id:
            continue
        condition_id = catalog.get(str(token_id))
        if not condition_id:
            continue

        price = Decimal(str(parsed.get("price", "0")))
        size = Decimal(str(parsed.get("size", "0")))
        ts_raw = parsed.get("timestamp")
        if isinstance(ts_raw, int):
            ts_iso = (
                datetime.fromtimestamp(ts_raw, tz=timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            )
        else:
            ts_iso = (
                str(ts_raw)
                if ts_raw
                else datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            )

        batch.append(
            {
                "trade_id": parsed.get("trade_id", ""),
                "token_id": str(token_id),
                "timestamp": ts_iso,
                "side": parsed.get("side", ""),
                "price": price,
                "size": size,
                "market_id": condition_id,
                "trader_address": trader,
            }
        )

    # Count trades before insert so we can compute how many were new.
    # Approximate via INSERT OR IGNORE diff using total_changes.
    # Chunk into 500-row pieces with brief asyncio yields so a heal pass
    # never holds the write lock for >50ms — monitor SELECTs stay responsive.
    inserted = 0
    if batch:
        before = db.conn.total_changes
        try:
            for i in range(0, len(batch), 500):
                chunk = batch[i : i + 500]
                db["trades"].insert_all(chunk, ignore=True)
                if i + 500 < len(batch):
                    await asyncio.sleep(0.05)
            inserted = db.conn.total_changes - before
        except Exception as e:
            return {
                "trader": trader,
                "error": f"insert: {type(e).__name__}: {e}",
                "events": len(events),
                "inserted": 0,
                "healed_markets": 0,
                "trapped_before": len(trapped_before),
            }

    trapped_after = trader_trapped_markets(db, trader)
    healed_markets = len(trapped_before - trapped_after)

    # Mark irredeemable (trader, market) pairs: Graph fetch succeeded yet no
    # BUYs landed for these markets — Goldsky doesn't have them. Setting
    # graph_retry_count=3 + data_incomplete=1 makes backfill stop retrying
    # them (matches the threshold used in commands/backfill.py).
    irredeemable_marked = 0
    if trapped_after:
        still = list(trapped_after)
        placeholders = ",".join("?" * len(still))
        cur = db.execute(
            f"""
            UPDATE positions
            SET graph_retry_count = 3, data_incomplete = 1
            WHERE trader_address = ?
              AND market_id IN ({placeholders})
              AND (COALESCE(graph_retry_count, 0) < 3 OR data_incomplete = 0)
            """,
            [trader, *still],
        )
        irredeemable_marked = cur.rowcount or 0

    return {
        "trader": trader,
        "events": len(events),
        "inserted": inserted,
        "healed_markets": healed_markets,
        "trapped_before": len(trapped_before),
        "trapped_after": len(trapped_after),
        "irredeemable_marked": irredeemable_marked,
        "elapsed_s": round(elapsed, 1),
    }


async def run(
    batch_size: int,
    batch_sleep_s: float,
    limit: int | None,
    resume: bool,
    dry_run: bool,
    retry_failed: bool,
    max_runtime_s: float | None = None,
) -> int:
    api_key = os.environ.get("GOLDSKY_API_KEY") or os.environ.get("GRAPH_API_KEY")
    # Route through get_db() so heal inherits the same 30s busy_timeout +
    # tuned cache/WAL PRAGMAs as monitor/backfill, instead of the raw
    # 5s default that lets heal abort on contention.
    db = get_db(DB_PATH)

    print(f"[heal] db={DB_PATH}")
    print("[heal] computing trapped-trader set...")
    t0 = time.time()
    all_traders = [row[0] for row in db.execute(TRAPPED_TRADERS_SQL).fetchall()]
    print(f"[heal]   {len(all_traders):,} trapped traders (scan {time.time()-t0:.1f}s)")

    if resume:
        completed, failed, attempts = load_progress()
    else:
        completed, failed, attempts = set(), set(), {}

    # Free cleanup: traders already flagged graph_unservable=1 are excluded
    # by TRAPPED_TRADERS_SQL anyway. Prune them from `failed` and `attempts`
    # so the progress file stays honest and auto-retry mode doesn't waste
    # cycles on them.
    if failed:
        placeholders = ",".join("?" * len(failed))
        unserv_rows = db.execute(
            f"SELECT address FROM traders "
            f"WHERE COALESCE(graph_unservable, 0) = 1 AND address IN ({placeholders})",
            list(failed),
        ).fetchall()
        unserv_now = {r[0] for r in unserv_rows}
        if unserv_now:
            print(
                f"[heal]   {len(unserv_now):,} pruned from failed "
                f"(already graph_unservable)"
            )
            failed -= unserv_now
            for a in unserv_now:
                attempts.pop(a, None)

    if completed:
        print(f"[heal]   {len(completed):,} already completed — resuming")
    if failed:
        if retry_failed:
            print(
                f"[heal]   {len(failed):,} previously failed — retrying all "
                f"(--retry-failed; resets attempts counter)"
            )
            failed = set()
            attempts.clear()
        else:
            print(
                f"[heal]   {len(failed):,} previously failed — skipping new-queue; "
                f"auto-retry kicks in if new-queue is empty"
            )

    skip = completed | failed
    new_queue = [t for t in all_traders if t not in skip]
    if limit:
        new_queue = new_queue[:limit]

    # Auto-retry mode: when there's nothing new to heal but we still have
    # failed traders sitting in the progress file, take a pass over them
    # with progressive timeouts (RETRY_TIMEOUTS_S) and reduced concurrency.
    auto_retry_mode = (not retry_failed) and (not new_queue) and bool(failed)
    if auto_retry_mode:
        queue = sorted(failed)
        if limit:
            queue = queue[:limit]
        concurrency = CONCURRENCY_RETRY
        # Seed missing attempt counts to 1: being in `failed` IS one prior
        # failure, so the first retry should already use the second slot in
        # RETRY_TIMEOUTS_S (600s), not the first (300s). Pre-existing entries
        # in `attempts` are preserved.
        seeded = 0
        for t in queue:
            if t not in attempts:
                attempts[t] = 1
                seeded += 1
        print(
            f"[heal]   queue empty + {len(failed):,} failed — entering "
            f"auto-retry mode (concurrency={concurrency}, "
            f"timeouts={RETRY_TIMEOUTS_S}, graduate at {GRADUATION_THRESHOLD})"
        )
        if seeded:
            print(
                f"[heal]   seeded {seeded:,} attempts to 1 (legacy failures "
                f"with no attempts data)"
            )
    else:
        queue = new_queue
        concurrency = CONCURRENCY

    print(
        f"[heal]   {len(queue):,} traders to process this run"
        f"{'  (retry)' if auto_retry_mode else ''}"
    )

    if dry_run:
        print("[heal] --dry-run: no Graph calls, no writes. Sample of queue:")
        for t in queue[:10]:
            print(f"  {t}  (attempt={attempts.get(t, 0)})")
        return 0

    if not queue:
        print("[heal] nothing to do.")
        return 0

    print("[heal] building token catalog...")
    catalog = build_token_catalog(db)
    print(f"[heal]   catalog: {len(catalog):,} tokens")

    graph = GraphAPIClient(api_key=api_key)
    sem = asyncio.Semaphore(concurrency)

    totals = {
        "traders_done": 0,
        "trades_inserted": 0,
        "markets_healed": 0,
        "irredeemable_marked": 0,
        "errors": 0,
        "graduated": 0,
        "retry_mode": auto_retry_mode,
    }

    _install_signal_handlers()

    run_start = time.monotonic()

    try:
        for batch_idx in range(0, len(queue), batch_size):
            if _stop_requested:
                print("[heal] stop requested — exiting before next batch.")
                break

            if max_runtime_s is not None:
                elapsed = time.monotonic() - run_start
                if elapsed >= max_runtime_s:
                    print(
                        f"[heal] runtime budget {max_runtime_s:.0f}s reached "
                        f"(elapsed {elapsed:.0f}s) — exiting between batches."
                    )
                    break

            chunk = queue[batch_idx : batch_idx + batch_size]
            batch_no = batch_idx // batch_size + 1
            total_batches = (len(queue) + batch_size - 1) // batch_size
            print(
                f"\n[heal] batch {batch_no}/{total_batches} — "
                f"{len(chunk)} traders (cursor {batch_idx}/{len(queue)})"
            )
            t_batch = time.time()

            # as_completed so we log per-trader as they finish — without this,
            # a slow trader silently blocks the whole batch (no feedback).
            tasks = []
            for t in chunk:
                attempt = attempts.get(t, 0)
                # Clamp into the schedule; graduation already happened upstream
                # if attempt >= GRADUATION_THRESHOLD, so we shouldn't see it.
                tmo = RETRY_TIMEOUTS_S[min(attempt, GRADUATION_THRESHOLD - 1)]
                tasks.append(
                    asyncio.create_task(
                        heal_one_trader(graph, db, catalog, t, sem, timeout=tmo)
                    )
                )
            batch_inserted = 0
            batch_healed = 0
            batch_irredeemable = 0
            batch_errors = 0
            batch_graduated = 0
            finished = 0
            for fut in asyncio.as_completed(tasks):
                r = await fut
                finished += 1
                trader = r["trader"]
                if "error" in r:
                    batch_errors += 1
                    err = r["error"]
                    is_timeout = err.startswith("timeout")
                    if is_timeout:
                        # Escalate; graduate at threshold.
                        new_attempt = attempts.get(trader, 0) + 1
                        if new_attempt >= GRADUATION_THRESHOLD:
                            db.execute(
                                "UPDATE traders SET graph_unservable = 1 "
                                "WHERE address = ?",
                                [trader],
                            )
                            db.conn.commit()
                            attempts.pop(trader, None)
                            failed.discard(trader)
                            batch_graduated += 1
                            print(
                                f"  [{finished:>2}/{len(chunk)}] [graduate] "
                                f"{trader[:10]}  {new_attempt} timeouts → "
                                f"graph_unservable=1"
                            )
                        else:
                            attempts[trader] = new_attempt
                            failed.add(trader)
                            print(
                                f"  [{finished:>2}/{len(chunk)}] [timeout] "
                                f"{trader[:10]}  attempt {new_attempt}/"
                                f"{GRADUATION_THRESHOLD}  {err}"
                            )
                    else:
                        # Non-timeout failure — keep in failed but don't escalate.
                        failed.add(trader)
                        print(
                            f"  [{finished:>2}/{len(chunk)}] [err] "
                            f"{trader[:10]}  {err}"
                        )
                    continue
                # Success: clear failed/attempts state for this trader.
                completed.add(trader)
                failed.discard(trader)
                attempts.pop(trader, None)
                batch_inserted += r["inserted"]
                batch_healed += r["healed_markets"]
                irr = r.get("irredeemable_marked", 0)
                batch_irredeemable += irr
                irr_tag = f"  irr={irr}" if irr else ""
                # Log every completion (success or no-op) so we always see
                # forward progress in the log, not just healing ones.
                print(
                    f"  [{finished:>2}/{len(chunk)}] {trader[:10]}  "
                    f"events={r['events']:>6}  inserted={r['inserted']:>5}  "
                    f"healed={r['healed_markets']}/{r['trapped_before']}{irr_tag}  "
                    f"({r['elapsed_s']}s)"
                )

            totals["traders_done"] += len(chunk) - batch_errors
            totals["trades_inserted"] += batch_inserted
            totals["markets_healed"] += batch_healed
            totals["irredeemable_marked"] += batch_irredeemable
            totals["errors"] += batch_errors
            totals["graduated"] += batch_graduated

            save_progress(completed, failed, attempts, totals)

            elapsed_b = time.time() - t_batch
            print(
                f"[heal]   batch done in {elapsed_b:.1f}s  "
                f"inserted={batch_inserted}  healed={batch_healed}  "
                f"irredeemable={batch_irredeemable}  errors={batch_errors}  "
                f"graduated={batch_graduated}"
            )
            print(
                f"[heal]   cumulative: traders_done={totals['traders_done']:,}  "
                f"trades_inserted={totals['trades_inserted']:,}  "
                f"markets_healed={totals['markets_healed']:,}  "
                f"irredeemable={totals['irredeemable_marked']:,}  "
                f"errors={totals['errors']}  "
                f"graduated={totals['graduated']}"
            )

            if batch_idx + batch_size < len(queue) and not _stop_requested:
                await asyncio.sleep(batch_sleep_s)
    finally:
        await graph.close()
        save_progress(completed, failed, attempts, totals)

    print("\n[heal] === done ===")
    print(
        f"  traders_done={totals['traders_done']:,}  "
        f"trades_inserted={totals['trades_inserted']:,}  "
        f"markets_healed={totals['markets_healed']:,}  "
        f"irredeemable_marked={totals['irredeemable_marked']:,}  "
        f"errors={totals['errors']}  "
        f"graduated={totals['graduated']}"
    )
    print(f"  progress saved to {PROGRESS_PATH}")
    return 0


def main() -> int:
    # Line-buffer stdout so progress appears in the log file in real time
    # when redirected (Python default is block-buffering for non-TTY stdout).
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    ap.add_argument("--batch-sleep", type=float, default=DEFAULT_BATCH_SLEEP_S)
    ap.add_argument(
        "--limit", type=int, default=None, help="Cap total traders processed this run"
    )
    ap.add_argument(
        "--resume", action="store_true", help="Skip traders already in progress file"
    )
    ap.add_argument(
        "--retry-failed",
        action="store_true",
        help="Also retry traders previously marked as failed (timeouts/errors)",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--max-runtime-s",
        type=float,
        default=None,
        help="Wall-clock budget. Exits cleanly between batches when exceeded.",
    )
    args = ap.parse_args()

    return asyncio.run(
        run(
            batch_size=args.batch_size,
            batch_sleep_s=args.batch_sleep,
            limit=args.limit,
            resume=args.resume,
            dry_run=args.dry_run,
            retry_failed=args.retry_failed,
            max_runtime_s=args.max_runtime_s,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
