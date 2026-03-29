"""Configuration module for Polymarket Analytics.

Exports:
    NicheConfig: Pydantic model for niche configuration validation
    load_niche_config: Function to load and validate YAML config files
"""

from polymarket_analytics.config.loader import NicheConfig, load_niche_config

__all__ = ["NicheConfig", "load_niche_config"]
