import pytest
from datetime import date

from app.models import BuildCandidate, BuildInput, PerkCard, SourceType, Status

from app.services.repair import repair_build


def _make_perk(overrides):
    defaults = {
        "id": "test_perk",
        "name": "Test Perk",
        "special": "Strength",
        "max_rank": 3,
        "rank_costs": {1: 1, 2: 2, 3: 3},
        "effect_by_rank": {1: "a", 2: "b", 3: "c"},
        "level_required": 1,
        "tags": [],
        "build_families": [],
        "power_armor_only": False,
        "regular_armor_only": False,
        "bloodied_synergy": False,
        "full_health_synergy": False,
        "vats_synergy": False,
        "stealth_synergy": False,
        "heavy_weapon_synergy": False,
        "energy_weapon_synergy": False,
        "explosive_synergy": False,
        "melee_synergy": False,
        "support_synergy": False,
        "crafting_or_swap_only": False,
        "source_url": "",
        "source_name": "",
        "source_type": SourceType.database,
        "last_verified_date": date(2026, 5, 6),
        "patch_version": "",
        "status": Status.verified,
        "character_restriction": "Any",
    }
    defaults.update(overrides)
    return PerkCard(**defaults)


def _make_user(**overrides):
    defaults = {
        "character_level": "50+",
        "primary_playstyle": "Commando",
        "primary_weapon_type": "Auto rifle",
        "preferred_weapons": "Fixer",
        "armor_type": "Regular armor",
        "health_model": "Full health",
        "combat_style": "VATS",
        "team_preference": "Public team",
        "mutation_preference": "Use mutations",
        "qol_preference": "Balanced",
        "legendary_perk_availability": "",
        "current_gear": "",
        "avoid_list": "",
        "character_type": "Human",
        "goal": None,
        "revision_intent": None,
    }
    defaults.update(overrides)
    return BuildInput(**defaults)


def _make_candidate(perks_by_special=None, legendary=None, assumptions=None, weaknesses=None):
    return BuildCandidate(
        build_name="Test Build",
        special_allocation={"Strength": 10, "Perception": 5, "Endurance": 5, "Charisma": 5, "Intelligence": 5, "Agility": 10, "Luck": 6},
        perk_cards_by_special=perks_by_special or {},
        legendary_perks=legendary or [],
        mutations=[],
        gear={},
        variants={},
        swap_cards={},
        assumptions=assumptions or [],
        weaknesses=weaknesses or ["test weakness"],
        reasoning_summary="",
    )


def test_repair_drops_unknown_perk_id():
    perk_db = {"known_perk": _make_perk({"id": "known_perk", "name": "Known"})}
    candidate = _make_candidate({
        "Strength": [
            {"card_id": "unknown_perk", "rank": 1, "role": "Damage", "why": "bad"},
            {"card_id": "known_perk", "rank": 1, "role": "Damage", "why": "good"},
        ]
    })
    user = _make_user()
    repaired, notes = repair_build(candidate, perk_db, {}, user)
    assert all(p["card_id"] != "unknown_perk" for picks in repaired.perk_cards_by_special.values() for p in picks)
    assert any("unknown_perk" in note for note in notes)


def test_repair_caps_rank_at_max_rank():
    perk_db = {"overrank": _make_perk({"id": "overrank", "name": "Overrank", "max_rank": 2, "rank_costs": {1: 1, 2: 2}})}
    candidate = _make_candidate({
        "Strength": [{"card_id": "overrank", "rank": 5, "role": "Damage", "why": "too high"}]
    })
    user = _make_user()
    repaired, notes = repair_build(candidate, perk_db, {}, user)
    pick = repaired.perk_cards_by_special["Strength"][0]
    assert pick["rank"] == 2
    assert any("Overrank" in note and "rank" in note.lower() for note in notes)


def test_repair_enforces_special_budget():
    perk_db = {
        "cheap": _make_perk({"id": "cheap", "special": "Strength", "rank_costs": {1: 3, 2: 5, 3: 6}}),
        "filler": _make_perk({"id": "filler", "special": "Strength", "rank_costs": {1: 3, 2: 5, 3: 6}}),
    }
    candidate = _make_candidate({
        "Strength": [
            {"card_id": "cheap", "rank": 3, "role": "Damage", "why": "fill"},
            {"card_id": "filler", "rank": 3, "role": "Damage", "why": "overfill"},
        ]
    })
    user = _make_user()
    repaired, notes = repair_build(candidate, perk_db, {}, user)
    spent = sum(perk_db[p["card_id"]].rank_costs[p["rank"]] for p in repaired.perk_cards_by_special["Strength"])
    assert spent <= 10
    assert any("Strength" in note and "budget" in note.lower() for note in notes)


def test_repair_removes_pa_only_perk_for_non_pa():
    perk_db = {
        "stabilized": _make_perk({"id": "stabilized", "name": "Stabilized", "special": "Intelligence", "power_armor_only": True}),
    }
    candidate = _make_candidate({
        "Intelligence": [{"card_id": "stabilized", "rank": 1, "role": "PA", "why": "needs PA"}]
    })
    user = _make_user(armor_type="Regular armor")
    repaired, notes = repair_build(candidate, perk_db, {}, user)
    assert not any(p["card_id"] == "stabilized" for p in repaired.perk_cards_by_special.get("Intelligence", []))
    assert any("Stabilized" in note for note in notes)


def test_repair_removes_bloodied_perk_for_full_health():
    perk_db = {
        "nerd_rage": _make_perk({"id": "nerd_rage", "name": "Nerd Rage", "special": "Intelligence", "bloodied_synergy": True}),
    }
    candidate = _make_candidate({
        "Intelligence": [{"card_id": "nerd_rage", "rank": 1, "role": "Damage", "why": "bloodied"}]
    })
    user = _make_user(health_model="Full health")
    repaired, notes = repair_build(candidate, perk_db, {}, user)
    assert not any(p["card_id"] == "nerd_rage" for p in repaired.perk_cards_by_special.get("Intelligence", []))
    assert any("Nerd Rage" in note for note in notes)


def test_repair_removes_vats_perk_for_non_vats():
    perk_db = {
        "concentrated_fire": _make_perk({"id": "concentrated_fire", "name": "Concentrated Fire", "special": "Perception", "vats_synergy": True}),
    }
    candidate = _make_candidate({
        "Perception": [{"card_id": "concentrated_fire", "rank": 1, "role": "VATS", "why": "vats"}]
    })
    user = _make_user(combat_style="Non-VATS")
    repaired, notes = repair_build(candidate, perk_db, {}, user)
    assert not any(p["card_id"] == "concentrated_fire" for p in repaired.perk_cards_by_special.get("Perception", []))
    assert any("Concentrated Fire" in note for note in notes)


def test_repair_removes_ghoul_restricted_perk_for_human():
    perk_db = {
        "glowing_one": _make_perk({"id": "glowing_one", "name": "Glowing One", "special": "Charisma", "tags": ["ghoul_only"], "character_restriction": "Ghoul"}),
    }
    candidate = _make_candidate({
        "Charisma": [{"card_id": "glowing_one", "rank": 1, "role": "Ghoul", "why": "ghoul"}]
    })
    user = _make_user(character_type="Human")
    repaired, notes = repair_build(candidate, perk_db, {}, user)
    assert not any(p["card_id"] == "glowing_one" for p in repaired.perk_cards_by_special.get("Charisma", []))
    assert any("Glowing One" in note for note in notes)


def test_repair_removes_character_restricted_legendary():
    legendary_db = {
        "Action Diet": _make_perk({
            "id": "action_diet",
            "name": "Action Diet",
            "character_restriction": "Ghoul",
            "max_rank": 4,
            "rank_costs": {1: 1, 2: 2, 3: 3, 4: 4},
            "special": "Luck",
        }),
    }
    candidate = _make_candidate(legendary=[{"name": "Action Diet", "rank": 3, "priority": "Required"}])
    user = _make_user(character_type="Human")
    repaired, notes = repair_build(candidate, {}, legendary_db, user)
    assert not any(lp.get("name") == "Action Diet" for lp in repaired.legendary_perks)
    assert any("Action Diet" in note for note in notes)


def test_repair_adds_fallback_for_underfilled_column():
    perk_db = {
        "filler_a": _make_perk({"id": "filler_a", "special": "Luck", "rank_costs": {1: 1}}),
        "filler_b": _make_perk({"id": "filler_b", "special": "Luck", "rank_costs": {1: 1}}),
    }
    candidate = _make_candidate({"Luck": []})
    user = _make_user()
    repaired, notes = repair_build(candidate, perk_db, {}, user)
    spent = sum(perk_db[p["card_id"]].rank_costs[p["rank"]] for p in repaired.perk_cards_by_special.get("Luck", []))
    assert spent <= 6
    assert any("Luck" in note and ("fallback" in note.lower() or "fill" in note.lower()) for note in notes)


def test_repair_returns_notes_list():
    candidate = _make_candidate()
    user = _make_user()
    _, notes = repair_build(candidate, {}, {}, user)
    assert isinstance(notes, list)
