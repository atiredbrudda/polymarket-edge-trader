"""Integration tests for the rewritten analyze command.

Test coverage:
- analyze command structure: flags, help text
- analyze Q5 leaderboard logic (via direct function unit tests)
- analyze --signals logic (via direct function unit tests)
- old --crawl flag is removed

Note: Full end-to-end CLI invocation tests require a valid .env; we test
the command handler functions directly to avoid Settings dependency issues.
The --help tests verify command structure without triggering Settings loading.
"""

from datetime import datetime, timedelta, UTC
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.cli.commands import cli
from src.db.models import Base, LiftScore, Market, Trader, Position, SignalSnapshot


@pytest.fixture
def runner():
    """Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def engine():
    """In-memory SQLite engine."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session_factory(engine):
    """Session factory bound to in-memory engine."""
    return sessionmaker(bind=engine)


@pytest.fixture
def now():
    return datetime.now(UTC)


def make_lift_score(trader_address, category, now, quintile=5, composite_score=None, rank=1):
    """Helper: create a LiftScore fixture."""
    if composite_score is None:
        composite_score = Decimal("2.5") - Decimal(str(rank * 0.1))
    window_start = now - timedelta(days=30)
    return LiftScore(
        trader_address=trader_address,
        category=category,
        composite_score=composite_score,
        clv_raw=Decimal("0.05"),
        clv_zscore=Decimal("1.5"),
        roi_raw=Decimal("0.12"),
        roi_zscore=Decimal("1.0"),
        sharpe_raw=Decimal("2.1"),
        sharpe_zscore=Decimal("1.0"),
        quintile=quintile,
        position_count=20,
        total_pnl=Decimal("500"),
        capital_deployed=Decimal("5000"),
        window_start=window_start,
        window_end=now,
        computed_at=now - timedelta(hours=1),
    )


class TestAnalyzeCommandStructure:
    """Tests for analyze command structure and help text (no Settings loading)."""

    def test_analyze_command_exists(self, runner):
        """analyze command exists in CLI."""
        result = runner.invoke(cli, ["analyze", "--help"])
        assert result.exit_code == 0

    def test_analyze_has_category_option(self, runner):
        """analyze has --category option."""
        result = runner.invoke(cli, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "--category" in result.output or "-c" in result.output

    def test_analyze_has_signals_flag(self, runner):
        """analyze has --signals flag."""
        result = runner.invoke(cli, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "--signals" in result.output

    def test_analyze_no_crawl_in_help(self, runner):
        """analyze help does not mention --crawl."""
        result = runner.invoke(cli, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "--crawl" not in result.output

    def test_analyze_has_verbose_option(self, runner):
        """analyze has --verbose flag."""
        result = runner.invoke(cli, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "--verbose" in result.output or "-v" in result.output

    def test_analyze_help_mentions_q5(self, runner):
        """analyze help text references Q5 or leaderboard."""
        result = runner.invoke(cli, ["analyze", "--help"])
        assert result.exit_code == 0
        # Should describe the Q5 leaderboard or signals functionality
        output = result.output.lower()
        assert "q5" in output or "leaderboard" in output or "signals" in output or "lift" in output


class TestAnalyzeCrawlRemoved:
    """Tests that old --crawl flag is removed from analyze."""

    def test_crawl_not_in_analyze_help(self, runner):
        """--crawl is not listed in analyze help text."""
        result = runner.invoke(cli, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "--crawl" not in result.output

    def test_crawl_flag_raises_usage_error(self, runner):
        """--crawl flag should raise UsageError (no such option)."""
        result = runner.invoke(cli, ["analyze", "--crawl"])
        # Should fail with non-zero exit code (no such option)
        assert result.exit_code != 0


class TestAnalyzeLeaderboardLogic:
    """Tests for Q5 leaderboard display logic — called via direct imports."""

    def test_get_lift_leaderboard_returns_q5_entries(self, engine, now):
        """get_lift_leaderboard returns entries for the given category."""
        from src.pipeline.queries import get_lift_leaderboard

        with Session(engine) as sess:
            for i in range(5):
                addr = f"0xQ5Trader{i:040d}"
                sess.add(Trader(address=addr, first_seen=now))
                sess.add(make_lift_score(addr, "esports", now, quintile=5, rank=i+1))
            # Q3 trader should not appear in top results
            q3_addr = "0xQ3Trader" + "0" * 31
            sess.add(Trader(address=q3_addr, first_seen=now))
            sess.add(make_lift_score(q3_addr, "esports", now, quintile=3, composite_score=Decimal("-1.0")))
            sess.commit()

            entries = get_lift_leaderboard(sess, "esports", top_n=5)

        assert len(entries) == 5
        # All entries should have composite_score > Q3 trader
        for entry in entries:
            assert entry.composite_score > Decimal("-1.0")

    def test_get_lift_leaderboard_empty_for_unknown_category(self, engine, now):
        """get_lift_leaderboard returns empty for category with no scores."""
        from src.pipeline.queries import get_lift_leaderboard

        with Session(engine) as sess:
            entries = get_lift_leaderboard(sess, "notacategory", top_n=20)
        assert entries == []

    def test_get_lift_leaderboard_ordered_by_composite_desc(self, engine, now):
        """get_lift_leaderboard returns entries ordered by composite_score DESC."""
        from src.pipeline.queries import get_lift_leaderboard

        with Session(engine) as sess:
            for i, score in enumerate([Decimal("1.0"), Decimal("3.0"), Decimal("2.0")]):
                addr = f"0xOrderTest{i:040d}"
                sess.add(Trader(address=addr, first_seen=now))
                sess.add(make_lift_score(addr, "esports", now, quintile=5, composite_score=score))
            sess.commit()

            entries = get_lift_leaderboard(sess, "esports", top_n=20)

        scores = [e.composite_score for e in entries]
        assert scores == sorted(scores, reverse=True)


class TestAnalyzeSignalsLogic:
    """Tests for --signals mode logic — Q5 consensus detection."""

    def test_get_markets_by_expert_activity_with_q5(self, engine, now):
        """Q5 traders with recent positions appear in market activity query."""
        from src.signals.queries import get_markets_by_expert_activity

        market_id = "0xmarket" + "a" * 56
        with Session(engine) as sess:
            sess.add(Market(
                condition_id=market_id,
                question="CS2: NaVi vs FaZe",
                category="esports",
                active=True,
            ))
            for i in range(3):
                addr = f"0xSigQ5{i:040d}"
                sess.add(Trader(address=addr, first_seen=now))
                sess.add(make_lift_score(addr, "esports", now, quintile=5, rank=i+1))
                sess.add(Position(
                    market_id=market_id,
                    trader_address=addr,
                    direction="LONG",
                    size=Decimal("100"),
                    avg_entry_price=Decimal("0.35"),
                    last_trade_timestamp=now - timedelta(hours=2),
                    resolved=False,
                ))
            sess.commit()

            results = get_markets_by_expert_activity(sess, window_hours=24)

        market_ids = [r[0] for r in results]
        assert market_id in market_ids

    def test_refresh_market_signal_with_q5_experts(self, engine, now):
        """refresh_market_signal with 3 Q5 experts LONG detects consensus."""
        from src.signals.pipeline import refresh_market_signal

        market_id = "0xmarket" + "b" * 56
        with Session(engine) as sess:
            sess.add(Market(
                condition_id=market_id,
                question="Test market",
                category="esports",
                active=True,
            ))
            for i in range(3):
                addr = f"0xSigQ5b{i:039d}"
                sess.add(Trader(address=addr, first_seen=now))
                sess.add(make_lift_score(addr, "esports", now, quintile=5, rank=i+1))
                sess.add(Position(
                    market_id=market_id,
                    trader_address=addr,
                    direction="LONG",
                    size=Decimal("100"),
                    avg_entry_price=Decimal("0.30") + Decimal(str(i * 0.05)),
                    last_trade_timestamp=now - timedelta(hours=2),
                    resolved=False,
                ))
            sess.commit()

            results = refresh_market_signal(sess, market_id, min_experts=3,
                                             min_agreement_pct=Decimal("75"), now=now)

        assert len(results) == 1
        result = results[0]
        assert result.direction == "LONG"
        assert result.expert_count == 3
        # expert_avg_entry should be populated
        assert result.expert_avg_entry is not None

    def test_signal_result_has_expert_avg_entry(self, engine, now):
        """SignalResult expert_avg_entry averages Q5 entry prices correctly."""
        from src.signals.pipeline import refresh_market_signal

        market_id = "0xmarket" + "c" * 56
        entry_prices = [Decimal("0.30"), Decimal("0.35"), Decimal("0.40")]
        with Session(engine) as sess:
            sess.add(Market(
                condition_id=market_id,
                question="Test market 2",
                category="esports",
                active=True,
            ))
            for i, price in enumerate(entry_prices):
                addr = f"0xSigQ5c{i:039d}"
                sess.add(Trader(address=addr, first_seen=now))
                sess.add(make_lift_score(addr, "esports", now, quintile=5, rank=i+1))
                sess.add(Position(
                    market_id=market_id,
                    trader_address=addr,
                    direction="LONG",
                    size=Decimal("100"),
                    avg_entry_price=price,
                    last_trade_timestamp=now - timedelta(hours=1),
                    resolved=False,
                ))
            sess.commit()

            results = refresh_market_signal(sess, market_id, min_experts=3,
                                             min_agreement_pct=Decimal("75"), now=now)

        assert len(results) == 1
        # Expected avg: (0.30 + 0.35 + 0.40) / 3 = 0.35
        expected = Decimal("0.35")
        assert results[0].expert_avg_entry is not None
        assert abs(results[0].expert_avg_entry - expected) < Decimal("0.01")
