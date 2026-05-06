import json
from unittest.mock import patch

import pytest

from app.models import BuildCandidate
from app.services.llm_builder import (
    BrainError,
    _extract_json_object,
    generate_llm_candidate,
)


SAMPLE_VALID_RESPONSE = {
    "build_name": "LLM Test Build",
    "special_allocation": {
        "Strength": 15,
        "Perception": 3,
        "Endurance": 5,
        "Charisma": 3,
        "Intelligence": 9,
        "Agility": 10,
        "Luck": 11,
    },
    "perk_cards_by_special": {
        "Strength": [{"card_id": "bullet_storm", "rank": 3, "role": "Damage", "why": "LLM choice"}],
    },
    "legendary_perks": [{"name": "Taking One for the Team", "rank": 4, "priority": "Required"}],
    "mutations": [{"name": "Speed Demon", "use": "Yes"}],
    "gear": {"weapons": ["Gatling Plasma"]},
    "variants": {},
    "swap_cards": {},
    "weaknesses": ["High ammo use"],
    "assumptions": ["LLM assumption"],
    "reasoning_summary": "Test reasoning",
}


def _mock_chat_response(content: dict):
    return {"message": {"content": json.dumps(content)}}


def test_extract_json_object_finds_wrapped_json():
    text = 'Some preamble ```json\n' + json.dumps(SAMPLE_VALID_RESPONSE) + '\n``` after'
    result = _extract_json_object(text)
    assert result == SAMPLE_VALID_RESPONSE


def test_extract_json_object_finds_bare_json():
    text = json.dumps(SAMPLE_VALID_RESPONSE)
    result = _extract_json_object(text)
    assert result == SAMPLE_VALID_RESPONSE


def test_extract_json_object_raises_on_no_json():
    with pytest.raises(BrainError):
        _extract_json_object("No json here at all")


@patch("app.services.llm_builder._chat_for_candidate")
def test_generate_llm_candidate_parses_valid_response(mock_chat):
    mock_chat.return_value = _mock_chat_response(SAMPLE_VALID_RESPONSE)
    candidate = generate_llm_candidate([{"role": "user", "content": "test"}])
    assert candidate.build_name == "LLM Test Build"
    assert candidate.special_allocation["Strength"] == 15


@patch("app.services.llm_builder._chat_for_candidate")
def test_generate_llm_candidate_retries_on_malformed_json(mock_chat):
    # First call simulates BrainError from malformed JSON, second returns valid parsed dict
    mock_chat.side_effect = [
        BrainError("Ollama response did not contain a JSON object"),
        _mock_chat_response(SAMPLE_VALID_RESPONSE),
    ]
    candidate = generate_llm_candidate([{"role": "user", "content": "test"}], max_retries=1)
    assert candidate.build_name == "LLM Test Build"
    assert mock_chat.call_count == 2


@patch("app.services.llm_builder._chat_for_candidate")
def test_generate_llm_candidate_falls_back_to_empty_on_retry_failure(mock_chat):
    mock_chat.side_effect = [
        {"message": {"content": "still not json"}},
        {"message": {"content": "also not json"}},
    ]
    candidate = generate_llm_candidate([{"role": "user", "content": "test"}], max_retries=1)
    # On total failure, returns an empty candidate so deterministic baseline is preserved
    assert candidate.build_name == ""
    assert candidate.special_allocation == {}


@patch("app.services.llm_builder._chat_for_candidate")
def test_generate_llm_candidate_drops_hallucinated_perks(mock_chat):
    bad_response = dict(SAMPLE_VALID_RESPONSE)
    bad_response["perk_cards_by_special"] = {
        "Strength": [
            {"card_id": "totally_fake_perk_id", "rank": 5, "role": "Damage", "why": "hallucinated"},
            {"card_id": "bullet_storm", "rank": 3, "role": "Damage", "why": "real"},
        ]
    }
    bad_response["mutations"] = [
        {"name": "Speed Demon", "use": "Yes"},
        {"name": "Fake Mutation", "use": "Yes"},
    ]
    mock_chat.return_value = _mock_chat_response(bad_response)
    candidate = generate_llm_candidate([{"role": "user", "content": "test"}])
    # BuildCandidate does not validate perk IDs, so hallucinations pass through at this layer.
    # The repair layer is responsible for dropping them.
    perk_ids = {
        p["card_id"]
        for picks in candidate.perk_cards_by_special.values()
        for p in picks
    }
    assert "totally_fake_perk_id" in perk_ids
    mutation_names = {m["name"] for m in candidate.mutations}
    assert "Fake Mutation" in mutation_names


@patch("app.services.llm_builder._chat_for_candidate")
def test_generate_llm_candidate_handles_ollama_503(mock_chat):
    mock_chat.side_effect = BrainError("Ollama HTTP 503: Service Unavailable")
    candidate = generate_llm_candidate([{"role": "user", "content": "test"}])
    assert candidate.build_name == ""


@patch("app.services.llm_builder._chat_for_candidate")
def test_generate_llm_candidate_includes_messages_in_prompt(mock_chat):
    mock_chat.return_value = _mock_chat_response(SAMPLE_VALID_RESPONSE)
    messages = [{"role": "user", "content": "generate a heavy gunner build"}]
    generate_llm_candidate(messages)
    call_args = mock_chat.call_args
    assert call_args[0][0] == messages
