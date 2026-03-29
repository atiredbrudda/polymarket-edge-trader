"""Click CLI entry point with --niche flag support."""

import click
from pathlib import Path

from src.polymarket_analytics.config.loader import load_niche_config


@click.group()
@click.option(
    "--niche",
    default="esports",
    help="Niche slug for config lookup (default: esports)",
)
@click.pass_context
def cli(ctx, niche: str):
    """Polymarket Smart Money Tracker CLI.

    Detects when multiple proven traders are positioned in the same new market.
    """
    ctx.ensure_object(dict)
    ctx.obj["niche"] = niche

    # Load niche config from niches/{niche}.yaml
    config_path = Path(__file__).parent.parent.parent / "niches" / f"{niche}.yaml"
    config = load_niche_config(config_path)
    ctx.obj["config"] = config


# Import commands after cli is defined to register them
# This must be at the end to avoid circular imports
import src.polymarket_analytics.commands  # noqa: E402,F401
