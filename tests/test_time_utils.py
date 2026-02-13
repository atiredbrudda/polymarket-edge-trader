"""Tests for time parsing utilities."""

import unittest
from datetime import datetime, timedelta, UTC

from src.pipeline.time_utils import parse_closing_within


class TestTimeUtils(unittest.TestCase):
    """Test cases for time parsing utilities."""

    def test_parse_closing_within_hours(self):
        """Test parsing hours duration string."""
        result = parse_closing_within("48h")
        expected = datetime.now(UTC) + timedelta(hours=48)
        self.assertAlmostEqual(
            result.timestamp(),
            expected.timestamp(),
            delta=2,
            msg="48h should return datetime ~48 hours from now",
        )

    def test_parse_closing_within_days(self):
        """Test parsing days duration string."""
        result = parse_closing_within("2d")
        expected = datetime.now(UTC) + timedelta(days=2)
        self.assertAlmostEqual(
            result.timestamp(),
            expected.timestamp(),
            delta=2,
            msg="2d should return datetime ~2 days from now",
        )

    def test_parse_closing_within_minutes(self):
        """Test parsing minutes duration string."""
        result = parse_closing_within("30m")
        expected = datetime.now(UTC) + timedelta(minutes=30)
        self.assertAlmostEqual(
            result.timestamp(),
            expected.timestamp(),
            delta=2,
            msg="30m should return datetime ~30 minutes from now",
        )

    def test_parse_closing_within_mixed(self):
        """Test parsing mixed duration string."""
        result = parse_closing_within("1d12h")
        expected = datetime.now(UTC) + timedelta(hours=36)
        self.assertAlmostEqual(
            result.timestamp(),
            expected.timestamp(),
            delta=2,
            msg="1d12h should return datetime ~36 hours from now",
        )

    def test_parse_closing_within_invalid(self):
        """Test that invalid duration raises ValueError."""
        with self.assertRaises(ValueError) as context:
            parse_closing_within("xyz")
        self.assertIn("Invalid time format", str(context.exception))

    def test_parse_closing_within_empty(self):
        """Test that empty string raises ValueError."""
        with self.assertRaises(ValueError) as context:
            parse_closing_within("")
        self.assertIn("Invalid time format", str(context.exception))

    def test_parse_closing_within_returns_utc(self):
        """Test that result has UTC timezone info."""
        result = parse_closing_within("1h")
        self.assertEqual(result.tzinfo, UTC, "Result should have UTC timezone")

    def test_parse_closing_within_is_future(self):
        """Test that result is always in the future."""
        now = datetime.now(UTC)
        result = parse_closing_within("1h")
        self.assertGreater(
            result,
            now,
            msg="Result should always be in the future",
        )


if __name__ == "__main__":
    unittest.main()
