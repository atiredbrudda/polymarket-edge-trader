"""Tests for position resolution from resolved market outcomes."""

import json
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Market, Position


class TestResolvePositions:
    """Tests for resolve_positions function."""

    def test_long_on_yes_market_wins(self):
        """Case 1 — LONG on YES market: position should resolve to 'win' with positive PnL."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            # Create market with YES outcome
            market = Market(
                condition_id="cond_1",
                question="Will team A win?",
                category="esports",
                outcome="YES",
            )
            session.add(market)

            # Create LONG position
            position = Position(
                market_id="cond_1",
                trader_address="0xTrader1",
                size=Decimal("100"),
                direction="LONG",
                avg_entry_price=Decimal("0.6"),
                resolved=False,
            )
            session.add(position)
            session.commit()

            from src.gamma.position_resolver import resolve_positions

            result = resolve_positions(session)

            assert position.resolved is True
            assert position.outcome == "win"
            assert position.pnl == Decimal("40.0")  # 100 * (1.0 - 0.6)
            assert result["resolved"] == 1
        finally:
            session.close()

    def test_long_on_no_market_loses(self):
        """Case 2 — LONG on NO market: position should resolve to 'loss' with negative PnL."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            market = Market(
                condition_id="cond_2",
                question="Will team A win?",
                category="esports",
                outcome="NO",
            )
            session.add(market)

            position = Position(
                market_id="cond_2",
                trader_address="0xTrader1",
                size=Decimal("100"),
                direction="LONG",
                avg_entry_price=Decimal("0.6"),
                resolved=False,
            )
            session.add(position)
            session.commit()

            from src.gamma.position_resolver import resolve_positions

            result = resolve_positions(session)

            assert position.resolved is True
            assert position.outcome == "loss"
            assert position.pnl == Decimal("-60.0")  # 100 * (0.0 - 0.6)
            assert result["resolved"] == 1
        finally:
            session.close()

    def test_short_on_no_market_wins(self):
        """Case 3 — SHORT on NO market: position should resolve to 'win' with positive PnL."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            market = Market(
                condition_id="cond_3",
                question="Will team A win?",
                category="esports",
                outcome="NO",
            )
            session.add(market)

            position = Position(
                market_id="cond_3",
                trader_address="0xTrader1",
                size=Decimal("100"),
                direction="SHORT",
                avg_entry_price=Decimal("0.4"),
                resolved=False,
            )
            session.add(position)
            session.commit()

            from src.gamma.position_resolver import resolve_positions

            result = resolve_positions(session)

            assert position.resolved is True
            assert position.outcome == "win"
            assert position.pnl == Decimal("40.0")  # 100 * (0.4 - 0.0)
            assert result["resolved"] == 1
        finally:
            session.close()

    def test_short_on_yes_market_loses(self):
        """Case 4 — SHORT on YES market: position should resolve to 'loss' with negative PnL."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            market = Market(
                condition_id="cond_4",
                question="Will team A win?",
                category="esports",
                outcome="YES",
            )
            session.add(market)

            position = Position(
                market_id="cond_4",
                trader_address="0xTrader1",
                size=Decimal("100"),
                direction="SHORT",
                avg_entry_price=Decimal("0.4"),
                resolved=False,
            )
            session.add(position)
            session.commit()

            from src.gamma.position_resolver import resolve_positions

            result = resolve_positions(session)

            assert position.resolved is True
            assert position.outcome == "loss"
            assert position.pnl == Decimal("-60.0")  # 100 * (0.4 - 1.0)
            assert result["resolved"] == 1
        finally:
            session.close()

    def test_flat_position(self):
        """Case 5 — FLAT position: should resolve to 'flat' with pnl=0."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            market = Market(
                condition_id="cond_5",
                question="Will team A win?",
                category="esports",
                outcome="YES",
            )
            session.add(market)

            position = Position(
                market_id="cond_5",
                trader_address="0xTrader1",
                size=Decimal("0"),
                direction="FLAT",
                resolved=False,
            )
            session.add(position)
            session.commit()

            from src.gamma.position_resolver import resolve_positions

            result = resolve_positions(session)

            assert position.resolved is True
            assert position.outcome == "flat"
            assert position.pnl == Decimal("0")
            assert result["resolved"] == 1
        finally:
            session.close()

    def test_market_outcome_null_skipped(self):
        """Case 6 — Market outcome is NULL: position should NOT be resolved, counted as skipped."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            market = Market(
                condition_id="cond_6",
                question="Will team A win?",
                category="esports",
                outcome=None,
            )
            session.add(market)

            position = Position(
                market_id="cond_6",
                trader_address="0xTrader1",
                size=Decimal("100"),
                direction="LONG",
                avg_entry_price=Decimal("0.6"),
                resolved=False,
            )
            session.add(position)
            session.commit()

            from src.gamma.position_resolver import resolve_positions

            result = resolve_positions(session)

            assert position.resolved is False
            assert result["skipped_no_outcome"] == 1
            assert result["resolved"] == 0
        finally:
            session.close()

    def test_idempotency_already_resolved(self):
        """Case 7 — Already resolved positions should be skipped."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            market = Market(
                condition_id="cond_7",
                question="Will team A win?",
                category="esports",
                outcome="YES",
            )
            session.add(market)

            # Already resolved position
            position = Position(
                market_id="cond_7",
                trader_address="0xTrader1",
                size=Decimal("100"),
                direction="LONG",
                avg_entry_price=Decimal("0.6"),
                resolved=True,
                outcome="win",
                pnl=Decimal("40.0"),
            )
            session.add(position)
            session.commit()

            from src.gamma.position_resolver import resolve_positions

            result = resolve_positions(session)

            # Position should remain unchanged
            assert position.resolved is True
            assert position.outcome == "win"
            assert position.pnl == Decimal("40.0")
            # Note: skipped_already_resolved is tracked but we return 0 in this implementation
            assert result["resolved"] == 0
        finally:
            session.close()

    def test_null_avg_entry_price(self):
        """Case 8 — NULL avg_entry_price: should resolve to 'flat' with pnl=0."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            market = Market(
                condition_id="cond_8",
                question="Will team A win?",
                category="esports",
                outcome="YES",
            )
            session.add(market)

            position = Position(
                market_id="cond_8",
                trader_address="0xTrader1",
                size=Decimal("100"),
                direction="LONG",
                avg_entry_price=None,  # NULL price
                resolved=False,
            )
            session.add(position)
            session.commit()

            from src.gamma.position_resolver import resolve_positions

            result = resolve_positions(session)

            assert position.resolved is True
            assert position.outcome == "flat"
            assert position.pnl == Decimal("0")
            assert result["resolved"] == 1
        finally:
            session.close()

    def test_void_market_outcome(self):
        """Case 9 — VOID market outcome: should resolve to 'void' with pnl=0."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            market = Market(
                condition_id="cond_9",
                question="Will team A win?",
                category="esports",
                outcome="VOID",
            )
            session.add(market)

            position = Position(
                market_id="cond_9",
                trader_address="0xTrader1",
                size=Decimal("100"),
                direction="LONG",
                avg_entry_price=Decimal("0.6"),
                resolved=False,
            )
            session.add(position)
            session.commit()

            from src.gamma.position_resolver import resolve_positions

            result = resolve_positions(session)

            assert position.resolved is True
            assert position.outcome == "void"
            assert position.pnl == Decimal("0")
            assert result["resolved"] == 1
        finally:
            session.close()
