from __future__ import annotations
from datetime import datetime
from uuid import uuid4
from app.models import BuildInput, CompareResult, GeneratedBuild, PerkChoice, Status
from app.services.repository import load_perks, list_sources

SPECIALS = ["Strength","Perception","Endurance","Charisma","Intelligence","Agility","Luck"]


def classify(inp: BuildInput) -> str:
    text = f"{inp.primary_playstyle} {inp.primary_weapon_type} {inp.preferred_weapons}".lower()
    if "power armor" in text and "heavy" in text and "energy" in text:
        return "power_armor_heavy_energy"
    if "power armor" in text and "heavy" in text:
        return "power_armor_heavy"
    if "bloodied" in text:
        return "bloodied_general"
    return "power_armor_heavy_energy"


def _build_power_armor_heavy_energy(user: BuildInput) -> GeneratedBuild:
    perks = {p.id: p for p in load_perks()}
    selected = [
        PerkChoice(card_id="heavy_gunner", rank=3, role="Damage", why="Core heavy-gun damage lane."),
        PerkChoice(card_id="expert_heavy_gunner", rank=3, role="Damage", why="Stacks heavy-gun damage."),
        PerkChoice(card_id="master_heavy_gunner", rank=3, role="Damage", why="Completes core damage setup."),
        PerkChoice(card_id="stabilized", rank=3, role="Power Armor Support", why="PA heavy armor penetration and accuracy."),
    ]
    by_special = {k: [] for k in SPECIALS}
    for c in selected:
        by_special[perks[c.card_id].special].append(c)

    sources = list_sources()
    return GeneratedBuild(
        id=f"build-{uuid4().hex[:12]}",
        build_name="Power Armor Heavy Energy Gunner",
        user_inputs=user,
        assumptions=[
            "Date context: validated against local source registry accessed on 2026-05-05.",
            "Default full-health unless user explicitly chooses bloodied.",
            "Non-stealth loud combat baseline.",
            "Legendary SPECIAL not required for base playability."
        ],
        special_allocation={"Strength":15,"Perception":3,"Endurance":8,"Charisma":6,"Intelligence":12,"Agility":4,"Luck":8},
        perk_cards_by_special=by_special,
        legendary_perks=[
            {"name":"Electric Absorption","priority":"Required","reason":"Fusion core sustain and damage mitigation."},
            {"name":"Taking One for the Team","priority":"Strongly Recommended","reason":"Team damage amplification in boss content."},
            {"name":"Power Armor Reboot","priority":"Optional","reason":"Stability and recovery layer."},
            {"name":"Ammo Factory","priority":"Swap-in","reason":"Economy and crafting profile."}
        ],
        mutations=[
            {"name":"Speed Demon","use":"Yes","reason":"Reload/mobility improvement.","support":"Class Freak"},
            {"name":"Adrenal Reaction","use":"Variant","reason":"Only in bloodied variant.","support":"Class Freak + Starched Genes"}
        ],
        gear={
            "weapons":["Gatling Plasma","Gatling Laser","Ultracite Gatling Laser","Gauss Minigun","Plasma Caster"],
            "armor":["Union Power Armor","Hellcat","T-65","Excavator (carry variant)"],
            "weapon_effects":["Anti-Armor","Aristocrat's","Vampire's","Bloodied (variant only)"],
            "armor_effects":["Overeater's","Enemy-specific situational sets"],
            "ammo_consumables":["Fusion Cores","Plasma Cores","Ultracite ammo","Overdrive","Psychobuff"]
        },
        variants={
            "Beginner":["Excavator variant","easier ammo economy","lower maintenance damage stack"],
            "Full-health":["Overeater's focus","high sustain"],
            "Bloodied":["bloodied weapon effect + adrenal mutation"],
            "Boss DPS":["armor penetration + max damage"],
            "Event farming":["AoE-capable heavy rotation"],
            "Quality-of-life":["carry-weight + repair + vendor swaps"]
        },
        swap_cards={"Crafting":["Weapon Artisan"],"Repairs":["Fix It Good"],"Selling/vendor":["Hard Bargain"],"Travel/carry weight":["Traveling Pharmacy"],"Daily Ops":["Ricochet"],"Expeditions":["Dodgy"],"Bosses":["One Gun Army"],"Events":["Grenadier"],"Nuke zones":["Rad Resistant"]},
        weaknesses=["High ammo/core consumption in long sessions.","Not stealth optimized.","Lower VATS efficiency than dedicated VATS builds."],
        validation_status="pending",
        source_verification_notes=[f"{s.source_name} | {s.source_url} | accessed {s.date_accessed.isoformat()} | type={s.source_type.value}" for s in sources],
        created_at=datetime.utcnow(),
    )


def generate_build(user: BuildInput) -> GeneratedBuild:
    archetype = classify(user)
    if archetype in {"power_armor_heavy_energy", "power_armor_heavy", "bloodied_general"}:
        return _build_power_armor_heavy_energy(user)
    return _build_power_armor_heavy_energy(user)


def validate_build(build: GeneratedBuild) -> list[str]:
    perks = {p.id: p for p in load_perks()}
    issues: list[str] = []
    for special, picks in build.perk_cards_by_special.items():
        spent = 0
        for pick in picks:
            card = perks.get(pick.card_id)
            if not card:
                issues.append(f"Unknown perk id: {pick.card_id}")
                continue
            if card.special != special:
                issues.append(f"Perk {card.name} mapped to wrong SPECIAL ({special})")
            if pick.rank < 1 or pick.rank > card.max_rank:
                issues.append(f"Perk {card.name} has invalid rank {pick.rank}")
            if pick.rank not in card.rank_costs:
                issues.append(f"Perk {card.name} missing rank cost for rank {pick.rank}")
                continue
            spent += card.rank_costs[pick.rank]
            if card.power_armor_only and "Power Armor" not in build.user_inputs.armor_type:
                issues.append(f"Perk {card.name} requires Power Armor")
            if card.stealth_synergy and build.user_inputs.combat_style in {"Non-VATS", "Balanced"}:
                issues.append(f"Stealth perk {card.name} in non-stealth baseline")
            if card.bloodied_synergy and build.user_inputs.health_model == "Full health":
                issues.append(f"Bloodied perk {card.name} used in full-health build")
            if card.vats_synergy and build.user_inputs.combat_style == "Non-VATS":
                issues.append(f"VATS perk {card.name} prioritized in non-VATS build")
            if card.status != Status.verified:
                issues.append(f"Unverified perk flagged: {card.name}")
        if spent > build.special_allocation.get(special, 0):
            issues.append(f"{special} overspent ({spent} > {build.special_allocation.get(special, 0)})")
    if not build.weaknesses:
        issues.append("Weaknesses/tradeoffs section required")
    return issues


def compare_builds(builds: list[GeneratedBuild]) -> CompareResult:
    return CompareResult(
        build_ids=[b.id for b in builds],
        special_diff={b.id: b.special_allocation for b in builds},
        core_perk_diff={b.id: [p.card_id for cards in b.perk_cards_by_special.values() for p in cards] for b in builds}
    )
