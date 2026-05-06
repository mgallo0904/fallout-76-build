from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models import BuildCandidate, BuildInput, GeneratedBuild, GenerationMode, PerkCard, PerkChoice
from app.services import brain, engine, repository
from app.services.repair import repair_build


# Module-level wrappers so tests can mock them at app.services.build_pipeline.*
def generate_build(*args, **kwargs):
    return engine.get_baseline_for_inputs(*args, **kwargs)

def validate_build(*args, **kwargs):
    return engine.validate_build(*args, **kwargs)

def generate_llm_candidate(*args, **kwargs):
    return brain.generate_build_candidate(*args, **kwargs)

def should_use_brain():
    return engine.should_use_brain()

def save_build(*args, **kwargs):
    return repository.save_build(*args, **kwargs)

def load_active_perks():
    return repository.load_active_perks()

def load_active_legendary_perks():
    return repository.load_active_legendary_perks()


def normalize_inputs(user: BuildInput) -> BuildInput:
    """Migrate legacy inputs to the current schema."""
    data = user.model_dump(mode="json")
    # Map legacy primary_weapon_type to preferred_weapons if empty
    if not data.get("preferred_weapons") and data.get("primary_weapon_type"):
        data["preferred_weapons"] = data["primary_weapon_type"]
    # Drop deprecated fields so they do not leak into downstream processing
    data.pop("legendary_perk_availability", None)
    validated = BuildInput.model_validate(data)
    if not validated.primary_playstyle.strip():
        raise ValueError("primary_playstyle is required")
    return validated


def _candidate_to_generated(
    candidate: BuildCandidate,
    user: BuildInput,
    repair_notes: list[str],
    mode: GenerationMode,
) -> GeneratedBuild:
    """Convert a repaired BuildCandidate into a full GeneratedBuild."""
    now = datetime.now(timezone.utc)
    perk_cards_by_special: dict[str, list[PerkChoice]] = {}
    for special, picks in candidate.perk_cards_by_special.items():
        perk_cards_by_special[special] = [
            PerkChoice(
                card_id=str(p.get("card_id", "")),
                rank=int(p.get("rank", 1)),
                role=str(p.get("role", "")),
                why=str(p.get("why", "")),
            )
            for p in picks
        ]

    return GeneratedBuild(
        id=f"build-{now.strftime('%Y%m%d%H%M%S%f')}",
        build_name=candidate.build_name or "Generated Build",
        user_inputs=user,
        assumptions=list(candidate.assumptions),
        special_allocation=dict(candidate.special_allocation),
        perk_cards_by_special=perk_cards_by_special,
        legendary_perks=[dict(lp) for lp in candidate.legendary_perks],
        mutations=[dict(m) for m in candidate.mutations],
        gear=dict(candidate.gear),
        variants={k: list(v) for k, v in candidate.variants.items()},
        swap_cards={k: list(v) for k, v in candidate.swap_cards.items()},
        weaknesses=list(candidate.weaknesses),
        validation_status="passed",
        source_verification_notes=[],
        created_at=now,
        logic_engine="deterministic",
        generation_mode=mode,
        repair_notes=repair_notes,
        brain_notes=[],
        web_search_results=[],
        brain_confirmed=False,
        brain_status="not_requested",
        brain_error=None,
        brain_updated_at=None,
        brain_suggested_swaps=[],
        brain_override_reasoning=[],
        legendary_perk_rank_changes=[],
    )


def _set_brain_pending(build: GeneratedBuild) -> None:
    """Mark build for background brain refinement when brain is available."""
    build.brain_status = "pending"
    build.brain_updated_at = datetime.now(timezone.utc)
    build.brain_notes.append("Brain refinement queued in the background.")


def run_build_pipeline(
    user: BuildInput,
    mode: GenerationMode | str | None = None,
    *,
    generation_mode: GenerationMode | str | None = None,
) -> GeneratedBuild:
    """Orchestrate the full build generation pipeline.

    1. Normalize inputs and determine generation mode.
    2. Get deterministic baseline.
    3. If hybrid/llm mode, get LLM candidate and apply sanity filtering.
    4. Validate and repair.
    5. Save and return the final GeneratedBuild.
    """
    user = normalize_inputs(user)

    # Resolve and validate mode (accept both positional `mode` and keyword `generation_mode`)
    effective_mode = mode if mode is not None else generation_mode
    resolved_mode: GenerationMode
    if effective_mode is None:
        resolved_mode = GenerationMode.hybrid
    elif isinstance(effective_mode, str):
        try:
            resolved_mode = GenerationMode(effective_mode)
        except ValueError as exc:
            raise ValueError(f"Invalid generation_mode: {effective_mode}") from exc
    else:
        resolved_mode = effective_mode

    # Deterministic mode
    if resolved_mode == GenerationMode.deterministic:
        build = generate_build(user)
        issues = validate_build(build)
        build.validation_status = "passed" if not issues else "issues"
        build.generation_mode = resolved_mode
        if should_use_brain():
            _set_brain_pending(build)
        save_build(build)
        return build

    # LLM / hybrid: attempt LLM candidate
    llm_candidate: BuildCandidate | None = None
    llm_error: str | None = None
    try:
        llm_candidate = generate_llm_candidate(
            user,
            list(load_active_perks()),
            list(load_active_legendary_perks()),
            {
                "Speed Demon", "Adrenal Reaction", "Marsupial", "Eagle Eyes",
                "Talons", "Bird Bones", "Egg Head", "Empath", "Healing Factor",
                "Herd Mentality", "Carnivore", "Herbivore", "Twisted Muscles",
                "Plague Walker", "Grounded", "Scaly Skin", "Electrically Charged",
                "Unstable Isotope", "Chameleon",
            },
        )
    except brain.BrainError as exc:
        llm_error = str(exc)

    # LLM mode
    if resolved_mode == GenerationMode.llm:
        if llm_candidate is None:
            build = generate_build(user)
            build.repair_notes.append(
                f"LLM mode requested but LLM call failed: {llm_error}. Falling back to deterministic baseline."
            )
            build.generation_mode = resolved_mode
            save_build(build)
            return build
        llm_candidate = brain.sanity_filter_candidate(
            llm_candidate,
            {p.name for p in load_active_legendary_perks()},
            {
                "Speed Demon", "Adrenal Reaction", "Marsupial", "Eagle Eyes",
                "Talons", "Bird Bones", "Egg Head", "Empath", "Healing Factor",
                "Herd Mentality", "Carnivore", "Herbivore", "Twisted Muscles",
                "Plague Walker", "Grounded", "Scaly Skin", "Electrically Charged",
                "Unstable Isotope", "Chameleon",
            },
        )
        repaired, repair_notes = repair_build(
            llm_candidate,
            {p.id: p for p in load_active_perks()},
            {p.name: p for p in load_active_legendary_perks()},
            user,
        )
        final = _candidate_to_generated(repaired, user, repair_notes, GenerationMode.llm)
        final.brain_notes.append("LLM-only generation used.")
        if llm_error:
            final.repair_notes.append(f"Initial LLM error (recovered): {llm_error}")
        save_build(final)
        return final

    # Hybrid mode (default)
    baseline = generate_build(user)
    baseline_issues = validate_build(baseline)
    if baseline_issues:
        baseline.validation_status = "issues"
        baseline.repair_notes.extend(baseline_issues)

    if llm_candidate is None:
        baseline.repair_notes.append(
            f"LLM candidate unavailable: {llm_error}. Using deterministic baseline only."
        )
        baseline.generation_mode = resolved_mode
        if should_use_brain():
            _set_brain_pending(baseline)
        save_build(baseline)
        return baseline

    llm_candidate = brain.sanity_filter_candidate(
        llm_candidate,
        {p.name for p in load_active_legendary_perks()},
        {
            "Speed Demon", "Adrenal Reaction", "Marsupial", "Eagle Eyes",
            "Talons", "Bird Bones", "Egg Head", "Empath", "Healing Factor",
            "Herd Mentality", "Carnivore", "Herbivore", "Twisted Muscles",
            "Plague Walker", "Grounded", "Scaly Skin", "Electrically Charged",
            "Unstable Isotope", "Chameleon",
        },
    )
    repaired, repair_notes = repair_build(
        llm_candidate,
        {p.id: p for p in load_active_perks()},
        {p.name: p for p in load_active_legendary_perks()},
        user,
    )

    # If repair dropped everything, fall back to baseline
    if not any(repaired.perk_cards_by_special.values()):
        baseline.repair_notes.append(
            "LLM candidate was fully rejected by repair layer. Using deterministic baseline."
        )
        baseline.generation_mode = resolved_mode
        if should_use_brain():
            _set_brain_pending(baseline)
        save_build(baseline)
        return baseline

    final = _candidate_to_generated(repaired, user, repair_notes, GenerationMode.hybrid)
    final.brain_notes.append("Hybrid generation: deterministic baseline + LLM candidate with repair.")
    if should_use_brain():
        _set_brain_pending(final)
    save_build(final)
    return final
