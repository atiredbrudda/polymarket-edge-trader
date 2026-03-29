"""CLI commands module - imports register commands with cli group."""

from src.polymarket_analytics.commands.build_token_catalog import build_token_catalog
from src.polymarket_analytics.commands.classify_tokens import classify_tokens
from src.polymarket_analytics.commands.discover import discover
from src.polymarket_analytics.commands.ingest_events import ingest_events
from src.polymarket_analytics.commands.resolve_outcomes import resolve_outcomes

__all__ = [
    "build_token_catalog",
    "classify_tokens",
    "discover",
    "ingest_events",
    "resolve_outcomes",
]
