from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List
from uuid import uuid4

from app.models import (
    BuildInput,
    CompareResult,
    GeneratedBuild,
    PerkCard,
    PerkChoice,
    Status,
)
from app.services.brain import enhance_build_with_brain
from app.services.repository import (
    latest_source_date_accessed,
    get_build,
    list_sources,
    load_active_legendary_perks,
    load_active_perks,
    load_legendary_perks,
    load_perks,
    save_build,
)

logger = logging.getLogger(__name__)

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
GHOUL_RESTRICTED_PERK_IDS = frozenset(
    {
        "chem_resistant",
        "dromedary",
        "ghoulish",
        "happy_camper",
        "hydro_fix",
        "iron_stomach",
        "lead_belly",
        "munchy_resistance",
        "mystery_meat",
        "natural_resistance",
        "overly_generous",
        "pharmacist",
        "quick_hands",
        "rad_resistant",
        "rad_sponge",
        "radicool",
        "rejuvenated",
        "slow_metabolizer",
        "sun_kissed",
        "thirst_quencher",
        "vaccinated",
    }
)

MUTATION_SUPPORT_PERK_PICKS: tuple[tuple[str, int, str, str], ...] = (
    ("starched_genes", 1, "Mutation Support", "Locks in selected mutations and protects against RadAway removal."),
    ("class_freak", 3, "Mutation Support", "Reduces negative mutation effects for multi-mutation builds."),
)
TEAM_MUTATION_SUPPORT_PICK = (
    "strange_in_numbers",
    1,
    "Team Mutation Support",
    "Boosts positive mutation effects while grouped with mutated teammates.",
)

MUTATION_DETAILS: dict[str, dict[str, str]] = {
    "Speed Demon": {"reason": "Reload speed and movement.", "support": "Class Freak + Starched Genes"},
    "Adrenal Reaction": {"reason": "Low-health damage scaling.", "support": "Class Freak + Starched Genes"},
    "Marsupial": {"reason": "Jump height and carry weight.", "support": "Class Freak + Starched Genes"},
    "Eagle Eyes": {"reason": "Critical damage and Perception.", "support": "Class Freak + Starched Genes"},
    "Talons": {"reason": "Unarmed damage support.", "support": "Class Freak + Starched Genes"},
    "Bird Bones": {"reason": "Agility and slower falling.", "support": "Class Freak + Starched Genes"},
    "Egg Head": {"reason": "Intelligence boost for XP and crafting utility.", "support": "Class Freak + Starched Genes"},
    "Empath": {"reason": "Team damage mitigation.", "support": "Class Freak + Starched Genes + Strange in Numbers"},
    "Healing Factor": {"reason": "Out-of-combat health regeneration.", "support": "Class Freak + Starched Genes"},
    "Herd Mentality": {"reason": "SPECIAL boost while grouped.", "support": "Class Freak + Starched Genes + Strange in Numbers"},
    "Carnivore": {"reason": "Meat food bonuses.", "support": "Class Freak + Starched Genes"},
    "Herbivore": {"reason": "Plant food bonuses.", "support": "Class Freak + Starched Genes"},
    "Twisted Muscles": {"reason": "Melee damage support.", "support": "Class Freak + Starched Genes"},
    "Plague Walker": {"reason": "Poison aura when diseases are active.", "support": "Class Freak + Starched Genes"},
    "Grounded": {"reason": "Energy resistance at the cost of energy weapon damage.", "support": "Class Freak + Starched Genes"},
    "Scaly Skin": {"reason": "Damage and energy resistance at an AP cost.", "support": "Class Freak + Starched Genes"},
    "Electrically Charged": {"reason": "Chance to shock melee attackers.", "support": "Class Freak + Starched Genes"},
    "Unstable Isotope": {"reason": "Radiation burst chance when hit in melee.", "support": "Class Freak + Starched Genes"},
    "Chameleon": {"reason": "Stealth invisibility while stationary and unarmored.", "support": "Class Freak + Starched Genes"},
}
GHOUL_RESTRICTED_LEGENDARY_NAMES = frozenset({"what rads?"})

OVEREATERS_NOTE = (
    "As of The Backwoods update (March 2026), Overeater's increases maximum Health "
    "by up to +40 per armor piece when well-fed and well-hydrated. "
    "It no longer provides percentage-based damage reduction."
)

LEGENDARY_PERK_STRATEGY_NOTE = (
    "Legendary Perks no longer require Perk Coins to unequip (March 2026 Backwoods update). "
    "Optimized endgame builds often use several Legendary SPECIAL cards plus one combat "
    "or utility flex slot. Utility perks such as Ammo Factory and Master Infiltrator "
    "can be swapped in situationally at no cost. This is a recommended default for "
    "endgame optimization, not a hard requirement."
)

# Expanded mutation recommendations grouped by role.
# These are strongly recommended for optimized builds but not mandatory.
# User mutation_preference always takes priority.
UNIVERSAL_MUTATIONS: tuple[Dict[str, str], ...] = (
    {"name": "Speed Demon", "use": "Recommended", "reason": "Reload speed and movement speed."},
    {"name": "Marsupial", "use": "Recommended", "reason": "Jump height and +20 carry weight."},
    {"name": "Herd Mentality", "use": "Recommended", "reason": "+2 all SPECIAL while on any team."},
)
VATS_MUTATIONS: tuple[Dict[str, str], ...] = (
    {"name": "Eagle Eyes", "use": "Recommended", "reason": "Critical damage +25%, Perception +4."},
    {"name": "Bird Bones", "use": "Recommended", "reason": "Agility +4 (AP pool), slower falling."},
)
BLOODIED_MUTATIONS: tuple[Dict[str, str], ...] = (
    {"name": "Adrenal Reaction", "use": "Yes", "reason": "Up to +50% weapon damage at low health."},
)
MELEE_MUTATIONS: tuple[Dict[str, str], ...] = (
    {"name": "Twisted Muscles", "use": "Recommended", "reason": "+25% melee damage."},
    {"name": "Talons", "use": "Unarmed Only", "reason": "+25% unarmed damage, bleed."},
)
TANK_MUTATIONS: tuple[Dict[str, str], ...] = (
    {"name": "Scaly Skin", "use": "Recommended", "reason": "+50 DR and ER."},
)


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
                "armor_effects": ["Overeater's (+40 max HP/piece)", "Enemy-specific situational sets"],
                "armor_mods": ["Buttressed (max DR/ER)", "Calibrated Shocks (PA carry weight)", "Emergency Protocols (PA low-health)"],
                "underarmor": ["Shielded Raider (PER +3, AGI +3, LCK +1)", "Shielded Casual (INT +3, PER +1, LCK +3)"],
                "ammo_consumables": ["Fusion Cores", "Plasma Cores", "Ultracite ammo", "Overdrive", "Psychobuff", "Ballistic Bock / High Voltage Hefe"],
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
                "armor_effects": ["Overeater's (+40 max HP/piece)", "Unyielding (if Bloodied non-PA)"],
                "armor_mods": ["Buttressed (max DR/ER)", "Deep Pocketed (carry weight)"],
                "underarmor": ["Shielded Raider (PER +3, AGI +3, LCK +1)"],
                "ammo_consumables": ["Psychobuff", "Overdrive", "Ballistic Bock"],
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
                "armor_effects": ["Unyielding (if Bloodied)", "Overeater's (+40 max HP/piece)"],
                "armor_mods": ["Ultra-Light (AP)", "Sleek (sneak speed)", "Muffled (sneak detection)"],
                "underarmor": ["Shielded Casual (INT +3, PER +1, LCK +3)", "Shielded Enclave (STR +1, PER +2, INT +3)"],
                "ammo_consumables": ["Company Tea", "Blight Soup", "Overdrive", "Bobblehead: Small Guns", "Live & Love 8 (team AP regen)"],
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
                "armor_effects": ["Unyielding (Bloodied)", "Overeater's (+40 max HP/piece)"],
                "armor_mods": ["Ultra-Light (AP)", "Muffled (sneak detection)", "Sleek (sneak speed)"],
                "underarmor": ["Shielded Casual (INT +3, PER +1, LCK +3)"],
                "ammo_consumables": ["Company Tea", "Bobblehead: Sneak", "Bobblehead: Small Guns"],
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
                "weapons": ["Somerset Special", "Western Revolver", "Crusader Pistol", ".44 Pistol", "10mm Auto Pistol"],
                "armor": ["Secret Service Armor", "Chinese Stealth Armor"],
                "weapon_effects": ["Anti-Armor", "Bloodied", "Instigating", "Quad (10mm Auto)"],
                "armor_effects": ["Overeater's (+40 max HP/piece)", "Unyielding (Bloodied)"],
                "armor_mods": ["Ultra-Light (AP)", "Muffled (sneak detection)"],
                "underarmor": ["Shielded Casual (INT +3, PER +1, LCK +3)", "Shielded Raider (PER +3, AGI +3, LCK +1)"],
                "ammo_consumables": ["Company Tea", "Bobblehead: Small Guns", "Overdrive"],
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
                "weapons": ["Auto Axe", "Chainsaw", "Power Fist", "Super Sledge", "Deathclaw Gauntlet"],
                "armor": ["Solar Armor", "Union PA (PA variant)", "Secret Service"],
                "weapon_effects": ["Bloodied", "Vampire's", "Furious", "Anti-Armor"],
                "armor_effects": ["Unyielding (Bloodied)", "Overeater's (+40 max HP/piece)"],
                "armor_mods": ["Buttressed (max DR/ER)", "Dense (explosion resistance)", "Weighted (melee reflect)"],
                "underarmor": ["Shielded Raider (PER +3, AGI +3, LCK +1)", "Shielded BOS (STR +2, END +3)"],
                "ammo_consumables": ["Psychobuff", "Fury", "Glowing Meat Steak", "Deathclaw Steak"],
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
                "Strength": 15,
                "Perception": 1,
                "Endurance": 8,
                "Charisma": 4,
                "Intelligence": 12,
                "Agility": 6,
                "Luck": 10,
            },
            perk_picks=(
                ("bullet_storm", 3, "Damage", "Pairs heavy energy with Ghoul mechanics."),
                ("tightly_wound", 3, "Utility", "Faster spin-up."),
                ("bringing_the_big_guns", 1, "Damage", "Doubles BS stack cap."),
                ("bear_arms", 3, "Carry", "Heavy weapon weight."),
                ("arms_of_steel", 2, "Accuracy", "Ghoul ranged accuracy support."),
                ("glowing_one", 2, "Team Glow", "Team Glow support while stocked on Glow."),
                ("stabilized", 3, "Accuracy", "Big-gun accuracy + PA bonus if equipped."),
                ("action_ghoul", 3, "AP", "AP regen while holding Glow."),
                ("class_freak", 3, "Mutations", "Reduce mutation downsides."),
            ),
            legendary_perks=(
                {"name": "Action Diet", "priority": "Required", "reason": "Maintains non-feral uptime and heals on kills.", "rank": 3},
                {"name": "Electric Absorption", "priority": "Strongly Recommended", "reason": "Sustains PA variant.", "rank": 3},
                {"name": "Taking One for the Team", "priority": "Recommended", "reason": "Team amp.", "rank": 2},
                {"name": "Legendary Strength", "priority": "Recommended", "reason": "Heavy-weapon perk pressure.", "rank": 2},
            ),
            mutations=(
                {"name": "Speed Demon", "use": "Yes", "reason": "Mobility."},
                {"name": "Marsupial", "use": "Optional", "reason": "Mobility + carry."},
            ),
            gear={
                "weapons": ["Holy Fire", "Gatling Plasma", "Cremator"],
                "armor": ["Civil Engineer Armor", "Union PA (variant)"],
                "weapon_effects": ["Anti-Armor", "Vampire's", "Furious"],
                "armor_effects": ["Powered", "Sentinel's", "Ghoul-friendly defensive rolls"],
                "ammo_consumables": ["Glowing Blood", "Toxic Goo", "Psychobuff"],
                "weapon_mods": ["Conductors"],
            },
            variants={
                "PA Ghoul": ["Stabilized stack", "Union PA"],
                "Non-PA Ghoul": ["Civil Engineer", "Action Ghoul + Glowing One stack"],
            },
            swap_cards={"Travel": ["Marsupial maintenance"]},
            extra_assumptions=(
                "Cannot use Unyielding armor (Ghoul restriction).",
                "Ghouls use Glow and the Feral meter as resources; Rad Sponge and Ghoulish are restricted for playable ghouls.",
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
            aliases=("cremator", "pyro", "pyromaniac", "holy fire"),
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
                ("one_gun_army", 3, "Utility", "Cripple/stagger support on heavy hits."),
                ("batteries_included", 3, "Economy", "Energy ammo weight."),
            ),
            optional_perk_picks=(
                ("science_monster", 3, "Ghoul Variant", "Glow-based damage option for ghoul pyromaniacs."),
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
                ("glowing_one", 2, "Team Glow", "Team Glow support."),
                ("hyper_reflexes", 3, "Speed", "Action speed while feral."),
                ("action_ghoul", 3, "AP", "AP regen while feral."),
                ("class_freak", 3, "Mutations", "Reduce mutation downsides."),
            ),
            optional_perk_picks=(
                ("glowing_hunter", 1, "Damage", "Marked target damage stack (ghoul; PER swap-in)."),
            ),
            legendary_perks=(
                {"name": "Follow Through", "priority": "Required", "reason": "Sneak amp + ghoul stealth synergy.", "rank": 4},
                {"name": "Action Diet", "priority": "Recommended", "reason": "Keeps the Feral meter controlled during events.", "rank": 3},
                {"name": "Legendary Agility", "priority": "Recommended", "reason": "AP throughput.", "rank": 2},
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
                "armor_effects": ["Powered", "Sentinel's", "Ghoul-friendly defensive rolls"],
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
                ("radioactive_strength", 3, "Damage", "Glow-fueled power attack and bash damage."),
                ("class_freak", 3, "Mutation", "Reduce mutation downsides."),
            ),
            optional_perk_picks=(
                ("brick_wall", 1, "Defense", "Stagger immunity while Glow is high."),
                ("wound_salter", 3, "Damage", "+30% vs bleeding (STR swap-in)."),
                ("battle_genes", 2, "Mutation", "Mutation damage stack (STR swap-in)."),
                ("blocker", 3, "Defense", "Melee damage taken reduction."),
                ("hyper_reflexes", 3, "Speed", "Action speed while feral."),
            ),
            legendary_perks=(
                {"name": "Hack and Slash", "priority": "Required", "reason": "Shockwave on melee hits.", "rank": 4},
                {"name": "Retribution", "priority": "Required", "reason": "Reflect damage taken as fire.", "rank": 4},
                {"name": "Feral Rage", "priority": "Recommended", "reason": "Reduces Glow costs while feral.", "rank": 3},
                {"name": "Legendary Strength", "priority": "Recommended", "reason": "Hard-cap on melee scaling.", "rank": 2},
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
                "armor_effects": ["Powered", "Sentinel's", "Ghoul-friendly defensive rolls"],
                "ammo_consumables": ["Glowing Blood", "Adrenal Reaction food", "Psychobuff"],
                "weapon_mods": ["Furious"],
            },
            variants={
                "Feral Ghoul Melee": ["Feral Rage legendary perk", "Hyper Reflexes", "Brick Wall"],
                "Full-health Ghoul Melee": ["Powered defensive armor"],
            },
            swap_cards={"Defense": ["Blocker"], "Events": ["Strange in Numbers"]},
            extra_assumptions=(
                "Cannot use Unyielding armor (Ghoul restriction).",
                "Glow + Feral state stack with melee damage via Radioactive Strength and Feral Rage.",
            ),
            weaknesses=(
                "Cannot use Unyielding.",
                "Limited at range.",
                "Bosses with knockback or toxic AoE.",
            ),
        ),
        ArchetypeBlueprint(
            archetype_id="xp_leveling_fallback",
            build_name="XP / Leveling Build",
            aliases=("xp", "leveling", "xp farm"),
            special_allocation={
                "Strength": 3,
                "Perception": 15,
                "Endurance": 3,
                "Charisma": 3,
                "Intelligence": 15,
                "Agility": 8,
                "Luck": 9,
            },
            perk_picks=(
                ("commando", 3, "Damage", "Core automatic rifle damage."),
                ("expert_commando", 3, "Damage", "Stacks automatic rifle damage."),
                ("master_commando", 3, "Damage", "Completes auto rifle damage stack."),
                ("tank_killer", 2, "Armor Pen", "Patch 62: 40% armor ignore for all ranged."),
                ("concentrated_fire", 3, "VATS", "Stacking accuracy + damage."),
                ("better_criticals", 3, "Criticals", "Big VATS crit damage."),
                ("critical_savvy", 3, "Criticals", "Reduced crit meter consumption."),
                ("grim_reapers_sprint", 1, "AP regen", "VATS kills restore AP."),
            ),
            legendary_perks=(
                {"name": "Legendary Intelligence", "priority": "Required", "reason": "Max INT for XP gain.", "rank": 4},
                {"name": "Legendary Luck", "priority": "Recommended", "reason": "Crit meter throughput.", "rank": 2},
                {"name": "Follow Through", "priority": "Recommended", "reason": "Damage support while leveling.", "rank": 2},
            ),
            mutations=(
                {"name": "Egg Head", "use": "Yes", "reason": "Intelligence boost for XP and crafting utility."},
                {"name": "Herd Mentality", "use": "Yes", "reason": "SPECIAL boost while grouped."},
                {"name": "Speed Demon", "use": "Yes", "reason": "Reload and mobility."},
            ),
            gear={
                "weapons": ["The Fixer", "Handmade Rifle", "V63 Laser Carbine"],
                "armor": ["Secret Service Armor", "Civil Engineer Armor"],
                "weapon_effects": ["Anti-Armor", "Quad", "Vampire's"],
                "armor_effects": ["Overeater's"],
                "ammo_consumables": ["Company Tea", "Cranberry Relish"],
            },
            variants={
                "Heavy Gunner XP": ["Switch to Heavy Gunner baseline if preferred."],
            },
            swap_cards={"XP Events": ["Inspirational"]},
            weaknesses=("Lower peak DPS than dedicated combat builds.",),
            extra_assumptions=(
                "XP / Leveling is a goal overlay, so the engine used the closest combat archetype and emphasized Intelligence/XP support.",
                "Preferred team context: Casual public team.",
            ),
        ),
        ArchetypeBlueprint(
            archetype_id="crafting_utility_fallback",
            build_name="Crafting / Utility Build",
            aliases=("crafting", "utility", "camp", "vendor"),
            special_allocation={
                "Strength": 6,
                "Perception": 6,
                "Endurance": 6,
                "Charisma": 9,
                "Intelligence": 15,
                "Agility": 6,
                "Luck": 8,
            },
            perk_picks=(
                ("commando", 3, "Damage", "Combat shell for playability."),
                ("tank_killer", 2, "Armor Pen", "Basic ranged support."),
            ),
            optional_perk_picks=(
                ("demolition_expert", 5, "Crafting", "Explosive crafting support."),
            ),
            legendary_perks=(
                {"name": "Ammo Factory", "priority": "Required", "reason": "Ammo crafting.", "rank": 1},
                {"name": "Master Infiltrator", "priority": "Recommended", "reason": "Lockpicking/hacking convenience.", "rank": 1},
                {"name": "Legendary Intelligence", "priority": "Recommended", "reason": "Crafting/XP overlap.", "rank": 2},
            ),
            mutations=(
                {"name": "Speed Demon", "use": "Optional", "reason": "Mobility."},
            ),
            gear={
                "weapons": ["The Fixer", "Handmade Rifle"],
                "armor": ["Secret Service Armor"],
                "weapon_effects": ["Anti-Armor", "Vampire's"],
                "armor_effects": ["Overeater's"],
            },
            variants={
                "Crafting Focus": ["Ammo Factory swap-in"],
            },
            swap_cards={"Crafting": ["Weapon Artisan", "Fix It Good"], "Selling": ["Hard Bargain"]},
            weaknesses=("Not optimized for boss DPS.",),
            extra_assumptions=(
                "Crafting / Utility is a non-combat loadout; combat performance is secondary.",
            ),
        ),
        ArchetypeBlueprint(
            archetype_id="enclave_flamer",
            build_name="Enclave Plasma Flamer",
            aliases=("enclave flamer", "enclave plasma flamer", "enclave plasma"),
            special_allocation={
                "Strength": 3,
                "Perception": 15,
                "Endurance": 5,
                "Charisma": 3,
                "Intelligence": 5,
                "Agility": 12,
                "Luck": 13,
            },
            perk_picks=(
                ("rifleman", 3, "Damage", "Enclave Flamer scales with Rifleman perks."),
                ("expert_rifleman", 3, "Damage", "Stacks Rifleman damage for Enclave Flamer."),
                ("master_rifleman", 3, "Damage", "Completes Rifleman stack."),
                ("tank_killer", 2, "Armor Pen", "All ranged armor ignore."),
                ("concentrated_fire", 3, "VATS", "Stacking VATS accuracy/damage."),
                ("better_criticals", 3, "Criticals", "VATS crit damage."),
                ("critical_savvy", 3, "Criticals", "Reduced crit meter consumption."),
                ("grim_reapers_sprint", 1, "AP regen", "VATS kills restore AP."),
            ),
            optional_perk_picks=(
                ("gun_fu", 3, "VATS", "Target swap with damage bonus (swap-in for mob clear)."),
            ),
            legendary_perks=(
                {"name": "Follow Through", "priority": "Recommended", "reason": "Sneak-amplified damage for close-range burst.", "rank": 4},
                {"name": "Taking One for the Team", "priority": "Recommended", "reason": "Team damage amp in boss fights.", "rank": 4},
                {"name": "Legendary Luck", "priority": "Recommended", "reason": "Crit meter throughput.", "rank": 2},
                {"name": "Legendary Perception", "priority": "Recommended", "reason": "Frees PER base points.", "rank": 2},
            ),
            mutations=(
                {"name": "Speed Demon", "use": "Yes", "reason": "Reload and mobility."},
                {"name": "Eagle Eyes", "use": "Yes", "reason": "Crit damage + Perception."},
                {"name": "Marsupial", "use": "Yes", "reason": "Mobility + carry weight."},
            ),
            gear={
                "weapons": ["Enclave Plasma Rifle (Aligned Flamer Barrel)", "Enclave Plasma Rifle (True Flamer Barrel)"],
                "armor": ["Secret Service Armor", "Union Power Armor (PA variant)"],
                "weapon_effects": ["Furious", "Bloodied", "Anti-Armor", "Vampire's"],
                "second_star": ["Faster Fire Rate (Rapid)"],
                "third_star": ["Breaks 50% Slower", "25% Less VATS AP Cost"],
                "armor_effects": ["Unyielding (Bloodied)", "Overeater's (+40 max HP/piece)"],
                "weapon_mods": ["Prime Capacitor", "Aligned Flamer Barrel (VATS)", "True Flamer Barrel (ADS)"],
                "ammo_consumables": ["Ultracite Plasma Cartridges", "Overdrive", "Psychobuff", "Blight Soup"],
                "underarmor": ["Shielded Casual (PER, INT, LCK)", "Shielded Raider (PER, AGI, LCK)"],
            },
            variants={
                "Bloodied Flamer": ["Unyielding armor", "Nerd Rage", "Adrenal Reaction"],
                "Full-health Flamer": ["Overeater's", "Vampire's for sustain"],
                "PA Flamer": ["Union PA", "Stabilized for accuracy"],
            },
            swap_cards={"Bosses": ["Concentrated Fire"], "Events": ["Gun Fu"]},
            weaknesses=(
                "Very short range; must be in melee range of enemies.",
                "High AP cost in VATS; consider ADS for sustained damage.",
                "Weapon breaks quickly; Repair Kit stacking recommended.",
                "Enclave Plasma Rifle and mods are difficult to acquire.",
            ),
            extra_assumptions=(
                "Enclave Plasma Flamer scales with Rifleman perks, not Heavy Gunner.",
                "Aligned Flamer Barrel preferred for VATS builds; True Flamer Barrel for ADS.",
                "Prime Capacitor recommended for damage boost.",
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
    playstyle = (inp.primary_playstyle or "").strip()

    # Primary playstyle dropdown values take priority.
    if playstyle == "XP / Leveling":
        return "xp_leveling_fallback"
    if playstyle == "Crafting / Utility":
        return "crafting_utility_fallback"

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
    # Enclave flamer disambiguation: "enclave" + "flamer"/"plasma" routes to
    # enclave_flamer; generic "cremator", "holy fire", "pyro", or bare "flamer"
    # routes to cremator_pyro.
    if "enclave" in text and ("flamer" in text or "plasma" in text):
        return "enclave_flamer"
    if "cremator" in text or "holy fire" in text or "pyro" in text or "pyromaniac" in text:
        return "cremator_pyro"
    if "flamer" in text:
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
        "Live baseline as of May 6 2026: Patch 62 (CAMP Revamp) plus the April 21 2026 update.",
        "April 28 2026 maintenance is recorded as no build-impact (status-bar display fix only).",
        "Protect Appalachia / Patch 68 PTS notes are tracked as future-facing context only and excluded from live defaults.",
        # Backwoods (March 2026) confirmed changes:
        "March 2026 (Backwoods): Legendary Perks no longer require Perk Coins to unequip.",
        f"March 2026 (Backwoods): {OVEREATERS_NOTE}",
        "March 2026 (Backwoods): 4-star legendary mods available from Bigfoot boss encounters.",
        "March 2026 (Backwoods): Armor resistance standardization; all armor types now provide energy, fire, cryo, poison, and radiation resistance.",
        # April 2026 changes:
        "April 21 2026: armor durability buffed; explosions retain more damage on indirect hits and vs high-resist enemies.",
        "April 21 2026: Demolition Expert + explosive bobbleheads now correctly factored into self-damage math.",
        "April 21 2026: Fancy Pump-Action Shotgun + Fancy Single-Action Revolver pivoted to stealth (smaller cone while sneaking, +25% reload, +10% fire rate, +10% AP cost, lower durability).",
        "April 21 2026: Fierce 2-star legendary mod normalized in cost; locked-mod consumption exploit closed.",
        # Build defaults:
        "Assumes default full-health unless the user selects bloodied.",
        LEGENDARY_PERK_STRATEGY_NOTE,
    ]
    base.extend(extra)
    return base


def _normalize_mutation_name(name: str) -> str:
    normalized = re.sub(r"\s+", " ", name.strip()).lower()
    for known in MUTATION_DETAILS:
        if known.lower() == normalized:
            return known
    return name.strip()


def _selected_mutation_names(blueprint: ArchetypeBlueprint, user: BuildInput) -> list[str]:
    preference = (user.mutation_preference or "").strip()
    if preference.lower().startswith("no mutations"):
        return []

    # User-specified mutations take priority.
    if preference.lower().startswith("specific mutations:"):
        names: list[str] = []
        raw_names = preference.split(":", 1)[1].split(",")
        for raw_name in raw_names:
            name = _normalize_mutation_name(raw_name)
            if name and name not in names:
                names.append(name)
        return names

    # Default: merge archetype-defined mutations + universal core.
    # Order: archetype-specific first (higher priority), then universal.
    names = []
    for mutation in blueprint.mutations:
        name = str(mutation.get("name", "")).strip()
        if name and name not in names:
            names.append(name)
    for mutation in UNIVERSAL_MUTATIONS:
        name = str(mutation.get("name", "")).strip()
        if name and name not in names:
            names.append(name)

    # Add VATS mutations for VATS-oriented archetypes.
    is_vats = any(
        kw in blueprint.archetype_id
        for kw in ("commando", "rifleman", "gunslinger", "bow", "pepper_shaker", "enclave_flamer")
    )
    if is_vats:
        for mutation in VATS_MUTATIONS:
            name = str(mutation.get("name", "")).strip()
            if name and name not in names:
                names.append(name)

    # Add melee mutations for melee archetypes.
    if "melee" in blueprint.archetype_id:
        for mutation in MELEE_MUTATIONS:
            name = str(mutation.get("name", "")).strip()
            if name and name not in names:
                names.append(name)

    # Add bloodied mutations if the build name or user input suggests bloodied.
    if "bloodied" in blueprint.build_name.lower() or user.health_model == "Bloodied":
        for mutation in BLOODIED_MUTATIONS:
            name = str(mutation.get("name", "")).strip()
            if name and name not in names:
                names.append(name)

    # Filter out conflicts: Grounded is harmful for energy weapon builds.
    if "energy" in user.primary_weapon_type.lower():
        names = [n for n in names if n != "Grounded"]

    return names


def _uses_mutations(blueprint: ArchetypeBlueprint, user: BuildInput) -> bool:
    return bool(_selected_mutation_names(blueprint, user))


def _mutation_recommendations(blueprint: ArchetypeBlueprint, user: BuildInput) -> List[Dict[str, str]]:
    preference = (user.mutation_preference or "").strip()
    is_no_mutations = preference.lower().startswith("no mutations")

    if is_no_mutations:
        return []

    specific_request = preference.lower().startswith("specific mutations:")
    names = _selected_mutation_names(blueprint, user)
    if not names:
        return []

    blueprint_by_name = {
        str(mutation.get("name", "")).strip().lower(): dict(mutation)
        for mutation in blueprint.mutations
    }
    # Also index the expanded pools for default builds.
    for pool in (UNIVERSAL_MUTATIONS, VATS_MUTATIONS, BLOODIED_MUTATIONS, MELEE_MUTATIONS, TANK_MUTATIONS):
        for mutation in pool:
            key = str(mutation.get("name", "")).strip().lower()
            if key not in blueprint_by_name:
                blueprint_by_name[key] = dict(mutation)

    recommendations: List[Dict[str, str]] = []
    seen_names: set[str] = set()
    for name in names:
        if name in seen_names:
            continue
        seen_names.add(name)
        recommendation = blueprint_by_name.get(name.lower(), {})
        details = MUTATION_DETAILS.get(name, {})
        if specific_request:
            recommendation["use"] = "Requested"
        recommendation["name"] = name
        recommendation.setdefault("use", "Recommended")
        recommendation.setdefault("reason", details.get("reason", "Recommended for optimized builds."))
        recommendation.setdefault("support", details.get("support", "Class Freak + Starched Genes"))
        if name == "Adrenal Reaction" and user.health_model == "Full health":
            recommendation["use"] = "Requested / bloodied variant" if specific_request else "Variant"
            recommendation["reason"] = "Best for bloodied or low-health variants; optional on full-health builds."
        if name == "Grounded" and "energy" in user.primary_weapon_type.lower():
            recommendation["reason"] = "Requested, but watch the energy weapon damage penalty on energy weapons."
        recommendations.append(recommendation)
    return recommendations


def _mutation_support_picks(blueprint: ArchetypeBlueprint, user: BuildInput) -> tuple[tuple[str, int, str, str], ...]:
    if not _uses_mutations(blueprint, user):
        return ()
    picks = list(MUTATION_SUPPORT_PERK_PICKS)
    if user.team_preference != "Solo":
        picks.append(TEAM_MUTATION_SUPPORT_PICK)
    return tuple(picks)


def _rank_cost(card: PerkCard, rank: int) -> int | None:
    return card.rank_costs.get(rank)


def _is_context_allowed_for_completion(card: PerkCard, blueprint: ArchetypeBlueprint, *, uses_mutations: bool) -> bool:
    is_ghoul = blueprint.archetype_id in GHOUL_ARCHETYPES
    tags = set(card.tags)
    families = set(card.build_families)
    if "mutation" in tags and not uses_mutations:
        return False
    if "ghoul_only" in tags and not is_ghoul:
        return False
    if is_ghoul and card.id in GHOUL_RESTRICTED_PERK_IDS:
        return False
    allowed_families: set[str] = set()
    if "heavy" in blueprint.archetype_id or "cremator" in blueprint.archetype_id:
        allowed_families.add("heavy")
    if "commando" in blueprint.archetype_id:
        allowed_families.add("commando")
    if "rifleman" in blueprint.archetype_id or "bow" in blueprint.archetype_id:
        allowed_families.add("rifleman")
    if "gunslinger" in blueprint.archetype_id:
        allowed_families.add("gunslinger")
    if "shotgun" in blueprint.archetype_id or "pepper_shaker" in blueprint.archetype_id:
        allowed_families.add("shotgunner")
    if "melee" in blueprint.archetype_id:
        allowed_families.add("melee")
    if is_ghoul:
        allowed_families.add("ghoul")
    exclusive_families = {"commando", "rifleman", "gunslinger", "shotgunner", "melee"}
    if families.intersection(exclusive_families) and not families.intersection(allowed_families):
        return False
    if card.bloodied_synergy and "Bloodied" not in blueprint.build_name:
        return False
    is_stealth_build = "stealth" in blueprint.archetype_id or "Stealth" in blueprint.build_name
    if (card.stealth_synergy or "stealth" in tags) and not is_stealth_build:
        return False
    is_vats_build = any(
        keyword in blueprint.archetype_id
        for keyword in ("commando", "rifleman", "gunslinger", "bow", "pepper_shaker")
    )
    if card.vats_synergy and not is_vats_build:
        return False
    return True


def _is_basic_allowed_for_completion(card: PerkCard, blueprint: ArchetypeBlueprint, *, uses_mutations: bool) -> bool:
    is_ghoul = blueprint.archetype_id in GHOUL_ARCHETYPES
    tags = set(card.tags)
    if "mutation" in tags and not uses_mutations:
        return False
    if "ghoul_only" in tags and not is_ghoul:
        return False
    if is_ghoul and card.id in GHOUL_RESTRICTED_PERK_IDS:
        return False
    if card.bloodied_synergy and "Bloodied" not in blueprint.build_name:
        return False
    return True


def _completion_score(
    card: PerkCard,
    blueprint: ArchetypeBlueprint,
    selected_tag_context: set[str],
    *,
    uses_mutations: bool,
) -> int:
    score = 10
    families = set(card.build_families)
    tags = set(card.tags)
    if blueprint.archetype_id in families:
        score += 100
    if blueprint.archetype_id in GHOUL_ARCHETYPES and "ghoul" in families:
        score += 90
    if "heavy" in families and "heavy" in blueprint.archetype_id:
        score += 65
    if families.intersection({"commando", "rifleman", "gunslinger", "shotgunner", "melee"}):
        if any(family in blueprint.archetype_id for family in families):
            score += 65
    score += 8 * len(tags.intersection(selected_tag_context))
    if "defense" in tags or "utility" in tags or "mutation" in tags:
        score += 12
    if "mutation" in tags and uses_mutations:
        score += 45
    if "damage" in tags:
        score += 8
    if card.crafting_or_swap_only:
        score -= 80
    return score


def _best_completion_choices(candidates: list[tuple[int, str, int, int, str, str]], remaining: int) -> list[tuple[str, int, str, str]]:
    """Choose one rank per candidate card to exactly fill the remaining cost."""
    grouped: dict[str, list[tuple[int, str, int, int, str, str]]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate[1], []).append(candidate)

    # cost -> (score, choices)
    dp: dict[int, tuple[int, list[tuple[str, int, str, str]]]] = {0: (0, [])}
    for card_id, options in grouped.items():
        next_dp = dict(dp)
        for current_cost, (current_score, current_choices) in dp.items():
            for score, _, rank, cost, role, why in options:
                new_cost = current_cost + cost
                if new_cost > remaining:
                    continue
                new_score = current_score + score
                new_choices = current_choices + [(card_id, rank, role, why)]
                previous = next_dp.get(new_cost)
                if previous is None or new_score > previous[0]:
                    next_dp[new_cost] = (new_score, new_choices)
        dp = next_dp
    return dp.get(remaining, (0, []))[1]


def _complete_special_allocations(
    blueprint: ArchetypeBlueprint,
    user: BuildInput,
    perks_by_id: dict[str, PerkCard],
    selected: list[PerkChoice],
    spent_per_special: dict[str, int],
) -> None:
    uses_mutations = _uses_mutations(blueprint, user)
    selected_ids = {choice.card_id for choice in selected}
    selected_tag_context = {
        tag
        for choice in selected
        if (card := perks_by_id.get(choice.card_id)) is not None
        for tag in card.tags
    }

    for special in SPECIALS:
        budget = blueprint.special_allocation.get(special, 0)
        remaining = budget - spent_per_special.get(special, 0)
        if remaining <= 0:
            continue

        def _build_candidates(*, strict: bool) -> list[tuple[int, str, int, int, str, str]]:
            built: list[tuple[int, str, int, int, str, str]] = []
            for card in perks_by_id.values():
                if card.special != special or card.id in selected_ids:
                    continue
                allowed = (
                    _is_context_allowed_for_completion(card, blueprint, uses_mutations=uses_mutations)
                    if strict
                    else _is_basic_allowed_for_completion(card, blueprint, uses_mutations=uses_mutations)
                )
                if not allowed:
                    continue
                base_score = _completion_score(
                    card,
                    blueprint,
                    selected_tag_context,
                    uses_mutations=uses_mutations,
                )
                if not strict:
                    base_score -= 35
                for rank in range(card.max_rank, 0, -1):
                    cost = _rank_cost(card, rank)
                    if cost is None or cost > remaining:
                        continue
                    role = "Completion"
                    why = f"Fills the {special} allocation for a complete playable loadout."
                    # Score by point value so a strong rank-3 fit beats three
                    # weak rank-1 fillers that merely happen to add up.
                    built.append((base_score * cost + cost - 25, card.id, rank, cost, role, why))
            return built

        candidates = _build_candidates(strict=True)
        choices = _best_completion_choices(candidates, remaining)
        if not choices:
            choices = _best_completion_choices(_build_candidates(strict=False), remaining)

        for card_id, rank, role, why in choices:
            card = perks_by_id[card_id]
            cost = _rank_cost(card, rank)
            if cost is None:
                continue
            selected_ids.add(card_id)
            spent_per_special[special] += cost
            selected.append(PerkChoice(card_id=card_id, rank=rank, role=role, why=why))


def _materialize_picks(blueprint: ArchetypeBlueprint, user: BuildInput) -> tuple[List[PerkChoice], Dict[str, List[PerkChoice]]]:
    perks_by_id = {p.id: p for p in load_active_perks()}
    spent_per_special: Dict[str, int] = {k: 0 for k in SPECIALS}
    selected: List[PerkChoice] = []
    selected_ids: set[str] = set()

    def _try_add(card_id: str, rank: int, role: str, why: str, *, optional: bool) -> None:
        if card_id in selected_ids:
            return
        card = perks_by_id.get(card_id)
        if card is None:
            return
        cost = _rank_cost(card, rank)
        if cost is None:
            return
        budget = blueprint.special_allocation.get(card.special, 0)
        if spent_per_special[card.special] + cost > budget:
            return
        spent_per_special[card.special] += cost
        selected_ids.add(card_id)
        selected.append(PerkChoice(card_id=card_id, rank=rank, role=role, why=why))

    for card_id, rank, role, why in blueprint.perk_picks:
        _try_add(card_id, rank, role, why, optional=False)

    for card_id, rank, role, why in blueprint.optional_perk_picks:
        _try_add(card_id, rank, role, why, optional=True)

    for card_id, rank, role, why in _mutation_support_picks(blueprint, user):
        _try_add(card_id, rank, role, why, optional=True)

    _complete_special_allocations(blueprint, user, perks_by_id, selected, spent_per_special)

    by_special: Dict[str, List[PerkChoice]] = {k: [] for k in SPECIALS}
    for choice in selected:
        card = perks_by_id.get(choice.card_id)
        if card is not None:
            by_special[card.special].append(choice)
    return selected, by_special


def _build_from_blueprint(blueprint: ArchetypeBlueprint, user: BuildInput) -> GeneratedBuild:
    selected, by_special = _materialize_picks(blueprint, user)
    sources = list_sources()
    return GeneratedBuild(
        id=f"build-{uuid4().hex[:12]}",
        build_name=blueprint.build_name,
        user_inputs=user,
        assumptions=_build_assumptions(blueprint.extra_assumptions),
        special_allocation=dict(blueprint.special_allocation),
        perk_cards_by_special=by_special,
        legendary_perks=[dict(lp) for lp in blueprint.legendary_perks],
        mutations=_mutation_recommendations(blueprint, user),
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


def _apply_revision_intent_archetype(archetype: str, user: BuildInput) -> str:
    """Reroute archetype based on temporary revision_intent modifiers."""
    intent = user.revision_intent
    if intent == "avoid_power_armor" and archetype == "power_armor_heavy_energy":
        return "bullet_storm_heavy"
    if intent == "avoid_bloodied" and archetype == "melee":
        return "onslaught_commando"
    return archetype


def get_baseline_for_inputs(user: BuildInput) -> GeneratedBuild:
    """Produce a deterministic baseline build for hybrid mode.

    Applies revision_intent routing, XP/Leveling and Crafting/Utility
    fallback templates, and records intent assumptions.
    """
    archetype = classify(user)
    archetype = _apply_revision_intent_archetype(archetype, user)
    blueprint = _BLUEPRINTS.get(archetype)
    if blueprint is None:
        raise NotImplementedError(f"Archetype '{archetype}' is not yet supported.")

    build = _build_from_blueprint(blueprint, user)

    # Add revision_intent assumptions
    if user.revision_intent == "more_damage":
        build.assumptions.append(
            "revision_intent=more_damage: Prefer offense-focused perk allocation where valid. "
            "Favor damage/crit/scaling perks over QOL. Do not violate survivability hard rules."
        )
    elif user.revision_intent == "more_tanky":
        build.assumptions.append(
            "revision_intent=more_tanky: Prefer defensive allocation. "
            "Increase survivability emphasis through Endurance, Agility, defensive perks, and defensive Legendary Perks where valid."
        )
    elif user.revision_intent == "avoid_power_armor":
        build.assumptions.append(
            "revision_intent=avoid_power_armor: Power Armor treated as excluded for this request only."
        )
    elif user.revision_intent == "avoid_bloodied":
        build.assumptions.append(
            "revision_intent=avoid_bloodied: Bloodied/Low Health treated as excluded for this request only."
        )

    return build


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def should_use_brain() -> bool:
    raw_use_brain = os.getenv("USE_OLLAMA_BRAIN")
    if raw_use_brain is None:
        return bool(os.getenv("OLLAMA_API_KEY"))
    return raw_use_brain.strip().lower() in {"1", "true", "yes", "on"}


def prepare_build_for_response(user: BuildInput) -> GeneratedBuild:
    """Return a fast deterministic build and mark brain work for background use."""
    build = generate_build(user)
    issues = validate_build(build)
    build.validation_status = "passed" if not issues else "issues"
    if should_use_brain():
        build.brain_status = "pending"
        build.brain_updated_at = _now_utc()
        build.brain_notes.append("Brain refinement queued in the background.")
    return build


def refine_saved_build_with_brain(build_id: str) -> None:
    """Refine a saved build with Ollama and persist the result.

    Build generation must stay responsive, so background brain failures are
    stored on the build instead of escaping as API request failures.
    """
    build = get_build(build_id)
    if build is None:
        logger.warning("brain refinement requested for missing build id=%s", build_id)
        return

    build.brain_status = "running"
    build.brain_error = None
    build.brain_updated_at = _now_utc()
    save_build(build)

    issues = validate_build(build)
    try:
        enhance_build_with_brain(
            build.user_inputs,
            build,
            issues,
            use_web_search=_env_bool("OLLAMA_BUILD_WEB_SEARCH", False),
        )
        new_issues = validate_build(build)
        build.validation_status = "passed" if not new_issues else "issues"
        build.brain_status = "complete"
        build.brain_error = None
    except Exception as exc:  # BrainError or unexpected provider failure
        message = str(exc)
        logger.warning("brain refinement failed for build id=%s: %s", build_id, message)
        build.brain_status = "failed"
        build.brain_error = message
        build.validation_status = "passed" if not issues else "issues"
        build.brain_notes.append(f"Brain refinement failed: {message}")
    finally:
        build.brain_updated_at = _now_utc()
        save_build(build)


def generate_and_refine_build(user: BuildInput, max_retries: int = 2) -> GeneratedBuild:
    """Generate a build, optionally refining it with the Ollama brain.

    The deterministic engine is the default so local app usage does not require
    an Ollama API key. Brain enhancement runs when USE_OLLAMA_BRAIN=1 or an
    OLLAMA_API_KEY is present; set USE_OLLAMA_BRAIN=0 to force deterministic
    generation even when a key is available.
    """
    build = generate_build(user)
    issues = validate_build(build)

    if not should_use_brain():
        build.validation_status = "passed" if not issues else "issues"
        return build

    for _ in range(max(1, max_retries)):
        enhance_build_with_brain(user, build, issues, use_web_search=_env_bool("OLLAMA_BUILD_WEB_SEARCH", False))
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

    for special in SPECIALS:
        picks = build.perk_cards_by_special.get(special, [])
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
        if spent < budget:
            issues.append(f"{special} underfilled ({spent} < {budget})")

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
        selected_restricted = []
        for picks in build.perk_cards_by_special.values():
            for pick in picks:
                if pick.card_id in GHOUL_RESTRICTED_PERK_IDS:
                    card = perks_by_id.get(pick.card_id)
                    selected_restricted.append(card.name if card else pick.card_id)
        for name in selected_restricted:
            issues.append(f"Ghoul build conflict: {name} is restricted for Playable Ghoul characters.")
        for lp in build.legendary_perks:
            name = str(lp.get("name", ""))
            if name.lower() in GHOUL_RESTRICTED_LEGENDARY_NAMES:
                issues.append(f"Ghoul build conflict: {name} is restricted for Playable Ghoul characters.")

    return issues


def compare_builds(builds: list[GeneratedBuild]) -> CompareResult:
    legendary_perk_diff = {
        b.id: [str(lp.get("name", "")) for lp in b.legendary_perks]
        for b in builds
    }
    mutation_diff = {
        b.id: [str(m.get("name", "")) for m in b.mutations]
        for b in builds
    }
    gear_diff = {
        b.id: {
            k: v if isinstance(v, list) else [str(v)]
            for k, v in b.gear.items()
        }
        for b in builds
    }

    # Generate concise tradeoff summary.
    tradeoffs: list[str] = []
    if len(builds) >= 2:
        names = [b.build_name for b in builds]
        tradeoffs.append(f"Comparing: {', '.join(names)}.")
        # SPECIAL total comparison.
        for b in builds:
            total = sum(b.special_allocation.values())
            tradeoffs.append(f"{b.build_name}: {total} SPECIAL points allocated.")
        # Perk count comparison.
        for b in builds:
            perk_count = sum(len(picks) for picks in b.perk_cards_by_special.values())
            tradeoffs.append(f"{b.build_name}: {perk_count} perk cards selected.")
        # Mutation count comparison.
        for b in builds:
            tradeoffs.append(f"{b.build_name}: {len(b.mutations)} mutations recommended.")

    return CompareResult(
        build_ids=[b.id for b in builds],
        special_diff={b.id: b.special_allocation for b in builds},
        core_perk_diff={
            b.id: [p.card_id for cards in b.perk_cards_by_special.values() for p in cards]
            for b in builds
        },
        legendary_perk_diff=legendary_perk_diff,
        mutation_diff=mutation_diff,
        gear_diff=gear_diff,
        tradeoff_summary=tradeoffs,
    )
