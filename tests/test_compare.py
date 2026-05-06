"""Tests for the expanded compare_builds function.

Verifies that the compare endpoint returns backward-compatible results
with the new diff fields populated.
"""
from __future__ import annotations

from app.models import BuildInput, CompareResult, GeneratedBuild, PerkChoice
from app.services.engine import compare_builds, SPECIALS


def _make_build(
    build_id: str,
    build_name: str,
    special: dict[str, int] | None = None,
    perks: dict[str, list] | None = None,
    legendary_perks: list[dict] | None = None,
    mutations: list[dict] | None = None,
    gear: dict | None = None,
) -> GeneratedBuild:
    """Helper to create a minimal GeneratedBuild for comparison."""
    if special is None:
        special = {s: 8 for s in SPECIALS}
    if perks is None:
        perks = {s: [] for s in SPECIALS}
    return GeneratedBuild(
        id=build_id,
        build_name=build_name,
        user_inputs=BuildInput(),
        assumptions=[],
        special_allocation=special,
        perk_cards_by_special=perks,
        legendary_perks=legendary_perks or [],
        mutations=mutations or [],
        gear=gear or {},
        variants={},
        swap_cards={},
        weaknesses=[],
        validation_status="valid",
        source_verification_notes=[],
    )


class TestCompareBuildsDiffs:
    """Verify the expanded CompareResult fields."""

    def test_backward_compatible_fields(self):
        """Old fields (build_ids, special_diff, core_perk_diff) are always present."""
        a = _make_build("a", "Build A")
        b = _make_build("b", "Build B")
        result = compare_builds([a, b])
        assert result.build_ids == ["a", "b"]
        assert "a" in result.special_diff
        assert "b" in result.special_diff
        assert "a" in result.core_perk_diff
        assert "b" in result.core_perk_diff

    def test_legendary_perk_diff_populated(self):
        a = _make_build("a", "Build A", legendary_perks=[{"name": "Follow Through"}])
        b = _make_build("b", "Build B", legendary_perks=[{"name": "Taking One for the Team"}])
        result = compare_builds([a, b])
        assert result.legendary_perk_diff["a"] == ["Follow Through"]
        assert result.legendary_perk_diff["b"] == ["Taking One for the Team"]

    def test_mutation_diff_populated(self):
        a = _make_build("a", "Build A", mutations=[{"name": "Speed Demon"}, {"name": "Marsupial"}])
        b = _make_build("b", "Build B", mutations=[])
        result = compare_builds([a, b])
        assert result.mutation_diff["a"] == ["Speed Demon", "Marsupial"]
        assert result.mutation_diff["b"] == []

    def test_gear_diff_populated(self):
        a = _make_build("a", "Build A", gear={"weapons": ["The Fixer"]})
        b = _make_build("b", "Build B", gear={"weapons": ["Holy Fire"]})
        result = compare_builds([a, b])
        assert result.gear_diff["a"]["weapons"] == ["The Fixer"]
        assert result.gear_diff["b"]["weapons"] == ["Holy Fire"]

    def test_tradeoff_summary_present(self):
        a = _make_build("a", "Commando", mutations=[{"name": "Speed Demon"}])
        b = _make_build("b", "Heavy Gunner", mutations=[])
        result = compare_builds([a, b])
        assert len(result.tradeoff_summary) > 0
        assert any("Comparing" in t for t in result.tradeoff_summary)

    def test_same_archetype_different_health(self):
        """Compare same archetype: bloodied vs full-health."""
        a = _make_build(
            "bloodied_commando", "Bloodied Commando",
            legendary_perks=[{"name": "Follow Through"}],
            mutations=[{"name": "Adrenal Reaction"}, {"name": "Speed Demon"}],
        )
        b = _make_build(
            "full_health_commando", "Full-Health Commando",
            legendary_perks=[{"name": "Follow Through"}],
            mutations=[{"name": "Speed Demon"}],
        )
        result = compare_builds([a, b])
        assert "bloodied_commando" in result.build_ids
        assert "full_health_commando" in result.build_ids
        assert result.mutation_diff["bloodied_commando"] == ["Adrenal Reaction", "Speed Demon"]
        assert result.mutation_diff["full_health_commando"] == ["Speed Demon"]

    def test_pa_vs_non_pa(self):
        """Compare PA vs non-PA gear differences."""
        pa = _make_build(
            "pa_heavy", "PA Heavy",
            gear={"armor": ["Union Power Armor"], "armor_mods": ["Calibrated Shocks"]},
        )
        non_pa = _make_build(
            "ss_commando", "SS Commando",
            gear={"armor": ["Secret Service Armor"], "armor_mods": ["Ultra-Light"]},
        )
        result = compare_builds([pa, non_pa])
        assert result.gear_diff["pa_heavy"]["armor"] == ["Union Power Armor"]
        assert result.gear_diff["ss_commando"]["armor"] == ["Secret Service Armor"]
