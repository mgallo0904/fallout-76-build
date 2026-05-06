from __future__ import annotations

from app.models import BuildCandidate, BuildInput, PerkCard


def repair_build(
    candidate: BuildCandidate,
    perks_by_id: dict[str, PerkCard],
    legendary_by_name: dict[str, PerkCard],
    user: BuildInput,
) -> tuple[BuildCandidate, list[str]]:
    """
    Repair an LLM-generated build candidate.

    - Drop unknown perk IDs.
    - Cap ranks at max_rank.
    - Ensure total card cost per SPECIAL does not exceed allocation.
    - Remove cards incompatible with armor/health/ghoul/VATS/stealth flags.
    - Remove character-restricted perks selected by wrong character type.
    - Add deterministic fallback picks if a column is underfilled.
    - Return repair_notes.
    """
    repair_notes: list[str] = []
    cleaned = BuildCandidate(
        build_name=candidate.build_name,
        special_allocation=dict(candidate.special_allocation),
        perk_cards_by_special={},
        legendary_perks=[dict(lp) for lp in candidate.legendary_perks],
        mutations=[dict(m) for m in candidate.mutations],
        gear=dict(candidate.gear),
        variants=dict(candidate.variants),
        swap_cards=dict(candidate.swap_cards),
        assumptions=list(candidate.assumptions),
        weaknesses=list(candidate.weaknesses),
        reasoning_summary=candidate.reasoning_summary,
    )

    pa_user = "Power Armor" in user.armor_type
    full_health = user.health_model == "Full health"
    non_vats = user.combat_style == "Non-VATS"
    avoid_stealth = "stealth" in user.avoid_list.lower()
    is_ghoul = user.character_type == "Ghoul"

    specials = ["Strength", "Perception", "Endurance", "Charisma", "Intelligence", "Agility", "Luck"]

    for special in specials:
        budget = cleaned.special_allocation.get(special, 0)
        picks = candidate.perk_cards_by_special.get(special, [])
        kept: list[dict[str, object]] = []
        spent = 0

        for pick in picks:
            card_id = str(pick.get("card_id", ""))
            rank = pick.get("rank", 1)
            if not isinstance(rank, int):
                try:
                    rank = int(rank)
                except (ValueError, TypeError):
                    repair_notes.append(f"Dropped {card_id}: invalid rank value.")
                    continue

            card = perks_by_id.get(card_id)
            if not card:
                repair_notes.append(f"Dropped unknown perk id: {card_id}.")
                continue

            # Cap rank
            if rank > card.max_rank:
                repair_notes.append(f"Capped {card.name} rank from {rank} to {card.max_rank}.")
                rank = card.max_rank
            if rank < 1:
                rank = 1

            cost = card.rank_costs.get(rank)
            if cost is None:
                repair_notes.append(f"Dropped {card.name}: missing cost for rank {rank}.")
                continue

            # Incompatibility checks
            if card.power_armor_only and not pa_user:
                repair_notes.append(f"Dropped {card.name}: requires Power Armor.")
                continue
            if card.regular_armor_only and pa_user:
                repair_notes.append(f"Dropped {card.name}: not usable in Power Armor.")
                continue
            if card.bloodied_synergy and full_health:
                repair_notes.append(f"Dropped {card.name}: bloodied perk in full-health build.")
                continue
            if card.vats_synergy and non_vats:
                repair_notes.append(f"Dropped {card.name}: VATS perk in non-VATS build.")
                continue
            if card.stealth_synergy and (non_vats or avoid_stealth):
                repair_notes.append(f"Dropped {card.name}: stealth perk conflicts with build preferences.")
                continue
            if card.character_restriction == "Ghoul" and not is_ghoul:
                repair_notes.append(f"Dropped {card.name}: Ghoul-only perk selected for Human character.")
                continue
            if card.character_restriction == "Human" and is_ghoul:
                repair_notes.append(f"Dropped {card.name}: Human-only perk selected for Ghoul character.")
                continue

            # Budget check
            if spent + cost > budget:
                # Try lower ranks that fit
                lowered = False
                for try_rank in range(rank - 1, 0, -1):
                    try_cost = card.rank_costs.get(try_rank)
                    if try_cost is not None and spent + try_cost <= budget:
                        repair_notes.append(f"Lowered {card.name} to rank {try_rank} to fit {special} budget.")
                        rank = try_rank
                        cost = try_cost
                        lowered = True
                        break
                if not lowered:
                    repair_notes.append(f"Dropped {card.name}: exceeds {special} budget ({spent + cost} > {budget}).")
                    continue

            spent += cost
            kept.append({"card_id": card_id, "rank": rank, "role": str(pick.get("role", "")), "why": str(pick.get("why", ""))})

        # Fallback: fill remaining budget with safe utility/damage cards
        remaining = budget - spent
        if remaining > 0:
            # Try to fill with known, compatible cards that aren't already picked
            selected_ids = {str(k["card_id"]) for k in kept}
            fallback_candidates = [
                c for c in perks_by_id.values()
                if c.special == special
                and c.id not in selected_ids
                and c.status.value == "verified"
                and not c.crafting_or_swap_only
                and (not c.power_armor_only or pa_user)
                and (not c.regular_armor_only or not pa_user)
                and (not c.bloodied_synergy or not full_health)
                and (not c.vats_synergy or not non_vats)
                and (not c.stealth_synergy or not (non_vats or avoid_stealth))
                and (c.character_restriction == "Any" or (c.character_restriction == "Ghoul" and is_ghoul) or (c.character_restriction == "Human" and not is_ghoul))
            ]
            # Sort by cost descending to fill efficiently
            fallback_candidates.sort(key=lambda c: max(c.rank_costs.values(), default=0), reverse=True)
            for card in fallback_candidates:
                if remaining <= 0:
                    break
                for try_rank in range(min(card.max_rank, 3), 0, -1):
                    try_cost = card.rank_costs.get(try_rank)
                    if try_cost is not None and try_cost <= remaining:
                        kept.append({"card_id": card.id, "rank": try_rank, "role": "Fallback", "why": f"Deterministic fallback to fill {special} budget."})
                        repair_notes.append(f"Added fallback {card.name} rank {try_rank} to fill {special} budget.")
                        remaining -= try_cost
                        break

        cleaned.perk_cards_by_special[special] = kept

    # Repair legendary perks
    cleaned_legendary: list[dict[str, object]] = []
    for lp in cleaned.legendary_perks:
        name = str(lp.get("name", ""))
        rank = lp.get("rank", 1)
        if not isinstance(rank, int):
            try:
                rank = int(rank)
            except (ValueError, TypeError):
                repair_notes.append(f"Dropped legendary perk {name}: invalid rank.")
                continue

        card = legendary_by_name.get(name)
        if not card:
            repair_notes.append(f"Dropped unknown legendary perk: {name}.")
            continue

        if rank > card.max_rank:
            repair_notes.append(f"Capped legendary {card.name} rank from {rank} to {card.max_rank}.")
            rank = card.max_rank
        if rank < 1:
            rank = 1

        if card.character_restriction == "Ghoul" and not is_ghoul:
            repair_notes.append(f"Dropped legendary {card.name}: Ghoul-only perk for Human character.")
            continue
        if card.character_restriction == "Human" and is_ghoul:
            repair_notes.append(f"Dropped legendary {card.name}: Human-only perk for Ghoul character.")
            continue

        cleaned_legendary.append({"name": name, "rank": rank, "priority": lp.get("priority", ""), "reason": lp.get("reason", "")})

    cleaned.legendary_perks = cleaned_legendary

    return cleaned, repair_notes
