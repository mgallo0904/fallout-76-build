from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.models import BuildCandidate, BuildInput, GeneratedBuild, PerkCard, SourceRecord, WebSearchResult
from app.services.ollama_client import (
    BrainConfig,
    BrainError,
    DEFAULT_MODEL,
    DEFAULT_WEB_SEARCH_URL,
    api_url,
    chat_json,
    env_bool,
    get_brain_config,
    post_json,
    extract_json_object,
)
from app.services.prompting import build_ollama_prompt
from app.services.llm_builder import generate_llm_candidate

# Re-export for compatibility
_extract_json_object = extract_json_object


class BuildEnhancement(BaseModel):
    build_name: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    legendary_perks: list[dict[str, str|int]] = Field(default_factory=list)
    mutations: list[dict[str, str]] = Field(default_factory=list)
    gear: dict[str, list[str]] = Field(default_factory=dict)
    variants: dict[str, list[str]] = Field(default_factory=dict)
    swap_cards: dict[str, list[str]] = Field(default_factory=dict)
    weaknesses: list[str] = Field(default_factory=list)
    brain_notes: list[str] = Field(default_factory=list)
    confirmed_picks: list[str] = Field(default_factory=list)
    suggested_swaps: list[dict[str, str]] = Field(default_factory=list)
    overrides: list[dict[str, str]] = Field(default_factory=list)
    override_reasoning: list[str] = Field(default_factory=list)
    legendary_perk_rank_changes: list[dict[str, str|int]] = Field(default_factory=list)


class ResearchDigest(BaseModel):
    summary: str = ''
    conflicts_or_uncertain: list[str] = Field(default_factory=list)
    recommended_followups: list[str] = Field(default_factory=list)


def brain_status() -> dict[str, Any]:
    try:
        cfg = get_brain_config()
        return {
            'enabled': True,
            'model': cfg.model,
            'base_url': cfg.base_url,
            'has_api_key': cfg.has_api_key,
            'web_search_enabled': cfg.web_search_enabled,
            'web_search_url': cfg.web_search_url,
            'max_search_results': cfg.max_search_results,
        }
    except BrainError:
        return {
            'enabled': False,
            'model': DEFAULT_MODEL,
            'base_url': 'https://ollama.com',
            'has_api_key': False,
            'web_search_enabled': False,
            'web_search_url': DEFAULT_WEB_SEARCH_URL,
            'max_search_results': 5,
        }


def web_search(query: str, max_results: int | None = None, cfg: BrainConfig | None = None) -> list[WebSearchResult]:
    cfg = cfg or get_brain_config()
    if not cfg.web_search_enabled:
        return []
    if not cfg.api_key:
        raise BrainError('OLLAMA_API_KEY is required for Ollama web search')

    limit = max(1, min(10, max_results or cfg.max_search_results))
    response = post_json(
        cfg.web_search_url,
        {'query': query, 'max_results': limit},
        cfg.api_key,
        cfg.timeout_seconds,
    )
    results = response.get('results', [])
    if not isinstance(results, list):
        raise BrainError('Ollama web search returned an unexpected response shape')
    return [WebSearchResult.model_validate(result) for result in results]


def _build_search_query(user: BuildInput) -> str:
    return ' '.join(
        part
        for part in [
            'Fallout 76 May 6 2026 live patch perk card build meta',
            user.primary_playstyle,
            user.primary_weapon_type,
            user.preferred_weapons,
            user.armor_type,
            user.health_model,
        ]
        if part
    )


def _build_prompt(
    user: BuildInput,
    build: GeneratedBuild,
    validation_issues: list[str],
    search_results: list[WebSearchResult],
) -> list[dict[str, str]]:
    baseline = build.model_dump(mode='json')
    baseline.pop('id', None)
    baseline.pop('created_at', None)
    return [
        {
            'role': 'system',
            'content': (
                'You are kimi-k2.6:cloud acting as the logic engine for a Fallout 76 SPECIAL '
                'and perk-card build generator. The current live game state is May 6 2026: '
                'Patch 62 (CAMP Revamp / Season 22) plus the April 21 2026 update; '
                'the April 28 2026 maintenance has no build impact, and Patch 68 / '
                'Protect Appalachia PTS notes must not be applied to live defaults. Key 2026 facts: '
                'armor durability buffed; explosions retain more damage on indirect hits and '
                'against high-resist enemies; Demolition Expert + explosive bobbleheads now '
                'count in self-damage math; Fancy Pump-Action Shotgun and Fancy Single-Action '
                'Revolver pivoted to a stealth niche (smaller cone while sneaking, +25% reload, '
                '+10% fire rate, +10% AP cost, lower durability); Playable Ghouls cannot equip '
                'Unyielding, cannot use restricted hunger/rad perks such as Rad Sponge, '
                'Ghoulish, Radicool, Thirst Quencher, Natural Resistance, or What Rads?, '
                'and use Glow/Feral meter as resources; Bows scale with Rifleman perks. '
                'Return only compact JSON matching the requested schema. Preserve the '
                'deterministic core perk IDs and SPECIAL allocation; you may only refine '
                'narrative fields (assumptions, gear, mutations, weaknesses, notes, variants, '
                'swap_cards, legendary_perks, build_name). Never invent source claims; treat '
                'web search snippets as unverified unless multiple trusted Fallout 76 sources '
                'agree.'
            ),
        },
        {
            'role': 'user',
            'content': json.dumps(
                {
                    'task': (
                        'Evaluate the deterministic build against live web search evidence. '
                        'Confirm core perk picks or suggest overrides with reasoning. '
                        'Evaluate legendary perk ranks (1-4) against current meta and suggest rank changes. '
                        'The response JSON schema is: build_name optional string, assumptions '
                        'array[string], legendary_perks array[object with name, priority, reason, rank int 1-4], mutations '
                        'array[object string values], gear object[array[string]], variants '
                        'object[array[string]], swap_cards object[array[string]], weaknesses '
                        'array[string], brain_notes array[string], confirmed_picks array[string], '
                        'suggested_swaps array[object with from_card_id, to_card_id, reason], '
                        'overrides array[object with field, old_value, new_value, reason], '
                        'override_reasoning array[string], legendary_perk_rank_changes array[object with name, rank int, reason].'
                    ),
                    'user_inputs': user.model_dump(mode='json'),
                    'deterministic_baseline': baseline,
                    'validation_issues': validation_issues,
                    'web_search_results': [result.model_dump(mode='json') for result in search_results],
                },
                default=str,
            ),
        },
    ]


def _apply_enhancement(build: GeneratedBuild, enhancement: BuildEnhancement) -> None:
    if enhancement.build_name:
        build.build_name = enhancement.build_name[:160]
    if enhancement.assumptions:
        build.assumptions = enhancement.assumptions[:12]
    if enhancement.legendary_perks:
        build.legendary_perks = enhancement.legendary_perks[:8]
    if enhancement.mutations:
        build.mutations = enhancement.mutations[:8]
    if enhancement.gear:
        build.gear = enhancement.gear
    if enhancement.variants:
        build.variants = enhancement.variants
    if enhancement.swap_cards:
        build.swap_cards = enhancement.swap_cards
    if enhancement.weaknesses:
        build.weaknesses = enhancement.weaknesses[:12]
    if enhancement.brain_notes:
        build.brain_notes.extend(enhancement.brain_notes[:10])
    if enhancement.confirmed_picks:
        build.brain_notes.append(f'Confirmed picks: {", ".join(enhancement.confirmed_picks)}')
    if enhancement.suggested_swaps:
        build.brain_suggested_swaps = enhancement.suggested_swaps[:12]
    if enhancement.overrides:
        build.brain_suggested_swaps.extend(enhancement.overrides[:8])
    if enhancement.override_reasoning:
        build.brain_override_reasoning = enhancement.override_reasoning[:8]
    if enhancement.legendary_perk_rank_changes:
        build.legendary_perk_rank_changes = enhancement.legendary_perk_rank_changes[:8]
        for change in build.legendary_perk_rank_changes:
            name = str(change.get('name', ''))
            new_rank = change.get('rank')
            for lp in build.legendary_perks:
                if lp.get('name') == name and isinstance(new_rank, int):
                    lp['rank'] = new_rank


def enhance_build_with_brain(
    user: BuildInput,
    build: GeneratedBuild,
    validation_issues: list[str],
    *,
    use_web_search: bool | None = None,
) -> dict[str, Any]:
    cfg = get_brain_config()

    notes: list[str] = []
    search_results: list[WebSearchResult] = []
    should_search = cfg.web_search_enabled if use_web_search is None else (use_web_search and cfg.web_search_enabled)
    if should_search:
        try:
            search_results = web_search(_build_search_query(user), cfg.max_search_results, cfg)
            build.web_search_results = search_results
            notes.append(f'Ollama web search returned {len(search_results)} result(s).')
        except BrainError as exc:
            notes.append(f'Ollama web search unavailable: {exc}')

    try:
        raw = chat_json(_build_prompt(user, build, validation_issues, search_results), cfg)
        enhancement = BuildEnhancement.model_validate(raw)
    except (BrainError, ValidationError) as exc:
        raise BrainError(f'Brain enhancement failed: {exc}') from exc

    _apply_enhancement(build, enhancement)
    build.logic_engine = f'ollama:{cfg.model}'
    build.brain_confirmed = True
    if notes:
        build.brain_notes.extend(notes)
    build.brain_notes.append('Build recommendation refined by Ollama logic engine.')
    return {
        'enabled': True,
        'model': cfg.model,
        'web_search_enabled': cfg.web_search_enabled,
        'search_results': len(search_results),
        'notes': build.brain_notes,
    }


def research_digest(sources: list[SourceRecord]) -> dict[str, Any]:
    cfg = get_brain_config()
    query = 'Fallout 76 latest perk card changes Power Armor Heavy Energy Gunner build'
    notes: list[str] = []
    search_results: list[WebSearchResult] = []

    if cfg.web_search_enabled:
        try:
            search_results = web_search(query, cfg.max_search_results, cfg)
            notes.append(f'Ollama web search returned {len(search_results)} result(s).')
        except BrainError as exc:
            notes.append(f'Ollama web search unavailable: {exc}')

    digest = ResearchDigest()
    try:
        raw = chat_json(
            [
                {
                    'role': 'system',
                    'content': (
                        'You summarize Fallout 76 source freshness for a build generator. '
                        'Return only JSON matching: summary string, conflicts_or_uncertain '
                        'array[string], recommended_followups array[string].'
                    ),
                },
                {
                    'role': 'user',
                    'content': json.dumps(
                        {
                            'known_sources': [s.model_dump(mode='json') for s in sources],
                            'web_search_results': [r.model_dump(mode='json') for r in search_results],
                        },
                        default=str,
                    ),
                },
            ],
            cfg,
        )
        digest = ResearchDigest.model_validate(raw)
        notes.append('Research digest refined by Ollama logic engine.')
    except (BrainError, ValidationError) as exc:
        notes.append(f'Ollama research digest unavailable: {exc}')

    return {
        'enabled': True,
        'model': cfg.model,
        'web_search_enabled': cfg.web_search_enabled,
        'search_results': [r.model_dump(mode='json') for r in search_results],
        'summary': digest.summary,
        'conflicts_or_uncertain': digest.conflicts_or_uncertain,
        'recommended_followups': digest.recommended_followups,
        'notes': notes,
    }


def research_patch_digest(query: str, max_results: int | None = None) -> dict[str, Any]:
    """Run a grounded web pull + LLM summary for an arbitrary Fallout 76 query.

    Used by the /api/brain/research endpoint to refresh patch / meta context on
    demand using kimi-k2.6:cloud and Ollama Web Search.
    """
    cfg = get_brain_config()
    notes: list[str] = []
    search_results: list[WebSearchResult] = []

    if cfg.web_search_enabled:
        try:
            search_results = web_search(query, max_results, cfg)
            notes.append(f'Ollama web search returned {len(search_results)} result(s).')
        except BrainError as exc:
            notes.append(f'Ollama web search unavailable: {exc}')

    digest = ResearchDigest()
    try:
        raw = chat_json(
            [
                {
                    'role': 'system',
                    'content': (
                        'You are kimi-k2.6:cloud summarizing live Fallout 76 patch and meta '
                        'information for a build generator. The current live game state is '
                        'May 6 2026 live baseline: Patch 62 + the April 21 2026 update; '
                        'April 28 maintenance has no build impact; exclude Patch 68 / Protect Appalachia PTS from live defaults. '
                        'Return only JSON matching: '
                        'summary string, conflicts_or_uncertain array[string], '
                        'recommended_followups array[string]. Cite only material that '
                        'appears in the provided web search results.'
                    ),
                },
                {
                    'role': 'user',
                    'content': json.dumps(
                        {
                            'query': query,
                            'web_search_results': [
                                r.model_dump(mode='json') for r in search_results
                            ],
                        },
                        default=str,
                    ),
                },
            ],
            cfg,
        )
        digest = ResearchDigest.model_validate(raw)
        notes.append('Patch digest refined by Ollama logic engine.')
    except (BrainError, ValidationError) as exc:
        notes.append(f'Ollama patch digest unavailable: {exc}')

    return {
        'enabled': True,
        'model': cfg.model,
        'query': query,
        'web_search_enabled': cfg.web_search_enabled,
        'search_results': [r.model_dump(mode='json') for r in search_results],
        'summary': digest.summary,
        'conflicts_or_uncertain': digest.conflicts_or_uncertain,
        'recommended_followups': digest.recommended_followups,
        'notes': notes,
    }


def sanity_filter_candidate(
    candidate: BuildCandidate,
    allowed_legendary_names: set[str],
    allowed_mutation_names: set[str],
) -> BuildCandidate:
    """
    Drop hallucinated/illegal Legendary Perks and mutations from an LLM candidate.
    Append brain_notes explaining each drop.
    """
    notes: list[str] = []

    cleaned_legendary: list[dict[str, object]] = []
    for lp in candidate.legendary_perks:
        name = str(lp.get("name", ""))
        if name in allowed_legendary_names:
            cleaned_legendary.append(dict(lp))
        else:
            notes.append(f"Sanity filter dropped unknown/hallucinated legendary perk: {name}.")
    candidate.legendary_perks = cleaned_legendary

    cleaned_mutations: list[dict[str, str]] = []
    for m in candidate.mutations:
        name = str(m.get("name", ""))
        if name in allowed_mutation_names:
            cleaned_mutations.append(dict(m))
        else:
            notes.append(f"Sanity filter dropped unknown/hallucinated mutation: {name}.")
    candidate.mutations = cleaned_mutations

    # What Rads? brain note per plan specification
    for lp in candidate.legendary_perks:
        if str(lp.get("name", "")).lower() == "what rads?":
            notes.append(
                "What Rads? has known Ghoul transformation behavior caveats in Bethesda's Ghoul Within notes. "
                "Verify in-game behavior before treating it as final for this character."
            )
            break

    # Attach notes to candidate via assumptions ( consumed by pipeline )
    if notes:
        candidate.assumptions.extend(notes)
    return candidate


def generate_build_candidate(
    user: BuildInput,
    allowed_perks: list[PerkCard],
    allowed_legendary_perks: list[PerkCard],
    allowed_mutation_names: set[str],
) -> BuildCandidate:
    """
    Generate a full build candidate using the Ollama brain.

    Uses the strict prompt builder and the LLM builder with one retry.
    Applies sanity filtering before returning.
    """
    messages = build_ollama_prompt(user, allowed_perks, allowed_legendary_perks)
    candidate = generate_llm_candidate(messages, max_retries=1)
    allowed_legendary_names = {p.name for p in allowed_legendary_perks}
    return sanity_filter_candidate(candidate, allowed_legendary_names, allowed_mutation_names)
