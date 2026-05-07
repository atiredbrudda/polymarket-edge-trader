Q5_COMPOSITE_THRESHOLD = -0.10

# Bias-conservative bot/MM filter — applied at heal scan AND backfill ingest.
# Replaces the prior composite-score-only filter that had a 13% false-positive
# rate by trade-velocity proxy (per MM Filter Critique 2026-05-02 wiki).
#
# Design: behavioral signature (high trade-per-position ratio at high volume)
# combined with a Q5 whitelist that exempts every scored signal trader.
#
#   trades > BOT_TRADE_FLOOR
#     AND (trades / positions) > BOT_TPR_THRESHOLD
#     AND trader NOT IN (lift_scores WHERE composite_score >= Q5_COMPOSITE_THRESHOLD)
#
# Live calibration (data/analytics.db @ 2026-05-03, 7.4M trades / 28,809 traders):
#   - Catches 110 traders representing 21.3% of all trades (~1.58M rows)
#   - Zero Q5 traders excluded (the 4 high-tpr Q5 traders all profitable, including
#     0x9b4a306 with composite=1.625, get whitelist-saved)
#   - User-explicit calibration target: bias toward false-negatives (some bots through
#     OK) over false-positives (no real signal traders lost)
#
# Re-tune as needed:
#   - Lowering BOT_TRADE_FLOOR (e.g. 2000) catches ~268 traders / 28% trades but
#     starts catching newer/lower-volume bots whose status is less certain
#   - Raising BOT_TPR_THRESHOLD (e.g. 30) drops to ~75 traders / 14.6% — more
#     conservative if Q5 whitelist isn't enough
BOT_TRADE_FLOOR = 5000
BOT_TPR_THRESHOLD = 20


# Self-contained SELECT that returns lowercase trader_address for every
# trader matching the bot signature. Reused by heal_trapped_batch,
# backfill ingest, the prune script, and the in-memory leak-closing
# loaders below. Keep this as the single source of truth.
BOT_EXCLUSION_SQL = f"""
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


def load_bot_set(db) -> frozenset[str]:
    """Load the materialized bot denylist from traders.is_bot.

    Reads traders WHERE is_bot=1 — a fast indexed lookup now that
    refresh_bot_flags.py keeps the column current each cron cycle.
    Falls back to the behavioral query if the column doesn't exist yet
    (pre-migration environments).

    Accepts either a sqlite3.Connection or sqlite_utils.Database.
    """
    try:
        rows = db.execute(
            "SELECT address FROM traders WHERE COALESCE(is_bot, 0) = 1"
        ).fetchall()
        return frozenset((r[0] or "").lower() for r in rows if r[0])
    except Exception:
        # Column not yet migrated — fall back to behavioral query.
        try:
            rows = db.execute(BOT_EXCLUSION_SQL).fetchall()
            return frozenset((r[0] or "").lower() for r in rows if r[0])
        except Exception:
            return frozenset()
