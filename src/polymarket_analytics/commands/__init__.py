"""CLI commands module - imports register commands with cli group."""

from src.polymarket_analytics.commands.backfill import backfill
from src.polymarket_analytics.commands.build_positions import build_positions
from src.polymarket_analytics.commands.classify_tokens import classify_tokens
from src.polymarket_analytics.commands.discover import discover
from src.polymarket_analytics.commands.ingest_events import ingest_events
from src.polymarket_analytics.commands.resolve_outcomes import resolve_outcomes
from src.polymarket_analytics.commands.sanity_check import sanity_check

__all__ = [
    "backfill",
    "build_positions",
    "classify_tokens",
    "discover",
    "ingest_events",
    "resolve_outcomes",
    "sanity_check",
]
