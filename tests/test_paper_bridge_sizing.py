"""Unit tests for paper_bridge._compute_size sizing logic.

Verifies that the Hi-conviction tier override (removed 2026-05-04) is gone,
and that tier-based sizing is the single axis controlling allocation.

Divisor changed 2026-05-09: event_group_size divisor is now ÷√N (not ÷N).
Single-market signals are unchanged (1/√1 = 1/1 = 1). Correlated signals
get a smaller discount: group=4 → ÷2 (was ÷4); group=3 → ÷1.732 (was ÷3).
"""

import math

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
    # ÷√4 = ÷2 → 100.0 (was 50.0 under ÷4)
    signal = {"tier": "ACT", "event_group_size": 4}
    assert _compute_size(signal, 10_000) == pytest.approx(200.0 / math.sqrt(4))


def test_compute_size_correlated_consider():
    # ÷√3 → 100/1.732 ≈ 57.74 (was 100/3 ≈ 33.33 under ÷3)
    signal = {"tier": "CONSIDER", "event_group_size": 3}
    assert _compute_size(signal, 10_000) == pytest.approx(100.0 / math.sqrt(3))


def test_compute_size_null_event_group_treated_as_one():
    signal = {"tier": "ACT", "event_group_size": None}
    assert _compute_size(signal, 10_000) == pytest.approx(200.0)
