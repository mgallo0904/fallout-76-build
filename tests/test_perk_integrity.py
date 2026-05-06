"""Perk and archetype integrity tests.

Guard against future drift between archetype blueprints and the underlying
perk/legendary-perk JSON catalogs.  Every test here should pass against the
live Patch 62 baseline.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.engine import _build_archetype_blueprints, SPECIAL_BUDGET, SPECIALS
from app.services.repository import load_active_perks, load_active_legendary_perks, load_perks

DATA_DIR = Path(__file__).resolve().parents[1] / "app" / "data"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def perks_json() -> list[dict]:
    return json.loads((DATA_DIR / "perks.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def legendary_json() -> list[dict]:
    return json.loads((DATA_DIR / "legendary_perks.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def perks_by_id(perks_json) -> dict[str, dict]:
    return {p["id"]: p for p in perks_json}


@pytest.fixture(scope="module")
def legendary_by_name(legendary_json) -> dict[str, dict]:
    return {p["name"]: p for p in legendary_json}


@pytest.fixture(scope="module")
def blueprints():
    return _build_archetype_blueprints()


# ---------------------------------------------------------------------------
# Priority 1: Every archetype perk reference resolves
# ---------------------------------------------------------------------------

class TestArchetypePerkResolution:
    """Assert every perk_picks and optional_perk_picks card_id resolves to a
    valid perk object in perks.json with required fields."""

    def test_all_perk_picks_resolve(self, blueprints, perks_by_id):
        missing = []
        for arch_id, bp in blueprints.items():
            for card_id, rank, role, why in bp.perk_picks:
                if card_id not in perks_by_id:
                    missing.append(f"{arch_id}: {card_id}")
        assert not missing, f"Perk IDs missing from perks.json: {missing}"

    def test_all_optional_perk_picks_resolve(self, blueprints, perks_by_id):
        missing = []
        for arch_id, bp in blueprints.items():
            for card_id, rank, role, why in bp.optional_perk_picks:
                if card_id not in perks_by_id:
                    missing.append(f"{arch_id}: {card_id}")
        assert not missing, f"Optional perk IDs missing from perks.json: {missing}"

    def test_resolved_perks_have_required_fields(self, blueprints, perks_by_id):
        """Each resolved perk must have id, name, special, rank_costs,
        max_rank, and at least one effect_by_rank entry."""
        errors = []
        seen = set()
        for bp in blueprints.values():
            for card_id, *_ in list(bp.perk_picks) + list(bp.optional_perk_picks):
                if card_id in seen:
                    continue
                seen.add(card_id)
                perk = perks_by_id.get(card_id)
                if perk is None:
                    continue  # caught by resolution test
                for field in ("id", "name", "special", "rank_costs", "max_rank"):
                    if not perk.get(field):
                        errors.append(f"{card_id} missing field: {field}")
                effects = perk.get("effect_by_rank", {})
                if not effects:
                    errors.append(f"{card_id} has no effect_by_rank entries")
        assert not errors, f"Perk field errors: {errors}"

    def test_perk_ranks_within_max(self, blueprints, perks_by_id):
        """Blueprint-specified ranks must not exceed the card's max_rank."""
        errors = []
        for arch_id, bp in blueprints.items():
            for card_id, rank, *_ in list(bp.perk_picks) + list(bp.optional_perk_picks):
                perk = perks_by_id.get(card_id)
                if perk is None:
                    continue
                if rank > perk["max_rank"]:
                    errors.append(
                        f"{arch_id}/{card_id}: rank {rank} > max_rank {perk['max_rank']}"
                    )
        assert not errors, f"Rank violations: {errors}"


# ---------------------------------------------------------------------------
# Priority 1: Legendary perk references resolve
# ---------------------------------------------------------------------------

class TestLegendaryPerkResolution:
    """Assert every legendary perk name referenced by archetypes exists in
    legendary_perks.json."""

    def test_all_legendary_names_resolve(self, blueprints, legendary_by_name):
        missing = []
        for arch_id, bp in blueprints.items():
            for lp in bp.legendary_perks:
                name = lp.get("name", "")
                if name not in legendary_by_name:
                    missing.append(f"{arch_id}: {name}")
        assert not missing, f"Legendary perk names missing: {missing}"


# ---------------------------------------------------------------------------
# Priority 1: SPECIAL budget integrity
# ---------------------------------------------------------------------------

class TestSpecialBudget:
    """Assert each archetype's SPECIAL allocation totals exactly 56."""

    def test_special_budget_is_56(self, blueprints):
        errors = []
        for arch_id, bp in blueprints.items():
            total = sum(bp.special_allocation.get(s, 0) for s in SPECIALS)
            if total != SPECIAL_BUDGET:
                errors.append(f"{arch_id}: total={total}, expected={SPECIAL_BUDGET}")
        assert not errors, f"SPECIAL budget errors: {errors}"

    def test_special_values_between_1_and_15(self, blueprints):
        errors = []
        for arch_id, bp in blueprints.items():
            for s in SPECIALS:
                v = bp.special_allocation.get(s, 0)
                if v < 1 or v > 15:
                    errors.append(f"{arch_id}/{s}: {v} out of range [1,15]")
        assert not errors, f"SPECIAL range errors: {errors}"

    def test_perk_cost_does_not_exceed_allocation(self, blueprints, perks_by_id):
        """Core perk_picks cost per SPECIAL column must not exceed the
        blueprint's allocation for that column."""
        errors = []
        for arch_id, bp in blueprints.items():
            spent: dict[str, int] = {s: 0 for s in SPECIALS}
            for card_id, rank, *_ in bp.perk_picks:
                perk = perks_by_id.get(card_id)
                if perk is None:
                    continue
                cost = perk.get("rank_costs", {}).get(str(rank))
                if cost is None:
                    continue
                spent[perk["special"]] += cost
            for s in SPECIALS:
                budget = bp.special_allocation.get(s, 0)
                if spent[s] > budget:
                    errors.append(
                        f"{arch_id}/{s}: spent {spent[s]} > budget {budget}"
                    )
        assert not errors, f"Perk cost exceeds allocation: {errors}"


# ---------------------------------------------------------------------------
# Priority 5: Starched Genes verification
# ---------------------------------------------------------------------------

class TestStarchedGenes:
    """Starched Genes must remain a 1-rank Endurance perk with full mutation
    protection (prevents mutation gain from rads AND prevents RadAway from
    curing mutations)."""

    def test_starched_genes_special(self, perks_by_id):
        sg = perks_by_id.get("starched_genes")
        assert sg is not None, "starched_genes not found in perks.json"
        assert sg["special"] == "Endurance"

    def test_starched_genes_max_rank(self, perks_by_id):
        sg = perks_by_id["starched_genes"]
        assert sg["max_rank"] == 1

    def test_starched_genes_effect_covers_both_protections(self, perks_by_id):
        sg = perks_by_id["starched_genes"]
        effects = sg.get("effect_by_rank", {})
        rank_1_effect = effects.get("1", "").lower()
        assert "mutate" in rank_1_effect or "mutation" in rank_1_effect, (
            f"Starched Genes rank 1 effect should mention mutation prevention: {rank_1_effect}"
        )
        assert "radaway" in rank_1_effect, (
            f"Starched Genes rank 1 effect should mention RadAway protection: {rank_1_effect}"
        )


# ---------------------------------------------------------------------------
# Priority 1: Build validation fails on missing perk ID
# ---------------------------------------------------------------------------

class TestValidationCatchesMissingPerks:
    """If a build references a perk ID not in the catalog, validate_build
    should flag it."""

    def test_validation_flags_unknown_perk(self):
        from app.models import BuildInput, GeneratedBuild, PerkChoice
        from app.services.engine import validate_build

        build = GeneratedBuild(
            id="test-missing-perk",
            build_name="Test",
            user_inputs=BuildInput(),
            assumptions=[],
            special_allocation={s: 8 for s in SPECIALS},
            perk_cards_by_special={
                "Strength": [PerkChoice(card_id="totally_fake_perk_xyz", rank=1, role="Test", why="Test")],
                **{s: [] for s in SPECIALS if s != "Strength"},
            },
            legendary_perks=[],
            mutations=[],
            gear={},
            variants={},
            swap_cards={},
            weaknesses=["test"],
            validation_status="pending",
            source_verification_notes=[],
        )
        issues = validate_build(build)
        assert any("unknown" in i.lower() or "totally_fake_perk_xyz" in i.lower() for i in issues), (
            f"Expected validation to flag unknown perk ID, got: {issues}"
        )
