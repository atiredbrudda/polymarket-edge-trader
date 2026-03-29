"""CLI commands module - imports register commands with cli group."""

from src.polymarket_analytics.commands.build_token_catalog import build_token_catalog
from src.polymarket_analytics.commands.ingest_events import ingest_events

__all__ = ["build_token_catalog", "ingest_events"]
