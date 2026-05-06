from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List
from uuid import uuid4

from app.models import (
    BuildInput,
    CompareResult,
    GeneratedBuild,
    PerkChoice,
    Status,
)
from app.services.brain import enhance_build_with_brain
from app.services.repository import (
    latest_source_date_accessed,
    list_sources,
    load_active_legendary_perks,
    load_active_perks,
    load_legendary_perks,
    load_perks,
)

SPECIALS: List[str] = [
    "Strength",
    "Perception",
    "Endurance",
    "Charisma",
    "Intelligence",
    "Agility",
    "Luck",
]
SPECIAL_BUDGET = 56
LEGENDARY_NAME_PATTERN = re.compile(
    r"^Legendary\s+(Strength|Perception|Endurance|Charisma|Intelligence|Agility|Luck)$",
    re.IGNORECASE,
)


RANK_TO_SPECIAL_BONUS = {1: 1, 2: 2, 3: 3, 4: 5}


def _legendary_special_bonus(rank: int) -> int:
    return RANK_TO_SPECIAL_BONUS.get(min(4, max(1, rank)), 1)


@dataclass(frozen=True)
class ArchetypeBlueprint:
    archetype_id: str
    build_name: str
    aliases: tuple[str, ...]
    """Lowercase alias keywords that select this archetype from user free-text input."""
    special_allocation: Dict[str, int]
    perk_picks: tuple[tuple[str, int, str, str], ...]
    """(card_id, rank, role, why) for verified perk cards."""
    optional_perk_picks: tuple[tuple[str, int, str, str], ...] = ()
    """Picks added only if the perk is loadable; tolerated if missing."""
    legendary_perks: tuple[Dict[str, str | int], ...] = ()
    mutations: tuple[Dict[str, str], ...] = ()
    gear: Dict[str, List[str]] = field(default_factory=dict)
    variants: Dict[str, List[str]] = field(default_factory=dict)
    swap_cards: Dict[str, List[str]] = field(default_factory=dict)
    weaknesses: tuple[str, ...] = ()
    extra_assumptions: tuple[str, ...] = ()


GHOUL_ARCHETYPES = frozenset({"playable_ghoul", "ghoul_commando", "ghoul_melee"})


def _build_archetype_blueprints() -> Dict[str, ArchetypeBlueprint]:
    blueprints: List[ArchetypeBlueprint] = [
        ArchetypeBlueprint(
            archetype_id="power_armor_heavy_energy",
            build_name="Power Armor Heavy Energy Gunner",
            aliases=("power armor heavy energy", "pa heavy energy"),
            special_allocation={
                "Strength": 15,
                "Perception": 3,
                "Endurance": 7,
                "Charisma": 3,
                "Intelligence": 13,
                "Agility": 4,
                "Luck": 11,
            },
            perk_picks=(
                ("bullet_storm", 3, "Damage", "Patch 62 core heavy-gun damage stack."),
                ("tightly_wound", 3, "Utility", "60% faster spin-up for Gatling/Plasma weapons."),
                ("bringing_the_big_guns", 1, "Damage", "Doubles Bullet Storm stack cap."),
                ("stabilized", 3, "Power Armor Support", "Big-gun accuracy doubled while in PA."),
                ("one_gun_army", 3, "Utility", "Stagger and cripple at range."),
                ("bear_arms", 3, "Carry / Bash", "Heavy weight reduction; bash damage per BS stack."),
            ),
            optional_perk_picks=(
                ("batteries_included", 3, "Economy", "Energy ammo weight reduction."),
                ("ricochet", 3, "Defense", "Ranged damage deflection."),
            ),
            legendary_perks=(
                {"name": "Electric Absorption", "priority": "Required", "reason": "Fusion core sustain and energy mitigation.", "rank": 4},
                {"name": "Taking One for the Team", "priority": "Strongly Recommended", "reason": "Team damage amplification in boss content.", "rank": 3},
                {"name": "Power Armor Reboot", "priority": "Optional", "reason": "Stand-back-up insurance for raid pulls.", "rank": 1},
                {"name": "Ammo Factory", "priority": "Swap-in", "reason": "Fusion / plasma core economy.", "rank": 1},
            ),
            mutations=(
                {"name": "Speed Demon", "use": "Yes", "reason": "Reload and mobility.", "support": "Class Freak"},
                {"name": "Adrenal Reaction", "use": "Variant", "reason": "Bloodied variant only.", "support": "Class Freak + Starched Genes"},
            ),
            gear={
                "weapons": ["Gatling Plasma", "Gatling Laser", "Ultracite Gatling Laser", "Gauss Minigun", "Plasma Caster"],
                "armor": ["Union Power Armor", "Hellcat", "T-65", "Excavator (carry variant)"],
                "weapon_effects": ["Anti-Armor", "Aristocrat's", "Vampire's", "Bloodied (variant only)"],
                "armor_effects": ["Overeater's", "Enemy-specific situational sets"],
                "ammo_consumables": ["Fusion Cores", "Plasma Cores", "Ultracite ammo", "Overdrive", "Psychobuff"],
                "weapon_mods": ["Furious", "Vital", "V.A.T.S. optimized", "Conductors"],
            },
            variants={
                "Beginner": ["Excavator variant", "easier ammo economy", "lower maintenance damage stack"],
                "Full-health": ["Overeater's focus", "high sustain"],
                "Bloodied": ["bloodied weapon effect + Adrenal Reaction"],
                "Boss DPS": ["armor penetration + max damage"],
                "Event farming": ["AoE-capable heavy rotation"],
                "Quality-of-life": ["carry-weight + repair + vendor swaps"],
            },
            swap_cards={
                "Crafting": ["Weapon Artisan"],
                "Repairs": ["Fix It Good"],
                "Selling/vendor": ["Hard Bargain"],
                "Travel/carry weight": ["Traveling Pharmacy"],
                "Daily Ops": ["Ricochet"],
                "Expeditions": ["Dodgy"],
                "Bosses": ["One Gun Army"],
                "Events": ["Grenadier"],
                "Nuke zones": ["Rad Resistant"],
            },
            weaknesses=(
                "High ammo/core consumption in long sessions.",
                "Not stealth optimized.",
                "Lower VATS efficiency than dedicated VATS builds.",
            ),
        ),
        ArchetypeBlueprint(
            archetype_id="bullet_storm_heavy",
            build_name="Bullet Storm Heavy Gunner",
            aliases=("bullet storm", "heavy ballistic", "ballistic heavy"),
            special_allocation={
                "Strength": 15,
                "Perception": 3,
                "Endurance": 5,
                "Charisma": 3,
                "Intelligence": 13,
                "Agility": 6,
                "Luck": 11,
            },
            perk_picks=(
                ("bullet_storm", 3, "Damage", "Patch 62 core heavy-gun damage stack."),
                ("tightly_wound", 3, "Utility", "60% faster spin-up."),
                ("bringing_the_big_guns", 1, "Damage", "Doubles BS stack cap."),
                ("lock_and_load", 3, "Sustain", "Retain half BS stacks on reload."),
                ("bear_arms", 3, "Carry / Bash", "Heavy weight reduction + bash bonus."),
                ("one_gun_army", 3, "Utility", "Stagger and cripple."),
            ),
            optional_perk_picks=(
                ("stabilized", 3, "Accuracy", "Pairs with PA variant."),
                ("ricochet", 3, "Defense", "Ranged deflection."),
            ),
            legendary_perks=(
                {"name": "Taking One for the Team", "priority": "Required", "reason": "Team damage amplification.", "rank": 4},
                {"name": "Legendary Strength", "priority": "Recommended", "reason": "Frees STR perk slots.", "rank": 2},
                {"name": "Ammo Factory", "priority": "Swap-in", "reason": "Ammo economy.", "rank": 1},
            ),
            mutations=(
                {"name": "Speed Demon", "use": "Yes", "reason": "Reload/mobility."},
            ),
            gear={
                "weapons": ["Holy Fire", "Gauss Minigun", "Cremator", "Light Machine Gun", ".50 Cal"],
                "armor": ["Union Power Armor", "Secret Service (if not PA)"],
                "weapon_effects": ["Anti-Armor", "Bloodied", "Vampire's"],
                "armor_effects": ["Overeater's", "Unyielding (if Bloodied non-PA)"],
                "ammo_consumables": ["Psychobuff", "Overdrive"],
                "weapon_mods": ["Furious", "Vital", "Conductors"],
            },
            variants={
                "Power Armor": ["Stabilized perk", "Union PA"],
                "Non-PA": ["Secret Service armor", "Serendipity"],
            },
            swap_cards={"Bosses": ["One Gun Army"], "Events": ["Grenadier"]},
            weaknesses=("High ammo consumption", "Spin-up time on some weapons"),
        ),
        ArchetypeBlueprint(
            archetype_id="onslaught_commando",
            build_name="Onslaught Commando",
            aliases=("commando", "onslaught", "fixer", "auto rifle", "automatic rifle"),
            special_allocation={
                "Strength": 3,
                "Perception": 15,
                "Endurance": 5,
                "Charisma": 3,
                "Intelligence": 3,
                "Agility": 15,
                "Luck": 12,
            },
            perk_picks=(
                ("commando", 3, "Damage", "Core automatic rifle damage."),
                ("expert_commando", 3, "Damage", "Stacks automatic rifle damage."),
                ("master_commando", 3, "Damage", "Completes auto rifle damage stack."),
                ("tank_killer", 2, "Armor Pen", "Patch 62: 40% armor ignore for all ranged."),
                ("concentrated_fire", 3, "VATS", "Stacking accuracy + damage."),
                ("gun_fu", 3, "VATS", "Auto target swap with damage bonus."),
                ("adrenaline", 3, "Damage", "+18% per kill, 60% cap."),
                ("better_criticals", 3, "Criticals", "Big VATS crit damage."),
                ("critical_savvy", 3, "Criticals", "Reduced crit meter consumption."),
                ("grim_reapers_sprint", 1, "AP regen", "VATS kills restore AP."),
            ),
            legendary_perks=(
                {"name": "Follow Through", "priority": "Required", "reason": "Stealth-amplified ranged damage.", "rank": 4},
                {"name": "Legendary Agility", "priority": "Recommended", "reason": "More AP and perk slots.", "rank": 2},
                {"name": "Legendary Luck", "priority": "Recommended", "reason": "Crit meter throughput.", "rank": 2},
            ),
            mutations=(
                {"name": "Eagle Eyes", "use": "Yes", "reason": "Critical damage and Perception."},
                {"name": "Speed Demon", "use": "Yes", "reason": "Reload and movement."},
            ),
            gear={
                "weapons": ["The Fixer", "Elder's Mark", "V63 Laser Carbine", "Handmade Rifle"],
                "armor": ["Secret Service Armor", "Civil Engineer Armor"],
                "weapon_effects": ["Anti-Armor", "Bloodied", "Quad", "Vampire's", "Furious"],
                "armor_effects": ["Unyielding (if Bloodied)", "Overeater's"],
                "ammo_consumables": ["Company Tea", "Blight Soup", "Overdrive"],
                "weapon_mods": ["Limit Breaking (4-star)", "Rejuvenators (4-star)", "Number Cruncher (4-star)"],
            },
            variants={
                "Bloodied": ["Unyielding armor", "Nerd Rage", "Adrenal Reaction"],
                "Full-health": ["Overeater's", "Vampire's weapons"],
            },
            swap_cards={"Daily Ops": ["Ricochet"], "Bosses": ["One Gun Army"]},
            weaknesses=("Squishy if not careful", "Dependent on VATS and AP regen"),
        ),
        ArchetypeBlueprint(
            archetype_id="rifleman",
            build_name="Stealth Rifleman",
            aliases=("rifleman", "non-automatic rifle", "sniper", "lever action"),
            special_allocation={
                "Strength": 3,
                "Perception": 15,
                "Endurance": 4,
                "Charisma": 3,
                "Intelligence": 3,
                "Agility": 15,
                "Luck": 13,
            },
            perk_picks=(
                ("rifleman", 3, "Damage", "Core non-automatic rifle damage."),
                ("expert_rifleman", 3, "Damage", "Stacks rifle damage."),
                ("master_rifleman", 3, "Damage", "Completes rifle stack."),
                ("tank_killer", 2, "Armor Pen", "All ranged armor ignore."),
                ("concentrated_fire", 3, "VATS", "Stacking VATS accuracy/damage."),
                ("gun_fu", 3, "VATS", "Auto target swap with damage bonus."),
                ("better_criticals", 3, "Criticals", "Big VATS crit damage."),
                ("critical_savvy", 3, "Criticals", "Reduced crit meter consumption."),
                ("grim_reapers_sprint", 1, "AP regen", "VATS kills restore AP."),
            ),
            legendary_perks=(
                {"name": "Follow Through", "priority": "Required", "reason": "Sneak attack damage amplifier.", "rank": 4},
                {"name": "Legendary Perception", "priority": "Recommended", "reason": "Long-range build cohesion.", "rank": 2},
                {"name": "Legendary Luck", "priority": "Recommended", "reason": "Crit cadence.", "rank": 2},
            ),
            mutations=(
                {"name": "Eagle Eyes", "use": "Yes", "reason": "Crit damage + Perception."},
                {"name": "Marsupial", "use": "Optional", "reason": "Mobility for sniping nests."},
            ),
            gear={
                "weapons": ["Lever Action Rifle", "Gauss Rifle", "Hunting Rifle", "Crossbow"],
                "armor": ["Secret Service Armor", "Chinese Stealth Armor"],
                "weapon_effects": ["Instigating", "Anti-Armor", "Bloodied"],
                "armor_effects": ["Unyielding (Bloodied)", "Overeater's"],
                "ammo_consumables": ["Company Tea", "Bobblehead: Sneak"],
                "weapon_mods": ["Limit Breaking (4-star)"],
            },
            variants={
                "Bloodied Sneak": ["Unyielding", "Nerd Rage"],
                "Full-health Sniper": ["Overeater's", "Instigating prefix"],
            },
            swap_cards={"Stealth": ["Sneak", "Mister Sandman"]},
            weaknesses=("Slow ammo cadence", "Weak to gap-closers without escape"),
        ),
        ArchetypeBlueprint(
            archetype_id="shotgunner",
            build_name="Power Armor Shotgunner",
            aliases=("shotgun", "shotgunner", "pepper shaker"),
            special_allocation={
                "Strength": 15,
                "Perception": 9,
                "Endurance": 5,
                "Charisma": 3,
                "Intelligence": 9,
                "Agility": 5,
                "Luck": 10,
            },
            perk_picks=(
                ("shotgunner", 3, "Damage", "Core shotgun damage."),
                ("expert_shotgunner", 3, "Damage", "Stacks shotgun damage."),
                ("master_shotgunner", 3, "Damage", "Completes shotgun stack."),
                ("scattershot", 3, "Utility", "Shotgun weight + reload speed."),
                ("skeet_shooter", 3, "Accuracy", "Hip-fire accuracy stack."),
                ("tank_killer", 2, "Armor Pen", "All ranged armor ignore."),
                ("stabilized", 3, "Accuracy", "Big-gun accuracy bonus carries to large shotguns."),
                ("better_criticals", 3, "Criticals", "VATS crit damage."),
                ("critical_savvy", 3, "Criticals", "Reduced crit meter consumption."),
            ),
            legendary_perks=(
                {"name": "Taking One for the Team", "priority": "Required", "reason": "Team damage amplifier.", "rank": 4},
                {"name": "Legendary Strength", "priority": "Recommended", "reason": "Free up STR perk slots.", "rank": 2},
            ),
            mutations=(
                {"name": "Speed Demon", "use": "Yes", "reason": "Reload speed."},
                {"name": "Adrenal Reaction", "use": "Variant", "reason": "Bloodied variant only."},
            ),
            gear={
                "weapons": ["Pepper Shaker", "Combat Shotgun", "Gauss Shotgun"],
                "armor": ["Union Power Armor", "Secret Service (if not PA)"],
                "weapon_effects": ["Anti-Armor", "Bloodied", "Furious"],
                "armor_effects": ["Overeater's", "Unyielding (if non-PA Bloodied)"],
                "ammo_consumables": ["Psychobuff", "Overdrive"],
                "weapon_mods": ["Furious", "Vital"],
            },
            variants={
                "Power Armor": ["Union PA", "Stabilized stack"],
                "Non-PA Bloodied": ["Secret Service", "Unyielding"],
            },
            swap_cards={"Bosses": ["One Gun Army"]},
            weaknesses=("Short effective range", "Pellet falloff at long range"),
        ),
        ArchetypeBlueprint(
            archetype_id="gunslinger",
            build_name="VATS Gunslinger",
            aliases=("gunslinger", "pistol", "revolver"),
            special_allocation={
                "Strength": 3,
                "Perception": 13,
                "Endurance": 5,
                "Charisma": 3,
                "Intelligence": 3,
                "Agility": 15,
                "Luck": 14,
            },
            perk_picks=(
                ("gunslinger", 3, "Damage", "Core non-automatic pistol damage."),
                ("expert_gunslinger", 3, "Damage", "Stacks pistol damage."),
                ("master_gunslinger", 3, "Damage", "Completes pistol stack."),
                ("tank_killer", 2, "Armor Pen", "All ranged armor ignore."),
                ("concentrated_fire", 3, "VATS", "Stacking VATS accuracy/damage."),
                ("gun_fu", 3, "VATS", "Auto target swap with damage bonus."),
                ("better_criticals", 3, "Criticals", "VATS crit damage."),
                ("critical_savvy", 3, "Criticals", "Reduced crit meter consumption."),
                ("grim_reapers_sprint", 1, "AP regen", "VATS kills restore AP."),
            ),
            legendary_perks=(
                {"name": "Follow Through", "priority": "Required", "reason": "Stealth pistol amp.", "rank": 4},
                {"name": "Legendary Agility", "priority": "Recommended", "reason": "AP + perk slots.", "rank": 2},
                {"name": "Legendary Luck", "priority": "Recommended", "reason": "Crit cadence.", "rank": 2},
            ),
            mutations=(
                {"name": "Eagle Eyes", "use": "Yes", "reason": "Crit damage + Perception."},
                {"name": "Speed Demon", "use": "Yes", "reason": "Reload and mobility."},
            ),
            gear={
                "weapons": ["Somerset Special", "Western Revolver", ".44 Pistol"],
                "armor": ["Secret Service Armor", "Chinese Stealth Armor"],
                "weapon_effects": ["Anti-Armor", "Bloodied", "Instigating"],
                "armor_effects": ["Overeater's", "Unyielding (Bloodied)"],
                "ammo_consumables": ["Company Tea"],
                "weapon_mods": ["Limit Breaking (4-star)"],
            },
            variants={
                "Bloodied": ["Unyielding", "Nerd Rage"],
                "Full-health": ["Overeater's"],
            },
            swap_cards={"Stealth": ["Sneak"]},
            weaknesses=("Limited to single-target burst", "Lower DPS than auto rifles in sustained fights"),
        ),
        ArchetypeBlueprint(
            archetype_id="melee",
            build_name="Bloodied Melee Bruiser",
            aliases=("melee", "two-handed", "unarmed", "chainsaw", "auto axe"),
            special_allocation={
                "Strength": 15,
                "Perception": 3,
                "Endurance": 13,
                "Charisma": 3,
                "Intelligence": 3,
                "Agility": 8,
                "Luck": 11,
            },
            perk_picks=(
                ("slugger", 3, "Damage", "Bonus damage to crippled targets."),
                ("wound_salter", 3, "Damage", "+30% damage vs bleeding."),
                ("incisor", 3, "Armor Pen", "75% armor ignore for melee."),
                ("martial_artist", 3, "Utility", "Swing speed and weight reduction."),
                ("knee_capper", 1, "Cripple", "+50% limb damage."),
            ),
            optional_perk_picks=(
                ("heavy_hitter", 1, "Damage", "Power-attack burst (swap-in)."),
                ("blood_luster", 1, "Damage", "Bleed multiplier (swap-in)."),
                ("natural_stance", 1, "Defense", "Stagger reduction (swap-in)."),
            ),
            legendary_perks=(
                {"name": "Legendary Strength", "priority": "Required", "reason": "Hard-cap on melee scaling.", "rank": 4},
                {"name": "Taking One for the Team", "priority": "Recommended", "reason": "Team amp at point-blank.", "rank": 2},
                {"name": "Power Armor Reboot", "priority": "Optional", "reason": "PA melee variant insurance.", "rank": 1},
            ),
            mutations=(
                {"name": "Adrenal Reaction", "use": "Yes", "reason": "Bloodied scaling."},
                {"name": "Talons", "use": "Yes", "reason": "+25 unarmed damage."},
                {"name": "Speed Demon", "use": "Yes", "reason": "Mobility for closing gaps."},
            ),
            gear={
                "weapons": ["Auto Axe", "Chainsaw", "Power Fist", "Super Sledge"],
                "armor": ["Solar Armor", "Union PA (PA variant)", "Secret Service"],
                "weapon_effects": ["Bloodied", "Vampire's", "Furious"],
                "armor_effects": ["Unyielding (Bloodied)", "Overeater's"],
                "ammo_consumables": ["Adrenal Reaction food", "Psychobuff"],
                "weapon_mods": ["Furious"],
            },
            variants={
                "Bloodied non-PA": ["Unyielding", "Nerd Rage", "Adrenal Reaction"],
                "PA Melee": ["Union PA", "Power Fist"],
            },
            swap_cards={"Defense": ["Blocker"], "Events": ["Strange in Numbers"]},
            weaknesses=("Bosses with knockback or toxic AoE", "Limited at range"),
        ),
        ArchetypeBlueprint(
            archetype_id="playable_ghoul",
            build_name="Playable Ghoul Heavy",
            aliases=("ghoul", "feral", "rad-absorber", "rad sponge"),
            special_allocation={
                "Strength": 13,
                "Perception": 3,
                "Endurance": 13,
                "Charisma": 3,
                "Intelligence": 11,
                "Agility": 3,
                "Luck": 10,
            },
            perk_picks=(
                ("rad_sponge", 2, "Survival", "Patch 62 rad-absorb to Hunger/Thirst."),
                ("ghoulish", 3, "Healing", "Radiation regenerates health."),
                ("bullet_storm", 3, "Damage", "Pairs heavy energy with Ghoul mechanics."),
                ("tightly_wound", 3, "Utility", "Faster spin-up."),
                ("bringing_the_big_guns", 1, "Damage", "Doubles BS stack cap."),
                ("stabilized", 3, "Accuracy", "Big-gun accuracy + PA bonus if equipped."),
                ("bear_arms", 3, "Carry", "Heavy weapon weight."),
                ("class_freak", 3, "Mutations", "Reduce mutation downsides."),
            ),
            legendary_perks=(
                {"name": "Legendary Endurance", "priority": "Required", "reason": "Health pool and rad management.", "rank": 4},
                {"name": "Electric Absorption", "priority": "Strongly Recommended", "reason": "Sustains PA variant.", "rank": 3},
                {"name": "Taking One for the Team", "priority": "Recommended", "reason": "Team amp.", "rank": 2},
            ),
            mutations=(
                {"name": "Speed Demon", "use": "Yes", "reason": "Mobility."},
                {"name": "Marsupial", "use": "Optional", "reason": "Mobility + carry."},
            ),
            gear={
                "weapons": ["Holy Fire", "Gatling Plasma", "Cremator"],
                "armor": ["Civil Engineer Armor", "Union PA (variant)"],
                "weapon_effects": ["Anti-Armor", "Vampire's", "Furious"],
                "armor_effects": ["Overeater's"],
                "ammo_consumables": ["Glowing Blood", "Toxic Goo", "Psychobuff"],
                "weapon_mods": ["Conductors"],
            },
            variants={
                "PA Ghoul": ["Stabilized stack", "Union PA"],
                "Non-PA Ghoul": ["Civil Engineer", "Ghoulish stack"],
            },
            swap_cards={"Travel": ["Marsupial maintenance"]},
            extra_assumptions=(
                "Cannot use Unyielding armor (Ghoul restriction).",
                "Radiation acts as a resource via Rad Sponge + Ghoulish.",
            ),
            weaknesses=("Cannot use Unyielding", "Pure-radiation immunity zones reduce uptime"),
        ),
        ArchetypeBlueprint(
            archetype_id="bow_stealth",
            build_name="Bow Stealth Sniper",
            aliases=("bow", "crossbow", "compound bow", "archery", "archer"),
            special_allocation={
                "Strength": 3,
                "Perception": 15,
                "Endurance": 3,
                "Charisma": 3,
                "Intelligence": 3,
                "Agility": 15,
                "Luck": 14,
            },
            perk_picks=(
                ("rifleman", 3, "Damage", "Bows scale with Rifleman family in 2026."),
                ("expert_rifleman", 3, "Damage", "Stacks rifle/bow damage."),
                ("master_rifleman", 3, "Damage", "Completes the rifle/bow stack."),
                ("long_shot", 3, "Range", "Range bonus for rifles and bows."),
                ("tank_killer", 2, "Armor Pen", "All ranged armor ignore."),
                ("mister_sandman", 3, "Stealth", "Silenced sneak-shot bonus; arrows are silent."),
                ("better_criticals", 3, "Criticals", "Crit damage on bow shots."),
                ("critical_savvy", 3, "Criticals", "Crit meter throughput."),
                ("grim_reapers_sprint", 1, "AP regen", "AP refund on VATS kills."),
            ),
            optional_perk_picks=(
                ("sneak", 3, "Stealth", "Stealth multiplier (swap-in if PER allows)."),
            ),
            legendary_perks=(
                {"name": "Follow Through", "priority": "Required", "reason": "Sneak attack damage amplifier.", "rank": 4},
                {"name": "Sneak Attacker", "priority": "Required", "reason": "Stacks with bow sneak damage.", "rank": 4},
                {"name": "Legendary Perception", "priority": "Recommended", "reason": "More PER for stealth tier.", "rank": 2},
                {"name": "Legendary Luck", "priority": "Recommended", "reason": "Crit cadence.", "rank": 2},
            ),
            mutations=(
                {"name": "Eagle Eyes", "use": "Yes", "reason": "Crit damage + Perception."},
                {"name": "Marsupial", "use": "Optional", "reason": "Mobility for high-ground sniping."},
            ),
            gear={
                "weapons": ["Compound Bow", "Crossbow", "Bow"],
                "armor": ["Chinese Stealth Armor", "Secret Service Armor"],
                "weapon_effects": ["Instigating", "Bloodied", "Anti-Armor"],
                "armor_effects": ["Unyielding (Bloodied)", "Overeater's"],
                "ammo_consumables": ["Plasma Arrows", "Explosive Arrows", "Company Tea"],
                "weapon_mods": ["True (4-star)", "Limit Breaking (4-star)"],
            },
            variants={
                "Bloodied Sneak Bow": ["Unyielding", "Nerd Rage", "Adrenal Reaction"],
                "Full-health Sniper Bow": ["Overeater's", "Instigating prefix"],
            },
            swap_cards={"Stealth": ["Sneak", "Mister Sandman"], "Travel": ["Marsupial maintenance"]},
            weaknesses=(
                "Slow draw cadence vs swarms.",
                "Limited horde clear.",
                "Requires high stealth uptime to maximize damage.",
            ),
            extra_assumptions=(
                "Bows scale with Rifleman perks per 2026 meta.",
                "Plasma/Explosive arrows benefit from explosion-retention buff (April 21 2026).",
            ),
        ),
        ArchetypeBlueprint(
            archetype_id="cremator_pyro",
            build_name="Cremator Pyromaniac",
            aliases=("cremator", "flamer", "pyro", "pyromaniac", "enclave flamer"),
            special_allocation={
                "Strength": 13,
                "Perception": 11,
                "Endurance": 5,
                "Charisma": 3,
                "Intelligence": 13,
                "Agility": 4,
                "Luck": 7,
            },
            perk_picks=(
                ("bullet_storm", 3, "Damage", "Cremator counts as a heavy weapon for Bullet Storm."),
                ("bringing_the_big_guns", 1, "Damage", "Doubles BS stack cap."),
                ("bear_arms", 3, "Carry / Bash", "Heavy weight reduction."),
                ("stabilized", 3, "Accuracy", "Big-gun accuracy + PA bonus."),
                ("demolition_expert", 5, "Damage", "Boosts Cremator splash and Enclave Flamer ignition."),
                ("grenadier", 2, "AoE", "Doubles explosive AoE radius."),
                ("fire_in_the_hole", 3, "Utility", "Better trajectory; pairs with Cremator alt-fire."),
                ("batteries_included", 3, "Economy", "Energy ammo weight."),
            ),
            optional_perk_picks=(
                ("one_gun_army", 3, "Utility", "Cripple/stagger on splash."),
            ),
            legendary_perks=(
                {"name": "Far-Flung Fireworks", "priority": "Required", "reason": "Cremator chains kills with rocket splash.", "rank": 4},
                {"name": "Taking One for the Team", "priority": "Strongly Recommended", "reason": "Team amp on tagged enemies.", "rank": 3},
                {"name": "Electric Absorption", "priority": "Optional", "reason": "Sustains PA Enclave Flamer variant.", "rank": 1},
                {"name": "Ammo Factory", "priority": "Swap-in", "reason": "Cremator/flamer ammo economy.", "rank": 1},
            ),
            mutations=(
                {"name": "Speed Demon", "use": "Yes", "reason": "Reload and mobility."},
                {"name": "Class Freak", "use": "Yes", "reason": "Reduce mutation downsides."},
            ),
            gear={
                "weapons": ["Cremator", "Enclave Flamer", "Holy Fire", "Plasma Caster"],
                "armor": ["Union Power Armor", "Hellcat", "T-65"],
                "weapon_effects": ["Anti-Armor", "Furious", "Vampire's"],
                "armor_effects": ["Overeater's"],
                "ammo_consumables": ["Cremator Cartridges", "Flamer Fuel", "Psychobuff", "Overdrive"],
                "weapon_mods": ["Vital", "Conductors"],
            },
            variants={
                "Power Armor Pyro": ["Stabilized stack", "Union PA"],
                "Non-PA Pyro": ["Civil Engineer Armor", "Marsupial"],
            },
            swap_cards={
                "Crowd control": ["Grenadier"],
                "Bosses": ["One Gun Army"],
                "Events": ["Far-Flung Fireworks"],
            },
            weaknesses=(
                "Splash self-damage now factors Demolition Expert in math (April 21 2026).",
                "Long-range targets still favor Gauss minigun.",
                "Cremator ammo can be expensive without Ammo Factory.",
            ),
            extra_assumptions=(
                "Explosion damage retention vs high-resist enemies improved in April 21 2026.",
                "Demolition Expert + explosive bobbleheads now correctly factored into self-damage.",
            ),
        ),
        ArchetypeBlueprint(
            archetype_id="pepper_shaker_stealth",
            build_name="Pepper Shaker Stealth Shotgunner",
            aliases=(
                "pepper shaker stealth",
                "fancy pump-action",
                "fancy pump action",
                "stealth shotgun",
                "fancy shotgun",
            ),
            special_allocation={
                "Strength": 13,
                "Perception": 13,
                "Endurance": 4,
                "Charisma": 3,
                "Intelligence": 5,
                "Agility": 11,
                "Luck": 7,
            },
            perk_picks=(
                ("shotgunner", 3, "Damage", "Core shotgun damage."),
                ("expert_shotgunner", 3, "Damage", "Stacks shotgun damage."),
                ("master_shotgunner", 3, "Damage", "Completes shotgun stack."),
                ("scattershot", 3, "Utility", "Shotgun weight + reload speed."),
                ("skeet_shooter", 3, "Accuracy", "Hip-fire accuracy stack."),
                ("tank_killer", 2, "Armor Pen", "All ranged armor ignore."),
                ("sneak", 3, "Stealth", "Core stealth multiplier for the new Fancy Pump-Action niche."),
                ("mister_sandman", 3, "Stealth", "Silenced sneak attack damage."),
                ("better_criticals", 3, "Criticals", "VATS crit damage."),
            ),
            legendary_perks=(
                {"name": "Follow Through", "priority": "Required", "reason": "Sneak attack damage amplifier for shotgun stealth pivot.", "rank": 4},
                {"name": "Sneak Attacker", "priority": "Required", "reason": "Stacks with the new Fancy Pump-Action stealth tuning.", "rank": 4},
                {"name": "Taking One for the Team", "priority": "Recommended", "reason": "Team amp on tagged enemies.", "rank": 2},
            ),
            mutations=(
                {"name": "Eagle Eyes", "use": "Yes", "reason": "Crit damage + Perception."},
                {"name": "Speed Demon", "use": "Yes", "reason": "Reload speed."},
            ),
            gear={
                "weapons": ["Fancy Pump-Action Shotgun", "Pepper Shaker", "Combat Shotgun"],
                "armor": ["Chinese Stealth Armor", "Secret Service Armor"],
                "weapon_effects": ["Instigating", "Anti-Armor", "Bloodied"],
                "armor_effects": ["Unyielding (Bloodied)", "Overeater's"],
                "ammo_consumables": ["Company Tea", "Bobblehead: Sneak"],
                "weapon_mods": ["Limit Breaking (4-star)", "True (4-star)"],
            },
            variants={
                "Bloodied Sneak Shotgun": ["Unyielding", "Nerd Rage"],
                "Full-health Sneak Shotgun": ["Overeater's"],
            },
            swap_cards={"Stealth": ["Sneak", "Mister Sandman"], "Bosses": ["One Gun Army"]},
            weaknesses=(
                "Fancy Pump-Action has lower durability and +10% AP cost (April 21 2026).",
                "Hip-fire cone is now wider; relies on sneak crouch fire.",
                "Falls off vs swarms.",
            ),
            extra_assumptions=(
                "Fancy Pump-Action tuned for stealth in April 21 2026 patch (smaller cone while sneaking, +25% reload, +10% fire rate).",
            ),
        ),
        ArchetypeBlueprint(
            archetype_id="ghoul_commando",
            build_name="Playable Ghoul Commando",
            aliases=("ghoul commando", "ghoul auto rifle", "feral commando"),
            special_allocation={
                "Strength": 3,
                "Perception": 14,
                "Endurance": 8,
                "Charisma": 3,
                "Intelligence": 3,
                "Agility": 14,
                "Luck": 11,
            },
            perk_picks=(
                ("commando", 3, "Damage", "Core automatic rifle damage."),
                ("expert_commando", 3, "Damage", "Stacks auto rifle damage."),
                ("master_commando", 3, "Damage", "Completes auto rifle damage stack."),
                ("tank_killer", 2, "Armor Pen", "All ranged armor ignore."),
                ("concentrated_fire", 3, "VATS", "Stacking VATS accuracy/damage."),
                ("better_criticals", 3, "Criticals", "VATS crit damage."),
                ("critical_savvy", 3, "Criticals", "Crit meter throughput."),
                ("hyper_reflexes", 3, "Speed", "Action speed while feral."),
                ("action_ghoul", 3, "AP", "AP regen while feral."),
                ("class_freak", 3, "Mutations", "Reduce mutation downsides."),
            ),
            optional_perk_picks=(
                ("glowing_hunter", 3, "Damage", "Marked target damage stack (ghoul; PER swap-in)."),
            ),
            legendary_perks=(
                {"name": "Follow Through", "priority": "Required", "reason": "Sneak amp + ghoul stealth synergy.", "rank": 4},
                {"name": "Glowing One", "priority": "Recommended", "reason": "Team glow buff.", "rank": 2},
                {"name": "Legendary Agility", "priority": "Recommended", "reason": "AP throughput.", "rank": 2},
                {"name": "What Rads?", "priority": "Optional", "reason": "Rad cap insurance.", "rank": 1},
            ),
            mutations=(
                {"name": "Eagle Eyes", "use": "Yes", "reason": "Crit damage + Perception."},
                {"name": "Speed Demon", "use": "Yes", "reason": "Reload and mobility."},
                {"name": "Marsupial", "use": "Optional", "reason": "Mobility + carry."},
            ),
            gear={
                "weapons": ["The Fixer", "Elder's Mark", "Handmade", "V63 Laser Carbine"],
                "armor": ["Civil Engineer Armor", "Secret Service Armor"],
                "weapon_effects": ["Anti-Armor", "Bloodied", "Vampire's"],
                "armor_effects": ["Overeater's"],
                "ammo_consumables": ["Glowing Blood", "Toxic Goo", "Company Tea"],
                "weapon_mods": ["Limit Breaking (4-star)", "Number Cruncher (4-star)"],
            },
            variants={
                "Feral Ghoul Commando": ["Hyper Reflexes", "Action Ghoul", "Glowing Criticals"],
                "Full-health Ghoul Commando": ["Overeater's", "Vampire's"],
            },
            swap_cards={"Stealth": ["Sneak"], "Bosses": ["One Gun Army"]},
            extra_assumptions=(
                "Cannot use Unyielding armor (Ghoul restriction).",
                "Glow + Feral state act as resources via Glowing Hunter / Action Ghoul.",
            ),
            weaknesses=(
                "Cannot use Unyielding.",
                "Reliant on Feral state for AP throughput.",
                "Pure-radiation immunity zones reduce uptime.",
            ),
        ),
        ArchetypeBlueprint(
            archetype_id="ghoul_melee",
            build_name="Playable Ghoul Melee Bruiser",
            aliases=("ghoul melee", "feral melee", "feral bruiser"),
            special_allocation={
                "Strength": 15,
                "Perception": 3,
                "Endurance": 13,
                "Charisma": 3,
                "Intelligence": 3,
                "Agility": 8,
                "Luck": 11,
            },
            perk_picks=(
                ("slugger", 3, "Damage", "Bonus damage to crippled targets."),
                ("incisor", 3, "Armor Pen", "75% armor ignore for melee."),
                ("martial_artist", 3, "Utility", "Swing speed + weight reduction."),
                ("bone_shatterer", 3, "Cripple", "Ghoul melee crippling chance."),
                ("feral_rage", 3, "Damage", "Damage while feral."),
                ("brick_wall", 3, "Defense", "DR while feral."),
                ("class_freak", 3, "Mutation", "Reduce mutation downsides."),
            ),
            optional_perk_picks=(
                ("wound_salter", 3, "Damage", "+30% vs bleeding (STR swap-in)."),
                ("battle_genes", 3, "Mutation", "Mutation damage stack (STR swap-in)."),
                ("blocker", 3, "Defense", "Melee damage taken reduction."),
                ("hyper_reflexes", 3, "Speed", "Action speed while feral."),
            ),
            legendary_perks=(
                {"name": "Hack and Slash", "priority": "Required", "reason": "Shockwave on melee hits.", "rank": 4},
                {"name": "Retribution", "priority": "Required", "reason": "Reflect damage taken as fire.", "rank": 4},
                {"name": "Legendary Strength", "priority": "Recommended", "reason": "Hard-cap on melee scaling.", "rank": 2},
                {"name": "Glowing One", "priority": "Recommended", "reason": "Team glow buff.", "rank": 2},
            ),
            mutations=(
                {"name": "Adrenal Reaction", "use": "Yes", "reason": "Bloodied scaling."},
                {"name": "Talons", "use": "Yes", "reason": "+25 unarmed damage."},
                {"name": "Speed Demon", "use": "Yes", "reason": "Mobility."},
            ),
            gear={
                "weapons": ["Auto Axe", "Chainsaw", "Power Fist", "Super Sledge"],
                "armor": ["Solar Armor", "Secret Service Armor"],
                "weapon_effects": ["Bloodied", "Vampire's", "Furious"],
                "armor_effects": ["Overeater's"],
                "ammo_consumables": ["Glowing Blood", "Adrenal Reaction food", "Psychobuff"],
                "weapon_mods": ["Furious"],
            },
            variants={
                "Feral Ghoul Melee": ["Feral Rage", "Hyper Reflexes", "Brick Wall"],
                "Full-health Ghoul Melee": ["Overeater's"],
            },
            swap_cards={"Defense": ["Blocker"], "Events": ["Strange in Numbers"]},
            extra_assumptions=(
                "Cannot use Unyielding armor (Ghoul restriction).",
                "Glow + Feral state stack with melee damage via Feral Rage / Battle-Genes.",
            ),
            weaknesses=(
                "Cannot use Unyielding.",
                "Limited at range.",
                "Bosses with knockback or toxic AoE.",
            ),
        ),
    ]
    return {bp.archetype_id: bp for bp in blueprints}


_BLUEPRINTS = _build_archetype_blueprints()


def _free_text(inp: BuildInput) -> str:
    return " ".join(
        [
            inp.primary_playstyle,
            inp.primary_weapon_type,
            inp.preferred_weapons,
            inp.armor_type,
            inp.health_model,
            inp.combat_style,
        ]
    ).lower()


def classify(inp: BuildInput) -> str:
    """Return the archetype id that best matches the user's free-text inputs."""
    text = _free_text(inp)

    is_ghoul = "ghoul" in text or "feral" in text

    # Specific high-priority signals first.
    if is_ghoul and ("commando" in text or "auto rifle" in text or "automatic rifle" in text or "fixer" in text):
        return "ghoul_commando"
    if is_ghoul and ("melee" in text or "unarmed" in text or "two-handed" in text or "chainsaw" in text or "auto axe" in text):
        return "ghoul_melee"
    if is_ghoul:
        return "playable_ghoul"
    if "bow" in text or "crossbow" in text or "archer" in text or "archery" in text:
        return "bow_stealth"
    if "cremator" in text or "flamer" in text or "pyro" in text:
        return "cremator_pyro"
    if "fancy pump" in text or "fancy shotgun" in text or ("stealth" in text and "shotgun" in text):
        return "pepper_shaker_stealth"
    if "melee" in text or "unarmed" in text or "two-handed" in text or "chainsaw" in text or "auto axe" in text:
        return "melee"
    if "shotgun" in text or "pepper shaker" in text:
        return "shotgunner"
    if "pistol" in text or "revolver" in text or "gunslinger" in text:
        return "gunslinger"
    if "non-automatic rifle" in text or "rifleman" in text or "sniper" in text or "lever" in text:
        return "rifleman"
    if "commando" in text or "automatic rifle" in text or "auto rifle" in text or "fixer" in text:
        return "onslaught_commando"
    if "bullet storm" in text or "heavy ballistic" in text:
        return "bullet_storm_heavy"
    if "power armor" in text and "heavy" in text and "energy" in text:
        return "power_armor_heavy_energy"
    if "power armor" in text and "heavy" in text:
        return "bullet_storm_heavy"
    if "heavy" in text and "energy" in text:
        return "power_armor_heavy_energy"
    if "heavy" in text:
        return "bullet_storm_heavy"
    if "bloodied" in text and "melee" in text:
        return "melee"
    if "bloodied" in text:
        return "onslaught_commando"
    return "power_armor_heavy_energy"


def list_archetypes() -> List[Dict[str, str]]:
    return [
        {"id": bp.archetype_id, "name": bp.build_name}
        for bp in _BLUEPRINTS.values()
    ]


def get_archetype_preview(archetype_id: str) -> Dict[str, object] | None:
    bp = _BLUEPRINTS.get(archetype_id)
    if bp is None:
        return None
    def _picks(picks):
        return [
            {"card_id": c, "rank": str(r), "role": role, "why": why}
            for (c, r, role, why) in picks
        ]
    return {
        "id": bp.archetype_id,
        "name": bp.build_name,
        "aliases": list(bp.aliases),
        "special_allocation": dict(bp.special_allocation),
        "perk_picks": _picks(bp.perk_picks),
        "optional_perk_picks": _picks(bp.optional_perk_picks),
        "legendary_perks": [dict(lp) for lp in bp.legendary_perks],
        "gear": dict(bp.gear),
        "weaknesses": list(bp.weaknesses),
        "extra_assumptions": list(bp.extra_assumptions),
    }


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _build_assumptions(extra: tuple[str, ...]) -> List[str]:
    accessed = latest_source_date_accessed().isoformat()
    base = [
        f"Validated against local source registry accessed on {accessed}.",
        "Aligned with Patch 62 (CAMP Revamp) and the April 21 2026 update.",
        "April 21 2026: armor durability buffed; explosions retain more damage on indirect hits and vs high-resist enemies.",
        "April 21 2026: Demolition Expert + explosive bobbleheads now correctly factored into self-damage math.",
        "April 21 2026: Fancy Pump-Action Shotgun + Fancy Single-Action Revolver pivoted to stealth (smaller cone while sneaking, +25% reload, +10% fire rate, +10% AP cost, lower durability).",
        "April 21 2026: Fierce 2-star legendary mod normalized in cost; locked-mod consumption exploit closed.",
        "Assumes default full-health unless the user selects bloodied.",
        "Legendary SPECIAL slots not strictly required for base playability.",
    ]
    base.extend(extra)
    return base


def _materialize_picks(blueprint: ArchetypeBlueprint) -> tuple[List[PerkChoice], Dict[str, List[PerkChoice]]]:
    perks_by_id = {p.id: p for p in load_active_perks()}
    spent_per_special: Dict[str, int] = {k: 0 for k in SPECIALS}
    selected: List[PerkChoice] = []

    def _try_add(card_id: str, rank: int, role: str, why: str, *, optional: bool) -> None:
        card = perks_by_id.get(card_id)
        if card is None:
            return
        cost = card.rank_costs.get(rank)
        if cost is None:
            return
        budget = blueprint.special_allocation.get(card.special, 0)
        if optional and spent_per_special[card.special] + cost > budget:
            return
        spent_per_special[card.special] += cost
        selected.append(PerkChoice(card_id=card_id, rank=rank, role=role, why=why))

    for card_id, rank, role, why in blueprint.perk_picks:
        _try_add(card_id, rank, role, why, optional=False)

    for card_id, rank, role, why in blueprint.optional_perk_picks:
        _try_add(card_id, rank, role, why, optional=True)

    by_special: Dict[str, List[PerkChoice]] = {k: [] for k in SPECIALS}
    for choice in selected:
        card = perks_by_id.get(choice.card_id)
        if card is not None:
            by_special[card.special].append(choice)
    return selected, by_special


def _build_from_blueprint(blueprint: ArchetypeBlueprint, user: BuildInput) -> GeneratedBuild:
    selected, by_special = _materialize_picks(blueprint)
    sources = list_sources()
    return GeneratedBuild(
        id=f"build-{uuid4().hex[:12]}",
        build_name=blueprint.build_name,
        user_inputs=user,
        assumptions=_build_assumptions(blueprint.extra_assumptions),
        special_allocation=dict(blueprint.special_allocation),
        perk_cards_by_special=by_special,
        legendary_perks=[dict(lp) for lp in blueprint.legendary_perks],
        mutations=[dict(m) for m in blueprint.mutations],
        gear=dict(blueprint.gear),
        variants=dict(blueprint.variants),
        swap_cards=dict(blueprint.swap_cards),
        weaknesses=list(blueprint.weaknesses),
        validation_status="pending",
        source_verification_notes=[
            f"{s.source_name} | {s.source_url} | accessed {s.date_accessed.isoformat()} | type={s.source_type.value}"
            for s in sources
        ],
        created_at=_now_utc(),
    )


def generate_build(user: BuildInput) -> GeneratedBuild:
    archetype = classify(user)
    blueprint = _BLUEPRINTS.get(archetype)
    if blueprint is None:
        raise NotImplementedError(
            f"Archetype '{archetype}' is not yet supported."
        )
    return _build_from_blueprint(blueprint, user)


def generate_and_refine_build(user: BuildInput, max_retries: int = 2) -> GeneratedBuild:
    """Deterministic build, mandatory brain-driven confirmation and enhancement."""
    build = generate_build(user)
    issues = validate_build(build)

    for _ in range(max(1, max_retries)):
        enhance_build_with_brain(user, build, issues)
        new_issues = validate_build(build)
        if not new_issues:
            build.validation_status = "passed"
            return build
        if new_issues == issues:
            break
        issues = new_issues

    build.validation_status = "passed" if not issues else "issues"
    return build


def _legendary_special_bonus_total(build: GeneratedBuild) -> int:
    bonus = 0
    for lp in build.legendary_perks:
        name = lp.get("name", "")
        if LEGENDARY_NAME_PATTERN.match(name):
            rank = lp.get("rank", 1)
            bonus += _legendary_special_bonus(rank if isinstance(rank, int) else 1)
    return bonus


def validate_build(build: GeneratedBuild) -> list[str]:
    perks_by_id = {p.id: p for p in load_perks()}
    legendary_perks_by_id = {p.id: p for p in load_legendary_perks()}
    issues: list[str] = []

    # SPECIAL totals
    total_special_points = 0
    legendary_special_bonus = _legendary_special_bonus_total(build)
    for special in SPECIALS:
        points = build.special_allocation.get(special, 1)
        total_special_points += points
        if points < 1 or points > 15:
            issues.append(f"{special} allocation ({points}) is invalid. Must be between 1 and 15.")

    max_allowed_points = SPECIAL_BUDGET + legendary_special_bonus
    if total_special_points > max_allowed_points:
        issues.append(
            f"Total SPECIAL points ({total_special_points}) exceed the maximum of "
            f"{max_allowed_points} (with {legendary_special_bonus} bonus from legendary stat perks)."
        )

    full_health = build.user_inputs.health_model == "Full health"
    non_vats = build.user_inputs.combat_style == "Non-VATS"
    avoid_stealth = "stealth" in build.user_inputs.avoid_list.lower()
    pa_user = "Power Armor" in build.user_inputs.armor_type

    for special, picks in build.perk_cards_by_special.items():
        spent = 0
        for pick in picks:
            card = perks_by_id.get(pick.card_id)
            if not card:
                issues.append(f"Unknown perk id: {pick.card_id}")
                continue
            if card.status == Status.deprecated:
                issues.append(f"Perk {card.name} is deprecated and should not be selected.")
            elif card.status != Status.verified:
                issues.append(f"Unverified perk flagged: {card.name}")
            if card.special != special:
                issues.append(f"Perk {card.name} mapped to wrong SPECIAL ({special})")
            if pick.rank < 1 or pick.rank > card.max_rank:
                issues.append(f"Perk {card.name} has invalid rank {pick.rank}")
                continue
            if pick.rank not in card.rank_costs:
                issues.append(f"Perk {card.name} missing rank cost for rank {pick.rank}")
                continue
            spent += card.rank_costs[pick.rank]
            if card.power_armor_only and not pa_user:
                issues.append(f"Perk {card.name} requires Power Armor")
            if card.stealth_synergy and (non_vats or avoid_stealth):
                issues.append(f"Stealth perk {card.name} conflicts with the user's combat preferences")
            if card.bloodied_synergy and full_health:
                issues.append(f"Bloodied perk {card.name} used in full-health build")
            if card.vats_synergy and non_vats:
                issues.append(f"VATS perk {card.name} used in non-VATS build")
        budget = build.special_allocation.get(special, 0)
        if spent > budget:
            issues.append(f"{special} overspent ({spent} > {budget})")

    # Validate legendary perks
    for lp in build.legendary_perks:
        name = str(lp.get("name", ""))
        rank = lp.get("rank", 1)
        if not name:
            issues.append("Legendary perk missing name")
            continue
        found = False
        for card in legendary_perks_by_id.values():
            if card.name == name:
                found = True
                if not isinstance(rank, int) or rank < 1 or rank > card.max_rank:
                    issues.append(
                        f"Legendary perk {name} has invalid rank {rank} (max {card.max_rank})"
                    )
                break
        if not found:
            issues.append(f"Unknown legendary perk: {name}")

    if not build.weaknesses:
        issues.append("Weaknesses/tradeoffs section required")

    # Ghoul archetype restriction (April 2026 patch + Ghoul Within update).
    is_ghoul_build = "ghoul" in build.build_name.lower() or any(
        "ghoul" in (a or "").lower() for a in build.assumptions
    )
    if is_ghoul_build:
        gear_armor = build.gear.get("armor_effects", []) + build.gear.get("armor", [])
        user_text = (
            build.user_inputs.armor_type + " " + build.user_inputs.current_gear
        ).lower()
        if "unyielding" in user_text or any("unyielding" in str(a).lower() for a in gear_armor):
            issues.append(
                "Ghoul build conflict: Unyielding armor is not usable by Playable Ghoul characters."
            )

    return issues


def compare_builds(builds: list[GeneratedBuild]) -> CompareResult:
    return CompareResult(
        build_ids=[b.id for b in builds],
        special_diff={b.id: b.special_allocation for b in builds},
        core_perk_diff={
            b.id: [p.card_id for cards in b.perk_cards_by_special.values() for p in cards]
            for b in builds
        },
    )
