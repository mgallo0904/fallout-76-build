from __future__ import annotations
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

class SourceType(str, Enum):
    official="official"
    database="database"
    wiki="wiki"
    guide="guide"
    community="community"

class Status(str, Enum):
    verified="verified"
    uncertain="uncertain"
    deprecated="deprecated"
    conflicting="conflicting"

class GenerationMode(str, Enum):
    deterministic="deterministic"
    llm="llm"
    hybrid="hybrid"

class PerkCard(BaseModel):
    id: str
    name: str
    special: str
    max_rank: int
    rank_costs: Dict[int,int]
    effect_by_rank: Dict[int,str]
    level_required: int
    tags: List[str]
    build_families: List[str]
    character_restriction: Literal["Any", "Human", "Ghoul"] = "Any"
    power_armor_only: bool=False
    regular_armor_only: bool=False
    bloodied_synergy: bool=False
    full_health_synergy: bool=False
    vats_synergy: bool=False
    stealth_synergy: bool=False
    heavy_weapon_synergy: bool=False
    energy_weapon_synergy: bool=False
    explosive_synergy: bool=False
    melee_synergy: bool=False
    support_synergy: bool=False
    crafting_or_swap_only: bool=False
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
    relevant_patch: Optional[str]=None
    summary: str
    reliability_score: float = Field(ge=0,le=1)
    notes: str=""

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
    legendary_perk_availability: str = ""
    legendary_loadout: List[Dict[str, Any]] = Field(default_factory=list)
    current_gear: str = ""
    avoid_list: str = ""
    character_type: Literal["Human", "Ghoul"] = "Human"
    goal: str | None = None
    revision_intent: Literal["more_damage", "more_tanky", "avoid_power_armor", "avoid_bloodied"] | None = None

class BuildCandidate(BaseModel):
    build_name: str = ""
    special_allocation: Dict[str, int] = Field(default_factory=dict)
    perk_cards_by_special: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    legendary_perks: List[Dict[str, Any]] = Field(default_factory=list)
    mutations: List[Dict[str, str]] = Field(default_factory=list)
    gear: Dict[str, List[str]] = Field(default_factory=dict)
    variants: Dict[str, List[str]] = Field(default_factory=dict)
    swap_cards: Dict[str, List[str]] = Field(default_factory=dict)
    assumptions: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    reasoning_summary: str = ""

class WebSearchRequest(BaseModel):
    query: str = Field(min_length=2)
    max_results: int = Field(default=5, ge=1, le=10)


class WebSearchResult(BaseModel):
    title: str
    url: str
    content: str = ""


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
    special_allocation: Dict[str,int]
    perk_cards_by_special: Dict[str,List[PerkChoice]]
    legendary_perks: List[Dict[str,str|int]]
    mutations: List[Dict[str,str]]
    gear: Dict[str,List[str]]
    variants: Dict[str,List[str]]
    swap_cards: Dict[str,List[str]]
    weaknesses: List[str]
    validation_status: str
    source_verification_notes: List[str]
    created_at: datetime | None = Field(default_factory=datetime.now)
    logic_engine: str = "deterministic"
    generation_mode: GenerationMode = GenerationMode.deterministic
    repair_notes: List[str] = Field(default_factory=list)
    brain_notes: List[str] = Field(default_factory=list)
    web_search_results: List[WebSearchResult] = Field(default_factory=list)
    brain_confirmed: bool = False
    brain_status: str = "not_requested"
    brain_error: Optional[str] = None
    brain_updated_at: Optional[datetime] = None
    brain_suggested_swaps: List[Dict[str,str]] = Field(default_factory=list)
    brain_override_reasoning: List[str] = Field(default_factory=list)
    legendary_perk_rank_changes: List[Dict[str,str|int]] = Field(default_factory=list)

class ArchetypeSummary(BaseModel):
    id: str
    name: str


class ArchetypePreview(BaseModel):
    id: str
    name: str
    aliases: List[str]
    special_allocation: Dict[str, int]
    perk_picks: List[Dict[str, str]]
    optional_perk_picks: List[Dict[str, str]] = Field(default_factory=list)
    legendary_perks: List[Dict[str, str|int]] = Field(default_factory=list)
    gear: Dict[str, List[str]] = Field(default_factory=dict)
    weaknesses: List[str] = Field(default_factory=list)
    extra_assumptions: List[str] = Field(default_factory=list)


class CompareRequest(BaseModel):
    build_ids: List[str] = Field(min_length=2, max_length=4)

class CompareResult(BaseModel):
    build_ids: List[str]
    special_diff: Dict[str, Dict[str, int]]
    core_perk_diff: Dict[str, List[str]]
