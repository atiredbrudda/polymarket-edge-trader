"""Polymarket Analytics CLI package."""

__version__ = "0.1.0"


def __getattr__(name):
    """Lazy import to avoid circular imports."""
    if name == "cli":
        from src.polymarket_analytics.cli import cli

        return cli
    raise AttributeError(f"module {__name__!r} has no attribute {__name__!r}")


__all__ = ["cli"]
