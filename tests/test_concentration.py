"""
Tests for concentration metrics and specialization classification.

Tests the two-tier concentration system:
1. eSports-level concentration (% of total volume in eSports)
2. Game-level concentration (% of eSports volume in specific game)

All tests use simple Decimal inputs, no mocks needed.
"""

from decimal import Decimal
import pytest

from src.evaluation.concentration import (
    calculate_esports_concentration,
    calculate_game_concentration,
    classify_specialization,
    SpecializationProfile,
)


class TestEsportsConcentration:
    """Tests for eSports-level concentration calculation."""

    def test_basic_concentration_calculation(self):
        """Calculate esports concentration from volumes."""
        esports_volume = Decimal("70")
        total_volume = Decimal("100")

        result = calculate_esports_concentration(esports_volume, total_volume)

        assert result == Decimal("0.7")

    def test_perfect_esports_specialist(self):
        """Trader with all volume in eSports."""
        esports_volume = Decimal("100")
        total_volume = Decimal("100")

        result = calculate_esports_concentration(esports_volume, total_volume)

        assert result == Decimal("1.0")

    def test_no_esports_activity(self):
        """Trader with no eSports volume."""
        esports_volume = Decimal("0")
        total_volume = Decimal("100")

        result = calculate_esports_concentration(esports_volume, total_volume)

        assert result == Decimal("0")

    def test_zero_total_volume(self):
        """Handle zero total volume edge case."""
        esports_volume = Decimal("0")
        total_volume = Decimal("0")

        result = calculate_esports_concentration(esports_volume, total_volume)

        assert result == Decimal("0")

    def test_partial_esports_concentration(self):
        """Trader active in eSports and other categories."""
        esports_volume = Decimal("3500.50")
        total_volume = Decimal("10000")

        result = calculate_esports_concentration(esports_volume, total_volume)

        assert result == Decimal("0.350050")


class TestGameConcentration:
    """Tests for game-level concentration calculation."""

    def test_basic_game_concentration(self):
        """Calculate game concentration from volumes."""
        game_volume = Decimal("50")
        esports_volume = Decimal("100")

        result = calculate_game_concentration(game_volume, esports_volume)

        assert result == Decimal("0.5")

    def test_single_game_specialist(self):
        """Trader focused on one game only."""
        game_volume = Decimal("100")
        esports_volume = Decimal("100")

        result = calculate_game_concentration(game_volume, esports_volume)

        assert result == Decimal("1.0")

    def test_no_game_activity(self):
        """Trader with no volume in specific game."""
        game_volume = Decimal("0")
        esports_volume = Decimal("100")

        result = calculate_game_concentration(game_volume, esports_volume)

        assert result == Decimal("0")

    def test_zero_esports_volume(self):
        """Handle zero eSports volume edge case."""
        game_volume = Decimal("0")
        esports_volume = Decimal("0")

        result = calculate_game_concentration(game_volume, esports_volume)

        assert result == Decimal("0")

    def test_multi_game_distribution(self):
        """Trader active in multiple games."""
        game_volume = Decimal("2500.75")
        esports_volume = Decimal("5000")

        result = calculate_game_concentration(game_volume, esports_volume)

        assert result == Decimal("0.500150")


class TestSpecializationClassification:
    """Tests for specialization classification at both levels."""

    def test_pure_esports_specialist(self):
        """Trader specialized at both eSports and game level."""
        esports_concentration = Decimal("0.9")
        game_concentration = Decimal("0.8")
        game_slug = "esports.cs2"

        result = classify_specialization(
            esports_concentration, game_concentration, game_slug
        )

        assert isinstance(result, SpecializationProfile)
        assert result.esports_level == "specialist"
        assert result.game_level == "specialist"
        assert result.esports_concentration == Decimal("0.9")
        assert result.game_concentration == Decimal("0.8")
        assert result.primary_game == "esports.cs2"

    def test_esports_specialist_game_generalist(self):
        """Trader specialized in eSports but plays multiple games."""
        esports_concentration = Decimal("0.85")
        game_concentration = Decimal("0.3")
        game_slug = "esports.valorant"

        result = classify_specialization(
            esports_concentration, game_concentration, game_slug
        )

        assert result.esports_level == "specialist"
        assert result.game_level == "generalist"
        assert result.esports_concentration == Decimal("0.85")
        assert result.game_concentration == Decimal("0.3")
        assert result.primary_game is None  # Generalist has no primary game

    def test_esports_generalist(self):
        """Trader not specialized in eSports."""
        esports_concentration = Decimal("0.3")
        game_concentration = Decimal("0.8")  # Irrelevant if not eSports specialist
        game_slug = "esports.dota2"

        result = classify_specialization(
            esports_concentration, game_concentration, game_slug
        )

        assert result.esports_level == "generalist"
        # Can still be game specialist within eSports
        assert result.game_level == "specialist"
        assert result.esports_concentration == Decimal("0.3")
        assert result.game_concentration == Decimal("0.8")
        # primary_game set if game_level is specialist
        assert result.primary_game == "esports.dota2"

    def test_boundary_esports_threshold(self):
        """Exactly at eSports threshold counts as specialist."""
        esports_concentration = Decimal("0.7")  # Exactly at default threshold
        game_concentration = Decimal("0.6")
        game_slug = "esports.lol"

        result = classify_specialization(
            esports_concentration, game_concentration, game_slug
        )

        assert result.esports_level == "specialist"  # >= comparison
        assert result.game_level == "specialist"
        assert result.primary_game == "esports.lol"

    def test_boundary_game_threshold(self):
        """Exactly at game threshold counts as specialist."""
        esports_concentration = Decimal("0.9")
        game_concentration = Decimal("0.5")  # Exactly at default threshold
        game_slug = "esports.cs2"

        result = classify_specialization(
            esports_concentration, game_concentration, game_slug
        )

        assert result.esports_level == "specialist"
        assert result.game_level == "specialist"  # >= comparison
        assert result.primary_game == "esports.cs2"

    def test_just_below_thresholds(self):
        """Just below thresholds counts as generalist."""
        esports_concentration = Decimal("0.69")  # Below 0.7
        game_concentration = Decimal("0.49")  # Below 0.5
        game_slug = "esports.valorant"

        result = classify_specialization(
            esports_concentration, game_concentration, game_slug
        )

        assert result.esports_level == "generalist"
        assert result.game_level == "generalist"
        assert result.primary_game is None

    def test_custom_thresholds(self):
        """Classification with custom thresholds."""
        esports_concentration = Decimal("0.6")
        game_concentration = Decimal("0.4")
        game_slug = "esports.cs2"

        result = classify_specialization(
            esports_concentration,
            game_concentration,
            game_slug,
            esports_threshold=Decimal("0.5"),  # Lower threshold
            game_threshold=Decimal("0.3"),  # Lower threshold
        )

        assert result.esports_level == "specialist"  # 0.6 >= 0.5
        assert result.game_level == "specialist"  # 0.4 >= 0.3
        assert result.primary_game == "esports.cs2"

    def test_multi_game_specialist_possible(self):
        """A trader can be specialist in multiple games (independent per call)."""
        # Scenario: Trader has 90% volume in eSports, split 55% CS2 and 45% Valorant
        esports_concentration = Decimal("0.9")

        # Check CS2 specialization
        cs2_concentration = Decimal("0.55")
        cs2_result = classify_specialization(
            esports_concentration, cs2_concentration, "esports.cs2"
        )

        # Check Valorant specialization
        valorant_concentration = Decimal("0.45")
        valorant_result = classify_specialization(
            esports_concentration, valorant_concentration, "esports.valorant"
        )

        # Both should be game specialists (>= 0.5 threshold is met for CS2,
        # just below for Valorant but demonstrates independence)
        assert cs2_result.game_level == "specialist"
        assert cs2_result.primary_game == "esports.cs2"
        # Valorant is generalist at 0.45 < 0.5
        assert valorant_result.game_level == "generalist"
        assert valorant_result.primary_game is None

    def test_zero_concentrations(self):
        """Handle zero concentrations (no activity)."""
        esports_concentration = Decimal("0")
        game_concentration = Decimal("0")
        game_slug = "esports.cs2"

        result = classify_specialization(
            esports_concentration, game_concentration, game_slug
        )

        assert result.esports_level == "generalist"
        assert result.game_level == "generalist"
        assert result.primary_game is None

    def test_primary_game_only_for_specialist(self):
        """primary_game is None for game generalists, set for specialists."""
        # Generalist case
        generalist_result = classify_specialization(
            Decimal("0.8"), Decimal("0.3"), "esports.dota2"
        )
        assert generalist_result.game_level == "generalist"
        assert generalist_result.primary_game is None

        # Specialist case
        specialist_result = classify_specialization(
            Decimal("0.8"), Decimal("0.7"), "esports.dota2"
        )
        assert specialist_result.game_level == "specialist"
        assert specialist_result.primary_game == "esports.dota2"


class TestSpecializationProfile:
    """Tests for SpecializationProfile dataclass."""

    def test_dataclass_frozen(self):
        """SpecializationProfile should be frozen."""
        profile = SpecializationProfile(
            esports_level="specialist",
            game_level="specialist",
            esports_concentration=Decimal("0.8"),
            game_concentration=Decimal("0.6"),
            primary_game="esports.cs2",
        )

        with pytest.raises(Exception):  # FrozenInstanceError in dataclasses
            profile.esports_level = "generalist"

    def test_dataclass_fields(self):
        """SpecializationProfile has all required fields."""
        profile = SpecializationProfile(
            esports_level="specialist",
            game_level="generalist",
            esports_concentration=Decimal("0.75"),
            game_concentration=Decimal("0.35"),
            primary_game=None,
        )

        assert profile.esports_level == "specialist"
        assert profile.game_level == "generalist"
        assert profile.esports_concentration == Decimal("0.75")
        assert profile.game_concentration == Decimal("0.35")
        assert profile.primary_game is None
