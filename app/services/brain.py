from __future__ import annotations

from dataclasses import dataclass
import json
import os
import urllib.error
import urllib.request
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.models import BuildInput, GeneratedBuild, SourceRecord, WebSearchResult


DEFAULT_MODEL = 'kimi-k2.6:cloud'
DEFAULT_WEB_SEARCH_URL = 'https://ollama.com/api/web_search'


class BrainError(RuntimeError):
    """Raised when the optional Ollama brain cannot complete a request."""


@dataclass(frozen=True)
class BrainConfig:
    enabled: bool
    model: str
    base_url: str
    api_key: str | None
    web_search_enabled: bool
    web_search_url: str
    timeout_seconds: float
    max_search_results: int

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


class BuildEnhancement(BaseModel):
    build_name: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    legendary_perks: list[dict[str, str]] = Field(default_factory=list)
    mutations: list[dict[str, str]] = Field(default_factory=list)
    gear: dict[str, list[str]] = Field(default_factory=dict)
    variants: dict[str, list[str]] = Field(default_factory=dict)
    swap_cards: dict[str, list[str]] = Field(default_factory=dict)
    weaknesses: list[str] = Field(default_factory=list)
    brain_notes: list[str] = Field(default_factory=list)


class ResearchDigest(BaseModel):
    summary: str = ''
    conflicts_or_uncertain: list[str] = Field(default_factory=list)
    recommended_followups: list[str] = Field(default_factory=list)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def get_brain_config() -> BrainConfig:
    api_key = os.getenv('OLLAMA_API_KEY') or None
    default_base_url = 'https://ollama.com' if api_key else 'http://localhost:11434'
    base_url = os.getenv('OLLAMA_BASE_URL') or os.getenv('OLLAMA_HOST') or default_base_url
    enabled = _env_bool('USE_OLLAMA_BRAIN', bool(api_key))
    return BrainConfig(
        enabled=enabled,
        model=os.getenv('OLLAMA_MODEL', DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        base_url=base_url.rstrip('/'),
        api_key=api_key,
        web_search_enabled=_env_bool('OLLAMA_WEB_SEARCH', bool(api_key)),
        web_search_url=os.getenv('OLLAMA_WEB_SEARCH_URL', DEFAULT_WEB_SEARCH_URL).rstrip('/'),
        timeout_seconds=_env_float('OLLAMA_TIMEOUT_SECONDS', 35.0, 1.0, 180.0),
        max_search_results=_env_int('OLLAMA_MAX_SEARCH_RESULTS', 5, 1, 10),
    )


def brain_status() -> dict[str, Any]:
    cfg = get_brain_config()
    return {
        'enabled': cfg.enabled,
        'model': cfg.model,
        'base_url': cfg.base_url,
        'has_api_key': cfg.has_api_key,
        'web_search_enabled': cfg.web_search_enabled,
        'web_search_url': cfg.web_search_url,
        'max_search_results': cfg.max_search_results,
    }


def api_url(base_url: str, path: str) -> str:
    root = base_url.rstrip('/')
    if root.endswith('/api'):
        return f'{root}{path}'
    return f'{root}/api{path}'


def post_json(url: str, payload: dict[str, Any], api_key: str | None, timeout_seconds: float) -> dict[str, Any]:
    body = json.dumps(payload, default=str).encode('utf-8')
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    request = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode('utf-8')
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')[:500]
        raise BrainError(f'Ollama HTTP {exc.code}: {detail}') from exc
    except urllib.error.URLError as exc:
        raise BrainError(f'Ollama connection failed: {exc.reason}') from exc
    except TimeoutError as exc:
        raise BrainError('Ollama request timed out') from exc

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BrainError(f'Ollama returned invalid JSON: {exc}') from exc


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith('```'):
        lines = [line for line in stripped.splitlines() if not line.strip().startswith('```')]
        stripped = '\n'.join(lines).strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find('{')
        end = stripped.rfind('}')
        if start < 0 or end <= start:
            raise BrainError('Ollama response did not contain a JSON object')
        try:
            parsed = json.loads(stripped[start:end + 1])
        except json.JSONDecodeError as exc:
            raise BrainError(f'Ollama response JSON could not be parsed: {exc}') from exc

    if not isinstance(parsed, dict):
        raise BrainError('Ollama response JSON must be an object')
    return parsed


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


def _chat_json(messages: list[dict[str, str]], cfg: BrainConfig) -> dict[str, Any]:
    response = post_json(
        api_url(cfg.base_url, '/chat'),
        {
            'model': cfg.model,
            'messages': messages,
            'stream': False,
            'format': 'json',
        },
        cfg.api_key,
        cfg.timeout_seconds,
    )
    message = response.get('message', {})
    content = message.get('content') if isinstance(message, dict) else None
    if not content:
        content = response.get('response')
    if not isinstance(content, str) or not content.strip():
        raise BrainError('Ollama chat returned no message content')
    return extract_json_object(content)


def _build_search_query(user: BuildInput) -> str:
    return ' '.join(
        part
        for part in [
            'Fallout 76 April 21 2026 patch perk card build meta',
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
                'and perk-card build generator. The current live game state is Patch 62 '
                '(CAMP Revamp / Season 22) plus the April 21 2026 update. Key 2026 facts: '
                'armor durability buffed; explosions retain more damage on indirect hits and '
                'against high-resist enemies; Demolition Expert + explosive bobbleheads now '
                'count in self-damage math; Fancy Pump-Action Shotgun and Fancy Single-Action '
                'Revolver pivoted to a stealth niche (smaller cone while sneaking, +25% reload, '
                '+10% fire rate, +10% AP cost, lower durability); Playable Ghouls cannot equip '
                'Unyielding and use radiation/glow as resources; Bows scale with Rifleman perks. '
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
                        'Improve the build recommendation around assumptions, legendary perks, '
                        'mutations, gear, variants, swap cards, weaknesses, and notes. '
                        'The response JSON schema is: build_name optional string, assumptions '
                        'array[string], legendary_perks array[object string values], mutations '
                        'array[object string values], gear object[array[string]], variants '
                        'object[array[string]], swap_cards object[array[string]], weaknesses '
                        'array[string], brain_notes array[string].'
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


def enhance_build_with_brain(
    user: BuildInput,
    build: GeneratedBuild,
    validation_issues: list[str],
) -> dict[str, Any]:
    cfg = get_brain_config()
    if not cfg.enabled:
        build.logic_engine = 'deterministic'
        return {
            'enabled': False,
            'model': cfg.model,
            'web_search_enabled': cfg.web_search_enabled,
            'search_results': 0,
            'notes': [],
        }

    notes: list[str] = []
    search_results: list[WebSearchResult] = []
    if cfg.web_search_enabled:
        try:
            search_results = web_search(_build_search_query(user), cfg.max_search_results, cfg)
            build.web_search_results = search_results
            notes.append(f'Ollama web search returned {len(search_results)} result(s).')
        except BrainError as exc:
            notes.append(f'Ollama web search unavailable: {exc}')

    try:
        raw = _chat_json(_build_prompt(user, build, validation_issues, search_results), cfg)
        enhancement = BuildEnhancement.model_validate(raw)
    except (BrainError, ValidationError) as exc:
        build.logic_engine = 'deterministic'
        build.brain_notes.extend(notes)
        build.brain_notes.append(f'Ollama brain unavailable: {exc}')
        return {
            'enabled': True,
            'model': cfg.model,
            'web_search_enabled': cfg.web_search_enabled,
            'search_results': len(search_results),
            'notes': build.brain_notes,
            'error': str(exc),
        }

    _apply_enhancement(build, enhancement)
    build.logic_engine = f'ollama:{cfg.model}'
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
    if cfg.enabled:
        try:
            raw = _chat_json(
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
        'enabled': cfg.enabled,
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
    if cfg.enabled:
        try:
            raw = _chat_json(
                [
                    {
                        'role': 'system',
                        'content': (
                            'You are kimi-k2.6:cloud summarizing live Fallout 76 patch and meta '
                            'information for a build generator. The current live game state is '
                            'Patch 62 + the April 21 2026 update. Return only JSON matching: '
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
        'enabled': cfg.enabled,
        'model': cfg.model,
        'query': query,
        'web_search_enabled': cfg.web_search_enabled,
        'search_results': [r.model_dump(mode='json') for r in search_results],
        'summary': digest.summary,
        'conflicts_or_uncertain': digest.conflicts_or_uncertain,
        'recommended_followups': digest.recommended_followups,
        'notes': notes,
    }
