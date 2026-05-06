from __future__ import annotations

import json
from typing import Any

from app.models import BuildInput, PerkCard


def summarize_effect(perk: PerkCard) -> str:
    """
    Return a compact prompt-safe effect summary for a Legendary Perk.
    Prefer rank 4 text because it represents full investment.
    Prefix with 'Rank 4:' so Kimi understands this is the max-rank effect.
    If rank 4 is missing, use the highest available rank and mark it.
    """
    if 4 in perk.effect_by_rank and perk.effect_by_rank[4]:
        return f"Rank 4: {perk.effect_by_rank[4]}"
    highest = max((k for k in perk.effect_by_rank if perk.effect_by_rank[k]), default=None)
    if highest is not None:
        return f"Highest verified rank {highest}: {perk.effect_by_rank[highest]}"
    return "Effect summary unavailable; use source data only."


def _compact_perk(perk: PerkCard) -> dict[str, Any]:
    return {
        "id": perk.id,
        "name": perk.name,
        "special": perk.special,
        "max_rank": perk.max_rank,
        "rank_costs": perk.rank_costs,
        "tags": perk.tags,
        "character_restriction": perk.character_restriction,
    }


def _compact_legendary_perk(perk: PerkCard) -> dict[str, Any]:
    return {
        "id": perk.id,
        "name": perk.name,
        "max_rank": perk.max_rank,
        "character_restriction": perk.character_restriction,
        "effect_summary": summarize_effect(perk),
    }


def build_ollama_prompt(
    user: BuildInput,
    allowed_perks: list[PerkCard],
    allowed_legendary_perks: list[PerkCard],
) -> list[dict[str, str]]:
    """
    Construct the strict prompt for Kimi with:
    - Rules (only allowed_perks, legal ranks, legal SPECIAL budgets).
    - User input JSON.
    - Allowed perks compact list.
    - Allowed legendary perks compact list with summarize_effect().
    - Return schema.
    """
    rules = (
        "You are kimi-k2.6:cloud acting as a constrained build generator for Fallout 76. "
        "You must return ONLY compact JSON matching the requested schema. "
        "Rules:\n"
        "1. Use ONLY perk IDs from the allowed_perks list. Do not invent perk IDs.\n"
        "2. Every perk rank must be <= max_rank for that perk.\n"
        "3. Total card cost per SPECIAL column must not exceed the special_allocation for that column.\n"
        "4. Respect character_restriction on perks: Ghoul-only perks cannot be used by Human characters.\n"
        "5. Respect build synergies: do not pick bloodied perks for full-health builds, "
        "power_armor_only perks for non-PA builds, stealth perks for non-VATS/non-stealth builds.\n"
        "6. Choose a playable, balanced build.\n"
        "7. Legendary perks must come from the allowed_legendary_perks list.\n"
        "8. Mutations must be from the known Fallout 76 mutation pool.\n"
    )

    return [
        {
            "role": "system",
            "content": rules,
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": (
                        "Generate a complete Fallout 76 build candidate. "
                        "The response JSON schema is: build_name string, "
                        "special_allocation object[string -> int 1-15], "
                        "perk_cards_by_special object[string -> array[object with card_id, rank, role, why]], "
                        "legendary_perks array[object with name, rank int 1-4, reason], "
                        "mutations array[object with name, use, reason], "
                        "gear object[array[string]], variants object[array[string]], "
                        "swap_cards object[array[string]], assumptions array[string], "
                        "weaknesses array[string], reasoning_summary string."
                    ),
                    "user_inputs": user.model_dump(mode="json"),
                    "allowed_perks": [_compact_perk(p) for p in allowed_perks],
                    "allowed_legendary_perks": [_compact_legendary_perk(p) for p in allowed_legendary_perks],
                },
                default=str,
            ),
        },
    ]
