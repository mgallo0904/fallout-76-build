from app.models import BuildInput, PerkChoice
from app.services import engine as engine_module
from app.services.repository import get_build, load_legendary_perks, load_perks, load_sources_json, save_build
from app.services.engine import (
    SPECIALS,
    SPECIAL_BUDGET,
    classify,
    generate_build,
    list_archetypes,
    validate_build,
)


def _input(**overrides) -> BuildInput:
    return BuildInput(**overrides)


def _spent_by_special(build):
    perks_by_id = {p.id: p for p in load_perks()}
    spent = {special: 0 for special in SPECIALS}
    for special, picks in build.perk_cards_by_special.items():
        for pick in picks:
            spent[special] += perks_by_id[pick.card_id].rank_costs[pick.rank]
    return spent


def _perk_ids(build):
    return {
        pick.card_id
        for picks in build.perk_cards_by_special.values()
        for pick in picks
    }


def test_archetype_listing_covers_2026_meta():
    ids = {arch["id"] for arch in list_archetypes()}
    assert ids == {
        "power_armor_heavy_energy",
        "bullet_storm_heavy",
        "onslaught_commando",
        "rifleman",
        "shotgunner",
        "gunslinger",
        "melee",
        "playable_ghoul",
        "bow_stealth",
        "cremator_pyro",
        "pepper_shaker_stealth",
        "ghoul_commando",
        "ghoul_melee",
        "xp_leveling_fallback",
        "crafting_utility_fallback",
    }


def test_classify_default_is_pa_heavy_energy():
    assert classify(BuildInput()) == "power_armor_heavy_energy"


def test_classify_each_archetype_via_keywords():
    cases = {
        "ghoul_commando": _input(primary_playstyle="Ghoul Commando", primary_weapon_type="Auto rifle"),
        "ghoul_melee": _input(primary_playstyle="Ghoul Melee", primary_weapon_type="Melee"),
        "playable_ghoul": _input(primary_playstyle="Ghoul Heavy", primary_weapon_type="Heavy energy"),
        "bow_stealth": _input(primary_playstyle="Bow Stealth", primary_weapon_type="Bow", preferred_weapons="Compound Bow"),
        "cremator_pyro": _input(primary_playstyle="Pyromaniac", primary_weapon_type="Cremator"),
        "pepper_shaker_stealth": _input(primary_playstyle="Stealth Shotgun", primary_weapon_type="Shotgun", preferred_weapons="Fancy Pump-Action"),
        "melee": _input(primary_playstyle="Melee", primary_weapon_type="Melee"),
        "shotgunner": _input(primary_playstyle="Shotgunner", primary_weapon_type="Shotgun"),
        "gunslinger": _input(primary_playstyle="Gunslinger", primary_weapon_type="Pistol"),
        "rifleman": _input(primary_playstyle="Rifleman", primary_weapon_type="Non-automatic rifle"),
        "onslaught_commando": _input(primary_playstyle="Commando", primary_weapon_type="Auto rifle", preferred_weapons="Fixer"),
        "bullet_storm_heavy": _input(primary_playstyle="Bullet Storm Heavy", primary_weapon_type="Heavy ballistic"),
        "power_armor_heavy_energy": _input(primary_playstyle="Power Armor Heavy", primary_weapon_type="Heavy energy"),
    }
    for expected, payload in cases.items():
        assert classify(payload) == expected, (expected, payload)


def test_each_archetype_passes_validation():
    inputs_for = {
        "power_armor_heavy_energy": _input(primary_playstyle="Power Armor Heavy", primary_weapon_type="Heavy energy"),
        "bullet_storm_heavy": _input(primary_playstyle="Bullet Storm Heavy", primary_weapon_type="Heavy ballistic"),
        "onslaught_commando": _input(
            primary_playstyle="Commando",
            primary_weapon_type="Auto rifle",
            armor_type="Regular armor",
            combat_style="VATS",
        ),
        "rifleman": _input(
            primary_playstyle="Rifleman",
            primary_weapon_type="Non-automatic rifle",
            armor_type="Regular armor",
            combat_style="VATS",
        ),
        "shotgunner": _input(
            primary_playstyle="Shotgunner",
            primary_weapon_type="Shotgun",
        ),
        "gunslinger": _input(
            primary_playstyle="Gunslinger",
            primary_weapon_type="Pistol",
            armor_type="Regular armor",
            combat_style="VATS",
        ),
        "melee": _input(
            primary_playstyle="Melee",
            primary_weapon_type="Melee",
            armor_type="Regular armor",
            health_model="Bloodied / low health",
        ),
        "playable_ghoul": _input(
            primary_playstyle="Ghoul Heavy",
            primary_weapon_type="Heavy energy",
        ),
        "bow_stealth": _input(
            primary_playstyle="Bow Stealth",
            primary_weapon_type="Bow",
            preferred_weapons="Compound Bow",
            armor_type="Regular armor",
        ),
        "cremator_pyro": _input(
            primary_playstyle="Pyromaniac",
            primary_weapon_type="Cremator",
            preferred_weapons="Cremator, Enclave Flamer",
        ),
        "pepper_shaker_stealth": _input(
            primary_playstyle="Stealth Shotgun",
            primary_weapon_type="Shotgun",
            preferred_weapons="Fancy Pump-Action",
            armor_type="Regular armor",
        ),
        "ghoul_commando": _input(
            primary_playstyle="Ghoul Commando",
            primary_weapon_type="Auto rifle",
            armor_type="Regular armor",
            combat_style="VATS",
        ),
        "ghoul_melee": _input(
            primary_playstyle="Ghoul Melee",
            primary_weapon_type="Melee",
            armor_type="Regular armor",
            health_model="Bloodied / low health",
        ),
    }
    for archetype, user in inputs_for.items():
        build = generate_build(user)
        issues = validate_build(build)
        assert classify(user) == archetype
        assert issues == [], (archetype, issues)
        assert _spent_by_special(build) == build.special_allocation


def test_special_budget_overflow_is_flagged():
    user = BuildInput()
    build = generate_build(user)
    build.special_allocation = {s: 15 for s in SPECIALS}  # 105 total, no legendary perks
    issues = validate_build(build)
    assert any("exceed" in issue for issue in issues)


def test_underfilled_special_column_is_flagged():
    build = generate_build(_input())
    build.perk_cards_by_special["Perception"] = []
    issues = validate_build(build)
    assert any("Perception underfilled" in issue for issue in issues), issues


def test_specific_mutations_are_reflected_and_supported():
    build = generate_build(_input(
        mutation_preference=(
            "Specific mutations: Adrenal Reaction, Marsupial, Eagle Eyes, Talons, "
            "Egg Head, Herd Mentality, Carnivore, Plague Walker, Unstable Isotope"
        )
    ))
    mutation_names = {mutation["name"] for mutation in build.mutations}
    assert mutation_names == {
        "Adrenal Reaction",
        "Marsupial",
        "Eagle Eyes",
        "Talons",
        "Egg Head",
        "Herd Mentality",
        "Carnivore",
        "Plague Walker",
        "Unstable Isotope",
    }
    assert {"class_freak", "starched_genes", "strange_in_numbers"} <= _perk_ids(build)
    assert validate_build(build) == []
    assert _spent_by_special(build) == build.special_allocation


def test_no_mutations_omits_mutation_cards_and_recommendations():
    build = generate_build(_input(mutation_preference="No mutations"))
    assert build.mutations == []
    assert not {"class_freak", "starched_genes", "strange_in_numbers"}.intersection(_perk_ids(build))
    assert validate_build(build) == []
    assert _spent_by_special(build) == build.special_allocation


def test_ghoul_unyielding_armor_is_flagged():
    user = _input(
        primary_playstyle="Ghoul Commando",
        primary_weapon_type="Auto rifle",
        current_gear="Unyielding Secret Service set",
    )
    build = generate_build(user)
    issues = validate_build(build)
    assert any("Unyielding" in i and "Ghoul" in i for i in issues), issues


def test_apr21_2026_assumptions_are_present():
    build = generate_build(_input())
    joined = " | ".join(build.assumptions)
    assert "May 6 2026" in joined
    assert "April 21 2026" in joined
    assert "April 28 2026 maintenance" in joined
    assert "Patch 68" in joined
    assert "armor durability" in joined.lower()


def test_pepper_shaker_stealth_assumption_includes_fancy_pump_pivot():
    build = generate_build(_input(
        primary_playstyle="Stealth Shotgun",
        primary_weapon_type="Shotgun",
        preferred_weapons="Fancy Pump-Action",
    ))
    joined = " | ".join(build.assumptions)
    assert "Fancy Pump-Action" in joined


def test_special_budget_legendary_special_perks_raise_cap():
    user = BuildInput()
    build = generate_build(user)
    # 56 + 5*7 = 91 cap with rank-4 legendary stat perks.
    build.special_allocation = {s: 13 for s in SPECIALS}
    build.special_allocation["Luck"] = 13  # 91 total
    build.legendary_perks = [{"name": f"Legendary {s}", "priority": "Required", "reason": "test", "rank": 4} for s in SPECIALS]
    issues = validate_build(build)
    assert not any("exceed" in issue for issue in issues), issues
    assert sum(build.special_allocation.values()) > SPECIAL_BUDGET


def test_ghoul_catalog_counts_match_live_may_2026_sources():
    ghoul_perks = [
        p for p in load_perks()
        if p.status.value == "verified" and "ghoul_only" in p.tags
    ]
    ghoul_legendary = [
        p for p in load_legendary_perks()
        if p.status.value == "verified" and "ghoul_only" in p.tags
    ]
    assert len(ghoul_perks) == 28
    assert {p.name for p in ghoul_legendary} == {"Action Diet", "Feral Rage"}


def test_glowing_one_is_regular_perk_not_legendary():
    regular = {p.id: p for p in load_perks()}
    legendary = {p.id: p for p in load_legendary_perks()}
    assert regular["glowing_one"].name == "Glowing One"
    assert regular["glowing_one"].special == "Charisma"
    assert "glowing_one" not in legendary
    assert {"action_diet", "feral_rage"} <= set(legendary)


def test_ghoul_restricted_perks_are_rejected():
    build = generate_build(_input(primary_playstyle="Ghoul Commando", primary_weapon_type="Auto rifle"))
    build.perk_cards_by_special["Endurance"].append(
        PerkChoice(card_id="rad_sponge", rank=2, role="Invalid", why="restricted test")
    )
    build.legendary_perks.append(
        {"name": "What Rads?", "priority": "Invalid", "reason": "restricted test", "rank": 1}
    )
    issues = validate_build(build)
    assert any("Rad Sponge" in issue and "restricted" in issue for issue in issues), issues
    assert any("What Rads?" in issue and "restricted" in issue for issue in issues), issues


def test_background_brain_failure_is_persisted_without_breaking_build(monkeypatch):
    build = generate_build(_input())
    save_build(build)

    def fail_enhancement(*_args, **_kwargs):
        raise RuntimeError("simulated timeout")

    monkeypatch.setattr(engine_module, "enhance_build_with_brain", fail_enhancement)
    engine_module.refine_saved_build_with_brain(build.id)

    persisted = get_build(build.id)
    assert persisted is not None
    assert persisted.brain_status == "failed"
    assert persisted.brain_error == "simulated timeout"
    assert persisted.validation_status == "passed"


def test_source_registry_records_may6_and_no_impact_maintenance():
    sources = load_sources_json()
    assert sources
    assert {s.date_accessed.isoformat() for s in sources} == {"2026-05-06"}
    apr28 = next(s for s in sources if s.id == "steam-apr28-2026-maintenance")
    assert "no build-impact" in apr28.summary
    assert any("Patch 68" in s.relevant_patch and "PTS" in s.notes for s in sources)
