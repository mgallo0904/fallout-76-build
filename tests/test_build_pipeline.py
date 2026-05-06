from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models import BuildCandidate, BuildInput, GeneratedBuild, GenerationMode

from app.services.build_pipeline import run_build_pipeline


def _make_input(**overrides):
    defaults = {
        "character_level": "50+",
        "primary_playstyle": "Commando",
        "primary_weapon_type": "Auto rifle",
        "preferred_weapons": "Fixer",
        "armor_type": "Regular armor",
        "health_model": "Full health",
        "combat_style": "VATS",
        "team_preference": "Public team",
        "mutation_preference": "Use mutations",
        "qol_preference": "Balanced",
        "legendary_perk_availability": "",
        "current_gear": "",
        "avoid_list": "",
        "character_type": "Human",
        "goal": None,
        "revision_intent": None,
    }
    defaults.update(overrides)
    return BuildInput(**defaults)


def _make_baseline():
    return GeneratedBuild(
        id="build-baseline",
        build_name="Deterministic Build",
        user_inputs=_make_input(),
        assumptions=[],
        special_allocation={"Strength": 3, "Perception": 15, "Endurance": 5, "Charisma": 3, "Intelligence": 3, "Agility": 15, "Luck": 12},
        perk_cards_by_special={},
        legendary_perks=[],
        mutations=[],
        gear={},
        variants={},
        swap_cards={},
        weaknesses=["test"],
        validation_status="passed",
        source_verification_notes=[],
        created_at=datetime.now(timezone.utc),
    )


def _make_candidate():
    return BuildCandidate(
        build_name="LLM Build",
        special_allocation={"Strength": 3, "Perception": 15, "Endurance": 5, "Charisma": 3, "Intelligence": 3, "Agility": 15, "Luck": 12},
        perk_cards_by_special={"Strength": [{"card_id": "bullet_storm", "rank": 3, "role": "Damage", "why": "LLM"}]},
        legendary_perks=[{"name": "Taking One for the Team", "rank": 4}],
        mutations=[{"name": "Speed Demon", "use": "Yes"}],
        gear={},
        variants={},
        swap_cards={},
        weaknesses=["test"],
        assumptions=[],
        reasoning_summary="test",
    )


@patch("app.services.build_pipeline.generate_build")
@patch("app.services.build_pipeline.validate_build")
@patch("app.services.build_pipeline.should_use_brain")
@patch("app.services.build_pipeline.generate_llm_candidate")
@patch("app.services.build_pipeline.repair_build")
@patch("app.services.build_pipeline.save_build")
@patch("app.services.build_pipeline.load_active_perks")
@patch("app.services.build_pipeline.load_active_legendary_perks")
def test_hybrid_mode_uses_deterministic_plus_llm(
    mock_load_leg, mock_load_perks, mock_save, mock_repair,
    mock_llm, mock_should_brain, mock_validate, mock_gen,
):
    mock_load_perks.return_value = []
    mock_load_leg.return_value = []
    mock_should_brain.return_value = False
    mock_gen.return_value = _make_baseline()
    mock_validate.return_value = []
    mock_llm.return_value = _make_candidate()
    mock_repair.return_value = (_make_candidate(), ["Dropped unknown perk"])

    result = run_build_pipeline(_make_input(), mode=GenerationMode.hybrid)
    assert mock_gen.called
    assert mock_llm.called
    assert mock_repair.called
    assert result.repair_notes == ["Dropped unknown perk"]
    assert result.generation_mode == GenerationMode.hybrid


@patch("app.services.build_pipeline.generate_build")
@patch("app.services.build_pipeline.validate_build")
@patch("app.services.build_pipeline.should_use_brain")
@patch("app.services.build_pipeline.generate_llm_candidate")
@patch("app.services.build_pipeline.repair_build")
@patch("app.services.build_pipeline.save_build")
@patch("app.services.build_pipeline.load_active_perks")
@patch("app.services.build_pipeline.load_active_legendary_perks")
def test_deterministic_mode_skips_llm(
    mock_load_leg, mock_load_perks, mock_save, mock_repair,
    mock_llm, mock_should_brain, mock_validate, mock_gen,
):
    mock_load_perks.return_value = []
    mock_load_leg.return_value = []
    mock_should_brain.return_value = False
    mock_gen.return_value = _make_baseline()
    mock_validate.return_value = []

    result = run_build_pipeline(_make_input(), mode=GenerationMode.deterministic)
    assert mock_gen.called
    assert not mock_llm.called
    assert not mock_repair.called
    assert result.generation_mode == GenerationMode.deterministic


@patch("app.services.build_pipeline.generate_build")
@patch("app.services.build_pipeline.validate_build")
@patch("app.services.build_pipeline.should_use_brain")
@patch("app.services.build_pipeline.generate_llm_candidate")
@patch("app.services.build_pipeline.repair_build")
@patch("app.services.build_pipeline.save_build")
@patch("app.services.build_pipeline.load_active_perks")
@patch("app.services.build_pipeline.load_active_legendary_perks")
def test_llm_mode_uses_llm_candidate(
    mock_load_leg, mock_load_perks, mock_save, mock_repair,
    mock_llm, mock_should_brain, mock_validate, mock_gen,
):
    mock_load_perks.return_value = []
    mock_load_leg.return_value = []
    mock_should_brain.return_value = False
    mock_gen.return_value = _make_baseline()
    mock_validate.return_value = []
    mock_llm.return_value = _make_candidate()
    mock_repair.return_value = (_make_candidate(), ["Repaired budget"])

    result = run_build_pipeline(_make_input(), mode=GenerationMode.llm)
    assert mock_llm.called
    assert mock_repair.called
    assert result.repair_notes == ["Repaired budget"]
    assert result.generation_mode == GenerationMode.llm


@patch("app.services.build_pipeline.generate_build")
@patch("app.services.build_pipeline.validate_build")
@patch("app.services.build_pipeline.should_use_brain")
@patch("app.services.build_pipeline.generate_llm_candidate")
@patch("app.services.build_pipeline.repair_build")
@patch("app.services.build_pipeline.save_build")
@patch("app.services.build_pipeline.load_active_perks")
@patch("app.services.build_pipeline.load_active_legendary_perks")
def test_hybrid_mode_repair_notes_included_in_response(
    mock_load_leg, mock_load_perks, mock_save, mock_repair,
    mock_llm, mock_should_brain, mock_validate, mock_gen,
):
    mock_load_perks.return_value = []
    mock_load_leg.return_value = []
    mock_should_brain.return_value = False
    mock_gen.return_value = _make_baseline()
    mock_validate.return_value = []
    mock_llm.return_value = _make_candidate()
    mock_repair.return_value = (_make_candidate(), ["Dropped hallucinated perk", "Capped rank"])

    result = run_build_pipeline(_make_input(), mode=GenerationMode.hybrid)
    assert result.repair_notes == ["Dropped hallucinated perk", "Capped rank"]


@patch("app.services.build_pipeline.generate_build")
@patch("app.services.build_pipeline.validate_build")
@patch("app.services.build_pipeline.should_use_brain")
@patch("app.services.build_pipeline.save_build")
@patch("app.services.build_pipeline.load_active_perks")
@patch("app.services.build_pipeline.load_active_legendary_perks")
def test_invalid_generation_mode_string_raises(
    mock_load_leg, mock_load_perks, mock_save, mock_should_brain, mock_validate, mock_gen,
):
    mock_load_perks.return_value = []
    mock_load_leg.return_value = []
    mock_should_brain.return_value = False
    mock_gen.return_value = _make_baseline()
    mock_validate.return_value = []

    with pytest.raises(ValueError):
        run_build_pipeline(_make_input(), mode="magic")


@patch("app.services.build_pipeline.generate_build")
@patch("app.services.build_pipeline.validate_build")
@patch("app.services.build_pipeline.should_use_brain")
@patch("app.services.build_pipeline.generate_llm_candidate")
@patch("app.services.build_pipeline.repair_build")
@patch("app.services.build_pipeline.save_build")
@patch("app.services.build_pipeline.load_active_perks")
@patch("app.services.build_pipeline.load_active_legendary_perks")
def test_default_generation_mode_is_hybrid(
    mock_load_leg, mock_load_perks, mock_save, mock_repair,
    mock_llm, mock_should_brain, mock_validate, mock_gen,
):
    mock_load_perks.return_value = []
    mock_load_leg.return_value = []
    mock_should_brain.return_value = False
    mock_gen.return_value = _make_baseline()
    mock_validate.return_value = []
    mock_llm.return_value = _make_candidate()
    mock_repair.return_value = (_make_candidate(), [])

    result = run_build_pipeline(_make_input())
    assert mock_gen.called
    assert mock_llm.called
    assert result.generation_mode == GenerationMode.hybrid


@patch("app.services.build_pipeline.generate_build")
@patch("app.services.build_pipeline.validate_build")
@patch("app.services.build_pipeline.should_use_brain")
@patch("app.services.build_pipeline.save_build")
@patch("app.services.build_pipeline.load_active_perks")
@patch("app.services.build_pipeline.load_active_legendary_perks")
def test_invalid_input_missing_playstyle_raises(
    mock_load_leg, mock_load_perks, mock_save, mock_should_brain, mock_validate, mock_gen,
):
    mock_load_perks.return_value = []
    mock_load_leg.return_value = []
    mock_should_brain.return_value = False
    mock_gen.return_value = _make_baseline()
    mock_validate.return_value = []

    with pytest.raises(ValueError):
        run_build_pipeline(BuildInput(primary_playstyle=""))
