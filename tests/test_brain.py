import io
import json
from unittest.mock import patch

import pytest

from app.models import BuildInput
from app.services import brain as brain_module
from app.services.brain import (
    BrainError,
    DEFAULT_MODEL,
    api_url,
    brain_status,
    enhance_build_with_brain,
    extract_json_object,
    get_brain_config,
)
from app.services.engine import generate_build


def test_extract_json_object_from_fenced_response():
    parsed = extract_json_object('```json\n{"ok": true, "items": [1]}\n```')
    assert parsed == {"ok": True, "items": [1]}


def test_default_brain_config_uses_kimi(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "secret-value")
    monkeypatch.setenv("USE_OLLAMA_BRAIN", "1")
    status = brain_status()
    assert status["enabled"] is True
    assert status["model"] == DEFAULT_MODEL
    assert status["has_api_key"] is True
    assert "secret-value" not in str(status)


def test_api_url_normalizes_hosts():
    assert api_url("https://ollama.com", "/chat") == "https://ollama.com/api/chat"
    assert api_url("https://ollama.com/api", "/chat") == "https://ollama.com/api/chat"


def test_mandatory_brain_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    with pytest.raises(BrainError):
        get_brain_config()


def test_enhance_build_with_brain_does_not_overwrite_special(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    monkeypatch.setenv("OLLAMA_WEB_SEARCH", "0")

    payload = json.dumps(
        {
            "message": {
                "content": json.dumps(
                    {
                        "build_name": "Brain Renamed",
                        "assumptions": ["a"],
                        "weaknesses": ["w"],
                        "brain_notes": ["bn"],
                        # Attempt to inject SPECIAL / perk overrides should be ignored.
                        "special_allocation": {s: 15 for s in ["Strength", "Perception", "Endurance", "Charisma", "Intelligence", "Agility", "Luck"]},
                        "perk_cards_by_special": {"Strength": []},
                    }
                )
            }
        }
    ).encode("utf-8")

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    user = BuildInput()
    build = generate_build(user)
    original_special = dict(build.special_allocation)

    def fake_urlopen(_request, timeout=None):
        return FakeResponse(payload)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        enhance_build_with_brain(user, build, validation_issues=[])

    assert build.build_name == "Brain Renamed"
    assert build.special_allocation == original_special


def test_enhance_build_continues_when_web_search_fails(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    monkeypatch.setenv("OLLAMA_WEB_SEARCH", "1")

    payload = json.dumps(
        {
            "message": {
                "content": json.dumps(
                    {
                        "build_name": "Brain Without Search",
                        "assumptions": ["a"],
                        "weaknesses": ["w"],
                        "brain_notes": ["bn"],
                    }
                )
            }
        }
    ).encode("utf-8")

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    user = BuildInput()
    build = generate_build(user)

    def fake_web_search(*_args, **_kwargs):
        raise BrainError("simulated search timeout")

    def fake_urlopen(_request, timeout=None):
        return FakeResponse(payload)

    monkeypatch.setattr(brain_module, "web_search", fake_web_search)
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        enhance_build_with_brain(user, build, validation_issues=[])

    assert build.build_name == "Brain Without Search"
    assert any("web search unavailable" in note.lower() for note in build.brain_notes)
