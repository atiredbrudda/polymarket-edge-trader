"""Unit tests for lift metric pure functions.

Tests compute_clv, compute_roi, compute_sharpe, compute_z_scores,
compute_composite, assign_quintiles, and MarketConfig lookup.

All financial values use Decimal per project convention.
"""

from decimal import Decimal
from datetime import datetime, timedelta

import pytest

from src.config.market_config import MarketConfig, MARKET_CONFIGS, get_market_config
from src.evaluation.lift_metrics import (
    LiftMetrics,
    compute_clv,
    compute_roi,
    compute_sharpe,
    compute_z_scores,
    compute_composite,
    assign_quintiles,
)


# ---------------------------------------------------------------------------
# Helpers: minimal position stubs for pure-function tests
# ---------------------------------------------------------------------------

class _Pos:
    """Minimal position stub for testing pure functions."""

    def __init__(
        self,
        market_id: str,
        direction: str,
        avg_entry_price,
        size,
        pnl=None,
    ):
        self.market_id = market_id
        self.direction = direction
        self.avg_entry_price = Decimal(str(avg_entry_price)) if avg_entry_price is not None else None
        self.size = Decimal(str(size))
        self.pnl = Decimal(str(pnl)) if pnl is not None else None


# ---------------------------------------------------------------------------
# compute_clv
# ---------------------------------------------------------------------------

class TestComputeCLV:
    def test_long_position_positive_clv(self):
        """LONG position: bought at lower price than crowd = positive CLV."""
        # market_avg=0.50, trader_avg=0.35 -> CLV = 0.50 - 0.35 = 0.15
        pos = _Pos("m1", "LONG", 0.35, 100)
        market_avgs = {"m1": Decimal("0.50")}
        result = compute_clv([pos], market_avgs)
        assert result == pytest.approx(Decimal("0.15"), abs=Decimal("0.0001"))

    def test_short_position_positive_clv(self):
        """SHORT position: sold at higher price than crowd = positive CLV."""
        # trader_avg=0.70, market_avg=0.50 -> CLV = 0.70 - 0.50 = 0.20
        pos = _Pos("m1", "SHORT", 0.70, 100)
        market_avgs = {"m1": Decimal("0.50")}
        result = compute_clv([pos], market_avgs)
        assert result == pytest.approx(Decimal("0.20"), abs=Decimal("0.0001"))

    def test_empty_positions_returns_zero(self):
        """Empty position list returns Decimal('0')."""
        result = compute_clv([], {})
        assert result == Decimal("0")

    def test_no_avg_entry_price_skipped(self):
        """Positions with no avg_entry_price are skipped."""
        pos = _Pos("m1", "LONG", None, 100)
        market_avgs = {"m1": Decimal("0.50")}
        result = compute_clv([pos], market_avgs)
        assert result == Decimal("0")

    def test_missing_market_avg_skipped(self):
        """Positions without a corresponding market_avg are skipped."""
        pos = _Pos("m1", "LONG", 0.35, 100)
        result = compute_clv([pos], {})
        assert result == Decimal("0")

    def test_clv_averaged_across_multiple_positions(self):
        """CLV is averaged across all valid positions."""
        # LONG m1: CLV = 0.50 - 0.40 = 0.10
        # SHORT m2: CLV = 0.60 - 0.50 = 0.10
        # average = 0.10
        positions = [
            _Pos("m1", "LONG", 0.40, 100),
            _Pos("m2", "SHORT", 0.60, 100),
        ]
        market_avgs = {"m1": Decimal("0.50"), "m2": Decimal("0.50")}
        result = compute_clv(positions, market_avgs)
        assert result == pytest.approx(Decimal("0.10"), abs=Decimal("0.0001"))

    def test_negative_clv_when_trader_worse_than_crowd(self):
        """Trader who bought high vs crowd has negative CLV."""
        # LONG at 0.70, crowd avg 0.50 -> CLV = 0.50 - 0.70 = -0.20
        pos = _Pos("m1", "LONG", 0.70, 100)
        market_avgs = {"m1": Decimal("0.50")}
        result = compute_clv([pos], market_avgs)
        assert result == pytest.approx(Decimal("-0.20"), abs=Decimal("0.0001"))


# ---------------------------------------------------------------------------
# compute_roi
# ---------------------------------------------------------------------------

class TestComputeROI:
    def test_basic_roi(self):
        """total_pnl=100, capital_deployed=500 -> ROI=0.20."""
        pos = _Pos("m1", "LONG", 0.40, 500, pnl=100)
        # LONG capital = 500 * 0.40 = 200, not 500
        # Let's use a simpler: size=1000, price=0.50 -> capital=500; pnl=100
        pos = _Pos("m1", "LONG", 0.50, 1000, pnl=100)
        result = compute_roi([pos])
        # capital = 1000 * 0.50 = 500; ROI = 100/500 = 0.20
        assert result == pytest.approx(Decimal("0.20"), abs=Decimal("0.0001"))

    def test_zero_capital_returns_zero(self):
        """If capital_deployed is zero, return Decimal('0') to avoid division by zero."""
        # SHORT at price 1.0: capital = size * (1 - 1.0) = 0
        pos = _Pos("m1", "SHORT", 1.0, 100, pnl=10)
        result = compute_roi([pos])
        assert result == Decimal("0")

    def test_long_capital_calculation(self):
        """LONG capital = size * avg_entry_price."""
        # size=100, price=0.40 -> capital=40
        pos = _Pos("m1", "LONG", 0.40, 100, pnl=10)
        result = compute_roi([pos])
        # capital = 40; ROI = 10/40 = 0.25
        assert result == pytest.approx(Decimal("0.25"), abs=Decimal("0.0001"))

    def test_short_capital_calculation(self):
        """SHORT capital = size * (1 - avg_entry_price)."""
        # size=100, price=0.40 -> capital = 100 * 0.60 = 60
        pos = _Pos("m1", "SHORT", 0.40, 100, pnl=15)
        result = compute_roi([pos])
        # capital = 60; ROI = 15/60 = 0.25
        assert result == pytest.approx(Decimal("0.25"), abs=Decimal("0.0001"))

    def test_skip_none_pnl(self):
        """Positions with None pnl are skipped."""
        pos_valid = _Pos("m1", "LONG", 0.50, 100, pnl=10)
        pos_none = _Pos("m2", "LONG", 0.50, 100, pnl=None)
        result = compute_roi([pos_valid, pos_none])
        # Only pos_valid counted: capital=50, pnl=10 -> ROI=0.20
        assert result == pytest.approx(Decimal("0.20"), abs=Decimal("0.0001"))

    def test_skip_none_avg_entry_price(self):
        """Positions with None avg_entry_price are skipped."""
        pos_none = _Pos("m1", "LONG", None, 100, pnl=10)
        result = compute_roi([pos_none])
        assert result == Decimal("0")

    def test_empty_positions_returns_zero(self):
        """Empty position list returns Decimal('0')."""
        result = compute_roi([])
        assert result == Decimal("0")


# ---------------------------------------------------------------------------
# compute_sharpe
# ---------------------------------------------------------------------------

class TestComputeSharpe:
    def test_basic_sharpe(self):
        """avg_pnl=5.0, stddev=2.5 -> Sharpe=2.0."""
        # We need a population where mean=5.0 and stdev=2.5.
        # Use pnl values [2.5, 7.5] -> mean=5.0, stdev=3.535... no
        # Use pnl values [3.5, 6.5] -> mean=5.0, stdev=2.12... no
        # stdev formula for sample: stdev([a, b]) = |b-a| / sqrt(2)
        # so for stdev=2.5: |b-a| = 2.5 * sqrt(2) ~ 3.535
        # with mean=5: pnl=[5-1.767, 5+1.767] = [3.232, 6.767]
        # Let's just test the ratio directly:
        # Create pnl list where avg=5, stdev=2.5: use [2.5, 7.5] -> stdev=3.535
        # Instead just verify the ratio is avg/stdev(pnl_list)
        # Use [4, 6] -> mean=5, stdev=sqrt(2) ~ 1.414
        # Sharpe = 5 / 1.414 ~ 3.535
        # Use explicit: avg=5, stdev=2.5: Sharpe=2.0
        # positions: pnl values [3, 4, 5, 6, 7] -> mean=5, stdev=1.581... no
        # Construct 2-element list: mean = (a+b)/2 = 5, stdev = sqrt(((a-5)^2 + (b-5)^2)/1)
        # Let's just do pnl = [5 - x, 5 + x] where stdev = x * sqrt(2) = 2.5 -> x = 2.5/sqrt(2)
        # Simplify: just verify relative behavior
        import math
        x = Decimal(str(2.5 / math.sqrt(2)))
        pnl_values = [Decimal("5") - x, Decimal("5") + x]
        positions = [
            _Pos("m1", "LONG", 0.50, 100, pnl=float(pnl_values[0])),
            _Pos("m2", "LONG", 0.50, 100, pnl=float(pnl_values[1])),
        ]
        result = compute_sharpe(positions)
        assert result == pytest.approx(Decimal("2.0"), abs=Decimal("0.01"))

    def test_zero_stddev_returns_zero(self):
        """stddev=0 (all same PnL) returns Decimal('0')."""
        positions = [
            _Pos("m1", "LONG", 0.50, 100, pnl=5.0),
            _Pos("m2", "LONG", 0.50, 100, pnl=5.0),
            _Pos("m3", "LONG", 0.50, 100, pnl=5.0),
        ]
        result = compute_sharpe(positions)
        assert result == Decimal("0")

    def test_single_position_returns_zero(self):
        """Single position -> Sharpe=Decimal('0') (can't compute stdev)."""
        pos = _Pos("m1", "LONG", 0.50, 100, pnl=5.0)
        result = compute_sharpe([pos])
        assert result == Decimal("0")

    def test_empty_positions_returns_zero(self):
        """Empty positions returns Decimal('0')."""
        result = compute_sharpe([])
        assert result == Decimal("0")

    def test_none_pnl_skipped(self):
        """Positions with None pnl are skipped."""
        positions = [
            _Pos("m1", "LONG", 0.50, 100, pnl=5.0),
            _Pos("m2", "LONG", 0.50, 100, pnl=None),  # skipped
        ]
        # Only 1 valid -> returns 0
        result = compute_sharpe(positions)
        assert result == Decimal("0")


# ---------------------------------------------------------------------------
# compute_z_scores
# ---------------------------------------------------------------------------

class TestComputeZScores:
    def test_normal_population(self):
        """Normal population z-normalizes correctly."""
        values = {
            "a": Decimal("10"),
            "b": Decimal("20"),
            "c": Decimal("30"),
        }
        z = compute_z_scores(values)
        # mean=20, stdev(sample)=10
        # a: (10-20)/10 = -1.0
        # b: (20-20)/10 = 0.0
        # c: (30-20)/10 = 1.0
        assert z["b"] == pytest.approx(Decimal("0"), abs=Decimal("0.001"))
        assert z["a"] < Decimal("0")
        assert z["c"] > Decimal("0")
        # symmetry
        assert float(z["a"]) == pytest.approx(-float(z["c"]), abs=0.001)

    def test_single_trader_returns_zero(self):
        """n=1 returns z=0 (can't normalize)."""
        values = {"a": Decimal("42")}
        z = compute_z_scores(values)
        assert z["a"] == Decimal("0")

    def test_all_same_values_returns_zero(self):
        """All-same values returns z=0 for all traders."""
        values = {
            "a": Decimal("5"),
            "b": Decimal("5"),
            "c": Decimal("5"),
        }
        z = compute_z_scores(values)
        for addr in z:
            assert z[addr] == Decimal("0")

    def test_empty_returns_empty(self):
        """Empty dict returns empty dict."""
        z = compute_z_scores({})
        assert z == {}

    def test_preserves_all_trader_addresses(self):
        """Output dict has same keys as input."""
        values = {"a": Decimal("1"), "b": Decimal("2"), "c": Decimal("3")}
        z = compute_z_scores(values)
        assert set(z.keys()) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# compute_composite
# ---------------------------------------------------------------------------

class TestComputeComposite:
    def test_sums_three_z_scores(self):
        """Composite = z(CLV) + z(ROI) + z(Sharpe) per trader."""
        clv_z = {"a": Decimal("1.0"), "b": Decimal("-1.0")}
        roi_z = {"a": Decimal("0.5"), "b": Decimal("0.5")}
        sharpe_z = {"a": Decimal("0.5"), "b": Decimal("-0.5")}
        composite = compute_composite(clv_z, roi_z, sharpe_z)
        assert composite["a"] == pytest.approx(Decimal("2.0"), abs=Decimal("0.0001"))
        assert composite["b"] == pytest.approx(Decimal("-1.0"), abs=Decimal("0.0001"))

    def test_intersects_trader_sets(self):
        """Only traders present in all three dicts are included."""
        clv_z = {"a": Decimal("1.0"), "b": Decimal("0.5")}
        roi_z = {"a": Decimal("0.5"), "c": Decimal("0.5")}  # c not in clv_z
        sharpe_z = {"a": Decimal("0.5"), "b": Decimal("0.5")}
        composite = compute_composite(clv_z, roi_z, sharpe_z)
        # Only "a" is in all three
        assert "a" in composite
        assert "b" not in composite
        assert "c" not in composite

    def test_empty_inputs_return_empty(self):
        """Empty dicts return empty composite."""
        composite = compute_composite({}, {}, {})
        assert composite == {}


# ---------------------------------------------------------------------------
# assign_quintiles
# ---------------------------------------------------------------------------

class TestAssignQuintiles:
    def test_10_traders_q1_bottom_q5_top(self):
        """10 traders -> Q1=bottom 2, Q5=top 2."""
        scores = {f"t{i}": Decimal(str(i)) for i in range(10)}
        quintiles = assign_quintiles(scores)

        # t0, t1 = lowest scores -> Q1
        assert quintiles["t0"] == 1
        assert quintiles["t1"] == 1
        # t8, t9 = highest scores -> Q5
        assert quintiles["t8"] == 5
        assert quintiles["t9"] == 5

    def test_single_trader_q3(self):
        """1 trader -> Q3 (middle quintile with n<=1)."""
        scores = {"a": Decimal("1.0")}
        quintiles = assign_quintiles(scores)
        assert quintiles["a"] == 3

    def test_empty_returns_empty(self):
        """Empty scores returns empty dict."""
        result = assign_quintiles({})
        assert result == {}

    def test_quintile_values_in_range(self):
        """All quintile values are in [1, 5]."""
        scores = {f"t{i}": Decimal(str(i)) for i in range(20)}
        quintiles = assign_quintiles(scores)
        for addr, q in quintiles.items():
            assert 1 <= q <= 5, f"Trader {addr} has quintile {q} out of range"

    def test_5_traders_each_gets_different_quintile(self):
        """5 traders get Q1 through Q5."""
        scores = {f"t{i}": Decimal(str(i * 10)) for i in range(5)}
        quintiles = assign_quintiles(scores)
        assert set(quintiles.values()) == {1, 2, 3, 4, 5}


# ---------------------------------------------------------------------------
# MarketConfig
# ---------------------------------------------------------------------------

class TestMarketConfig:
    def test_esports_config(self):
        """esports returns min_positions=30, actionable=True."""
        cfg = get_market_config("esports")
        assert cfg is not None
        assert cfg.min_positions == 30
        assert cfg.actionable is True

    def test_epl_config(self):
        """epl returns min_positions=10, actionable=True."""
        cfg = get_market_config("epl")
        assert cfg is not None
        assert cfg.min_positions == 10
        assert cfg.actionable is True

    def test_politics_config(self):
        """politics returns min_positions=30, actionable=True."""
        cfg = get_market_config("politics")
        assert cfg is not None
        assert cfg.min_positions == 30
        assert cfg.actionable is True

    def test_la_liga_config(self):
        """la-liga returns min_positions=20, actionable=False."""
        cfg = get_market_config("la-liga")
        assert cfg is not None
        assert cfg.min_positions == 20
        assert cfg.actionable is False

    def test_ligue_1_config(self):
        """ligue-1 returns min_positions=10, actionable=False."""
        cfg = get_market_config("ligue-1")
        assert cfg is not None
        assert cfg.min_positions == 10
        assert cfg.actionable is False

    def test_nba_returns_none(self):
        """NBA intentionally absent from config -> returns None."""
        cfg = get_market_config("nba")
        assert cfg is None

    def test_unknown_returns_none(self):
        """Unknown category returns None."""
        cfg = get_market_config("cricket")
        assert cfg is None

    def test_case_insensitive_lookup(self):
        """Lookup is case-insensitive (eSports -> esports)."""
        cfg = get_market_config("eSports")
        assert cfg is not None
        assert cfg.min_positions == 30

    def test_market_config_is_frozen(self):
        """MarketConfig is frozen (immutable)."""
        cfg = get_market_config("esports")
        with pytest.raises((AttributeError, TypeError)):
            cfg.min_positions = 99  # type: ignore

    def test_all_configs_in_market_configs(self):
        """MARKET_CONFIGS has exactly 5 entries."""
        assert len(MARKET_CONFIGS) == 5
        assert set(MARKET_CONFIGS.keys()) == {
            "esports", "epl", "politics", "la-liga", "ligue-1"
        }
