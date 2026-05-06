"""Classifier tests for archetype routing.

Verifies that the classify() function routes user input to the correct
archetype, including the Enclave Flamer vs Cremator disambiguation.
"""
from __future__ import annotations

import pytest

from app.models import BuildInput
from app.services.engine import classify


class TestClassifierRouting:
    """Verify keyword-based classifier routes to the correct archetype."""

    @pytest.mark.parametrize(
        "weapon_input,expected",
        [
            # Enclave Flamer disambiguation
            ("Enclave Plasma Flamer", "enclave_flamer"),
            ("enclave flamer", "enclave_flamer"),
            ("enclave plasma", "enclave_flamer"),
            ("enclave plasma rifle flamer", "enclave_flamer"),
            # Cremator / Holy Fire / generic flamer -> cremator_pyro
            ("Cremator", "cremator_pyro"),
            ("Holy Fire", "cremator_pyro"),
            ("Pyromaniac build", "cremator_pyro"),
            ("Flamer", "cremator_pyro"),
            # Standard archetypes
            ("The Fixer commando", "onslaught_commando"),
            ("Lever Action Rifle sniper", "rifleman"),
            ("Pepper Shaker shotgun", "shotgunner"),
            ("Western Revolver pistol", "gunslinger"),
            ("Auto Axe melee", "melee"),
            ("Compound Bow", "bow_stealth"),
            ("Gatling Plasma heavy energy", "power_armor_heavy_energy"),
            ("Bullet Storm heavy ballistic", "bullet_storm_heavy"),
        ],
    )
    def test_weapon_routes(self, weapon_input, expected):
        inp = BuildInput(primary_weapon_type=weapon_input)
        assert classify(inp) == expected

    @pytest.mark.parametrize(
        "playstyle,expected",
        [
            ("XP / Leveling", "xp_leveling_fallback"),
            ("Crafting / Utility", "crafting_utility_fallback"),
        ],
    )
    def test_playstyle_dropdown_routes(self, playstyle, expected):
        inp = BuildInput(primary_playstyle=playstyle)
        assert classify(inp) == expected

    def test_ghoul_commando_route(self):
        inp = BuildInput(primary_weapon_type="ghoul commando auto rifle")
        assert classify(inp) == "ghoul_commando"

    def test_ghoul_melee_route(self):
        inp = BuildInput(primary_weapon_type="ghoul melee unarmed")
        assert classify(inp) == "ghoul_melee"

    def test_generic_ghoul_falls_back(self):
        inp = BuildInput(primary_weapon_type="ghoul build")
        assert classify(inp) == "playable_ghoul"

    def test_stealth_shotgun_route(self):
        inp = BuildInput(primary_weapon_type="fancy pump action stealth shotgun")
        assert classify(inp) == "pepper_shaker_stealth"

    def test_default_fallback(self):
        """Empty or vague input falls back to PA heavy energy."""
        inp = BuildInput()
        assert classify(inp) == "power_armor_heavy_energy"
