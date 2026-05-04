"""Unit tests for paper_bridge._compute_size sizing logic.

Verifies that the Hi-conviction tier override (removed 2026-05-04) is gone,
and that tier-based sizing is the single axis controlling allocation.
"""

import pytest

from polymarket_analytics.commands.paper_bridge import _compute_size


def test_compute_size_act_standard():
    signal = {"tier": "ACT", "event_group_size": 1}
    assert _compute_size(signal, 10_000) == pytest.approx(200.0)


def test_compute_size_consider():
    signal = {"tier": "CONSIDER", "event_group_size": 1}
    assert _compute_size(signal, 10_000) == pytest.approx(100.0)


def test_compute_size_no_hi_conv_override():
    """Post-2026-05-04: Hi-conv tier removed. q5>=5 + clv_ratio>0.6 should
    size at the standard ACT 2% rate, not 2.5%."""
    signal = {"tier": "ACT", "event_group_size": 1}
    assert _compute_size(signal, 10_000) == pytest.approx(200.0)


def test_compute_size_unanimous_clv_dom_at_consider():
    """Unanimous-CLV-dom signals are demoted to CONSIDER by convergence.py.
    Sizing must respect that — 1% not 2.5%."""
    signal = {"tier": "CONSIDER", "event_group_size": 1}
    assert _compute_size(signal, 10_000) == pytest.approx(100.0)


def test_compute_size_correlated_act():
    signal = {"tier": "ACT", "event_group_size": 4}
    assert _compute_size(signal, 10_000) == pytest.approx(50.0)


def test_compute_size_correlated_consider():
    signal = {"tier": "CONSIDER", "event_group_size": 3}
    assert _compute_size(signal, 10_000) == pytest.approx(100.0 / 3)


def test_compute_size_null_event_group_treated_as_one():
    signal = {"tier": "ACT", "event_group_size": None}
    assert _compute_size(signal, 10_000) == pytest.approx(200.0)
