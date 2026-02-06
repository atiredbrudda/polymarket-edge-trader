"""
YAML taxonomy loader with Pydantic validation.

Loads taxonomy definitions from YAML files and validates against schema.
Uses yaml.safe_load() for security.
"""

from pathlib import Path
import yaml
from pydantic import ValidationError

from src.taxonomy.models import TaxonomyConfig


def load_taxonomy(path: Path) -> TaxonomyConfig:
    """
    Load taxonomy from YAML file.

    Args:
        path: Path to YAML taxonomy file

    Returns:
        Validated TaxonomyConfig instance

    Raises:
        FileNotFoundError: If file doesn't exist
        yaml.YAMLError: If YAML syntax is invalid
        ValidationError: If YAML structure doesn't match schema
    """
    if not path.exists():
        raise FileNotFoundError(f"Taxonomy file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Invalid YAML syntax in {path}: {e}") from e

    try:
        taxonomy = TaxonomyConfig.model_validate(data)
    except ValidationError as e:
        # Re-raise the original ValidationError with context message
        raise

    return taxonomy
