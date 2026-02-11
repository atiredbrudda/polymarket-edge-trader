"""Tests for sweep orchestration and polling loop.

Test coverage:
- run_sweep: returns stats dict with all expected keys
- run_sweep: continues on ingest failure (logs error, proceeds to scoring)
- run_sweep: continues on scoring failure
- run_sweep: skips alerts when skip_alerts=True
- run_sweep: skips alerts when alerter is None
- run_polling_loop: respects shutdown flag (mock signal)
- run_polling_loop: logs cycle stats correctly

All tests use mocked pipeline functions to avoid real API calls.
"""

import signal
import time
from datetime import datetime, UTC
from decimal import Decimal
from unittest.mock import MagicMock, patch, call

import pytest

from src.cli.scheduler import run_sweep, run_polling_loop, _signal_handler


class TestRunSweep:
    """Tests for run_sweep function."""

    def test_returns_stats_dict_with_all_keys(self):
        """run_sweep returns stats dict with all expected keys."""
        # Mock dependencies
        session_factory = MagicMock()
        client = MagicMock()
        category_filter = MagicMock()

        # Mock pipeline functions
        with patch("src.cli.scheduler.IngestionPipeline") as mock_ingest, \
             patch("src.cli.scheduler.compute_all_game_scores") as mock_scoring, \
             patch("src.cli.scheduler.refresh_all_signals") as mock_signals:

            # Configure mocks
            mock_pipeline_instance = MagicMock()
            mock_ingest.return_value = mock_pipeline_instance
            mock_pipeline_instance.run_full_sweep.return_value = {
                "markets_ingested": 10,
                "traders_discovered": 5,
            }
            mock_scoring.return_value = {
                "esports.cs2": [MagicMock(), MagicMock()],
                "esports.lol": [MagicMock()],
            }
            mock_signals.return_value = [MagicMock(), MagicMock(), MagicMock()]

            # Run sweep
            stats = run_sweep(session_factory, client, category_filter)

            # Verify all expected keys present
            assert "markets_ingested" in stats
            assert "traders_discovered" in stats
            assert "scores_computed" in stats
            assert "signals_detected" in stats
            assert "alerts_sent" in stats
            assert "alerts_failed" in stats
            assert "duration_seconds" in stats

            # Verify values
            assert stats["markets_ingested"] == 10
            assert stats["traders_discovered"] == 5
            assert stats["scores_computed"] == 3  # 2 + 1
            assert stats["signals_detected"] == 3
            assert stats["alerts_sent"] == 0
            assert stats["alerts_failed"] == 0
            assert stats["duration_seconds"] > 0

    def test_continues_on_ingest_failure(self):
        """run_sweep continues on ingest failure, proceeds to scoring."""
        session_factory = MagicMock()
        client = MagicMock()
        category_filter = MagicMock()

        with patch("src.cli.scheduler.IngestionPipeline") as mock_ingest, \
             patch("src.cli.scheduler.compute_all_game_scores") as mock_scoring, \
             patch("src.cli.scheduler.refresh_all_signals") as mock_signals, \
             patch("src.cli.scheduler.logger") as mock_logger:

            # Ingest raises exception
            mock_ingest.side_effect = Exception("Ingest failed")

            # Other stages succeed
            mock_scoring.return_value = {"esports.cs2": [MagicMock()]}
            mock_signals.return_value = [MagicMock()]

            # Run sweep
            stats = run_sweep(session_factory, client, category_filter)

            # Verify ingest failure logged
            assert any("Ingestion stage failed" in str(call_args) for call_args in mock_logger.error.call_args_list)

            # Verify subsequent stages still ran
            assert mock_scoring.called
            assert mock_signals.called

            # Verify stats - ingest stats zero, but other stages populated
            assert stats["markets_ingested"] == 0
            assert stats["traders_discovered"] == 0
            assert stats["scores_computed"] == 1
            assert stats["signals_detected"] == 1

    def test_continues_on_scoring_failure(self):
        """run_sweep continues on scoring failure."""
        session_factory = MagicMock()
        client = MagicMock()
        category_filter = MagicMock()

        with patch("src.cli.scheduler.IngestionPipeline") as mock_ingest, \
             patch("src.cli.scheduler.compute_all_game_scores") as mock_scoring, \
             patch("src.cli.scheduler.refresh_all_signals") as mock_signals, \
             patch("src.cli.scheduler.logger") as mock_logger:

            # Ingest succeeds
            mock_pipeline = MagicMock()
            mock_ingest.return_value = mock_pipeline
            mock_pipeline.run_full_sweep.return_value = {"markets_ingested": 5, "traders_discovered": 2}

            # Scoring raises exception
            mock_scoring.side_effect = Exception("Scoring failed")

            # Signal detection succeeds
            mock_signals.return_value = [MagicMock(), MagicMock()]

            # Run sweep
            stats = run_sweep(session_factory, client, category_filter)

            # Verify scoring failure logged
            assert any("Scoring stage failed" in str(call_args) for call_args in mock_logger.error.call_args_list)

            # Verify signal detection still ran
            assert mock_signals.called

            # Verify stats
            assert stats["markets_ingested"] == 5
            assert stats["scores_computed"] == 0
            assert stats["signals_detected"] == 2

    def test_skips_alerts_when_skip_alerts_true(self):
        """run_sweep skips alerts when skip_alerts=True."""
        session_factory = MagicMock()
        client = MagicMock()
        category_filter = MagicMock()
        alerter = MagicMock()

        with patch("src.cli.scheduler.IngestionPipeline") as mock_ingest, \
             patch("src.cli.scheduler.compute_all_game_scores") as mock_scoring, \
             patch("src.cli.scheduler.refresh_all_signals") as mock_signals, \
             patch("src.cli.scheduler.deliver_signal_alerts") as mock_deliver:

            # Configure mocks
            mock_pipeline = MagicMock()
            mock_ingest.return_value = mock_pipeline
            mock_pipeline.run_full_sweep.return_value = {"markets_ingested": 5}
            mock_scoring.return_value = {"esports.cs2": []}
            mock_signals.return_value = []

            # Run sweep with skip_alerts=True
            stats = run_sweep(session_factory, client, category_filter, alerter, skip_alerts=True)

            # Verify deliver_signal_alerts NOT called
            assert not mock_deliver.called

            # Verify alert stats zero
            assert stats["alerts_sent"] == 0
            assert stats["alerts_failed"] == 0

    def test_skips_alerts_when_alerter_none(self):
        """run_sweep skips alerts when alerter is None."""
        session_factory = MagicMock()
        client = MagicMock()
        category_filter = MagicMock()

        with patch("src.cli.scheduler.IngestionPipeline") as mock_ingest, \
             patch("src.cli.scheduler.compute_all_game_scores") as mock_scoring, \
             patch("src.cli.scheduler.refresh_all_signals") as mock_signals, \
             patch("src.cli.scheduler.deliver_signal_alerts") as mock_deliver:

            # Configure mocks
            mock_pipeline = MagicMock()
            mock_ingest.return_value = mock_pipeline
            mock_pipeline.run_full_sweep.return_value = {"markets_ingested": 5}
            mock_scoring.return_value = {"esports.cs2": []}
            mock_signals.return_value = []

            # Run sweep with alerter=None
            stats = run_sweep(session_factory, client, category_filter, alerter=None)

            # Verify deliver_signal_alerts NOT called
            assert not mock_deliver.called

            # Verify alert stats zero
            assert stats["alerts_sent"] == 0
            assert stats["alerts_failed"] == 0

    def test_delivers_alerts_when_alerter_provided(self):
        """run_sweep delivers alerts when alerter provided and skip_alerts=False."""
        session_factory = MagicMock()
        client = MagicMock()
        category_filter = MagicMock()
        alerter = MagicMock()

        with patch("src.cli.scheduler.IngestionPipeline") as mock_ingest, \
             patch("src.cli.scheduler.compute_all_game_scores") as mock_scoring, \
             patch("src.cli.scheduler.refresh_all_signals") as mock_signals, \
             patch("src.cli.scheduler.deliver_signal_alerts") as mock_deliver:

            # Configure mocks
            mock_pipeline = MagicMock()
            mock_ingest.return_value = mock_pipeline
            mock_pipeline.run_full_sweep.return_value = {"markets_ingested": 5}
            mock_scoring.return_value = {"esports.cs2": []}
            mock_signals.return_value = []

            # Mock alert delivery results
            mock_result_success = MagicMock(success=True)
            mock_result_failure = MagicMock(success=False)
            mock_deliver.return_value = [mock_result_success, mock_result_success, mock_result_failure]

            # Run sweep with alerter
            stats = run_sweep(session_factory, client, category_filter, alerter)

            # Verify deliver_signal_alerts called
            assert mock_deliver.called

            # Verify alert stats
            assert stats["alerts_sent"] == 2
            assert stats["alerts_failed"] == 1


class TestRunPollingLoop:
    """Tests for run_polling_loop function."""

    def test_respects_shutdown_flag(self):
        """run_polling_loop respects shutdown flag (mock signal)."""
        session_factory = MagicMock()
        client = MagicMock()
        category_filter = MagicMock()

        with patch("src.cli.scheduler.run_sweep") as mock_sweep, \
             patch("src.cli.scheduler.signal.signal") as mock_signal_register, \
             patch("src.cli.scheduler._shutdown_flag", False):

            # Mock run_sweep to return stats
            mock_sweep.return_value = {
                "markets_ingested": 5,
                "traders_discovered": 2,
                "scores_computed": 10,
                "signals_detected": 3,
                "alerts_sent": 1,
                "alerts_failed": 0,
                "duration_seconds": 5.5,
            }

            # Patch time.sleep to trigger shutdown after first sleep check
            call_count = [0]

            def mock_sleep(seconds):
                call_count[0] += 1
                if call_count[0] >= 2:  # After second call, trigger shutdown
                    import src.cli.scheduler
                    src.cli.scheduler._shutdown_flag = True

            with patch("src.cli.scheduler.time.sleep", side_effect=mock_sleep):
                # Run polling loop with short interval
                run_polling_loop(session_factory, client, category_filter, interval_minutes=1)

            # Verify sweep was called at least once
            assert mock_sweep.call_count >= 1

            # Verify signal handlers registered
            assert mock_signal_register.call_count == 2  # SIGINT and SIGTERM

    def test_logs_cycle_stats(self):
        """run_polling_loop logs cycle stats correctly."""
        session_factory = MagicMock()
        client = MagicMock()
        category_filter = MagicMock()

        with patch("src.cli.scheduler.run_sweep") as mock_sweep, \
             patch("src.cli.scheduler.signal.signal"), \
             patch("src.cli.scheduler.logger") as mock_logger, \
             patch("src.cli.scheduler._shutdown_flag", False):

            # Mock run_sweep to return stats
            mock_sweep.return_value = {
                "markets_ingested": 10,
                "traders_discovered": 5,
                "scores_computed": 20,
                "signals_detected": 7,
                "alerts_sent": 3,
                "alerts_failed": 1,
                "duration_seconds": 12.3,
            }

            # Patch time.sleep to trigger shutdown immediately
            def mock_sleep(seconds):
                import src.cli.scheduler
                src.cli.scheduler._shutdown_flag = True

            with patch("src.cli.scheduler.time.sleep", side_effect=mock_sleep):
                # Run polling loop
                run_polling_loop(session_factory, client, category_filter, interval_minutes=1)

            # Verify cycle stats logged
            # Should contain: "Cycle", markets, signals, alerts, duration
            logged_messages = [str(call_args) for call_args in mock_logger.info.call_args_list]
            cycle_logs = [msg for msg in logged_messages if "Cycle" in msg]

            assert len(cycle_logs) > 0
            cycle_log = cycle_logs[0]
            assert "10 mkts" in cycle_log
            assert "7 sigs" in cycle_log
            assert "3 alerts" in cycle_log
            assert "12.3s" in cycle_log


class TestSignalHandler:
    """Tests for signal handler."""

    def test_signal_handler_sets_shutdown_flag(self):
        """_signal_handler sets shutdown flag when called."""
        import src.cli.scheduler

        # Reset flag
        src.cli.scheduler._shutdown_flag = False

        # Call signal handler
        _signal_handler(signal.SIGINT, None)

        # Verify flag set
        assert src.cli.scheduler._shutdown_flag is True

        # Reset for other tests
        src.cli.scheduler._shutdown_flag = False
