from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    official = "official"
    database = "database"
    wiki = "wiki"
    guide = "guide"
    community = "community"


class Status(str, Enum):
    verified = "verified"
    uncertain = "uncertain"
    deprecated = "deprecated"
    conflicting = "conflicting"


class PerkCard(BaseModel):
    id: str
    name: str
    special: str
    max_rank: int
    rank_costs: Dict[int, int]
    effect_by_rank: Dict[int, str]
    level_required: int
    tags: List[str]
    build_families: List[str]
    power_armor_only: bool = False
    regular_armor_only: bool = False
    bloodied_synergy: bool = False
    full_health_synergy: bool = False
    vats_synergy: bool = False
    stealth_synergy: bool = False
    heavy_weapon_synergy: bool = False
    energy_weapon_synergy: bool = False
    explosive_synergy: bool = False
    melee_synergy: bool = False
    support_synergy: bool = False
    crafting_or_swap_only: bool = False
    source_url: str
    source_name: str
    source_type: SourceType
    last_verified_date: date
    patch_version: str
    status: Status


class SourceRecord(BaseModel):
    id: str
    source_name: str
    source_url: str
    source_type: SourceType
    date_accessed: date
    relevant_patch: Optional[str] = None
    summary: str
    reliability_score: float = Field(ge=0, le=1)
    notes: str = ""


class BuildInput(BaseModel):
    character_level: str = "50+"
    primary_playstyle: str = "Power Armor Heavy"
    primary_weapon_type: str = "Heavy energy"
    preferred_weapons: str = "Gatling Plasma, Gatling Laser"
    armor_type: str = "Power Armor"
    health_model: str = "Full health"
    combat_style: str = "Balanced"
    team_preference: str = "Public team"
    mutation_preference: str = "Use mutations"
    qol_preference: str = "Balanced"
    legendary_perk_availability: str = "Some"
    current_gear: str = ""
    avoid_list: str = ""
    use_ai_provider: bool = False
    ai_prompt: str = ""


class PerkChoice(BaseModel):
    card_id: str
    rank: int
    role: str
    why: str


class GeneratedBuild(BaseModel):
    id: str
    build_name: str
    user_inputs: BuildInput
    assumptions: List[str]
    special_allocation: Dict[str, int]
    perk_cards_by_special: Dict[str, List[PerkChoice]]
    legendary_perks: List[Dict[str, str]]
    mutations: List[Dict[str, str]]
    gear: Dict[str, List[str]]
    variants: Dict[str, List[str]]
    swap_cards: Dict[str, List[str]]
    weaknesses: List[str]
    validation_status: str
    source_verification_notes: List[str]
    created_at: datetime


class CompareRequest(BaseModel):
    build_ids: List[str] = Field(min_length=2, max_length=4)


class CompareResult(BaseModel):
    build_ids: List[str]
    special_diff: Dict[str, Dict[str, int]]
    core_perk_diff: Dict[str, List[str]]