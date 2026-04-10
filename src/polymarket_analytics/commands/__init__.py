"""CLI commands module - imports register commands with cli group."""

from polymarket_analytics.commands.backfill import backfill
from polymarket_analytics.commands.build_positions import build_positions
from polymarket_analytics.commands.classify_tokens import classify_tokens
from polymarket_analytics.commands.detect import detect
from polymarket_analytics.commands.discover import discover
from polymarket_analytics.commands.paper_bridge import paper_bridge
from polymarket_analytics.commands.monitor import monitor
from polymarket_analytics.commands.ingest_events import ingest_events
from polymarket_analytics.commands.resolve_outcomes import resolve_outcomes
from polymarket_analytics.commands.resolve_positions import resolve_positions
from polymarket_analytics.commands.sanity_check import sanity_check
from polymarket_analytics.commands.score import score
from polymarket_analytics.commands.serve import serve
from polymarket_analytics.commands.show_traders import show_traders

__all__ = [
    "backfill",
    "build_positions",
    "classify_tokens",
    "detect",
    "discover",
    "monitor",
    "paper_bridge",
    "ingest_events",
    "resolve_outcomes",
    "resolve_positions",
    "sanity_check",
    "score",
    "serve",
    "show_traders",
]
