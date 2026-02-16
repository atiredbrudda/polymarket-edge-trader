"""Integration tests for targeted market scanning flow."""

import unittest
from unittest.mock import MagicMock, patch

from src.pipeline.ingest import IngestionPipeline


MOCK_GAMMA_MARKETS = [
    {
        "condition_id": "0xabc123",
        "question": "Will Team A win?",
        "end_date": "2026-02-15T00:00:00Z",
        "closed": False,
        "active": True,
        "category": "eSports",
        "tags": [{"label": "eSports", "id": 1}],
        "tokens": [
            {"token_id": "tok1", "outcome": "Yes"},
            {"token_id": "tok2", "outcome": "No"},
        ],
    },
    {
        "condition_id": "0xdef456",
        "question": "Will Team B win?",
        "end_date": "2026-02-16T00:00:00Z",
        "closed": False,
        "active": True,
        "category": "eSports",
        "tags": [{"label": "eSports", "id": 1}],
        "tokens": [
            {"token_id": "tok3", "outcome": "Yes"},
            {"token_id": "tok4", "outcome": "No"},
        ],
    },
]

# Events wrap markets — the /events endpoint returns this structure
MOCK_GAMMA_EVENTS = [
    {
        "id": "evt-1",
        "title": "Team A vs Team B",
        "startDate": "2026-02-15T18:00:00Z",
        "endDate": "2026-02-15T21:00:00Z",
        "tags": [{"label": "eSports", "id": 64}],
        "markets": [
            {
                "conditionId": "0xabc123",
                "question": "Will Team A win?",
                "endDateIso": "2026-02-15T21:00:00Z",
                "closed": False,
                "active": True,
                "tokens": [
                    {"token_id": "tok1", "outcome": "Yes"},
                    {"token_id": "tok2", "outcome": "No"},
                ],
            },
        ],
    },
    {
        "id": "evt-2",
        "title": "Team C vs Team D",
        "startDate": "2026-02-16T15:00:00Z",
        "endDate": "2026-02-16T18:00:00Z",
        "tags": [{"label": "eSports", "id": 64}],
        "markets": [
            {
                "conditionId": "0xdef456",
                "question": "Will Team C win?",
                "endDateIso": "2026-02-16T18:00:00Z",
                "closed": False,
                "active": True,
                "tokens": [
                    {"token_id": "tok3", "outcome": "Yes"},
                    {"token_id": "tok4", "outcome": "No"},
                ],
            },
        ],
    },
]


class TestCLITargetedOptions(unittest.TestCase):
    """Test CLI shows targeted scanning options."""

    def test_sweep_help_shows_niche_option(self):
        """sweep --help shows --niche option."""
        from click.testing import CliRunner
        from src.cli.commands import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["sweep", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--niche", result.output)

    def test_sweep_help_shows_closing_within_option(self):
        """sweep --help shows --closing-within option."""
        from click.testing import CliRunner
        from src.cli.commands import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["sweep", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--closing-within", result.output)

    def test_poll_help_shows_niche_option(self):
        """poll --help shows --niche option."""
        from click.testing import CliRunner
        from src.cli.commands import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["poll", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--niche", result.output)

    def test_poll_help_shows_closing_within_option(self):
        """poll --help shows --closing-within option."""
        from click.testing import CliRunner
        from src.cli.commands import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["poll", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--closing-within", result.output)


class TestIngestionPipeline(unittest.TestCase):
    """Test IngestionPipeline targeted methods."""

    def test_ingest_targeted_markets_with_niches(self):
        """Test ingest_targeted_markets calls Gamma get_events for each niche."""
        mock_client = MagicMock()
        mock_session_factory = MagicMock()
        mock_category_filter = MagicMock()

        mock_gamma_client = MagicMock()
        mock_gamma_client.get_events.side_effect = [
            [MOCK_GAMMA_EVENTS[0]],
            [],
        ]

        pipeline = IngestionPipeline(
            mock_client,
            mock_session_factory,
            mock_category_filter,
            gamma_client=mock_gamma_client,
        )

        with patch.object(pipeline, "session_factory") as mock_session:
            mock_session_instance = MagicMock()
            mock_session.return_value = mock_session_instance
            mock_session_instance.query.return_value.filter_by.return_value.first.return_value = None

            result = pipeline.ingest_targeted_markets(niches=("esports", "crypto"))

            self.assertEqual(mock_gamma_client.get_events.call_count, 2)
            call_args_list = mock_gamma_client.get_events.call_args_list
            self.assertEqual(call_args_list[0].kwargs.get("tag_id"), 64)
            self.assertEqual(call_args_list[1].kwargs.get("tag_id"), 100630)

    def test_ingest_targeted_markets_with_time_filter(self):
        """Test ingest_targeted_markets passes end_date_max to Gamma get_events."""
        from datetime import datetime, UTC

        mock_client = MagicMock()
        mock_session_factory = MagicMock()
        mock_category_filter = MagicMock()

        mock_gamma_client = MagicMock()
        mock_gamma_client.get_events.return_value = MOCK_GAMMA_EVENTS

        pipeline = IngestionPipeline(
            mock_client,
            mock_session_factory,
            mock_category_filter,
            gamma_client=mock_gamma_client,
        )

        test_date = datetime(2026, 2, 20, tzinfo=UTC)

        with patch.object(pipeline, "session_factory") as mock_session:
            mock_session_instance = MagicMock()
            mock_session.return_value = mock_session_instance
            mock_session_instance.query.return_value.filter_by.return_value.first.return_value = None

            result = pipeline.ingest_targeted_markets(niches=(), end_date_max=test_date)

            mock_gamma_client.get_events.assert_called_once()
            call_kwargs = mock_gamma_client.get_events.call_args.kwargs
            self.assertEqual(call_kwargs.get("end_date_max"), test_date)

    def test_ingest_targeted_markets_fallback(self):
        """Test ingest_targeted_markets falls back when gamma_client is None."""
        mock_client = MagicMock()
        mock_session_factory = MagicMock()
        mock_category_filter = MagicMock()

        pipeline = IngestionPipeline(
            mock_client,
            mock_session_factory,
            mock_category_filter,
            gamma_client=None,
        )

        with patch.object(pipeline, "ingest_active_markets") as mock_ingest:
            mock_ingest.return_value = 5
            result = pipeline.ingest_targeted_markets(niches=("esports",))

            mock_ingest.assert_called_once()

    def test_run_full_sweep_accepts_niches_param(self):
        """Test run_full_sweep accepts niches and closing_within params."""
        mock_client = MagicMock()
        mock_session_factory = MagicMock()
        mock_category_filter = MagicMock()
        mock_gamma_client = MagicMock()

        pipeline = IngestionPipeline(
            mock_client,
            mock_session_factory,
            mock_category_filter,
            gamma_client=mock_gamma_client,
        )

        with patch.object(pipeline, "ingest_targeted_markets") as mock_ingest:
            mock_ingest.return_value = 10

            result = pipeline.run_full_sweep(niches=("esports",), closing_within="48h")

            mock_ingest.assert_called_once()
            call_kwargs = mock_ingest.call_args.kwargs
            self.assertEqual(call_kwargs.get("niches"), ("esports",))
            self.assertIsNotNone(call_kwargs.get("end_date_max"))

    def test_run_full_sweep_without_filters(self):
        """Test run_full_sweep without filters uses existing path."""
        mock_client = MagicMock()
        mock_session_factory = MagicMock()
        mock_category_filter = MagicMock()

        pipeline = IngestionPipeline(
            mock_client,
            mock_session_factory,
            mock_category_filter,
            gamma_client=None,
        )

        with patch.object(pipeline, "ingest_active_markets") as mock_ingest:
            mock_ingest.return_value = 5

            result = pipeline.run_full_sweep()

            mock_ingest.assert_called_once()


if __name__ == "__main__":
    unittest.main()
