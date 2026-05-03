"""Ingestion-time filter to skip prop markets before they hit the DB.

Prop questions (kill counts, dragon objectives, first blood, etc.) are
empirically signal-free for Q5 traders — see wiki page "Prop-Market Prune".
Filtering at ingest keeps the DB clean and avoids pruning later.

The pattern matching here mirrors the SQL LIKE matching used by the prune
scripts so that the in-Python filter and the SQL DELETE produce identical sets.
"""

from __future__ import annotations

import fnmatch
from typing import Optional

from polymarket_analytics.filters.prop_patterns import PROP_PATTERNS


def _sql_like_to_glob(pattern: str) -> str:
    """Translate SQL LIKE pattern to fnmatch glob pattern.

    SQL LIKE: % = any sequence, _ = single char. fnmatch: * and ?.
    """
    return pattern.replace("%", "*").replace("_", "?")


_GLOB_PATTERNS: list[tuple[str, str]] = [(label, _sql_like_to_glob(p)) for label, p in PROP_PATTERNS]


def matched_prop_label(question: Optional[str]) -> Optional[str]:
    """Return the matching PROP_PATTERNS label, or None if not a prop."""
    if not question:
        return None
    q_lower = question.lower()
    for label, glob in _GLOB_PATTERNS:
        if fnmatch.fnmatchcase(q_lower, glob):
            return label
    return None


def is_prop_market(question: Optional[str]) -> bool:
    """True if the question text matches any prop pattern."""
    return matched_prop_label(question) is not None
