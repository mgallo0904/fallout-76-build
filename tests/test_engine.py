from app.models import BuildInput
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
        # Allow up to a couple of soft warnings (e.g. status drift) but the SPECIAL math must be clean.
        assert not any("exceed" in i for i in issues), (archetype, issues)
        assert not any("overspent" in i for i in issues), (archetype, issues)


def test_special_budget_overflow_is_flagged():
    user = BuildInput()
    build = generate_build(user)
    build.special_allocation = {s: 15 for s in SPECIALS}  # 105 total, no legendary perks
    issues = validate_build(build)
    assert any("exceed" in issue for issue in issues)


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
    assert "April 21 2026" in joined
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
    # 56 + 5*7 = 91 cap; allocate 91 evenly with legendary stat perks for each SPECIAL.
    build.special_allocation = {s: 13 for s in SPECIALS}
    build.special_allocation["Luck"] = 13  # 91 total
    build.legendary_perks = [{"name": f"Legendary {s}", "priority": "Required", "reason": "test"} for s in SPECIALS]
    issues = validate_build(build)
    assert not any("exceed" in issue for issue in issues), issues
    assert sum(build.special_allocation.values()) > SPECIAL_BUDGET
