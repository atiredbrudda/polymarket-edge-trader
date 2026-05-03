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
