from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional, Set


class ValidationError(ValueError):
    """Raised when model validation fails."""


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNCERTAIN = "uncertain"
    DEPRECATED = "deprecated"
    RENAMED = "renamed"
    CONFLICTING = "conflicting"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


PERK_TAGS: Set[str] = {
    "heavy_weapon", "energy_weapon", "ballistic_weapon", "explosive", "commando", "rifleman", "shotgun", "pistol",
    "melee", "bow", "vats", "crit", "stealth", "power_armor", "regular_armor", "bloodied", "full_health", "team",
    "solo", "mutation", "crafting", "carry_weight", "ammo", "repair", "vendor", "xp",
}

ALLOWED_CONTEXTS: Set[str] = {
    "Power Armor", "Regular Armor", "Full Health", "Bloodied", "Solo", "Team", "VATS", "Non-VATS", "Stealth", "Loud Combat",
}

SPECIAL_CATEGORIES: Set[str] = {"Strength", "Perception", "Endurance", "Charisma", "Intelligence", "Agility", "Luck"}
PERK_CARD_TYPES: Set[str] = {"Combat", "Defense", "Utility", "Crafting", "Quality of Life", "Mutation Support", "Power Armor", "VATS / Crit", "Team Support", "Swap-only"}


def _ensure(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


@dataclass(slots=True)
class MetadataBase:
    source_records: List[str] = field(default_factory=list)
    last_verified_date: Optional[date] = None
    verified_against_patch: Optional[str] = None
    status: VerificationStatus = VerificationStatus.UNCERTAIN
    confidence_score: float = 0.5
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        _ensure(0.0 <= self.confidence_score <= 1.0, "confidence_score must be between 0 and 1")


@dataclass(slots=True)
class SourceRecord:
    source_id: str
    source_type: str
    title: str
    url: Optional[str]
    retrieved_at: datetime
    reliability_score: float
    excerpt: Optional[str] = None

    def __post_init__(self) -> None:
        _ensure(self.source_type in {"official_patch_notes", "datamine", "community_testing", "manual_entry"}, "invalid source_type")
        _ensure(0.0 <= self.reliability_score <= 1.0, "reliability_score must be between 0 and 1")


@dataclass(slots=True)
class PatchRecord:
    patch_id: str
    game_version: str
    release_date: date
    title: str
    summary: str
    source_record_ids: List[str] = field(default_factory=list)


@dataclass(slots=True)
class SpecialAllocation:
    strength: int
    perception: int
    endurance: int
    charisma: int
    intelligence: int
    agility: int
    luck: int

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            _ensure(1 <= value <= 15, f"{name} must be in range [1, 15]")


@dataclass(slots=True)
class PerkCardMetadata(MetadataBase):
    perk_id: str = ""
    canonical_name: str = ""
    display_name: str = ""
    previous_names: List[str] = field(default_factory=list)
    special_category: str = ""
    max_rank: int = 1
    rank_costs: Dict[int, int] = field(default_factory=dict)
    effect_by_rank: Dict[int, str] = field(default_factory=dict)
    level_required: int = 1
    card_type: str = "Combat"
    tags: List[str] = field(default_factory=list)
    allowed_contexts: List[str] = field(default_factory=list)
    excluded_contexts: List[str] = field(default_factory=list)
    synergy_cards: List[str] = field(default_factory=list)
    conflicting_cards: List[str] = field(default_factory=list)
    recommended_rank_default: int = 1
    recommended_rank_min: int = 1
    recommended_rank_max: int = 1
    core_for_archetypes: List[str] = field(default_factory=list)
    optional_for_archetypes: List[str] = field(default_factory=list)
    swap_card_only: bool = False
    power_armor_only: bool = False
    regular_armor_only: bool = False
    low_health_synergy: bool = False
    full_health_synergy: bool = False
    vats_synergy: bool = False
    non_vats_synergy: bool = False
    stealth_synergy: bool = False

    def __post_init__(self) -> None:
        MetadataBase.__post_init__(self)
        _ensure(self.special_category in SPECIAL_CATEGORIES, "invalid special_category")
        _ensure(self.card_type in PERK_CARD_TYPES, "invalid card_type")
        _ensure(1 <= self.max_rank <= 5, "max_rank must be in range [1, 5]")
        _ensure(self.level_required >= 1, "level_required must be >= 1")
        _ensure(set(self.tags).issubset(PERK_TAGS), "invalid perk tag")
        _ensure(set(self.allowed_contexts).issubset(ALLOWED_CONTEXTS), "invalid allowed context")
        expected = set(range(1, self.max_rank + 1))
        _ensure(set(self.rank_costs) == expected, "rank_costs keys must match 1..max_rank")
        _ensure(set(self.effect_by_rank) == expected, "effect_by_rank keys must match 1..max_rank")
        _ensure(self.recommended_rank_min <= self.recommended_rank_default <= self.recommended_rank_max <= self.max_rank, "invalid recommended rank bounds")


@dataclass(slots=True)
class LegendaryPerkMetadata(MetadataBase):
    legendary_perk_id: str = ""
    canonical_name: str = ""
    max_rank: int = 1
    unlock_level_or_slot_requirement: str = ""
    effect_by_rank: Dict[int, str] = field(default_factory=dict)
    perk_coin_cost_by_rank: Dict[int, int] = field(default_factory=dict)
    role: str = "Damage"
    build_tags: List[str] = field(default_factory=list)
    required_for_archetypes: List[str] = field(default_factory=list)
    recommended_for_archetypes: List[str] = field(default_factory=list)
    optional_for_archetypes: List[str] = field(default_factory=list)
    conflicts_or_redundancies: List[str] = field(default_factory=list)
    requires_power_armor: bool = False
    works_best_with: Dict[str, List[str]] = field(default_factory=dict)


@dataclass(slots=True)
class MutationMetadata(MetadataBase):
    mutation_id: str = ""
    canonical_name: str = ""
    positive_effects: List[str] = field(default_factory=list)
    negative_effects: List[str] = field(default_factory=list)
    supported_build_types: List[str] = field(default_factory=list)
    bad_for_build_types: List[str] = field(default_factory=list)
    required: bool = False


@dataclass(slots=True)
class WeaponMetadata(MetadataBase):
    weapon_id: str = ""
    canonical_name: str = ""
    weapon_class: str = ""
    tags: List[str] = field(default_factory=list)


@dataclass(slots=True)
class ArmorMetadata(MetadataBase):
    armor_id: str = ""
    canonical_name: str = ""
    armor_class: str = "armor"
    tags: List[str] = field(default_factory=list)


@dataclass(slots=True)
class LegendaryEffectMetadata(MetadataBase):
    effect_id: str = ""
    canonical_name: str = ""
    star_tier: int = 1
    applicable_to: List[str] = field(default_factory=list)


@dataclass(slots=True)
class ArchetypeMetadata(MetadataBase):
    archetype_id: str = ""
    canonical_name: str = ""
    description: str = ""
    core_tags: List[str] = field(default_factory=list)


@dataclass(slots=True)
class BuildVariant:
    variant_id: str
    label: str
    contexts: List[str] = field(default_factory=list)
    perk_overrides: Dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class SwapCardLoadout:
    loadout_id: str
    purpose: str
    cards: List[str] = field(default_factory=list)


@dataclass(slots=True)
class UserPreferenceProfile:
    profile_id: str
    playstyle_tags: List[str] = field(default_factory=list)
    preferred_contexts: List[str] = field(default_factory=list)
    disallowed_contexts: List[str] = field(default_factory=list)


@dataclass(slots=True)
class ValidationIssue:
    code: str
    message: str
    severity: Severity
    path: Optional[str] = None


@dataclass(slots=True)
class ValidationResult:
    validation_id: str
    build_id: str
    passed: bool
    checked_at: datetime
    issues: List[ValidationIssue] = field(default_factory=list)


@dataclass(slots=True)
class ConfidenceUncertainty:
    object_type: str
    object_id: str
    confidence_score: float
    uncertainty_reason: Optional[str] = None
    requires_manual_review: bool = False

    def __post_init__(self) -> None:
        _ensure(0.0 <= self.confidence_score <= 1.0, "confidence_score must be between 0 and 1")


@dataclass(slots=True)
class GeneratedBuild:
    build_id: str
    build_name: str
    archetype_id: str
    special_allocation: SpecialAllocation
    perk_cards: List[str] = field(default_factory=list)
    legendary_perks: List[str] = field(default_factory=list)
    mutations: List[str] = field(default_factory=list)
    weapons: List[str] = field(default_factory=list)
    armor: List[str] = field(default_factory=list)
    legendary_effects: List[str] = field(default_factory=list)
    variants: List[BuildVariant] = field(default_factory=list)
    swap_card_loadouts: List[SwapCardLoadout] = field(default_factory=list)
    preference_profile_id: Optional[str] = None
    validation_results: List[ValidationResult] = field(default_factory=list)
    confidence_tracking: List[ConfidenceUncertainty] = field(default_factory=list)
    source_record_ids: List[str] = field(default_factory=list)
    patch_record_ids: List[str] = field(default_factory=list)
